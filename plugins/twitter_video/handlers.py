"""推特/X 链接解析：镜像 API 取直链，下载后把视频/图片发回 QQ。"""

from __future__ import annotations

import asyncio
import base64
import shutil
import subprocess
import tempfile
import time
from datetime import date
from pathlib import Path

import httpx
from nonebot import get_driver, get_plugin_config, logger, on_command, on_message
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import Rule
from qqbot_filters import is_blocked
from yt_dlp import YoutubeDL

from plugins.common.access import event_is_allowed

from . import resolver
from .config import Config

plugin_config = get_plugin_config(Config)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_MAX_PHOTO_BYTES = 20 * 1024 * 1024

_last_request: dict[int, float] = {}
_daily_user: dict[int, int] = {}
_recent_tweets: dict[tuple[str, str], float] = {}
_day = date.today()

HELP_TEXT = """\
🎬 群里/私聊直接发 X/Twitter 链接就会自动解析；也可以手动：
/推文 <链接>
示例：/推文 https://x.com/xxx/status/123
别名：/推特、/tweet。
带视频的推文发视频（默认 ≤720P），纯图推文发原图。"""


def _effective_proxy() -> str:
    """推特解析代理：优先自己的配置，留空时借用 MEDIA_PROXY / PARSEHUB_PROXY。"""
    proxy = plugin_config.twitter_proxy.strip()
    if proxy:
        return proxy
    driver_config = get_driver().config
    for name in ("media_proxy", "parsehub_proxy"):
        value = str(getattr(driver_config, name, "") or "").strip()
        if value:
            return value
    return ""


def _allowed(event: MessageEvent) -> bool:
    return event_is_allowed(
        event,
        allowed_users=plugin_config.twitter_allowed_users,
        allowed_groups=plugin_config.twitter_allowed_groups,
    )


def _roll_day() -> None:
    global _day, _daily_user
    today = date.today()
    if today != _day:
        _day = today
        _daily_user.clear()


def _chat_key(event: MessageEvent) -> str:
    if isinstance(event, GroupMessageEvent):
        return f"group:{event.group_id}"
    return f"private:{event.user_id}"


async def _fetch_bytes(url: str, max_bytes: int) -> bytes:
    proxy = _effective_proxy()
    timeout = httpx.Timeout(plugin_config.twitter_timeout_seconds, read=60.0)
    headers = {"user-agent": _UA, "referer": "https://x.com/"}
    async with httpx.AsyncClient(
        proxy=proxy or None,
        timeout=timeout,
        follow_redirects=True,
        headers=headers,
    ) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            length = resp.headers.get("content-length")
            if length and int(length) > max_bytes:
                raise RuntimeError("文件超过大小上限")
            buffer = bytearray()
            async for chunk in resp.aiter_bytes(64 * 1024):
                buffer.extend(chunk)
                if len(buffer) > max_bytes:
                    raise RuntimeError("文件超过大小上限")
            if not buffer:
                raise RuntimeError("没有下载到数据")
            return bytes(buffer)


async def _download_video(url: str, tmpdir: Path) -> Path:
    max_bytes = plugin_config.twitter_max_mb * 1024 * 1024
    target = tmpdir / "video.mp4"
    data = await _fetch_bytes(url, max_bytes)
    target.write_bytes(data)
    return target


def _pick_video_file(tmpdir: Path) -> Path | None:
    candidates = [
        item
        for item in tmpdir.iterdir()
        if item.is_file() and item.suffix.casefold() in {".mp4", ".mkv", ".webm", ".mov"}
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_size)


def _to_mp4(source: Path, tmpdir: Path) -> Path:
    if source.suffix.casefold() == ".mp4":
        return source
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("下载到的不是 mp4，且找不到 ffmpeg 转封装")
    target = tmpdir / "video.mp4"
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-c",
        "copy",
        str(target),
    ]
    subprocess.run(command, check=True, timeout=300)
    return target


def _ytdlp_download_sync(url: str, tmpdir: Path) -> Path:
    max_bytes = plugin_config.twitter_max_mb * 1024 * 1024
    max_duration = plugin_config.twitter_max_duration_seconds

    def match_filter(info: dict, *, incomplete: bool = False) -> str | None:
        if info.get("is_live"):
            return "不支持直播"
        duration = info.get("duration")
        if duration and duration > max_duration:
            return f"视频超过 {max_duration // 60} 分钟"
        return None

    opts: dict = {
        "format": "b[ext=mp4]/bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b",
        "outtmpl": str(tmpdir / "video.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "max_filesize": max_bytes,
        "socket_timeout": plugin_config.twitter_timeout_seconds,
        "retries": 2,
        "match_filter": match_filter,
        "overwrites": True,
    }
    if plugin_config.twitter_cookies_file and Path(plugin_config.twitter_cookies_file).exists():
        opts["cookiefile"] = plugin_config.twitter_cookies_file
    proxy = _effective_proxy()
    if proxy:
        opts["proxy"] = proxy

    with YoutubeDL(opts) as ydl:
        ydl.extract_info(url, download=True)

    source = _pick_video_file(tmpdir)
    if source is None:
        raise RuntimeError("yt-dlp 没有下载到视频文件")
    if source.stat().st_size > max_bytes:
        raise RuntimeError(f"视频超过 {plugin_config.twitter_max_mb}MB")
    return _to_mp4(source, tmpdir)


class _NoMediaError(RuntimeError):
    """镜像接口正常返回但推文里没有视频（yt-dlp 也确认没有）。"""


def _is_no_media_error(exc: Exception) -> bool:
    return "No video could be found" in str(exc)


async def _ytdlp_fallback(url: str, tmpdir: Path, resolve_error: str = "") -> Path:
    if not plugin_config.twitter_use_ytdlp:
        raise RuntimeError(resolve_error or "镜像接口没拿到媒体，且 yt-dlp 兜底已关闭")
    try:
        return await asyncio.to_thread(_ytdlp_download_sync, url, tmpdir)
    except Exception as exc:
        if _is_no_media_error(exc):
            raise _NoMediaError("这条推文里没有视频或图片。") from exc
        raise


async def _send_video(
    event: MessageEvent,
    matcher: Matcher,
    info: resolver.TweetInfo,
    media: resolver.TweetMedia,
    tmpdir: Path,
) -> None:
    url = resolver.pick_video_url(media, plugin_config.twitter_max_height)
    if media.duration and media.duration > plugin_config.twitter_max_duration_seconds:
        raise RuntimeError(f"视频超过 {plugin_config.twitter_max_duration_seconds // 60} 分钟")
    path = await _download_video(url, tmpdir)
    size_mb = path.stat().st_size / 1024 / 1024
    if size_mb > plugin_config.twitter_max_mb:
        raise RuntimeError(f"视频超过 {plugin_config.twitter_max_mb}MB")

    _daily_user[event.user_id] = _daily_user.get(event.user_id, 0) + 1
    logger.info(f"推特视频已下载：@{info.screen_name} {size_mb:.1f}MB -> {event.user_id}")
    video = MessageSegment("video", {"file": f"file:///{path.as_posix()}"})
    await matcher.finish(video)


async def _send_photos(
    event: MessageEvent,
    matcher: Matcher,
    info: resolver.TweetInfo,
    photos: list[resolver.TweetMedia],
) -> None:
    sent = 0
    for media in photos[: plugin_config.twitter_max_photos]:
        try:
            data = await _fetch_bytes(resolver.photo_url(media), _MAX_PHOTO_BYTES)
        except Exception as exc:
            logger.warning(f"推特图片下载失败：{exc}")
            continue
        encoded = base64.b64encode(data).decode("ascii")
        await matcher.send(MessageSegment.image(f"base64://{encoded}"))
        sent += 1
    if not sent:
        raise RuntimeError("图片下载失败")

    _daily_user[event.user_id] = _daily_user.get(event.user_id, 0) + 1
    await matcher.finish()


async def _run_tweet(
    event: MessageEvent,
    matcher: Matcher,
    tweet_id: str,
    screen_name: str | None,
    *,
    auto: bool = False,
) -> None:
    _roll_day()
    now = time.time()
    cooldown = plugin_config.twitter_cooldown_seconds
    if now - _last_request.get(event.user_id, 0.0) < cooldown:
        if auto:
            return
        remaining = int(cooldown - (now - _last_request.get(event.user_id, 0.0))) + 1
        await matcher.finish(f"刚解析过，等 {remaining} 秒再试。")
    if _daily_user.get(event.user_id, 0) >= plugin_config.twitter_daily_limit_per_user:
        if auto:
            return
        await matcher.finish("今天你解析得够多了，明天再来。")
    _last_request[event.user_id] = now

    if auto:
        await matcher.send("🔗 收到推特链接，正在解析…")
    else:
        await matcher.send("🔗 正在解析推文，可能要十几秒…")

    tmpdir = Path(tempfile.mkdtemp(prefix="qqbot_tweet_"))
    try:
        info: resolver.TweetInfo | None = None
        resolve_error = ""
        try:
            info = await resolver.fetch_tweet(
                tweet_id,
                screen_name,
                bases=plugin_config.twitter_api_bases,
                proxy=_effective_proxy(),
                timeout=float(plugin_config.twitter_timeout_seconds),
            )
        except resolver.TweetError as exc:
            resolve_error = str(exc)
            logger.info(f"镜像 API 解析失败：{exc}")

        if info is not None and plugin_config.twitter_send_caption:
            await matcher.send(resolver.build_caption(info))

        videos = [m for m in (info.media if info else []) if m.kind in ("video", "gif")]
        photos = [m for m in (info.media if info else []) if m.kind == "photo"]
        if videos:
            await _send_video(event, matcher, info, videos[0], tmpdir)  # type: ignore[arg-type]
        elif photos and plugin_config.twitter_send_photos:
            await _send_photos(event, matcher, info, photos)  # type: ignore[arg-type]
        elif info is not None:
            # 接口成功拿到了推文，确实没有可发的媒体
            if photos:
                raise RuntimeError("推文里只有图片，发图功能已关闭。")
            raise RuntimeError("这条推文里没有视频或图片。")
        else:
            # 两个镜像接口都没拿到推文，交给 yt-dlp 兜底
            url = resolver.tweet_url(screen_name, tweet_id)
            try:
                path = await _ytdlp_fallback(url, tmpdir, resolve_error)
            except _NoMediaError as exc:
                raise RuntimeError(str(exc)) from exc
            await matcher.finish(MessageSegment("video", {"file": f"file:///{path.as_posix()}"}))
    except FinishedException:
        raise
    except Exception as exc:
        logger.warning(f"推特解析失败：{exc}")
        if not auto or plugin_config.twitter_notify_errors:
            await matcher.finish(f"❌ 推特解析失败：{str(exc)[:120]}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


tweet_cmd = on_command(
    "推文",
    aliases={"tweet", "推特", "推特视频"},
    priority=10,
    block=True,
)


@tweet_cmd.handle()
async def _handle_tweet(
    bot: Bot,
    event: MessageEvent,
    matcher: Matcher,
    args: Message = CommandArg(),
) -> None:
    if is_blocked(event.user_id):
        return
    if not plugin_config.twitter_enabled:
        await matcher.finish("推特解析功能已关闭。")
    if not _allowed(event):
        await matcher.finish("这个群/账号没有推特解析权限。")

    links = resolver.find_tweet_urls(args.extract_plain_text())
    if not links:
        await matcher.finish(HELP_TEXT)
    screen_name, tweet_id = links[0]
    await _run_tweet(event, matcher, tweet_id, screen_name, auto=False)


def _auto_rule(event: MessageEvent) -> bool:
    if not plugin_config.twitter_enabled or not plugin_config.twitter_auto_enabled:
        return False
    if is_blocked(event.user_id):
        return False
    if str(event.user_id) == str(event.self_id):
        return False
    if isinstance(event, GroupMessageEvent):
        if plugin_config.twitter_auto_groups and event.group_id not in plugin_config.twitter_auto_groups:
            return False
    if not _allowed(event):
        return False
    text = event.get_plaintext().strip()
    if not text or text.startswith("/"):
        return False
    return bool(resolver.find_tweet_urls(text))


# priority 15：抢在 ParseHub 自动解析（20）和 yt-dlp 通用下载（25）之前接管 X 链接，
# block=True 保证后面两者不再重复处理。
twitter_auto = on_message(rule=Rule(_auto_rule), priority=15, block=True)


@twitter_auto.handle()
async def _handle_auto(event: MessageEvent, matcher: Matcher) -> None:
    if is_blocked(event.user_id):
        return
    links = resolver.find_tweet_urls(event.get_plaintext())
    if not links:
        return
    screen_name, tweet_id = links[0]

    now = time.time()
    key = (_chat_key(event), tweet_id)
    if now - _recent_tweets.get(key, 0.0) < plugin_config.twitter_dedup_seconds:
        return
    _recent_tweets[key] = now
    if len(_recent_tweets) > 500:
        for old_key, _ in sorted(_recent_tweets.items(), key=lambda item: item[1])[:100]:
            _recent_tweets.pop(old_key, None)

    await _run_tweet(event, matcher, tweet_id, screen_name, auto=True)
