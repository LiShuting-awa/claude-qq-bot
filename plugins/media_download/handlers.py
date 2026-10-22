"""链接视频下载并转成 MP4 发回 QQ。"""

from __future__ import annotations

import asyncio
import base64
import re
import shutil
import subprocess
import tempfile
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from nonebot import get_plugin_config, logger, on_command, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import Rule
from qqbot_filters import configure as configure_blocked
from qqbot_filters import is_blocked
from yt_dlp import YoutubeDL

from plugins.common.access import event_is_allowed
from plugins.common.network import host_is_private
from plugins.common.parsehub_media import parsehub_handles

from . import bilibili
from .config import Config

plugin_config = get_plugin_config(Config)
configure_blocked(plugin_config.blocked_users)
bilibili.JINA_BASE = plugin_config.bilibili_jina_base

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_BARE_RE = re.compile(
    r"(?i)((?:www\.)?(?:bilibili\.com|b23\.tv|youtube\.com|youtu\.be|douyin\.com|v\.douyin\.com|"
    r"ixigua\.com|weibo\.com|xiaohongshu\.com|xhslink\.com|twitter\.com|x\.com|tiktok\.com)/[^\s]+)"
)

_last_request: dict[int, float] = {}
_daily_user: dict[int, int] = {}
_recent_links: dict[tuple[str, str], float] = {}
_day = date.today()

_VIDEO_EXTENSIONS = (".mp4", ".m3u8", ".webm", ".mov", ".flv", ".mkv")
_VIDEO_HOSTS = (
    "bilibili.com",
    "b23.tv",
    "youtube.com",
    "youtu.be",
    "douyin.com",
    "iesdouyin.com",
    "tiktok.com",
    "ixigua.com",
    "weibo.com",
    "weibo.cn",
    "xiaohongshu.com",
    "xhslink.com",
    "twitter.com",
    "x.com",
    "vimeo.com",
    "dailymotion.com",
    "twitch.tv",
    "kuaishou.com",
    "instagram.com",
)

HELP_TEXT = """\
🎬 群里/私聊直接发视频链接就会自动下载；也可以手动：
/mp4 <链接>
示例：/mp4 https://www.bilibili.com/video/BVxxxx
别名：/视频、/转mp4、/下载视频
默认 480P，兼顾速度和 QQ 上传大小；直播、付费/DRM 内容不支持。"""


def _extract_url(text: str) -> str:
    match = _URL_RE.search(text)
    if match:
        return match.group(0).rstrip("，。！？、；：,.!?;:)]}>\"'")
    match = _BARE_RE.search(text)
    if match:
        return "https://" + match.group(1).rstrip("，。！？、；：,.!?;:)]}>\"'")
    return ""


def _looks_like_video(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    path = parsed.path.casefold()
    if any(path.endswith(ext) for ext in _VIDEO_EXTENSIONS):
        return True
    return any(host == item or host.endswith("." + item) for item in _VIDEO_HOSTS)


def _blocked_host(host: str) -> bool:
    return host_is_private(host, block_local_names=True)


async def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("只支持 http/https 链接")
    if await asyncio.to_thread(_blocked_host, parsed.hostname):
        raise ValueError("这个链接指向内网/本机，不允许下载")


def _allowed(event: MessageEvent) -> bool:
    return event_is_allowed(
        event,
        allowed_users=plugin_config.media_allowed_users,
        allowed_groups=plugin_config.media_allowed_groups,
    )


def _roll_day() -> None:
    global _day, _daily_user
    today = date.today()
    if today != _day:
        _day = today
        _daily_user.clear()


def _pick_video_file(tmpdir: Path) -> Path | None:
    candidates = [
        item
        for item in tmpdir.iterdir()
        if item.is_file() and item.suffix.casefold() in {".mp4", ".mkv", ".webm", ".mov", ".flv"}
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_size)


def _to_mp4(source: Path, tmpdir: Path) -> Path:
    if source.suffix.casefold() == ".mp4":
        return source
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("找不到 ffmpeg，无法转 MP4")
    target = tmpdir / "video.mp4"
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(target),
    ]
    subprocess.run(command, check=True, timeout=600)
    return target


def _download_sync(url: str, tmpdir: Path) -> tuple[Path, str, float | None]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("找不到 ffmpeg")

    max_bytes = plugin_config.media_max_mb * 1024 * 1024
    max_duration = plugin_config.media_max_duration_seconds

    def match_filter(info: dict, *, incomplete: bool = False) -> str | None:
        if info.get("is_live"):
            return "不支持直播"
        duration = info.get("duration")
        if duration and duration > max_duration:
            return f"视频超过 {max_duration // 60} 分钟"
        return None

    opts: dict = {
        "format": (
            "bv*[ext=mp4][vcodec^=avc1][height<=480]+ba[ext=m4a]/"
            "bv*[ext=mp4][height<=480]+ba[ext=m4a]/"
            "b[ext=mp4]/bv*+ba/b"
        ),
        "outtmpl": str(tmpdir / "video.%(ext)s"),
        "merge_output_format": "mp4",
        "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "max_filesize": max_bytes,
        "socket_timeout": plugin_config.media_socket_timeout_seconds,
        "retries": 2,
        "ffmpeg_location": ffmpeg,
        "match_filter": match_filter,
        "overwrites": True,
        "source_address": "0.0.0.0",
        "http_headers": {"User-Agent": "Mozilla/5.0 QQBot/1.0"},
    }
    if plugin_config.media_cookies_file and Path(plugin_config.media_cookies_file).exists():
        opts["cookiefile"] = plugin_config.media_cookies_file
    if plugin_config.media_proxy.strip():
        opts["proxy"] = plugin_config.media_proxy.strip()

    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    source = _pick_video_file(tmpdir)
    if source is None:
        raise RuntimeError("没有下载到视频文件")
    if source.stat().st_size > max_bytes:
        raise RuntimeError(f"视频超过 {plugin_config.media_max_mb}MB")

    duration = info.get("duration") if isinstance(info, dict) else None
    if duration and duration > max_duration:
        raise RuntimeError(f"视频超过 {max_duration // 60} 分钟")

    path = _to_mp4(source, tmpdir)
    if path.stat().st_size > max_bytes:
        raise RuntimeError(f"视频超过 {plugin_config.media_max_mb}MB")
    title = str(info.get("title") or "video") if isinstance(info, dict) else "video"
    return path, title, float(duration) if duration else None


download_cmd = on_command(
    "mp4",
    aliases={"视频", "转mp4", "下载视频"},
    priority=5,
    block=True,
)


async def _run_download(
    event: MessageEvent,
    matcher: Matcher,
    url: str,
    *,
    auto: bool = False,
) -> None:
    _roll_day()
    now = time.time()
    cooldown = plugin_config.media_cooldown_seconds
    if now - _last_request.get(event.user_id, 0.0) < cooldown:
        if auto:
            return
        remaining = int(cooldown - (now - _last_request.get(event.user_id, 0.0))) + 1
        await matcher.finish(f"刚下过，等 {remaining} 秒再试。")
    if _daily_user.get(event.user_id, 0) >= plugin_config.media_daily_limit_per_user:
        if auto:
            return
        await matcher.finish("今天你下载得够多了，明天再来。")

    _last_request[event.user_id] = now
    try:
        await _validate_url(url)
    except Exception as exc:
        logger.warning(f"视频链接校验失败：{exc}")
        if not auto or plugin_config.media_auto_notify_errors:
            await matcher.finish(f"❌ 下载失败：{str(exc)[:120]}")
        return

    bili_info = None
    card_sent = False
    if bilibili.is_bilibili_url(url):
        try:
            bili_info = await bilibili.fetch_info(url)
            if plugin_config.bilibili_card_enabled:
                try:
                    png = await bilibili.build_card_async(bili_info)
                    encoded = base64.b64encode(png).decode("ascii")
                    card = MessageSegment.image(f"base64://{encoded}")
                    await matcher.send(card)
                    card_sent = True
                    logger.info(f"B 站信息卡已发送：{bili_info.bvid}（{len(png)} bytes）")
                except Exception as exc:
                    logger.warning(f"B 站信息卡发送失败：{exc}")
        except Exception as exc:
            logger.warning(f"B 站信息获取失败，回退普通下载：{exc}")

    if not card_sent:
        if auto:
            await matcher.send("🔗 收到视频链接，正在下载并转 MP4…")
        else:
            await matcher.send("🔗 正在解析链接并下载，可能要几十秒…")

    tmpdir = Path(tempfile.mkdtemp(prefix="qqbot_video_"))
    try:
        max_bytes = plugin_config.media_max_mb * 1024 * 1024
        if bili_info is not None:
            try:
                path, title, duration = await bilibili.download(
                    bili_info,
                    tmpdir,
                    max_bytes=max_bytes,
                    max_height=plugin_config.bilibili_max_height,
                )
            except Exception as exc:
                logger.warning(f"B 站专用下载失败，回退 yt-dlp：{exc}")
                path, title, duration = await asyncio.to_thread(_download_sync, url, tmpdir)
        else:
            path, title, duration = await asyncio.to_thread(_download_sync, url, tmpdir)
        size_mb = path.stat().st_size / 1024 / 1024
        if size_mb > plugin_config.media_max_mb:
            raise RuntimeError(f"视频超过 {plugin_config.media_max_mb}MB")

        _daily_user[event.user_id] = _daily_user.get(event.user_id, 0) + 1
        video = MessageSegment("video", {"file": f"file:///{path.as_posix()}"})
        logger.info(f"视频下载完成：{title} {size_mb:.1f}MB {duration or '?'}s -> {event.user_id}")
        await matcher.finish(video)
    except FinishedException:
        raise
    except Exception as exc:
        logger.warning(f"视频下载失败：{exc}")
        if not auto or plugin_config.media_auto_notify_errors:
            await matcher.finish(f"❌ 下载失败：{str(exc)[:120]}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@download_cmd.handle()
async def _handle_download(
    bot: Bot,
    event: MessageEvent,
    matcher: Matcher,
    args: Message = CommandArg(),
) -> None:
    if is_blocked(event.user_id):
        return
    if not plugin_config.media_download_enabled:
        await matcher.finish("视频下载功能已关闭。")
    if not _allowed(event):
        await matcher.finish("这个群/账号没有视频下载权限。")

    url = _extract_url(args.extract_plain_text())
    if not url:
        await matcher.finish(HELP_TEXT)
    await _run_download(event, matcher, url, auto=False)


def _auto_rule(event: MessageEvent) -> bool:
    if not plugin_config.media_auto_enabled:
        return False
    if is_blocked(event.user_id):
        return False
    if str(event.user_id) == str(event.self_id):
        return False
    if isinstance(event, GroupMessageEvent):
        if plugin_config.media_auto_groups and event.group_id not in plugin_config.media_auto_groups:
            return False
    if not _allowed(event):
        return False

    text = event.get_plaintext().strip()
    if not text or text.startswith("/"):
        return False
    url = _extract_url(text)
    if not url or parsehub_handles(url):
        return False
    return bool(_looks_like_video(url))


media_auto = on_message(rule=Rule(_auto_rule), priority=25, block=True)


def _bilibili_auto_rule(event: MessageEvent) -> bool:
    if not plugin_config.bilibili_native_auto:
        return False
    if not plugin_config.media_auto_enabled:
        return False
    if is_blocked(event.user_id):
        return False
    if str(event.user_id) == str(event.self_id):
        return False
    if isinstance(event, GroupMessageEvent):
        if plugin_config.media_auto_groups and event.group_id not in plugin_config.media_auto_groups:
            return False
    if not _allowed(event):
        return False
    text = event.get_plaintext().strip()
    if not text or text.startswith("/"):
        return False
    url = _extract_url(text)
    return bool(url and bilibili.is_bilibili_url(url))


# 保证 B 站优先由本地 Jina 链路处理，不被通用解析插件抢走；
# 社区插件在本机没有 B 站 Cookie 时会 412，B 站仍走 Jina 链路。
bilibili_auto = on_message(rule=Rule(_bilibili_auto_rule), priority=0, block=True)


@bilibili_auto.handle()
async def _handle_bilibili_auto(event: MessageEvent, matcher: Matcher) -> None:
    await _handle_auto(event, matcher)


def _chat_key(event: MessageEvent) -> str:
    if isinstance(event, GroupMessageEvent):
        return f"group:{event.group_id}"
    return f"private:{event.user_id}"


@media_auto.handle()
async def _handle_auto(event: MessageEvent, matcher: Matcher) -> None:
    if is_blocked(event.user_id):
        return
    url = _extract_url(event.get_plaintext())
    if not url:
        return

    now = time.time()
    key = (_chat_key(event), url)
    if now - _recent_links.get(key, 0.0) < plugin_config.media_auto_dedup_seconds:
        return
    _recent_links[key] = now
    if len(_recent_links) > 500:
        for old_key, _ in sorted(_recent_links.items(), key=lambda item: item[1])[:100]:
            _recent_links.pop(old_key, None)

    await _run_download(event, matcher, url, auto=True)
