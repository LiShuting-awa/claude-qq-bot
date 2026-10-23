"""网图搜索插件：/img 关键词，搜网上的真实图片发回 QQ。"""

from __future__ import annotations

import asyncio
import time
from datetime import date

from nonebot import get_plugin_config, logger, on_command
from nonebot.adapters.onebot.v11 import (
    Bot,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from qqbot_filters import configure as configure_blocked
from qqbot_filters import is_blocked

from plugins.common.access import event_is_allowed

from .config import Config
from .search import collect_images, is_unsafe, search_images, send_image_bytes
from .verify import build_verify_fn

plugin_config = get_plugin_config(Config)
configure_blocked(plugin_config.blocked_users)
verify_fn = build_verify_fn(plugin_config)

_last_request: dict[int, float] = {}
_daily_user: dict[int, int] = {}
_daily_total = 0
_day = date.today()

HELP_TEXT = (
    "🖼 用法：/img 柴犬\n"
    "别名：/找图、/搜图。搜的是网上的真实图片，不是 AI 画；发之前会先核对内容对不对得上。"
)


def _allowed(event: MessageEvent) -> bool:
    return event_is_allowed(
        event,
        allowed_users=plugin_config.image_search_allowed_users,
        allowed_groups=plugin_config.image_search_allowed_groups,
    )


def _roll_day() -> None:
    global _day, _daily_total, _daily_user
    today = date.today()
    if today != _day:
        _day = today
        _daily_total = 0
        _daily_user.clear()


def _target(event: MessageEvent) -> tuple[int | None, int | None]:
    """返回 (group_id, user_id)：群里发群消息，私聊发私聊消息。"""
    group_id = getattr(event, "group_id", None)
    if group_id is not None:
        return group_id, None
    return None, event.user_id


img_cmd = on_command(
    "img",
    aliases={"找图", "搜图"},
    priority=5,
    block=True,
)


@img_cmd.handle()
async def _handle_img(
    bot: Bot,
    event: MessageEvent,
    matcher: Matcher,
    args: Message = CommandArg(),
) -> None:
    global _daily_total

    if is_blocked(event.user_id):
        return
    if not plugin_config.image_search_enabled:
        await matcher.finish("图片搜索功能已关闭。")
    if not _allowed(event):
        await matcher.finish("这个群/账号没有开启图片搜索权限。")

    query = " ".join(args.extract_plain_text().split()).strip()
    if not query:
        await matcher.finish(HELP_TEXT)
    if len(query) > 60:
        await matcher.finish("关键词太长了，控制在 60 字以内。")
    if is_unsafe(query):
        await matcher.finish("这个关键词不适合搜，换一个。")

    _roll_day()
    now = time.time()
    cooldown = plugin_config.image_search_cooldown_seconds
    if now - _last_request.get(event.user_id, 0.0) < cooldown:
        remaining = int(cooldown - (now - _last_request.get(event.user_id, 0.0))) + 1
        await matcher.finish(f"刚搜过，等 {remaining} 秒再搜。")
    if _daily_user.get(event.user_id, 0) >= plugin_config.image_search_daily_limit_per_user:
        await matcher.finish("今天你搜得够多了，明天再来。")
    if _daily_total >= plugin_config.image_search_daily_limit_total:
        await matcher.finish("今天全局限额用完了，明天再来。")

    _last_request[event.user_id] = now
    await matcher.send("🔍 搜图里，稍等…")

    try:
        hits = await search_images(
            query,
            limit=plugin_config.image_search_max_candidates,
            timeout=plugin_config.image_search_timeout_seconds,
            safe=plugin_config.image_search_safe_search,
        )
    except Exception as exc:
        logger.warning(f"图片搜索失败（{query}）：{exc}")
        await matcher.finish("搜索服务这会儿连不上，稍后再试。")

    if not hits:
        await matcher.finish("没搜到能用的图，换个说法试试。")

    max_bytes = int(plugin_config.image_search_max_file_mb * 1024 * 1024)
    images, had_rejections = await collect_images(
        query,
        hits,
        plugin_config.image_search_send_count,
        timeout=plugin_config.image_search_timeout_seconds,
        max_bytes=max_bytes,
        max_candidates=plugin_config.image_search_max_candidates,
        verify_fn=verify_fn,
    )
    if not images:
        if had_rejections:
            await matcher.finish(f"搜到的图都对不上「{query}」，换个更具体的说法试试。")
        await matcher.finish("图找到了但都下不动，换个说法再试。")

    group_id, user_id = _target(event)
    sent = 0
    for data, _media_type in images:
        ok = await send_image_bytes(
            bot,
            data=data,
            group_id=group_id,
            user_id=user_id,
            reply_to=event.message_id if sent == 0 else None,
        )
        if not ok:
            continue
        sent += 1
        if sent < len(images):
            await asyncio.sleep(0.4)

    if sent == 0:
        await matcher.finish("图找到了但都下不动，换个说法再试。")
    _daily_user[event.user_id] = _daily_user.get(event.user_id, 0) + 1
    _daily_total += 1
    logger.info(f"图片搜索完成：{query}，发送 {sent}/{len(hits)} 张（{event.user_id}）")
    await matcher.finish()
