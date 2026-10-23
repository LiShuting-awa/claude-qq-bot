"""网图搜索核心：Bing + 360 + 百度 + Wallhaven + Openverse + Safebooru 六源检索、
下载去重与内容核对、[IMG:] 标记解析。

本模块保持与 NoneBot 插件机制解耦（只依赖 logger），可被 claude_chat 直接导入复用。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html
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
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


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


def parse_so(payload: dict, limit: int = 24) -> list[ImageHit]:
    """解析 360 图片（image.so.com/j）JSON：img 是原图，link 是来源页。"""
    items = []
    try:
        items = payload.get("list") or []
    except AttributeError:
        return []
    hits: list[ImageHit] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        image_url = str(item.get("img") or item.get("_thumb") or "").strip()
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
                page_url=str(item.get("link") or "").strip(),
                title=_clean_text(str(item.get("title") or ""))[:120],
                width=max(0, width),
                height=max(0, height),
                referer="https://image.so.com/",
                source="360",
            )
        )
        if len(hits) >= limit:
            break
    return hits


def parse_baidu(text: str, limit: int = 24) -> list[ImageHit]:
    """解析百度图片 acjson：middleURL/thumbURL 是百度 CDN 直链，带 /*?*/ 前缀要剥掉。"""
    text = text or ""
    start = text.find("{")
    if start < 0:
        return []
    try:
        payload, _ = json.JSONDecoder().raw_decode(text, start)
    except ValueError:
        return []
    items = payload.get("data")
    if not isinstance(items, list):
        return []
    hits: list[ImageHit] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        image_url = str(
            item.get("middleURL") or item.get("thumbURL") or item.get("hoverURL") or ""
        ).strip()
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
                page_url=str(item.get("fromURL") or "").strip(),
                title=_clean_text(str(item.get("fromPageTitle") or ""))[:120],
                width=max(0, width),
                height=max(0, height),
                referer="https://image.baidu.com/",
                source="baidu",
            )
        )
        if len(hits) >= limit:
            break
    return hits


def _safe_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def parse_wallhaven(payload: dict, limit: int = 24) -> list[ImageHit]:
    """解析 Wallhaven API JSON：path 是原图直链，tags 拼标题。"""
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    hits: list[ImageHit] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        image_url = str(item.get("path") or "").strip()
        if not image_url.startswith(("http://", "https://")):
            continue
        tags = " ".join(
            str(tag.get("name") or "").strip()
            for tag in (item.get("tags") or [])[:4]
            if isinstance(tag, dict)
        ).strip()
        hits.append(
            ImageHit(
                image_url=image_url,
                page_url=str(item.get("source") or item.get("url") or "").strip(),
                title=tags[:120],
                width=_safe_int(item.get("dimension_x")),
                height=_safe_int(item.get("dimension_y")),
                referer="https://wallhaven.cc/",
                source="wallhaven",
            )
        )
        if len(hits) >= limit:
            break
    return hits


def parse_openverse(payload: dict, limit: int = 24) -> list[ImageHit]:
    """解析 Openverse API JSON：url 是原图直链（多为 Flickr 等 CC 图源）。"""
    items = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    hits: list[ImageHit] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        image_url = str(item.get("url") or "").strip()
        if not image_url.startswith(("http://", "https://")):
            continue
        hits.append(
            ImageHit(
                image_url=image_url,
                page_url=str(item.get("foreign_landing_url") or "").strip(),
                title=_clean_text(str(item.get("title") or ""))[:120],
                width=_safe_int(item.get("width")),
                height=_safe_int(item.get("height")),
                source="openverse",
            )
        )
        if len(hits) >= limit:
            break
    return hits


def parse_safebooru(posts, limit: int = 24) -> list[ImageHit]:
    """解析 Safebooru dapi JSON：directory+image 拼原图直链，本身就是全龄内容。"""
    if not isinstance(posts, list):
        return []
    hits: list[ImageHit] = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        name = str(post.get("image") or "").strip()
        directory = str(post.get("directory") or "").strip()
        if not name or not directory:
            continue
        image_url = f"https://safebooru.org/images/{directory}/{name}"
        post_id = str(post.get("id") or "").strip()
        hits.append(
            ImageHit(
                image_url=image_url,
                page_url=(
                    f"https://safebooru.org/index.php?page=post&s=view&id={post_id}"
                    if post_id
                    else ""
                ),
                title=_clean_text(str(post.get("tags") or ""))[:120],
                width=_safe_int(post.get("width")),
                height=_safe_int(post.get("height")),
                referer="https://safebooru.org/",
                source="safebooru",
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
    # Bing 会按 IP 临时墙掉自动化流量（返回无结果的空壳页）；搜狗则对非浏览器流量
    # 一律 forbid。所以 Bing 只当尽力而为的一路，空了不报错；实测 2026-10 桌面/移动
    # UA 在部分网络下都被墙，届时靠其余五路顶上。
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


async def _so_images(query: str, limit: int, timeout: float) -> list[ImageHit]:
    params = {"q": query, "src": "srp", "pn": str(min(60, limit + 10)), "sn": "0"}
    async with httpx2.AsyncClient(
        timeout=timeout, follow_redirects=True, headers=_HEADERS
    ) as client:
        response = await client.get("https://image.so.com/j", params=params)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            # 无结果时 360 有时回非 JSON 空响应，当作没搜到而不是故障
            return []
        return parse_so(payload, limit=limit)


async def _baidu_images(query: str, limit: int, timeout: float) -> list[ImageHit]:
    params = {
        "tn": "resultjson_com",
        "ipn": "rj",
        "ct": "201326592",
        "fp": "result",
        "queryWord": query,
        "cl": "2",
        "lm": "-1",
        "ie": "utf-8",
        "oe": "utf-8",
        "word": query,
        "pn": "0",
        "rn": str(min(30, limit + 6)),
    }
    async with httpx2.AsyncClient(
        timeout=timeout, follow_redirects=True, headers=_HEADERS
    ) as client:
        response = await client.get("https://image.baidu.com/search/acjson", params=params)
        response.raise_for_status()
        return parse_baidu(response.text, limit=limit)


async def _wallhaven_images(query: str, limit: int, timeout: float) -> list[ImageHit]:
    # 键词是英文标签；中文查询多半 0 结果，空结果不算故障
    params = {"q": query, "purity": "100", "sorting": "relevance"}
    async with httpx2.AsyncClient(
        timeout=timeout, follow_redirects=True, headers=_HEADERS
    ) as client:
        response = await client.get("https://wallhaven.cc/api/v1/search", params=params)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            return []
        return parse_wallhaven(payload, limit=limit)


async def _openverse_images(query: str, limit: int, timeout: float, safe: bool) -> list[ImageHit]:
    params: dict[str, str] = {"q": query, "page_size": str(min(20, limit + 5))}
    if safe:
        params["mature"] = "false"
    async with httpx2.AsyncClient(
        timeout=timeout, follow_redirects=True, headers=_HEADERS
    ) as client:
        response = await client.get("https://api.openverse.org/v1/images/", params=params)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            return []
        return parse_openverse(payload, limit=limit)


async def _safebooru_images(query: str, limit: int, timeout: float) -> list[ImageHit]:
    # dapi 一次最多接受 2 个标签（AND 语义），且只认英文标签；中文查询直接跳过。
    # 试过并放弃：DuckDuckGo/Wikimedia/Unsplash 对本机出口 IP 直接 403，
    # Ecosia 403、Yahoo 500、Bing RSS 与普通页同样被墙。
    words = [w for w in query.split() if w.isascii()]
    if not words:
        return []
    params = {
        "page": "dapi",
        "s": "post",
        "q": "index",
        "tags": "_".join(words[:2]),
        "limit": str(min(30, limit + 6)),
        "json": "1",
    }
    async with httpx2.AsyncClient(
        timeout=timeout, follow_redirects=True, headers=_HEADERS
    ) as client:
        response = await client.get("https://safebooru.org/index.php", params=params)
        response.raise_for_status()
        try:
            posts = json.loads(response.text or "[]")
        except ValueError:
            return []
        return parse_safebooru(posts, limit=limit)


async def search_images(
    query: str,
    *,
    limit: int = 24,
    timeout: float = 15,
    safe: bool = True,
) -> list[ImageHit]:
    """并行检索六源（Bing+360+百度+Wallhaven+Openverse+Safebooru），按顺序合并去重；
    全部引擎都失败时抛出异常。"""
    query = " ".join(query.split()).strip()[:100]
    if not query:
        return []

    raw = await asyncio.gather(
        asyncio.create_task(_bing_images(query, limit, timeout, safe)),
        asyncio.create_task(_so_images(query, limit, timeout)),
        asyncio.create_task(_baidu_images(query, limit, timeout)),
        asyncio.create_task(_wallhaven_images(query, limit, timeout)),
        asyncio.create_task(_openverse_images(query, limit, timeout, safe)),
        asyncio.create_task(_safebooru_images(query, limit, timeout)),
        return_exceptions=True,
    )
    merged: list[ImageHit] = []
    errors: list[Exception] = []
    ok_engines = 0
    for group in raw:
        if isinstance(group, BaseException):
            if not isinstance(group, asyncio.CancelledError):
                errors.append(group)
            continue
        ok_engines += 1
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
    # 有引擎正常返回但没结果 → 真没搜到；一个都没返回成功 → 当故障抛出
    if not output and ok_engines == 0 and errors:
        raise RuntimeError(f"图片搜索失败：{errors[0]}")
    return output


async def collect_images(
    query: str,
    hits: list[ImageHit],
    want: int,
    *,
    timeout: float = 12,
    max_bytes: int = 8 * 1024 * 1024,
    max_candidates: int = 12,
    verify_fn=None,
) -> tuple[list[tuple[bytes, str]], bool]:
    """按引擎顺序下载候选图，字节级去重，可选让模型核对内容，凑满 want 张就停。

    verify_fn(query, [(bytes, media_type), ...]) -> list[bool] | None，
    出错或返回 None 都按「不核对」处理，绝不卡住发图。
    返回（通过核对的图片列表, 是否有候选因内容不符被拒）。
    """
    picked: list[tuple[bytes, str]] = []
    pending: list[tuple[bytes, str]] = []  # 下载好待核对的一批
    seen: set[str] = set()
    rejected_any = False

    async def _flush(batch: list[tuple[bytes, str]]) -> None:
        nonlocal rejected_any
        if not batch:
            return
        verdicts: list[bool] | None = None
        if verify_fn is not None:
            try:
                verdicts = await verify_fn(query, batch)
            except Exception as exc:
                logger.warning(f"图片核对失败，按原样发送：{exc}")
        if verdicts is None or len(verdicts) != len(batch):
            picked.extend(batch)
            return
        for item, ok in zip(batch, verdicts):
            if ok:
                picked.append(item)
            else:
                rejected_any = True

    for hit in hits[:max_candidates]:
        if len(picked) >= want:
            break
        try:
            data, media_type = await download_hit(hit, timeout=timeout, max_bytes=max_bytes)
        except Exception as exc:
            logger.info(f"图片下载失败，换下一张（{hit.image_url[:80]}）：{exc}")
            continue
        digest = hashlib.md5(data).hexdigest()
        if digest in seen:  # 多引擎常返回同一张图，核对前先去重
            continue
        seen.add(digest)
        pending.append((data, media_type))
        if len(pending) >= 4:  # 一次请求最多核对 4 张
            await _flush(pending)
            pending = []
    await _flush(pending)
    return picked[:want], rejected_any


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
