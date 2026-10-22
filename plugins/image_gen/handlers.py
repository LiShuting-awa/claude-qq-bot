"""文生图插件：/draw <描述>，生成后把图片发回 QQ。"""

from __future__ import annotations

import asyncio
import base64
import random
import time
from datetime import date
from typing import Any
from urllib.parse import quote

import httpx2
from nonebot import get_plugin_config, logger, on_command
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

from plugins.common.access import event_is_allowed
from plugins.common.media import sniff_media_type as _sniff_media_type

from .config import Config

plugin_config = get_plugin_config(Config)
configure_blocked(plugin_config.blocked_users)

_last_request: dict[int, float] = {}
_daily_user: dict[int, int] = {}
_daily_total = 0
_day = date.today()

_BLOCKED = (
    "nsfw",
    "nude",
    "naked",
    "porn",
    "hentai",
    "sex",
    "gore",
    "裸",
    "色情",
    "性交",
    "做爱",
    "幼女",
    "儿童色情",
    "血腥",
    "分尸",
    "loli",
    "child porn",
)

HELP_TEXT = "🎨 用法：/draw 一只在雨里打伞的猫\n别名：/画图、/生成图片、/画一张"


def _allowed(event: MessageEvent) -> bool:
    return event_is_allowed(
        event,
        allowed_users=plugin_config.image_gen_allowed_users,
        allowed_groups=plugin_config.image_gen_allowed_groups,
    )


def _unsafe(prompt: str) -> bool:
    lowered = prompt.casefold()
    return any(word in lowered for word in _BLOCKED)


def _roll_day() -> None:
    global _day, _daily_total, _daily_user
    today = date.today()
    if today != _day:
        _day = today
        _daily_total = 0
        _daily_user.clear()


async def _generate(prompt: str) -> tuple[bytes, str]:
    base = plugin_config.image_gen_api_url.rstrip("/")
    url = f"{base}/{quote(prompt, safe='')}"
    params: dict[str, Any] = {
        "width": plugin_config.image_gen_width,
        "height": plugin_config.image_gen_height,
        "seed": random.randint(1, 2_000_000_000),
        "safe": "true",
    }
    if plugin_config.image_gen_model.strip():
        params["model"] = plugin_config.image_gen_model.strip()
    if plugin_config.image_gen_nologo:
        params["nologo"] = "true"

    timeout = httpx2.Timeout(plugin_config.image_gen_timeout_seconds, connect=15.0)
    last_error: Exception | None = None
    async with httpx2.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 QQBot/1.0"},
    ) as client:
        for attempt in range(1, 3):
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.content
                if not data:
                    raise ValueError("图片内容为空")
                if len(data) > 12 * 1024 * 1024:
                    raise ValueError("图片太大")
                media_type = _sniff_media_type(data)
                if media_type is None:
                    raise ValueError("返回的不是图片")
                return data, media_type
            except Exception as exc:
                last_error = exc
                if attempt == 1:
                    logger.warning(f"图片生成失败，重试一次：{exc}")
                    await asyncio.sleep(1.5)
        raise RuntimeError(f"图片生成失败：{last_error}")


draw_cmd = on_command(
    "draw",
    aliases={"画图", "生成图片", "画一张"},
    priority=5,
    block=True,
)


@draw_cmd.handle()
async def _handle_draw(
    bot: Bot,
    event: MessageEvent,
    matcher: Matcher,
    args: Message = CommandArg(),
) -> None:
    global _daily_total

    if is_blocked(event.user_id):
        return
    if not plugin_config.image_gen_enabled:
        await matcher.finish("图片生成功能已关闭。")
    if not _allowed(event):
        await matcher.finish("这个群/账号没有开启图片生成权限。")

    prompt = " ".join(args.extract_plain_text().split()).strip()
    if not prompt:
        await matcher.finish(HELP_TEXT)
    if len(prompt) > plugin_config.image_gen_max_prompt_chars:
        await matcher.finish(f"描述太长了，控制在 {plugin_config.image_gen_max_prompt_chars} 字以内。")
    if _unsafe(prompt):
        await matcher.finish("这个描述不适合生成，换一个。")

    _roll_day()
    now = time.time()
    cooldown = plugin_config.image_gen_cooldown_seconds
    if now - _last_request.get(event.user_id, 0.0) < cooldown:
        remaining = int(cooldown - (now - _last_request.get(event.user_id, 0.0))) + 1
        await matcher.finish(f"刚画过，等 {remaining} 秒再画。")
    if _daily_user.get(event.user_id, 0) >= plugin_config.image_gen_daily_limit_per_user:
        await matcher.finish("今天你画得够多了，明天再来。")
    if _daily_total >= plugin_config.image_gen_daily_limit_total:
        await matcher.finish("今天全局限额用完了，明天再来。")

    _last_request[event.user_id] = now
    await matcher.send("🎨 正在画，大约 5–15 秒…")

    try:
        data, media_type = await _generate(
            f"{prompt}, {plugin_config.image_gen_safety_suffix}".strip(", ")
        )
    except Exception as exc:
        logger.warning(f"图片生成请求失败：{exc}")
        await matcher.finish("画失败了，可能是生成服务暂时不可用，稍后再试。")

    _daily_user[event.user_id] = _daily_user.get(event.user_id, 0) + 1
    _daily_total += 1
    encoded = base64.b64encode(data).decode("ascii")
    message = MessageSegment.reply(event.message_id) + MessageSegment.image(
        f"base64://{encoded}"
    )
    logger.info(f"图片生成完成：{len(data)} bytes（{event.user_id}）")
    await matcher.finish(message)
