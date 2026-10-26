"""识别“这条链接是不是一个视频/媒体作品”，而不是博主主页、频道页或搜索页。"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

_VIDEO_EXTS = (
    ".mp4",
    ".m3u8",
    ".webm",
    ".mov",
    ".mkv",
    ".flv",
    ".avi",
)

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
    "instagram.com",
    "kuaishou.com",
)

_SHORT_HOSTS = {
    "b23.tv",
    "youtu.be",
    "v.douyin.com",
    "iesdouyin.com",
    "v.kuaishou.com",
    "v.m.chenzhongtech.com",
    "xhslink.com",
    "xhslink.cn",
    "t.co",
}


def _host_matches(host: str, item: str) -> bool:
    return host == item or host.endswith("." + item)


def _is_bilibili(host: str, path: str) -> bool:
    if host in {"b23.tv"}:
        return bool(path.strip("/"))
    return any(
        marker in path
        for marker in ("/video/", "/bangumi/play/", "/list/", "/festival/")
    )


def _is_youtube(host: str, path: str, query: dict[str, list[str]]) -> bool:
    if host in {"youtu.be"}:
        return bool(path.strip("/"))
    if host.endswith("youtube.com"):
        if path in {"/watch", "/watch/"}:
            return bool(query.get("v"))
        return path.startswith(("/shorts/", "/live/", "/embed/"))
    return False


def _is_twitter(host: str, path: str) -> bool:
    if not (_host_matches(host, "x.com") or _host_matches(host, "twitter.com")):
        return False
    return "/status/" in path or path.startswith("/i/status/")


def _is_instagram(host: str, path: str) -> bool:
    if not _host_matches(host, "instagram.com"):
        return False
    parts = [part for part in path.split("/") if part]
    return bool(parts and parts[0] in {"reel", "reels", "p", "tv"})


def _is_tiktok(host: str, path: str) -> bool:
    if not _host_matches(host, "tiktok.com"):
        return False
    return "/video/" in path or path.startswith("/t/")


def _is_douyin(host: str, path: str, query: dict[str, list[str]]) -> bool:
    if host in {"v.douyin.com", "iesdouyin.com"}:
        return bool(path.strip("/")) or bool(query.get("modal_id"))
    if not _host_matches(host, "douyin.com"):
        return False
    return "/video/" in path or "/note/" in path or bool(query.get("modal_id"))


def _is_kuaishou(host: str, path: str) -> bool:
    if host in {"v.kuaishou.com", "v.m.chenzhongtech.com"}:
        return bool(path.strip("/"))
    if not _host_matches(host, "kuaishou.com"):
        return False
    return "/short-video/" in path or "/photo/" in path


def _is_weibo(host: str, path: str) -> bool:
    if not (_host_matches(host, "weibo.com") or _host_matches(host, "weibo.cn")):
        return False
    return "/status/" in path or "/tv/show/" in path


def _is_xhs(host: str, path: str) -> bool:
    if host in {"xhslink.com", "xhslink.cn"}:
        return bool(path.strip("/"))
    if not _host_matches(host, "xiaohongshu.com"):
        return False
    return "/explore/" in path or "/discovery/item/" in path


def is_video_url(url: str) -> bool:
    """只把作品页/视频页当视频；主页、频道页、搜索页返回 False。"""
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").casefold()
    path = parsed.path.casefold()
    if any(path.endswith(ext) for ext in _VIDEO_EXTS):
        return True
    if not any(_host_matches(host, item) for item in _VIDEO_HOSTS):
        return False
    if host in _SHORT_HOSTS:
        return bool(path.strip("/"))
    if _host_matches(host, "bilibili.com"):
        return _is_bilibili(host, path)
    if _host_matches(host, "youtube.com") or host == "youtu.be":
        return _is_youtube(host, path, parse_qs(parsed.query))
    if _host_matches(host, "x.com") or _host_matches(host, "twitter.com"):
        return _is_twitter(host, path)
    if _host_matches(host, "instagram.com"):
        return _is_instagram(host, path)
    if _host_matches(host, "tiktok.com"):
        return _is_tiktok(host, path)
    if _host_matches(host, "douyin.com") or host in {"v.douyin.com", "iesdouyin.com"}:
        return _is_douyin(host, path, parse_qs(parsed.query))
    if _host_matches(host, "kuaishou.com"):
        return _is_kuaishou(host, path)
    if _host_matches(host, "weibo.com") or _host_matches(host, "weibo.cn"):
        return _is_weibo(host, path)
    if _host_matches(host, "xiaohongshu.com") or host in {"xhslink.com", "xhslink.cn"}:
        return _is_xhs(host, path)
    # vimeo / dailymotion / twitch / ixigua：至少要求不是首页/搜索页
    return bool(path.strip("/"))
