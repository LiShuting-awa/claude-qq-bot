"""X/Twitter 链接解析：优先 fxtwitter / vxtwitter 镜像 API，字段宽松解析。

X 的官方 GraphQL 接口对匿名请求越来越不友好（query hash 经常变、游客访问被限），
所以这里走固定的镜像 API：无需 Key、返回直链 mp4。两边都挂了再交给 yt-dlp 兜底。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx
from nonebot import logger

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class TweetError(Exception):
    """推文拿不到（不存在/受限/接口挂了），message 可以直接发给群友。"""


# 匹配 twitter.com / x.com / fixupx / vxtwitter / fxtwitter 的推文链接，
# 前面不能是字母数字点@-（排除 max.com、邮箱这类），scheme 和 mobile. 可省略；
# screen_name 段可有可无（x.com/i/web/status/1 这类分享路径没有）。
_TWEET_RE = re.compile(
    r"(?<![\w.@-])"
    r"(?:https?://)?"
    r"(?:mobile\.)?"
    r"(?:twitter|x|fixupx|vxtwitter|fxtwitter)\.com/"
    r"(?:([A-Za-z0-9_]{1,20})/)?"
    r"(?:web/)?"
    r"status(?:es)?/(\d+)",
    re.IGNORECASE,
)

# 这些「用户名」其实是路径前缀，不是真实 handle，请求镜像 API 时要丢掉。
_BOGUS_SCREENS = {"i", "web", "home", "hashtag", "search"}

_VARIANT_SIZE_RE = re.compile(r"/(\d{2,4})x(\d{2,4})/")
_TCO_RE = re.compile(r"https?://t\.co/\w+")


@dataclass
class VideoVariant:
    url: str
    bitrate: int = 0
    width: int = 0
    height: int = 0


@dataclass
class TweetMedia:
    kind: str  # "video" / "photo" / "gif"
    url: str
    thumb: str = ""
    duration: float | None = None
    width: int = 0
    height: int = 0
    variants: list[VideoVariant] = field(default_factory=list)


@dataclass
class TweetInfo:
    tweet_id: str = ""
    screen_name: str = ""
    author_name: str = ""
    text: str = ""
    media: list[TweetMedia] = field(default_factory=list)
    from_quote: bool = False
    """媒体其实取自引用的推文（转推视频时本体常常没媒体）。"""
    quoted_name: str = ""


def find_tweet_urls(text: str) -> list[tuple[str | None, str]]:
    """从文本里抽出（screen_name, tweet_id）列表，按出现顺序去重；screen_name 可能为 None。"""
    found: list[tuple[str | None, str]] = []
    seen: set[str] = set()
    for match in _TWEET_RE.finditer(text or ""):
        tweet_id = match.group(2)
        if tweet_id in seen:
            continue
        seen.add(tweet_id)
        screen = match.group(1)
        if screen and screen.casefold() in _BOGUS_SCREENS:
            screen = None
        found.append((screen, tweet_id))
    return found


def tweet_url(screen_name: str | None, tweet_id: str) -> str:
    """还原一条规范的推文链接，交给 yt-dlp 之类使用。"""
    handle = screen_name or "i"
    return f"https://x.com/{handle}/status/{tweet_id}"


def pick_video_url(media: TweetMedia, max_height: int) -> str:
    """从清晰度变体里挑一个：优先不超过上限里最高的；都超了就取最小的，保证有得发。"""
    candidates = [v for v in media.variants if _is_mp4(v.url)]
    if not candidates:
        return media.url
    for variant in candidates:
        if variant.height <= 0:
            variant.width, variant.height = _variant_size(variant.url)
    fitting = [v for v in candidates if 0 < v.height <= max_height]
    if fitting:
        return max(fitting, key=lambda v: (v.height, v.bitrate)).url
    sized = [v for v in candidates if v.height > 0]
    if sized:
        smallest = min(v.height for v in sized)
        return max((v for v in sized if v.height == smallest), key=lambda v: v.bitrate).url
    return max(candidates, key=lambda v: v.bitrate).url


def photo_url(media: TweetMedia) -> str:
    """补全成原图 URL（pbs.twimg.com 的媒体链接缺 name= 时加上 orig）。"""
    url = media.url
    if "pbs.twimg.com/media/" in url and "name=" not in url:
        url += ("&" if "?" in url else "?") + "name=orig"
    return url


def build_caption(info: TweetInfo, limit: int = 160) -> str:
    """拼一条「𝕏 作者：推文内容」的摘要，超长截断。"""
    header = f"𝕏 {info.author_name or '@' + info.screen_name}".strip()
    if info.from_quote:
        header += f"（转推 {info.quoted_name}）" if info.quoted_name else "（转推）"
    text = _clean_text(info.text)
    if not text:
        return header
    budget = max(20, limit - len(header) - 1)
    if len(text) > budget:
        text = text[:budget].rstrip() + "…"
    return f"{header}：{text}"


async def fetch_tweet(
    tweet_id: str,
    screen_name: str | None,
    *,
    bases: list[str],
    proxy: str = "",
    timeout: float = 15.0,
) -> TweetInfo:
    """按顺序请求镜像 API，第一个成功的直接返回；全失败抛 TweetError。"""
    errors: list[str] = []
    not_found = False
    headers = {"user-agent": _UA, "accept": "application/json"}
    async with httpx.AsyncClient(
        proxy=proxy or None,
        timeout=timeout,
        follow_redirects=True,
        headers=headers,
    ) as client:
        for base in bases:
            base = str(base).strip().rstrip("/")
            if not base:
                continue
            style = _api_style(base)
            url = _api_url(base, style, screen_name, tweet_id)
            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:
                logger.warning(f"推特镜像 {base} 请求失败：{type(exc).__name__}: {exc}")
                errors.append(f"{_host(base)} 连不上")
                continue
            try:
                data = resp.json()
            except ValueError:
                errors.append(f"{_host(base)} 返回的不是 JSON")
                continue
            if style == "fx":
                code = int(data.get("code") or 200) if isinstance(data, dict) else 200
                if resp.status_code >= 400 or code >= 400:
                    error = _fx_error(data if isinstance(data, dict) else {}, resp.status_code)
                    if "不存在" in str(error):
                        not_found = True
                    errors.append(f"{_host(base)}: {error}")
                    continue
                info = parse_fxtwitter(data)
            else:
                if resp.status_code >= 400:
                    errors.append(f"{_host(base)}: HTTP {resp.status_code}")
                    continue
                info = parse_vxtwitter(data)
            if info is None:
                errors.append(f"{_host(base)} 响应格式不对")
                continue
            return info
    if not_found:
        raise TweetError("推文不存在或已删除")
    if errors:
        raise TweetError("；".join(errors))
    raise TweetError("没有配置可用的解析接口")


def parse_fxtwitter(data: dict) -> TweetInfo | None:
    """解析 api.fxtwitter.com 的 JSON（见 https://github.com/FixTweet/FxTwitter）。"""
    tweet = data.get("tweet") if isinstance(data, dict) else None
    if not isinstance(tweet, dict):
        return None
    info = _tweet_base(tweet)
    info.media = _fx_media(tweet)
    if not info.media:
        info.media, info.from_quote, info.quoted_name = _fx_quote_media(tweet)
    return info


def parse_vxtwitter(data: dict) -> TweetInfo | None:
    """解析 api.vxtwitter.com 的 JSON（见 https://github.com/dylanpdx/BetterTwitFix）。"""
    if not isinstance(data, dict):
        return None
    if not data.get("tweetID") and "mediaURLs" not in data and "media_extended" not in data:
        return None
    info = TweetInfo(
        tweet_id=str(data.get("tweetID") or ""),
        screen_name=str(data.get("user_screen_name") or ""),
        author_name=str(data.get("user_name") or data.get("user_screen_name") or ""),
        text=_clean_text(data.get("text")),
    )
    extended = data.get("media_extended")
    if isinstance(extended, list) and extended:
        for item in extended:
            media = _vx_item(item) if isinstance(item, dict) else None
            if media:
                info.media.append(media)
    else:
        for url in data.get("mediaURLs") or []:
            if isinstance(url, str) and url:
                info.media.append(_guess_media(url))
    if not info.media:
        quote = data.get("qrt")
        if isinstance(quote, dict):
            quote_media = _vx_media_list(quote)
            if quote_media:
                info.media = quote_media
                info.from_quote = True
                info.quoted_name = str(quote.get("user_name") or quote.get("user_screen_name") or "")
    return info


def _tweet_base(tweet: dict) -> TweetInfo:
    author = tweet.get("author") if isinstance(tweet.get("author"), dict) else {}
    return TweetInfo(
        tweet_id=str(tweet.get("id") or ""),
        screen_name=str(author.get("screen_name") or ""),
        author_name=str(author.get("name") or author.get("screen_name") or ""),
        text=_clean_text(tweet.get("text")),
    )


def _fx_media(tweet: dict) -> list[TweetMedia]:
    container = tweet.get("media")
    items = container.get("all") if isinstance(container, dict) else None
    media: list[TweetMedia] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if parsed := _fx_item(item):
            media.append(parsed)
    return media


def _fx_item(item: dict) -> TweetMedia | None:
    kind = str(item.get("type") or "").casefold()
    url = str(item.get("url") or "")
    if kind not in {"video", "photo", "gif"} or not url:
        return None
    variants: dict[str, VideoVariant] = {}
    raw_variants = list(item.get("formats") or []) + list(item.get("variants") or [])
    for raw in raw_variants:
        if not isinstance(raw, dict):
            continue
        variant_url = str(raw.get("url") or "")
        if not variant_url or not _is_mp4(variant_url):
            continue
        bitrate = _int(raw.get("bitrate"))
        width, height = _variant_size(variant_url)
        old = variants.get(variant_url)
        if old is None or bitrate > old.bitrate:
            variants[variant_url] = VideoVariant(variant_url, bitrate, width, height)
    return TweetMedia(
        kind=kind,
        url=url,
        thumb=str(item.get("thumbnail_url") or ""),
        duration=_float(item.get("duration")),
        width=_int(item.get("width")),
        height=_int(item.get("height")),
        variants=list(variants.values()),
    )


def _fx_quote_media(tweet: dict) -> tuple[list[TweetMedia], bool, str]:
    quote = tweet.get("quote") or tweet.get("qrt")
    if not isinstance(quote, dict):
        return [], False, ""
    media = _fx_media(quote)
    if not media:
        return [], False, ""
    author = quote.get("author") if isinstance(quote.get("author"), dict) else {}
    return media, True, str(author.get("name") or author.get("screen_name") or "")


def _vx_media_list(data: dict) -> list[TweetMedia]:
    media: list[TweetMedia] = []
    extended = data.get("media_extended")
    if isinstance(extended, list) and extended:
        for item in extended:
            parsed = _vx_item(item) if isinstance(item, dict) else None
            if parsed:
                media.append(parsed)
    else:
        for url in data.get("mediaURLs") or []:
            if isinstance(url, str) and url:
                media.append(_guess_media(url))
    return media


def _vx_item(item: dict) -> TweetMedia | None:
    url = str(item.get("url") or "")
    if not url:
        return None
    kind_map = {"video": "video", "image": "photo", "photo": "photo", "gif": "gif"}
    kind = kind_map.get(str(item.get("type") or "").casefold(), "")
    if not kind:
        return None
    size = item.get("size") if isinstance(item.get("size"), dict) else {}
    duration_ms = _float(item.get("duration_millis"))
    return TweetMedia(
        kind=kind,
        url=url,
        thumb=str(item.get("thumbnail_url") or ""),
        duration=duration_ms / 1000 if duration_ms else None,
        width=_int(size.get("width")),
        height=_int(size.get("height")),
    )


def _guess_media(url: str) -> TweetMedia:
    kind = "photo" if "pbs.twimg.com" in url else "video"
    return TweetMedia(kind=kind, url=url)


def _api_style(base: str) -> str:
    name = base.casefold()
    return "vx" if "vxtwitter" in name or "fixvx" in name else "fx"


def _api_url(base: str, style: str, screen_name: str | None, tweet_id: str) -> str:
    screen = (screen_name or "").casefold()
    if style == "vx":
        return f"{base}/{screen_name or 'i'}/status/{tweet_id}"
    if not screen_name or screen in _BOGUS_SCREENS:
        return f"{base}/status/{tweet_id}"
    return f"{base}/{screen_name}/status/{tweet_id}"


def _fx_error(data: dict, status: int) -> TweetError:
    code = _int(data.get("code")) or status
    message = str(data.get("message") or "").strip()
    if code == 404:
        return TweetError("推文不存在或已删除")
    if code in (401, 403):
        return TweetError("推文受限（受保护账号或年龄限制），匿名看不到")
    if code == 429:
        return TweetError("解析接口被限流了，稍后再试")
    return TweetError(f"接口返回 {code}{('：' + message) if message else ''}")


def _variant_size(url: str) -> tuple[int, int]:
    match = _VARIANT_SIZE_RE.search(url)
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def _is_mp4(url: str) -> bool:
    bare = url.casefold().split("?", 1)[0].split("#", 1)[0]
    return bare.endswith(".mp4")


def _clean_text(value: object) -> str:
    text = _TCO_RE.sub("", str(value or ""))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _host(base: str) -> str:
    return base.split("://", 1)[-1].split("/", 1)[0]
