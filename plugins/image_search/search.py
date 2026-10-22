"""网图搜索核心：Bing + 搜谷双源检索、下载校验、[IMG:] 标记解析。

本模块保持与 NoneBot 插件机制解耦（只依赖 logger），可被 claude_chat 直接导入复用。
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx2
from bs4 import BeautifulSoup
from nonebot import logger

from plugins.common.network import host_is_private

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
}

# 与 image_gen 插件保持同一套底线词表
UNSAFE_WORDS = (
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

_IMG_MARKER = re.compile(r"\[IMG\s*[:：]\s*([^\[\]\n]{0,80})\]", re.IGNORECASE)


@dataclass(slots=True)
class ImageHit:
    image_url: str
    page_url: str = ""
    title: str = ""
    width: int = 0
    height: int = 0
    referer: str = ""
    source: str = ""


def is_unsafe(query: str) -> bool:
    lowered = (query or "").casefold()
    return any(word in lowered for word in UNSAFE_WORDS)


def parse_img_marker(text: str) -> tuple[str, str]:
    """从回复文本里取出 [IMG:搜索词] 标记：返回（去掉标记的正文, 搜索词）。"""
    match = _IMG_MARKER.search(text or "")
    query = ""
    if match:
        query = " ".join(match.group(1).split()).strip()[:60]
    cleaned = _IMG_MARKER.sub(" ", text or "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned, query


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_bing(html_text: str, limit: int = 24) -> list[ImageHit]:
    """解析 Bing 图片搜索结果页：a.iusc 的 m 属性是 JSON，murl 是原图直链。"""
    soup = BeautifulSoup(html_text, "lxml")
    hits: list[ImageHit] = []
    for anchor in soup.select("a.iusc"):
        try:
            meta = json.loads(anchor.get("m") or "")
        except (TypeError, ValueError):
            continue
        if not isinstance(meta, dict):
            continue
        image_url = str(meta.get("murl") or "").strip()
        if not image_url.startswith(("http://", "https://")):
            continue
        hits.append(
            ImageHit(
                image_url=image_url,
                page_url=str(meta.get("purl") or "").strip(),
                title=_clean_text(str(meta.get("t") or ""))[:120],
                referer="https://www.bing.com/",
                source="bing",
            )
        )
        if len(hits) >= limit:
            break
    return hits


def parse_sogou(payload: dict, limit: int = 24) -> list[ImageHit]:
    """解析搜狗图片 searchList JSON：oriPicUrl 是原图，picUrl 是缩略图。"""
    items = []
    try:
        items = (payload.get("data") or {}).get("items") or []
    except AttributeError:
        return []
    hits: list[ImageHit] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        image_url = str(item.get("oriPicUrl") or item.get("picUrl") or "").strip()
        if not image_url.startswith(("http://", "https://")):
            continue
        try:
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
        except (TypeError, ValueError):
            width = height = 0
        hits.append(
            ImageHit(
                image_url=image_url,
                page_url=str(item.get("linkUrl") or "").strip(),
                title=_clean_text(str(item.get("title") or ""))[:120],
                width=max(0, width),
                height=max(0, height),
                referer="https://pic.sogou.com/",
                source="sogou",
            )
        )
        if len(hits) >= limit:
            break
    return hits


async def _assert_public(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("只支持 http/https 图片地址")
    if await asyncio.to_thread(host_is_private, parsed.hostname):
        raise ValueError("内网/本机地址不允许抓取")


async def _bing_images(query: str, limit: int, timeout: float, safe: bool) -> list[ImageHit]:
    params: dict[str, str] = {
        "q": query,
        "first": "1",
        "count": str(min(35, limit + 10)),
        "mkt": "zh-CN",
    }
    if safe:
        params["adlt"] = "strict"
    async with httpx2.AsyncClient(
        timeout=timeout, follow_redirects=True, headers=_HEADERS
    ) as client:
        response = await client.get("https://www.bing.com/images/search", params=params)
        response.raise_for_status()
        return parse_bing(response.text, limit=limit)


async def _sogou_images(query: str, limit: int, timeout: float) -> list[ImageHit]:
    params = {
        "mode": "1",
        "start": "0",
        "xml_len": str(min(48, limit + 10)),
        "query": query,
    }
    async with httpx2.AsyncClient(
        timeout=timeout, follow_redirects=True, headers=_HEADERS
    ) as client:
        response = await client.get("https://pic.sogou.com/napi/pc/searchList", params=params)
        response.raise_for_status()
        return parse_sogou(response.json(), limit=limit)


async def search_images(
    query: str,
    *,
    limit: int = 24,
    timeout: float = 15,
    safe: bool = True,
) -> list[ImageHit]:
    """并行检索 Bing + 搜狗，按顺序合并去重；两边都失败时抛出最后一个异常。"""
    query = " ".join(query.split()).strip()[:100]
    if not query:
        return []

    raw = await asyncio.gather(
        asyncio.create_task(_bing_images(query, limit, timeout, safe)),
        asyncio.create_task(_sogou_images(query, limit, timeout)),
        return_exceptions=True,
    )
    merged: list[ImageHit] = []
    errors: list[Exception] = []
    for group in raw:
        if isinstance(group, BaseException):
            if not isinstance(group, asyncio.CancelledError):
                errors.append(group)
            continue
        merged.extend(group)

    seen: set[str] = set()
    output: list[ImageHit] = []
    for hit in merged:
        key = hit.image_url.split("#", 1)[0]
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(hit)
        if len(output) >= limit:
            break
    if not output and errors:
        raise RuntimeError(f"图片搜索失败：{errors[0]}")
    return output


def _normalize_image(data: bytes, max_side: int = 4096) -> tuple[bytes, str] | None:
    """校验图片内容；webp/冷门格式转成 png/jpg，超大边降采样，动图 gif 原样保留。"""
    sniffed = None
    if data.startswith(b"\xff\xd8\xff"):
        sniffed = "image/jpeg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        sniffed = "image/png"
    elif data[:6] in (b"GIF87a", b"GIF89a"):
        sniffed = "image/gif"

    if sniffed in ("image/jpeg", "image/png", "image/gif"):
        return data, sniffed
    if not data:
        return None

    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if max(image.size) > max_side:
                image.thumbnail((max_side, max_side))
            out = io.BytesIO()
            if image.mode in ("RGBA", "LA", "P"):
                image.save(out, "PNG")
                return out.getvalue(), "image/png"
            image.convert("RGB").save(out, "JPEG", quality=90)
            return out.getvalue(), "image/jpeg"
    except Exception:
        return None


async def _download_one(
    client: httpx2.AsyncClient,
    url: str,
    *,
    max_bytes: int,
    referer: str = "",
) -> bytes | None:
    await _assert_public(url)
    headers = {"User-Agent": _UA}
    if referer:
        headers["Referer"] = referer
    response = await client.get(url, headers=headers)
    if response.status_code >= 400:
        return None
    final = str(response.url)
    await _assert_public(final)
    data = response.content
    if not data or len(data) > max_bytes:
        return None
    return data


async def fetch_image_bytes(
    url: str,
    *,
    referer: str = "",
    timeout: float = 12,
    max_bytes: int = 8 * 1024 * 1024,
) -> tuple[bytes, str]:
    """下载原图并校验；先不带 Referer 试一次，失败再带上引擎 Referer 绕防盗链。"""
    await _assert_public(url)
    async with httpx2.AsyncClient(
        timeout=timeout, follow_redirects=True
    ) as client:
        data = await _download_one(client, url, max_bytes=max_bytes)
        if data is None and referer:
            data = await _download_one(client, url, max_bytes=max_bytes, referer=referer)
    if data is None:
        raise RuntimeError("图片下载失败")
    normalized = await asyncio.to_thread(_normalize_image, data)
    if normalized is None:
        raise RuntimeError("返回的内容不是图片")
    return normalized


async def download_hit(
    hit: ImageHit,
    *,
    timeout: float = 12,
    max_bytes: int = 8 * 1024 * 1024,
) -> tuple[bytes, str]:
    return await fetch_image_bytes(
        hit.image_url,
        referer=hit.referer,
        timeout=timeout,
        max_bytes=max_bytes,
    )


async def send_image_bytes(
    bot,
    *,
    data: bytes,
    group_id: int | None = None,
    user_id: int | None = None,
    reply_to: int | None = None,
) -> bool:
    """把一张图片（bytes）发到群或私聊；成功返回 True。"""
    from nonebot.adapters.onebot.v11 import MessageSegment

    encoded = base64.b64encode(data).decode("ascii")
    segment = MessageSegment.image(f"base64://{encoded}")
    if reply_to is not None:
        segment = MessageSegment.reply(reply_to) + segment
    try:
        if group_id is not None:
            await bot.call_api("send_group_msg", group_id=group_id, message=segment)
        elif user_id is not None:
            await bot.call_api("send_private_msg", user_id=user_id, message=segment)
        else:
            return False
    except Exception:
        logger.exception("图片发送失败")
        return False
    return True
