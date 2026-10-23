"""说话学习插件：/learn_speech 从群聊记录里学大家的说话方式。"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path

from nonebot import get_driver, get_plugin_config, logger, on_command, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from qqbot_filters import configure as configure_blocked
from qqbot_filters import is_blocked

from .config import Config
from .learn import build_learner, collect_samples
from .log import SpeechLog
from .style import STYLE_PATH, remove_style, write_style

plugin_config = get_plugin_config(Config)
configure_blocked(plugin_config.blocked_users)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
log = SpeechLog(
    _PROJECT_ROOT / "data" / "speech_log",
    retention_days=plugin_config.speech_learn_retention_days,
)
learner = build_learner(plugin_config)

log.cleanup()

_last_learn = 0.0

HELP_TEXT = (
    "📖 用法：/learn_speech 分析最近的群聊记录，学大家怎么说话（群主/管理员）。\n"
    "/learn_speech off 停止参考学到的风格。\n"
    "平时每天也会自动学一次，不用手动来。"
)


def _is_group_admin(event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return True  # 私聊只有号主自己用，直接放行
    try:
        return getattr(event.sender, "role", None) in ("owner", "admin")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 群聊记录（跟着消息流静默落盘）
# ---------------------------------------------------------------------------

_recorder = on_message(priority=1, block=False)


@_recorder.handle()
async def _record_speech(event: MessageEvent) -> None:
    if not plugin_config.speech_learn_enabled:
        return
    if not isinstance(event, GroupMessageEvent):
        return
    if is_blocked(event.user_id):
        return
    if str(event.user_id) == str(event.self_id):
        return
    text = event.get_plaintext().strip()
    if not text or text.startswith("/"):
        return
    if "http://" in text or "https://" in text or len(text) > 300:
        return
    try:
        nickname = str(event.sender.card or event.sender.nickname or event.user_id)
    except Exception:
        nickname = str(event.user_id)
    try:
        log.append(event.group_id, event.user_id, nickname, text)
    except OSError:
        logger.warning("群聊记录写入失败", exc_info=True)


# ---------------------------------------------------------------------------
# /learn_speech 命令
# ---------------------------------------------------------------------------

learn_cmd = on_command("learn_speech", aliases={"学说话"}, priority=5, block=True)


@learn_cmd.handle()
async def _handle_learn(
    event: MessageEvent,
    matcher: Matcher,
    args: Message = CommandArg(),
) -> None:
    global _last_learn

    if is_blocked(event.user_id):
        return
    if not plugin_config.speech_learn_enabled:
        await matcher.finish("说话学习功能已关闭。")
    if not _is_group_admin(event):
        await matcher.finish("只有群主/管理员能让大家学习说话。")

    arg = " ".join(args.extract_plain_text().split()).lower()
    if arg in ("off", "关闭", "停"):
        removed = remove_style()
        await matcher.finish(
            "✅ 已停止参考学到的风格，回到人格文件本来的说话方式。"
            if removed
            else "还没有学过，不用停。"
        )
    if arg not in ("", "run", "开始", "学习"):
        await matcher.finish(HELP_TEXT)

    now = time.time()
    if now - _last_learn < plugin_config.speech_learn_cooldown_seconds:
        remaining = int(
            plugin_config.speech_learn_cooldown_seconds - (now - _last_learn)
        )
        await matcher.finish(f"刚学过，休息 {remaining} 秒再来。")

    records = log.recent(plugin_config.speech_learn_max_messages)
    samples = collect_samples(
        records,
        max_messages=plugin_config.speech_learn_max_messages,
        max_chars=plugin_config.speech_learn_max_sample_chars,
    )
    if len(samples) < plugin_config.speech_learn_min_messages:
        await matcher.finish(
            f"群聊记录还不够（可用 {len(samples)} 条，要 {plugin_config.speech_learn_min_messages} 条），"
            "先让我在群里多听几天。"
        )
    if learner is None:
        await matcher.finish("还没配置模型凭据，学不了。")

    _last_learn = now
    await matcher.send(f"📖 正在读最近 {len(samples)} 条群聊，学大家的说话方式，稍等…")

    persona = ""
    persona_path = _PROJECT_ROOT / "persona.md"
    try:
        persona = persona_path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("说话学习读 persona.md 失败，忽略人格上下文")

    try:
        style = await learner(persona, samples)
    except Exception as exc:
        logger.warning(f"说话学习失败：{exc}")
        await matcher.finish("学习这会儿没成功，稍后再试一次。")

    write_style(style)
    await matcher.finish(
        f"✅ 学完了：分析了 {len(samples)} 条群聊，风格档案 {len(style)} 字已存好。\n"
        "之后回话会参考大家的语气（学说话方式，不学身份）。"
    )


# ---------------------------------------------------------------------------
# 每日自动学说话（不用手动敲命令）
# ---------------------------------------------------------------------------

_auto_task: asyncio.Task | None = None
_last_auto_day: str = ""


def _auto_due(now: datetime, last_day: str, hour: int) -> bool:
    """到点且今天还没学过就算到期；错过这个钟点就等明天。"""
    return now.hour == hour and now.strftime("%Y-%m-%d") != last_day


async def _auto_learn_once() -> str:
    """跑一次自动学习，返回结果摘要；记录不够时直接说明并跳过。"""
    records = log.recent(plugin_config.speech_learn_max_messages)
    samples = collect_samples(
        records,
        max_messages=plugin_config.speech_learn_max_messages,
        max_chars=plugin_config.speech_learn_max_sample_chars,
    )
    if len(samples) < plugin_config.speech_learn_min_messages:
        return (
            f"跳过：可用记录 {len(samples)} 条，"
            f"不够 {plugin_config.speech_learn_min_messages} 条"
        )
    persona = ""
    try:
        persona = (_PROJECT_ROOT / "persona.md").read_text(encoding="utf-8")
    except OSError:
        logger.warning("自动学说话读 persona.md 失败，忽略人格上下文")
    style = await learner(persona, samples)
    write_style(style)
    return f"分析了 {len(samples)} 条群聊，风格档案 {len(style)} 字"


async def _auto_learn_loop() -> None:
    global _last_auto_day
    while True:
        try:
            now = datetime.now()
            if _auto_due(now, _last_auto_day, plugin_config.speech_learn_auto_hour):
                # 先占坑再学：失败也别在同一个钟点里反复重试
                _last_auto_day = now.strftime("%Y-%m-%d")
                try:
                    result = await _auto_learn_once()
                    logger.info(f"自动学说话：{result}")
                except Exception:
                    logger.warning("自动学说话失败", exc_info=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("自动学说话循环异常", exc_info=True)
        await asyncio.sleep(1800)


_speech_driver = get_driver()


@_speech_driver.on_startup
async def _start_auto_learn() -> None:
    global _auto_task
    if not plugin_config.speech_learn_auto_enabled:
        return
    if learner is None:
        logger.info("未配置模型凭据，自动学说话不启动")
        return
    _auto_task = asyncio.create_task(_auto_learn_loop(), name="speech_learn_auto")
    logger.info(
        "自动学说话已启动：每天 "
        f"{plugin_config.speech_learn_auto_hour} 点前后用最近群聊更新风格档案"
    )
