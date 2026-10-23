"""国际新闻插件入口：/news 命令 + 每天纽约时间早 8 点的群里早报。"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from nonebot import get_bots, get_driver, get_plugin_config, logger, on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from plugins.common.access import event_is_allowed

from .config import Config
from .news import build_digest

plugin_config = get_plugin_config(Config)

_NY = ZoneInfo("America/New_York")


def _allowed(event: MessageEvent) -> bool:
    if not plugin_config.world_news_enabled:
        return False
    return event_is_allowed(
        event,
        allowed_users=plugin_config.world_news_allowed_users,
        allowed_groups=plugin_config.world_news_allowed_groups,
    )


news_cmd = on_command(
    "news",
    aliases={"今日新闻", "国际新闻", "外媒", "世界新闻"},
    rule=Rule(_allowed),
    priority=10,
    block=True,
)

_last_run: dict[int, float] = {}


@news_cmd.handle()
async def _handle_news(event: MessageEvent, matcher: Matcher) -> None:
    key = event.group_id if isinstance(event, GroupMessageEvent) else 0
    now = time.monotonic()
    cooldown = plugin_config.world_news_cooldown_seconds
    elapsed = now - _last_run.get(key, 0.0)
    if elapsed < cooldown:
        await matcher.finish(f"刚看过一轮外媒，歇 {int(cooldown - elapsed)} 秒再来。")
    _last_run[key] = now

    await matcher.send("📰 正在翻外媒头条，稍等…")
    digest = await build_digest()
    await matcher.finish(digest)


# ---------------------------------------------------------------------------
# 纽约早报：每天纽约时间早上到点，往配置的群里发一轮外媒汇总
# ---------------------------------------------------------------------------

_broadcast_task: asyncio.Task | None = None
_last_broadcast_day: str = ""


def _ny_now() -> datetime:
    return datetime.now(_NY)


def _broadcast_due(now: datetime, last_day: str, hour: int) -> bool:
    """纽约时间到点且这个纽约日还没播过才算到期；错过就等明天。"""
    return now.hour == hour and now.strftime("%Y-%m-%d") != last_day


async def _broadcast_once() -> int:
    digest = await build_digest(title="🗽 纽约每日新闻早报")
    bot = next(iter(get_bots().values()), None)
    if bot is None:
        return 0
    sent = 0
    for group_id in plugin_config.world_news_broadcast_groups:
        try:
            await bot.call_api("send_group_msg", group_id=int(group_id), message=digest)
            sent += 1
        except Exception:
            logger.warning(f"纽约早报发送失败（群 {group_id}）", exc_info=True)
        await asyncio.sleep(1.0)
    return sent


async def _broadcast_loop() -> None:
    global _last_broadcast_day
    while True:
        try:
            now = _ny_now()
            if _broadcast_due(
                now, _last_broadcast_day, plugin_config.world_news_broadcast_hour_ny
            ):
                # 先占坑：失败也别在这个钟点里反复重发
                _last_broadcast_day = now.strftime("%Y-%m-%d")
                try:
                    sent = await _broadcast_once()
                    logger.info(f"纽约早报已播报 {sent} 个群")
                except Exception:
                    logger.warning("纽约早报播报失败", exc_info=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("纽约早报循环异常", exc_info=True)
        await asyncio.sleep(1800)


_driver = get_driver()


@_driver.on_startup
async def _start_broadcast() -> None:
    global _broadcast_task
    if not plugin_config.world_news_enabled:
        return
    if not plugin_config.world_news_broadcast_enabled:
        return
    if not plugin_config.world_news_broadcast_groups:
        logger.info("未配置 WORLD_NEWS_BROADCAST_GROUPS，纽约早报不播报（/news 仍可用）")
        return
    _broadcast_task = asyncio.create_task(_broadcast_loop(), name="world_news_broadcast")
    logger.info(
        f"纽约早报已排班：每天纽约时间 "
        f"{plugin_config.world_news_broadcast_hour_ny} 点播报 "
        f"{len(plugin_config.world_news_broadcast_groups)} 个群"
    )
