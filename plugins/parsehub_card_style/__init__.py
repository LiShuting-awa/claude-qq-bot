"""把 ParseHub 的封面式卡片换成更接近原来的白底简介卡。

不改 nonebot-plugin-parsehub 的解析和投递，只在启动时替换它的
``card.layout.render``：解析结果、封面、字体缓存和发送流程都保持原样。
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from nonebot import get_driver, logger
from PIL import Image, ImageDraw, ImageFont, ImageOps

WIDTH = 800
MARGIN = 40
COVER_H = 380
TITLE_SIZE = 40
BODY_SIZE = 24
SMALL_SIZE = 22

_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    text = (text or "").replace("\r", "").strip()
    if not text:
        return []
    lines: list[str] = []
    current = ""
    for char in text:
        if char == "\n":
            if current:
                lines.append(current)
                current = ""
            if len(lines) >= max_lines:
                break
            continue
        trial = current + char
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
            continue
        if current:
            lines.append(current)
        current = char
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if lines and len("".join(lines)) < len(text):
        lines[-1] = lines[-1].rstrip("…") + "…"
    return lines


def _duration(result: Any) -> str:
    media = getattr(result, "media", None)
    items = list(media) if isinstance(media, (list, tuple)) else [media]
    seconds = max((getattr(item, "duration", 0) or 0 for item in items), default=0)
    if not seconds:
        return ""
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _cover(cover: bytes, width: int, height: int) -> tuple[Image.Image, Image.Image]:
    image = Image.open(io.BytesIO(cover)).convert("RGB")
    image = ImageOps.fit(
        image,
        (width, height),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, width, height), radius=18, fill=255
    )
    return image, mask


def _title_of(result: Any) -> str:
    title = str(getattr(result, "title", "") or "").strip()
    if title:
        return title
    return "无标题"


def _platform_of(result: Any) -> str:
    platform = getattr(result, "platform", None)
    return str(getattr(platform, "display_name", "") or "视频")


def _type_of(result: Any) -> str:
    kind = getattr(result, "type", None)
    value = str(getattr(kind, "value", kind) or "").lower()
    return {"video": "视频", "image": "图集"}.get(value, "媒体")


def _render(result: Any, cover: bytes, out_path: Path) -> bool:
    font_title = _font(TITLE_SIZE)
    font_body = _font(BODY_SIZE)
    font_small = _font(SMALL_SIZE)

    probe = Image.new("RGB", (WIDTH, 10), "white")
    draw = ImageDraw.Draw(probe)
    title_lines = _wrap(draw, _title_of(result), font_title, WIDTH - 2 * MARGIN, 3)
    content = str(getattr(result, "content", "") or "").strip()
    if not content:
        content = ""
    body_lines = _wrap(draw, content, font_body, WIDTH - 2 * MARGIN, 3) if content else []

    header_y = 32
    title_y = header_y + 48
    title_height = len(title_lines) * 52
    cover_y = title_y + title_height + 18
    body_y = cover_y + COVER_H + 22
    body_height = len(body_lines) * 34
    footer_y = body_y + body_height + 22
    height = footer_y + 46

    card = Image.new("RGB", (WIDTH, height), "white")
    draw = ImageDraw.Draw(card)
    ink = (28, 28, 30)
    muted = (120, 120, 126)

    platform = _platform_of(result)
    type_label = _type_of(result)
    duration = _duration(result)
    meta = f"{platform} · {type_label}"
    if duration:
        meta += f" · {duration}"
    draw.text((MARGIN, header_y), platform, font=font_small, fill=ink)
    right = type_label + (f" · {duration}" if duration else "")
    right_w = draw.textlength(right, font=font_small)
    draw.text((WIDTH - MARGIN - right_w, header_y), right, font=font_small, fill=muted)

    y = title_y
    for line in title_lines:
        draw.text((MARGIN, y), line, font=font_title, fill=ink)
        y += 52

    cover_img, mask = _cover(cover, WIDTH - 2 * MARGIN, COVER_H)
    card.paste(cover_img, (MARGIN, cover_y), mask)

    y = body_y
    for line in body_lines:
        draw.text((MARGIN, y), line, font=font_body, fill=(66, 66, 70))
        y += 34

    draw.line(
        (MARGIN, footer_y - 10, WIDTH - MARGIN, footer_y - 10),
        fill=(236, 236, 238),
        width=1,
    )
    footer = "Claude · 帮你看过了"
    draw.text((MARGIN, footer_y + 2), footer, font=font_small, fill=muted)
    domain = ""
    raw_url = str(getattr(result, "raw_url", "") or "")
    if "://" in raw_url:
        domain = raw_url.split("://", 1)[1].split("/", 1)[0]
    if domain:
        domain_w = draw.textlength(domain, font=font_small)
        draw.text(
            (WIDTH - MARGIN - domain_w, footer_y + 2),
            domain,
            font=font_small,
            fill=muted,
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    card.save(out_path, "JPEG", quality=92, optimize=True)
    return True


def render_card(result: Any, cover: bytes, out_path: Path) -> bool:
    try:
        return _render(result, cover, out_path)
    except Exception as exc:
        logger.warning(f"Claude 简介卡渲染失败：{type(exc).__name__}: {exc}")
        return False


@get_driver().on_startup
def _install_card_style() -> None:
    try:
        from nonebot_plugin_parsehub.card import layout

        layout.render = render_card
        logger.info("ParseHub 卡片已切换为 Claude 白底简介卡")
    except Exception:
        logger.exception("切换 ParseHub 卡片样式失败")
