"""点歌语音：群里说「来一首 xxx」或发 /点歌，搜到歌就转成语音消息发回来。"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import date
from pathlib import Path

import httpx
from nonebot import get_plugin_config, logger, on_command, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import Rule

from plugins.common.access import event_is_allowed
from qqbot_filters import is_blocked

from . import music
from .config import Config

plugin_config = get_plugin_config(Config)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = Path(plugin_config.music_cache_dir) if plugin_config.music_cache_dir else (
    _PROJECT_ROOT / "data" / "music_cache"
)

# 「来一首晴天」「放首歌 稻香」这类口令；带 / 的走命令，不在这里抢
_AUTO_RE = re.compile(
    r"^(?:来一首|来首歌|放一首|放首歌|播一首|点一首|点歌|点播)[\s:：,，]?(?P<title>.{1,60})$"
)

_last_request: dict[int, float] = {}
_daily_user: dict[int, int] = {}
_recent_songs: dict[tuple[str, str], float] = {}
_day = date.today()


def _parse_auto_title(text: str) -> str:
    match = _AUTO_RE.match(text.strip())
    if not match:
        return ""
    title = match.group("title").strip().strip("，,。.！!？?～~ ")
    # 口令后面跟链接、或者只剩个语气词，都不是真的要点歌
    if not title or "http" in title.lower() or title in {"吧", "啊", "哦", "呢", "吗"}:
        return ""
    return title


def _cache_cleanup() -> None:
    """清掉过期缓存；顺手做，点歌时才触发。"""
    hours = plugin_config.music_cache_hours
    if hours <= 0 or not _CACHE_DIR.is_dir():
        return
    deadline = time.time() - hours * 3600
    for item in _CACHE_DIR.iterdir():
        try:
            if item.is_file() and item.stat().st_mtime < deadline:
                item.unlink()
        except OSError:
            continue


def _roll_day() -> None:
    global _day
    today = date.today()
    if today != _day:
        _day = today
        _daily_user.clear()


def _allowed(event: MessageEvent) -> bool:
    return event_is_allowed(
        event,
        allowed_users=plugin_config.music_allowed_users,
        allowed_groups=plugin_config.music_allowed_groups,
    )


def _chat_key(event: MessageEvent) -> str:
    if isinstance(event, GroupMessageEvent):
        return f"group:{event.group_id}"
    return f"private:{event.user_id}"


def _mark_recent(event: MessageEvent, song_key: str) -> None:
    dedup = plugin_config.music_dedup_seconds
    if dedup <= 0:
        return
    key = (_chat_key(event), song_key)
    _recent_songs[key] = time.time()
    if len(_recent_songs) > 300:
        for old_key, _ in sorted(_recent_songs.items(), key=lambda item: item[1])[:100]:
            _recent_songs.pop(old_key, None)


def _is_recent(event: MessageEvent, song_key: str) -> bool:
    dedup = plugin_config.music_dedup_seconds
    if dedup <= 0:
        return False
    key = (_chat_key(event), song_key)
    recent = time.time() - _recent_songs.get(key, 0.0) < dedup
    if recent:
        return True
    _recent_songs.pop(key, None)
    return False


async def _run_request(event: MessageEvent, matcher: Matcher, title: str, *, auto: bool) -> None:
    _roll_day()
    now = time.time()
    cooldown = plugin_config.music_cooldown_seconds
    if now - _last_request.get(event.user_id, 0.0) < cooldown:
        if auto:
            return
        remaining = int(cooldown - (now - _last_request.get(event.user_id, 0.0))) + 1
        await matcher.finish(f"刚点过，等 {remaining} 秒。")
    if _daily_user.get(event.user_id, 0) >= plugin_config.music_daily_limit_per_user:
        await matcher.finish("今天点的歌够多了，明天再来。")

    timeout = float(plugin_config.music_timeout_seconds)
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 QQBot/1.0"},
        follow_redirects=True,
    ) as client:
        try:
            candidates = await music.search_songs(
                client,
                api_base=plugin_config.music_api_base,
                keyword=title,
                source=plugin_config.music_source,
                count=plugin_config.music_search_count,
            )
        except music.MusicApiError as exc:
            logger.warning(f"点歌搜索失败：{exc}")
            await matcher.finish(f"没搜到「{title}」，换个别名试试。")

        if not candidates:
            await matcher.finish(f"没搜到「{title}」。")

        # 按匹配度逐个取直链，前几首拿不到（比如要会员）就顺延下一首
        song = None
        audio_url = ""
        for candidate in sorted(
            candidates,
            key=lambda item: -_candidate_score(item, title),
        )[:3]:
            try:
                link = await music.fetch_song_url(
                    client,
                    api_base=plugin_config.music_api_base,
                    source=plugin_config.music_source,
                    song_id=str(candidate.get("id")),
                    bitrate=plugin_config.music_bitrate,
                )
            except music.MusicApiError as exc:
                logger.warning(f"点歌取链失败：{exc}")
                continue
            if link.get("url"):
                song, audio_url = candidate, str(link["url"])
                break
        if song is None:
            await matcher.finish("这首要会员或者下架了，换首吧。")

        song_key = f"{plugin_config.music_source}:{song.get('id')}"
        if _is_recent(event, song_key):
            if auto:
                return
            await matcher.finish("这首刚放过，换个别的吧。")

        _last_request[event.user_id] = now
        _daily_user[event.user_id] = _daily_user.get(event.user_id, 0) + 1
        _mark_recent(event, song_key)

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(_cache_cleanup)
        cached = _CACHE_DIR / f"{plugin_config.music_source}_{song.get('id')}.mp3"

        try:
            if not cached.exists() or cached.stat().st_size == 0:
                raw = cached.with_suffix(".raw")
                await music.download_to(
                    client,
                    url=audio_url,
                    dest=raw,
                    max_bytes=plugin_config.music_max_mb * 1024 * 1024,
                    timeout=timeout,
                )
                # 统一转成 mp3，顺带把太长的截掉，NapCat 那边就能直接发语音
                duration = await asyncio.to_thread(music.probe_duration, raw)
                trim = None
                max_seconds = plugin_config.music_max_duration_seconds
                if duration and duration > max_seconds:
                    trim = float(max_seconds)
                    logger.info(f"点歌超长截断：{music.song_label(song)} {duration:.0f}s -> {max_seconds}s")
                await asyncio.to_thread(music.ensure_mp3, raw, cached, trim_seconds=trim)
                if raw != cached:
                    raw.unlink(missing_ok=True)
        except music.MusicApiError as exc:
            logger.warning(f"点歌下载失败：{exc}")
            await matcher.finish(str(exc))
        except Exception as exc:
            logger.warning(f"点歌处理失败：{exc}")
            await matcher.finish("下载失败了，等会儿再试。")

    logger.info(f"点歌发送：{music.song_label(song)} -> {_chat_key(event)}")
    await matcher.send(f"🎵 {music.song_label(song)}")
    await matcher.finish(MessageSegment.record(f"file:///{cached.as_posix()}"))


def _candidate_score(item: dict, query: str) -> float:
    """和 pick_song 同一套打分；这里只为排序取前三首试链接。"""
    return music.song_score(item, query)


song_cmd = on_command(
    "点歌",
    aliases={"点播", "music"},
    priority=5,
    block=True,
)


@song_cmd.handle()
async def _handle_command(
    event: MessageEvent,
    matcher: Matcher,
    args: Message = CommandArg(),
) -> None:
    if is_blocked(event.user_id):
        return
    if not plugin_config.music_voice_enabled:
        await matcher.finish("点歌功能已关闭。")
    if not _allowed(event):
        await matcher.finish("这个群/账号没有点歌权限。")
    title = args.extract_plain_text().strip()
    if not title:
        await matcher.finish("用法：/点歌 歌名（也可以直接说「来一首 xxx」）")
    await _run_request(event, matcher, title, auto=False)


def _plain_text_ignoring_at(event: MessageEvent) -> str:
    """取纯文本，忽略指向机器人的 @；@着机器人点歌也当口令处理。"""
    self_id = str(event.self_id)
    for seg in event.get_message():
        if seg.type == "at" and str(seg.data.get("qq", "")) != self_id:
            # @了别人再带口令的，不抢
            return ""
        if seg.type not in ("text", "at"):
            return ""
    return event.get_plaintext().strip()


def _auto_rule(event: MessageEvent) -> bool:
    if not plugin_config.music_voice_enabled or not plugin_config.music_auto_enabled:
        return False
    if is_blocked(event.user_id):
        return False
    if str(event.user_id) == str(event.self_id):
        return False
    if isinstance(event, GroupMessageEvent):
        if plugin_config.music_auto_groups and event.group_id not in plugin_config.music_auto_groups:
            return False
    if not _allowed(event):
        return False
    text = _plain_text_ignoring_at(event)
    if not text or text.startswith("/"):
        return False
    return bool(_parse_auto_title(text))


# claude_chat 的闲聊监听在 priority 20，自动点歌要排在它前面把口令截下来
music_auto = on_message(rule=Rule(_auto_rule), priority=15, block=True)


@music_auto.handle()
async def _handle_auto(event: MessageEvent, matcher: Matcher) -> None:
    title = _parse_auto_title(_plain_text_ignoring_at(event))
    if not title:
        return
    await _run_request(event, matcher, title, auto=True)
