"""主动发言：像群友一样接话、冷场时主动起话，带防抖和频率限制。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx2
import nonebot
from nonebot import get_driver, get_plugin_config, logger, on_command, on_message
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from qqbot_filters import configure as configure_blocked
from qqbot_filters import is_blocked
from qqbot_stickers import stickers

from plugins.common.media import sniff_media_type as _sniff_media_type

from .activity import Activity, ActivityBuffer, format_clock, in_quiet_hours
from .config import Config
from .formatting import clean_solution, split_solution
from .llm import ProactiveSpeaker

plugin_config = get_plugin_config(Config)
configure_blocked(plugin_config.blocked_users)

# 冷场起话需要看到更早的消息，缓冲 TTL 至少覆盖“安静时间 + 10 分钟”
_BUFFER_TTL = max(
    plugin_config.proactive_window_minutes * 60,
    plugin_config.proactive_initiative_after_minutes * 60 + 600,
    1800,
)
buffer = ActivityBuffer(ttl_seconds=_BUFFER_TTL)
speaker = ProactiveSpeaker(plugin_config)

BOT_SPEAKER = "Claude"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STATE_PATH = _PROJECT_ROOT / "data" / "proactive.json"

_state_groups: set[int] = set()
_last_spoke: dict[int, float] = {}
_daily_by_group: dict[int, int] = {}
_daily_total = 0
_day = datetime.now().strftime("%Y-%m-%d")
_task: asyncio.Task | None = None
_join_tasks: dict[int, asyncio.Task] = {}
_speaking: set[int] = set()

_image_tasks: dict[int, asyncio.Task] = {}
_image_pending: set[int] = set()
_image_speaking: set[int] = set()
_pending_images: dict[int, "_PendingImage"] = {}
_last_image_spoke: dict[int, float] = {}
_daily_images: dict[int, int] = {}


@dataclass(slots=True)
class _PendingImage:
    group_id: int
    message_id: int
    text: str
    urls: list[str]
    at: float

HELP_TEXT = """\
主动发言命令：
/proactive status  查看本群状态
/proactive on      开启本群（群主/管理员）
/proactive off     关闭本群（群主/管理员）
/proactive test    立即试发一条（群主/管理员）
/proactive id      查看本群群号
/sticker           随机发一个本号收藏的表情包

开启后，群里发图片会自动识别；如果是题目会直接解答。
"""


# ---------------------------------------------------------------------------
# 群聊缓冲与接话调度
# ---------------------------------------------------------------------------


_activity_recorder = on_message(priority=1, block=False)


def _mentions_me(event: GroupMessageEvent) -> bool:
    try:
        return any(
            seg.type == "at" and str(seg.data.get("qq", "")) == str(event.self_id)
            for seg in event.original_message
        )
    except Exception:
        return False


def _replies_to_me(event: GroupMessageEvent) -> bool:
    reply = getattr(event, "reply", None)
    sender = getattr(reply, "sender", None)
    return bool(sender and str(getattr(sender, "user_id", "")) == str(event.self_id))


def _is_sticker(seg: MessageSegment) -> bool:
    if str(seg.data.get("sub_type", "")) == "1":
        return True
    return "动画表情" in str(seg.data.get("summary", ""))


def _usable_images(event: GroupMessageEvent) -> list[MessageSegment]:
    return [
        seg
        for seg in event.get_message()
        if seg.type == "image" and not _is_sticker(seg)
    ]


@_activity_recorder.handle()
async def _record_activity(event: MessageEvent) -> None:
    if not isinstance(event, GroupMessageEvent):
        return
    if is_blocked(event.user_id):
        return
    if str(event.user_id) == str(event.self_id):
        return
    text = event.get_plaintext().strip()
    # 链接交给 media_download 自动处理，主动发言不要抢话
    if "http://" in text or "https://" in text:
        return
    if not plugin_config.proactive_enabled:
        return
    if event.group_id not in _state_groups:
        return

    image_segs = _usable_images(event)
    if not text and not image_segs:
        return
    if text.startswith("/"):
        return

    nickname = ""
    try:
        nickname = str(event.sender.card or event.sender.nickname or event.user_id)
    except Exception:
        nickname = str(event.user_id)
    if text:
        buffer.record(event.group_id, nickname, text, user_id=event.user_id)

    addressed = event.to_me or _mentions_me(event) or _replies_to_me(event)
    if image_segs and plugin_config.proactive_image_enabled:
        # 图片交给图片解题任务；@ 机器人的图片仍由 claude_chat 处理
        if not addressed:
            _schedule_image(event, image_segs, text)
        return

    if not text or addressed:
        return
    # 图片还在等模型/正在解答时，先不额外接话，避免双回复
    if event.group_id in _image_pending:
        return
    _schedule_join(event.group_id, force=_called_by_name(text))


def _called_by_name(text: str) -> bool:
    lowered = text.casefold()
    return "claude" in lowered or "克劳德" in lowered


def _schedule_join(group_id: int, *, force: bool = False) -> None:
    if plugin_config.proactive_mode != "conversation":
        return
    old = _join_tasks.get(group_id)
    # 只在“还在等安静”的阶段取消；已经开始生成/发送就不要打断
    if old is not None and not old.done() and group_id not in _speaking:
        old.cancel()
    _join_tasks[group_id] = asyncio.create_task(
        _delayed_join(group_id, force), name=f"proactive_join_{group_id}"
    )


async def _delayed_join(group_id: int, force: bool = False) -> None:
    try:
        await asyncio.sleep(0.6 if force else plugin_config.proactive_reply_delay_seconds)
        await _try_join(group_id, force=force)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(f"主动接话任务异常（群 {group_id}）")


def _transcript(activities: list[Activity]) -> str:
    def label(item: Activity) -> str:
        return f"{item.nickname}（QQ {item.user_id}）" if item.user_id else item.nickname

    return "\n".join(
        f"[{format_clock(item.at)}] {label(item)}：{item.text[:160]}"
        for item in activities
    )


# ---------------------------------------------------------------------------
# 图片识别 / 解题
# ---------------------------------------------------------------------------


def _schedule_image(event: GroupMessageEvent, segs: list[MessageSegment], text: str) -> None:
    if not plugin_config.proactive_enabled or not plugin_config.proactive_image_enabled:
        return
    if event.group_id not in _state_groups:
        return

    urls = [
        str(seg.data.get("url") or "")
        for seg in segs
        if str(seg.data.get("url") or "").startswith(("http://", "https://"))
    ]
    if not urls:
        return

    _image_pending.add(event.group_id)
    _pending_images[event.group_id] = _PendingImage(
        group_id=event.group_id,
        message_id=event.message_id,
        text=text,
        urls=urls[: plugin_config.proactive_image_max_count],
        at=time.time(),
    )

    old = _image_tasks.get(event.group_id)
    if old is not None and not old.done() and event.group_id not in _image_speaking:
        old.cancel()
    _image_tasks[event.group_id] = asyncio.create_task(
        _delayed_image(event.group_id), name=f"proactive_image_{event.group_id}"
    )


async def _delayed_image(group_id: int) -> None:
    try:
        await asyncio.sleep(plugin_config.proactive_image_delay_seconds)
        await _solve_image(group_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(f"图片识别任务异常（群 {group_id}）")


async def _fetch_image(url: str) -> tuple[str, bytes]:
    if not url.startswith(("http://", "https://")):
        raise ValueError("图片没有可用的 http 地址")

    max_bytes = int(plugin_config.proactive_image_max_mb * 1024 * 1024)
    timeout = httpx2.Timeout(30.0, connect=10.0)
    async with httpx2.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QQBot/1.0"},
    ) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise ValueError("图片超过大小限制")
            buffer = bytearray()
            async for chunk in response.aiter_bytes():
                buffer.extend(chunk)
                if len(buffer) > max_bytes:
                    raise ValueError("图片超过大小限制")
            data = bytes(buffer)

    if not data:
        raise ValueError("图片内容为空")
    media_type = _sniff_media_type(data)
    if media_type is None:
        raise ValueError("图片格式不支持")
    return media_type, data


async def _solve_image(group_id: int) -> None:
    pending = _pending_images.pop(group_id, None)
    if pending is None:
        return

    try:
        if not plugin_config.proactive_enabled or not plugin_config.proactive_image_enabled:
            return
        if group_id not in _state_groups:
            return
        if group_id in _image_speaking:
            return

        _roll_day()
        if in_quiet_hours(plugin_config.proactive_quiet_hours):
            return
        if _daily_images.get(group_id, 0) >= plugin_config.proactive_image_daily_limit_per_group:
            logger.info(f"图片解答跳过（群 {group_id}）：今日额度已用完")
            return
        if time.time() - _last_image_spoke.get(group_id, 0.0) < plugin_config.proactive_image_cooldown_seconds:
            return
        if not speaker.available():
            return

        bot = _pick_bot()
        if bot is None:
            return

        results = await asyncio.gather(
            *(_fetch_image(url) for url in pending.urls),
            return_exceptions=True,
        )
        images = [item for item in results if isinstance(item, tuple)]
        for item in results:
            if not isinstance(item, tuple):
                logger.warning(f"图片下载失败（群 {group_id}）：{item!r}")
        if not images:
            return

        recent = buffer.last(group_id, limit=6)
        transcript = _transcript(recent) if recent else ""
        latest_text = ""
        if recent and time.time() - recent[-1].at < 180:
            latest_text = next(
                (item.text for item in reversed(recent) if item.nickname != BOT_SPEAKER),
                "",
            )
        prompt_text = pending.text or latest_text

        _image_speaking.add(group_id)
        try:
            raw = await speaker.generate_vision(
                group_id,
                prompt_text,
                images,
                transcript=transcript,
            )
            if not raw:
                return
            cleaned = clean_solution(raw, limit=plugin_config.proactive_image_max_chars)
            chunks = split_solution(
                cleaned,
                limit=plugin_config.proactive_image_chunk_chars,
                max_chunks=8,
            )
            if not chunks:
                return

            await asyncio.sleep(random.uniform(1.0, 2.0))
            for index, chunk in enumerate(chunks):
                message = Message(chunk)
                if index == 0:
                    message = MessageSegment.reply(pending.message_id) + message
                try:
                    await bot.call_api("send_group_msg", group_id=group_id, message=message)
                except Exception:
                    logger.exception(f"图片解答发送失败（群 {group_id}）")
                    return
                if index < len(chunks) - 1:
                    await asyncio.sleep(0.5)

            _last_image_spoke[group_id] = time.time()
            _daily_images[group_id] = _daily_images.get(group_id, 0) + 1
            logger.info(f"图片解答 -> 群 {group_id}：{chunks[0][:80]}")
        finally:
            _image_speaking.discard(group_id)
    finally:
        _image_pending.discard(group_id)


def _pick_bot() -> Bot | None:
    return next(iter(nonebot.get_bots().values()), None)


async def _send_line(bot: Bot, group_id: int, line: str, *, at_qq: int | None = None) -> bool:
    global _daily_total

    text, sticker_id = stickers.parse_marker(line)
    if not text and sticker_id is None:
        return False

    if text:
        message = Message()
        if at_qq is not None:
            message += MessageSegment.at(at_qq) + Message(" ")
        message += Message(text)
        try:
            await bot.call_api("send_group_msg", group_id=group_id, message=message)
        except Exception:
            logger.exception(f"主动发言发送失败（群 {group_id}）")
            return False

    sticker = stickers.get(sticker_id) if stickers.enabled else None
    sticker_sent = False
    if sticker is not None and stickers.can_send(f"group:{group_id}"):
        await asyncio.sleep(0.3)
        sticker_sent = await stickers.send(bot, sticker, group_id=group_id)
        if sticker_sent:
            stickers.mark_sent(f"group:{group_id}")
            logger.info(f"主动发表情包 {sticker.id}（{sticker.description}）-> 群 {group_id}")
        elif not text:
            return False
    elif not text:
        return False

    _last_spoke[group_id] = time.time()
    _daily_by_group[group_id] = _daily_by_group.get(group_id, 0) + 1
    _daily_total += 1
    buffer.record(group_id, BOT_SPEAKER, text or "（发了一个表情包）")
    if text:
        suffix = f"（@ {at_qq}）" if at_qq is not None else ""
        logger.info(f"主动发言{suffix} -> 群 {group_id}：{text}")
    return True


_AT_RE = re.compile(r"\[AT:(\d+)\]", re.IGNORECASE)


def _extract_at(
    line: str,
    activities: list[Activity],
    self_id: str | int,
) -> tuple[str, int | None]:
    """从模型输出里取出 [AT:QQ]，只允许 @ 最近发过言的人，最多一个。"""
    markers = _AT_RE.findall(line)
    line = _AT_RE.sub("", line)
    line = re.sub(r"[ \t]{2,}", " ", line).strip()
    if not plugin_config.proactive_allow_at or not markers:
        return line, None

    allowed = {
        item.user_id
        for item in activities
        if item.user_id and not is_blocked(item.user_id) and str(item.user_id) != str(self_id)
    }
    for raw in markers:
        try:
            target = int(raw)
        except (TypeError, ValueError):
            continue
        if target in allowed:
            return line, target
    return line, None


async def _try_join(group_id: int, *, force: bool = False) -> None:
    if not plugin_config.proactive_enabled:
        return
    if plugin_config.proactive_mode != "conversation":
        return
    if group_id not in _state_groups:
        return
    if group_id in _speaking:
        return

    _roll_day()
    if in_quiet_hours(plugin_config.proactive_quiet_hours):
        return
    if _daily_total >= plugin_config.proactive_daily_limit_total:
        return
    if _daily_by_group.get(group_id, 0) >= plugin_config.proactive_daily_limit_per_group:
        return
    if not speaker.available():
        return

    now = time.time()
    min_interval = 5 if force else plugin_config.proactive_min_reply_interval_seconds
    if now - _last_spoke.get(group_id, 0.0) < min_interval:
        return

    activities = buffer.recent(
        group_id,
        minutes=plugin_config.proactive_window_minutes,
        limit=plugin_config.proactive_max_context_messages,
    )
    if len(activities) < (1 if force else plugin_config.proactive_min_messages):
        return
    if activities[-1].nickname == BOT_SPEAKER:
        return
    if not force and random.random() >= plugin_config.proactive_reply_probability:
        logger.info(f"主动接话跳过（群 {group_id}）：概率未命中")
        return
    logger.info(f"主动接话命中（群 {group_id}，点名={force}）：调用模型判断")

    bot = _pick_bot()
    if bot is None:
        return

    _speaking.add(group_id)
    try:
        started = time.perf_counter()
        try:
            line = await asyncio.wait_for(
                speaker.generate(group_id, _transcript(activities), kind="reply"),
                timeout=plugin_config.proactive_generate_timeout_seconds,
            )
        except TimeoutError:
            logger.warning(f"主动接话模型超时（群 {group_id}）")
            line = None
        logger.info(f"主动接话模型耗时 {time.perf_counter() - started:.2f}s（群 {group_id}）")
        if line is None:
            if not force:
                return
            line = "在。说事。"
        line, at_qq = _extract_at(line, activities, getattr(bot, "self_id", 0))
        if not line:
            return
        await asyncio.sleep(random.uniform(0.8, 1.8))
        await _send_line(bot, group_id, line, at_qq=at_qq)
    finally:
        _speaking.discard(group_id)


# ---------------------------------------------------------------------------
# 状态
# ---------------------------------------------------------------------------


def _roll_day() -> None:
    global _day, _daily_total, _daily_by_group
    today = datetime.now().strftime("%Y-%m-%d")
    if today != _day:
        _day = today
        _daily_total = 0
        _daily_by_group.clear()
        _daily_images.clear()


def _is_admin(event: MessageEvent) -> bool:
    try:
        superusers = {str(uid) for uid in nonebot.get_driver().config.superusers}
    except Exception:
        superusers = set()
    if str(event.user_id) in superusers:
        return True
    if isinstance(event, GroupMessageEvent):
        return getattr(event.sender, "role", None) in ("owner", "admin")
    return False


async def _load_state() -> None:
    global _state_groups
    groups = {int(gid) for gid in plugin_config.proactive_groups}

    if _STATE_PATH.exists():
        try:
            payload = json.loads(await asyncio.to_thread(_STATE_PATH.read_text, "utf-8"))
            for raw in payload.get("groups", []):
                try:
                    groups.add(int(raw))
                except (TypeError, ValueError):
                    continue
        except (OSError, ValueError) as exc:
            logger.warning(f"主动发言状态读取失败：{exc}")
    _state_groups = groups


async def _save_state() -> None:
    payload = {"groups": sorted(_state_groups), "updated_at": time.time()}
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE_PATH.with_suffix(".tmp")

    def _write() -> None:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, _STATE_PATH)

    try:
        await asyncio.to_thread(_write)
    except OSError as exc:
        logger.warning(f"主动发言状态写入失败：{exc}")


# ---------------------------------------------------------------------------
# 定时器（冷场起话 / 旧随机模式）
# ---------------------------------------------------------------------------


async def _loop() -> None:
    while True:
        await asyncio.sleep(plugin_config.proactive_check_interval_seconds)
        try:
            await _tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("主动发言定时检查异常")


async def _tick() -> None:
    if plugin_config.proactive_mode == "conversation":
        await _tick_initiative()
    else:
        await _tick_random()


async def _tick_initiative() -> None:
    global _daily_total

    if not plugin_config.proactive_enabled or not _state_groups:
        return

    _roll_day()
    buffer.purge()

    if in_quiet_hours(plugin_config.proactive_quiet_hours):
        return
    if _daily_total >= plugin_config.proactive_daily_limit_total:
        return
    if not speaker.available():
        return

    bot = _pick_bot()
    if bot is None:
        return

    groups = list(_state_groups)
    random.shuffle(groups)
    now = time.time()

    for group_id in groups:
        if group_id in _speaking:
            continue
        if _daily_by_group.get(group_id, 0) >= plugin_config.proactive_daily_limit_per_group:
            continue
        if now - _last_spoke.get(group_id, 0.0) < plugin_config.proactive_group_cooldown_minutes * 60:
            continue

        activities = buffer.last(group_id, limit=plugin_config.proactive_max_context_messages)
        if not activities:
            continue
        if now - activities[-1].at < plugin_config.proactive_initiative_after_minutes * 60:
            continue
        if len(activities) >= 2 and all(a.nickname == BOT_SPEAKER for a in activities[-2:]):
            continue
        if random.random() >= plugin_config.proactive_initiative_probability:
            continue

        _speaking.add(group_id)
        try:
            try:
                line = await asyncio.wait_for(
                    speaker.generate(group_id, _transcript(activities), kind="initiative"),
                    timeout=plugin_config.proactive_generate_timeout_seconds,
                )
            except TimeoutError:
                logger.warning(f"主动起话模型超时（群 {group_id}）")
                line = None
            if line is None:
                return
            line, at_qq = _extract_at(line, activities, getattr(bot, "self_id", 0))
            if not line:
                return
            await asyncio.sleep(random.uniform(0.8, 1.8))
            latest = buffer.last(group_id, limit=1)
            if latest and latest[-1].at > activities[-1].at:
                return
            if not await _send_line(bot, group_id, line, at_qq=at_qq):
                return
        finally:
            _speaking.discard(group_id)
        return


async def _tick_random() -> None:
    global _daily_total

    if not plugin_config.proactive_enabled or not _state_groups:
        return

    _roll_day()
    buffer.purge()

    if in_quiet_hours(plugin_config.proactive_quiet_hours):
        return
    if _daily_total >= plugin_config.proactive_daily_limit_total:
        return
    if not speaker.available():
        return

    bot = _pick_bot()
    if bot is None:
        return

    groups = list(_state_groups)
    random.shuffle(groups)
    now = time.time()

    for group_id in groups:
        if group_id in _speaking:
            continue
        if _daily_by_group.get(group_id, 0) >= plugin_config.proactive_daily_limit_per_group:
            continue
        if now - _last_spoke.get(group_id, 0.0) < plugin_config.proactive_group_cooldown_minutes * 60:
            continue

        activities = buffer.recent(
            group_id,
            minutes=plugin_config.proactive_window_minutes,
            limit=plugin_config.proactive_max_context_messages,
        )
        if len(activities) < plugin_config.proactive_min_messages:
            continue
        if random.random() >= plugin_config.proactive_probability:
            continue

        _speaking.add(group_id)
        try:
            line = await speaker.generate(group_id, _transcript(activities), kind="reply")
            if line is None:
                return
            if not await _send_line(bot, group_id, line):
                return
        finally:
            _speaking.discard(group_id)
        return


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------


_driver = get_driver()


@_driver.on_startup
async def _startup() -> None:
    global _task, _day
    await _load_state()
    _day = datetime.now().strftime("%Y-%m-%d")

    if not speaker.available():
        logger.warning("主动发言：未配置 LLM 凭据，插件不会自动发言。")

    if plugin_config.proactive_enabled:
        _task = asyncio.create_task(_loop(), name="proactive_chat")
        logger.info(
            "主动发言已启动：模式={mode}，{count} 个群，检查间隔 {interval}s，免打扰 {quiet}".format(
                mode=plugin_config.proactive_mode,
                count=len(_state_groups),
                interval=plugin_config.proactive_check_interval_seconds,
                quiet=plugin_config.proactive_quiet_hours or "无",
            )
        )
    else:
        logger.info("主动发言总开关关闭（PROACTIVE_ENABLED=false）")


@_driver.on_shutdown
async def _shutdown() -> None:
    global _task

    tasks = [task for task in _join_tasks.values() if not task.done()]
    tasks += [task for task in _image_tasks.values() if not task.done()]
    _join_tasks.clear()
    _image_tasks.clear()
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task

    _image_pending.clear()
    _image_speaking.clear()
    _pending_images.clear()

    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None

    _speaking.clear()


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------


proactive_cmd = on_command("proactive", aliases={"主动发言"}, priority=5, block=True)
sticker_cmd = on_command("sticker", aliases={"表情包", "发表情"}, priority=5, block=True)


@sticker_cmd.handle()
async def _handle_sticker(bot: Bot, event: MessageEvent, matcher: Matcher) -> None:
    if is_blocked(event.user_id):
        return
    if not stickers.enabled or not stickers.stickers:
        await matcher.finish("表情包库还没准备好。")
    key = (
        f"group:{event.group_id}"
        if isinstance(event, GroupMessageEvent)
        else f"private:{event.user_id}"
    )
    if not stickers.can_send(key):
        await matcher.finish("刚发过表情包，等一会儿再发。")
    sticker = random.choice(stickers.stickers)
    if isinstance(event, GroupMessageEvent):
        ok = await stickers.send(bot, sticker, group_id=event.group_id, reply_to=event.message_id)
    else:
        ok = await stickers.send(bot, sticker, user_id=event.user_id, reply_to=event.message_id)
    if not ok:
        await matcher.finish("表情包发送失败，看日志。")
    stickers.mark_sent(key)
    await matcher.finish(f"发了一个：{sticker.description}")


@proactive_cmd.handle()
async def _handle_command(
    bot: Bot,
    event: MessageEvent,
    matcher: Matcher,
    args: Message = CommandArg(),
) -> None:
    if is_blocked(event.user_id):
        return

    arg = args.extract_plain_text().strip().lower()

    if not isinstance(event, GroupMessageEvent):
        if arg in ("list", "列表") and _is_admin(event):
            groups = ", ".join(str(gid) for gid in sorted(_state_groups)) or "（空）"
            await matcher.finish(f"主动发言已开启的群：{groups}")
        await matcher.finish("在群里使用：/proactive status | on | off | test | id")

    group_id = event.group_id

    if arg in ("", "status", "状态"):
        activities = buffer.recent(group_id, minutes=plugin_config.proactive_window_minutes, limit=1000)
        cooldown = plugin_config.proactive_group_cooldown_minutes * 60
        last_spoke = _last_spoke.get(group_id)
        if last_spoke is None or time.time() - last_spoke >= cooldown:
            cooldown_text = "可发言"
        else:
            remaining = max(0, int(cooldown - (time.time() - last_spoke)))
            cooldown_text = f"{max(1, (remaining + 59) // 60)} 分钟"
        await matcher.finish(
            "主动发言：{state}\n"
            "模式：{mode}\n"
            "群号：{gid}\n"
            "最近 {window} 分钟：{count} 条消息\n"
            "本群今日：{used}/{limit}\n"
            "图片解题：{image_state}（今日 {image_used}/{image_limit}）\n"
            "冷却：{cooldown}".format(
                state="已开启" if group_id in _state_groups else "未开启",
                mode=plugin_config.proactive_mode,
                gid=group_id,
                window=plugin_config.proactive_window_minutes,
                count=len(activities),
                used=_daily_by_group.get(group_id, 0),
                limit=plugin_config.proactive_daily_limit_per_group,
                image_state="开" if plugin_config.proactive_image_enabled else "关",
                image_used=_daily_images.get(group_id, 0),
                image_limit=plugin_config.proactive_image_daily_limit_per_group,
                cooldown=cooldown_text,
            )
        )

    if arg in ("id", "群号"):
        await matcher.finish(f"本群群号：{group_id}")

    if arg in ("on", "开启", "off", "关闭"):
        if not _is_admin(event):
            await matcher.finish("只有群主/管理员能改这个设置。")
        if arg in ("on", "开启"):
            _state_groups.add(group_id)
            await _save_state()
            suffix = "" if plugin_config.proactive_enabled else "\n注意：总开关 PROACTIVE_ENABLED=false，当前不会自动发言。"
            await matcher.finish(f"✅ 已开启本群主动发言（{group_id}）。{suffix}")
        _state_groups.discard(group_id)
        await _save_state()
        await matcher.finish(f"已关闭本群主动发言（{group_id}）。")

    if arg in ("test", "试发"):
        if not _is_admin(event):
            await matcher.finish("只有群主/管理员能试发。")
        if not speaker.available():
            await matcher.finish("还没有配置 LLM 凭据，无法生成发言。")
        activities = buffer.recent(
            group_id,
            minutes=plugin_config.proactive_window_minutes,
            limit=plugin_config.proactive_max_context_messages,
        )
        if not activities:
            await matcher.finish("最近没有群聊记录，先在群里聊几句再试。")
        line = await speaker.generate(group_id, _transcript(activities), kind="reply")
        if line is None:
            await matcher.finish("模型判断现在不适合接话（SKIP），或请求失败；可以稍后再试。")
        try:
            await bot.call_api("send_group_msg", group_id=group_id, message=Message(line))
        except Exception:
            logger.exception("主动发言试发失败")
            await matcher.finish("生成成功但发送失败，请查看日志。")
        buffer.record(group_id, BOT_SPEAKER, line)
        await matcher.finish(f"✅ 试发：{line}")

    await matcher.finish(HELP_TEXT)
