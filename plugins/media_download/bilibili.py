"""B 站信息卡 + 视频下载（走 Jina Reader 绕开 B 站 412）。"""

from __future__ import annotations

import asyncio
import io
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx2
from PIL import Image, ImageDraw, ImageFont

BVID_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
_BILI_HOSTS = ("bilibili.com", "b23.tv", "bili2233.cn", "bili22.cn")
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}

JINA_BASE = "https://r.jina.ai/"


@dataclass(slots=True)
class BilibiliInfo:
    bvid: str
    title: str
    author: str
    cover_url: str
    view: int
    like: int
    coin: int
    favorite: int
    share: int
    danmaku: int
    duration: float
    cid: int


def is_bilibili_url(url: str) -> bool:
    host = (httpx2.URL(url).host or "").casefold()
    return any(host == item or host.endswith("." + item) for item in _BILI_HOSTS)


def _extract_bvid(text: str) -> str:
    match = BVID_RE.search(text)
    return match.group(1) if match else ""


async def resolve_bvid(url: str) -> str:
    bvid = _extract_bvid(url)
    if bvid:
        return bvid
    if not is_bilibili_url(url):
        return ""
    try:
        async with httpx2.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": _UA},
        ) as client:
            response = await client.get(url)
            return _extract_bvid(str(response.url))
    except Exception:
        return ""


async def _jina_json(api_url: str, *, timeout: float = 60) -> dict:
    async with httpx2.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": _UA},
    ) as client:
        response = await client.get(JINA_BASE + api_url)
        response.raise_for_status()
        text = response.text
    start = text.find('{"code"')
    if start < 0:
        start = text.find("{")
    if start < 0:
        raise RuntimeError("B 站接口没有返回 JSON")
    data = json.loads(text[start:])
    if int(data.get("code", -1)) != 0:
        raise RuntimeError(f"B 站接口错误：{data.get('message') or data.get('code')}")
    return data.get("data") or {}


async def fetch_info(url: str) -> BilibiliInfo:
    bvid = await resolve_bvid(url)
    if not bvid:
        raise RuntimeError("没有识别出 B 站 BV 号")
    data = await _jina_json(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")
    stat = data.get("stat") or {}
    owner = data.get("owner") or {}
    pages = data.get("pages") or []
    cid = data.get("cid") or (pages[0].get("cid") if pages else 0)
    if not cid:
        raise RuntimeError("没有拿到视频 cid")
    cover = str(data.get("pic") or "")
    if cover.startswith("http://"):
        cover = "https://" + cover[7:]
    return BilibiliInfo(
        bvid=bvid,
        title=str(data.get("title") or "B 站视频"),
        author=str(owner.get("name") or "UP 主"),
        cover_url=cover,
        view=int(stat.get("view") or 0),
        like=int(stat.get("like") or 0),
        coin=int(stat.get("coin") or 0),
        favorite=int(stat.get("favorite") or 0),
        share=int(stat.get("share") or 0),
        danmaku=int(stat.get("danmaku") or 0),
        duration=float(data.get("duration") or 0),
        cid=int(cid),
    )


async def fetch_cover(url: str) -> bytes:
    if not url:
        return b""
    async with httpx2.AsyncClient(
        timeout=30,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.content
        if len(data) > 6 * 1024 * 1024:
            raise RuntimeError("封面太大")
        return data


def _fmt_count(value: int) -> str:
    if value >= 100_000_000:
        return f"{value / 100_000_000:.1f}亿".replace(".0亿", "亿")
    if value >= 10_000:
        return f"{value / 10_000:.1f}万".replace(".0万", "万")
    return str(value)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path(r"C:\Windows\Fonts") / ("msyhbd.ttc" if bold else "msyh.ttc"),
        Path(r"C:\Windows\Fonts") / ("simhei.ttf" if bold else "simsun.ttc"),
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int = 2,
) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    remaining = text
    for index in range(max_lines):
        if not remaining:
            break
        cut = 0
        while cut < len(remaining) and draw.textlength(remaining[: cut + 1], font=font) <= max_width:
            cut += 1
        cut = max(1, cut)
        line = remaining[:cut]
        remaining = remaining[cut:]
        if index == max_lines - 1 and remaining:
            while line and draw.textlength(line + "…", font=font) > max_width:
                line = line[:-1]
            line += "…"
        lines.append(line)
    return lines


def _cover_image(data: bytes, width: int, height: int) -> Image.Image:
    canvas = Image.new("RGB", (width, height), "#242432")
    if data:
        try:
            image = Image.open(io.BytesIO(data)).convert("RGB")
            scale = max(width / image.width, height / image.height)
            image = image.resize(
                (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
                Image.Resampling.LANCZOS,
            )
            left = max(0, (image.width - width) // 2)
            top = max(0, (image.height - height) // 2)
            canvas.paste(image.crop((left, top, left + width, top + height)), (0, 0))
            return canvas
        except Exception:
            pass
    draw = ImageDraw.Draw(canvas)
    draw.text((width // 2, height // 2), "Bilibili", fill="#ffffff", font=_font(40, True), anchor="mm")
    return canvas


def build_card(info: BilibiliInfo, cover_data: bytes) -> bytes:
    width, height = 720, 800
    card = Image.new("RGB", (width, height), "#f7f7f9")
    draw = ImageDraw.Draw(card)
    draw.rectangle([0, 0, width, 6], fill="#fb7299")

    cover_w, cover_h = 640, 360
    cover = _cover_image(cover_data, cover_w, cover_h)
    mask = Image.new("L", (cover_w, cover_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, cover_w, cover_h], radius=18, fill=255)
    card.paste(cover, (40, 40), mask)

    title_font = _font(30, True)
    title_lines = _wrap(draw, info.title, title_font, 640, 2)
    y = 428
    for line in title_lines:
        draw.text((40, y), line, fill="#18181b", font=title_font)
        y += 40

    author_font = _font(20)
    draw.text((40, y + 6), f"UP 主：{info.author}", fill="#6b6b76", font=author_font)

    label_font = _font(16)
    value_font = _font(27, True)
    stats = [
        ("观看", info.view),
        ("点赞", info.like),
        ("投币", info.coin),
        ("收藏", info.favorite),
        ("转发", info.share),
        ("弹幕", info.danmaku),
    ]
    for index, (label, value) in enumerate(stats):
        col = index % 3
        row = index // 3
        x = 40 + col * 220
        y = 570 + row * 80
        draw.text((x, y), label, fill="#8a8a96", font=label_font)
        draw.text((x, y + 24), _fmt_count(value), fill="#18181b", font=value_font)

    draw.line([40, 738, 680, 738], fill="#e5e5ea", width=1)
    footer_font = _font(16)
    draw.text((40, 756), "Bilibili · Claude 帮你看过了", fill="#8a8a96", font=footer_font)
    draw.text((680, 756), info.bvid, fill="#b0b0ba", font=footer_font, anchor="ra")

    output = io.BytesIO()
    card.save(output, format="PNG", optimize=True)
    return output.getvalue()


async def build_card_async(info: BilibiliInfo) -> bytes:
    cover = b""
    try:
        cover = await fetch_cover(info.cover_url)
    except Exception:
        pass
    return await asyncio.to_thread(build_card, info, cover)


def _pick_streams(dash: dict, max_height: int = 480) -> tuple[dict, dict]:
    videos = [
        item
        for item in (dash.get("video") or [])
        if int(item.get("height") or 0) <= max_height
    ]
    if not videos:
        videos = list(dash.get("video") or [])
    if not videos:
        raise RuntimeError("没有可下载的视频流")

    def video_key(item: dict) -> tuple:
        return (
            str(item.get("codecs") or "").startswith("avc1"),
            int(item.get("height") or 0),
            int(item.get("bandwidth") or 0),
        )

    videos.sort(key=video_key, reverse=True)
    audios = list(dash.get("audio") or [])
    if not audios:
        raise RuntimeError("没有可下载的音频流")
    audios.sort(key=lambda item: int(item.get("bandwidth") or 0), reverse=True)
    return videos[0], audios[0]


def _stream_url(item: dict) -> list[str]:
    urls = []
    for key in ("baseUrl", "base_url"):
        value = item.get(key)
        if value:
            urls.append(str(value))
    for key in ("backupUrl", "backup_url"):
        for value in item.get(key) or []:
            if value:
                urls.append(str(value))
    return list(dict.fromkeys(urls))


async def _download_stream(urls: list[str], path: Path, max_bytes: int) -> None:
    last_error: Exception | None = None
    for url in urls:
        try:
            async with httpx2.AsyncClient(
                timeout=120,
                follow_redirects=True,
                headers=_HEADERS,
            ) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    written = 0
                    with path.open("wb") as handle:
                        async for chunk in response.aiter_bytes():
                            written += len(chunk)
                            if written > max_bytes:
                                raise RuntimeError("视频流超过大小上限")
                            handle.write(chunk)
                    if written == 0:
                        raise RuntimeError("视频流为空")
                    return
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(f"下载 B 站流失败：{last_error}")


async def download(
    info: BilibiliInfo,
    tmpdir: Path,
    *,
    max_bytes: int,
    max_height: int = 480,
) -> tuple[Path, str, float]:
    play = await _jina_json(
        "https://api.bilibili.com/x/player/playurl"
        f"?bvid={info.bvid}&cid={info.cid}&qn=64&fnval=16&fourk=1"
    )
    dash = play.get("dash") or {}
    video, audio = _pick_streams(dash, max_height)

    video_path = tmpdir / "bili-video.m4s"
    audio_path = tmpdir / "bili-audio.m4s"
    await _download_stream(_stream_url(video), video_path, max_bytes)
    await _download_stream(_stream_url(audio), audio_path, max_bytes)

    output = tmpdir / "video.mp4"
    await asyncio.to_thread(
        subprocess.run,
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output),
        ],
        check=True,
        timeout=300,
    )
    if output.stat().st_size > max_bytes:
        raise RuntimeError("视频超过大小上限")
    return output, info.title, info.duration
