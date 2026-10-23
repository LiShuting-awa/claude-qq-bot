"""外媒新闻聚合：多源 RSS → 合并去重 → 抓原文做详细摘录。

不依赖大模型凭据：头条来自外媒官方 RSS，摘录直接取原文正文。
直连被拒的源（如纽约每日新闻有反爬）自动退到 Bing News RSS 搜索同站文章；
被墙的站点靠 claude_chat 的 fetch_page（直连失败自动走 r.jina.ai 镜像）。
"""

from __future__ import annotations

import asyncio
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlparse

import httpx2
from nonebot import get_plugin_config, logger

from .config import Config

_config = get_plugin_config(Config)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass(slots=True)
class Feed:
    name: str
    url: str
    bing_site: str = ""
    """官方 RSS 抓不到时，用 Bing News RSS 搜这个域名下的新闻当备胎。"""


# 内置外媒源：官方 RSS，都是当天的头条和链接；纽约每日新闻放最前
BUILTIN_FEEDS: list[Feed] = [
    Feed("纽约每日新闻", "https://www.nydailynews.com/feed/", bing_site="nydailynews.com"),
    Feed("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml", bing_site="bbc.com"),
    Feed("卫报", "https://www.theguardian.com/world/rss", bing_site="theguardian.com"),
    Feed("半岛电视台", "https://www.aljazeera.com/xml/rss/all.xml", bing_site="aljazeera.com"),
    Feed("纽约时报", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", bing_site="nytimes.com"),
    Feed("德国之声", "https://rss.dw.com/rdf/rss-en-world", bing_site="dw.com"),
    Feed("NPR", "https://feeds.npr.org/1004/rss.xml", bing_site="npr.org"),
    Feed("France 24", "https://www.france24.com/en/rss", bing_site="france24.com"),
    Feed("CNA", "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml", bing_site="channelnewsasia.com"),
]


@dataclass(slots=True)
class NewsItem:
    title: str
    url: str
    source: str
    published: datetime | None = None
    summary: str = ""


# ---------------------------------------------------------------------------
# RSS 解析（兼容 RSS2 / RDF(RSS1) / Atom，忽略命名空间）
# ---------------------------------------------------------------------------


def _local(tag: str) -> str:
    return tag.rpartition("}")[2]


def _child_text(node: ET.Element, name: str) -> str:
    for child in node:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)  # 转义后可能又露出标签
    return re.sub(r"\s+", " ", text).strip()


def parse_date(raw: str) -> datetime | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_feed(data: bytes | str, source: str) -> list[NewsItem]:
    """把任意 RSS/Atom 源解析成 NewsItem；标题和链接缺一不可。"""
    root = ET.fromstring(data if isinstance(data, bytes) else data.encode("utf-8"))
    items: list[NewsItem] = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        title = _strip_html(_child_text(node, "title"))
        link = _child_text(node, "link")
        if not link:  # Atom 的链接在 href 属性里
            for child in node:
                if _local(child.tag) == "link":
                    link = (child.get("href") or "").strip()
                    break
        if not title or not link:
            continue
        summary = _strip_html(
            _child_text(node, "description") or _child_text(node, "summary")
        )
        items.append(
            NewsItem(
                title=title,
                url=link,
                source=source,
                published=parse_date(
                    _child_text(node, "pubDate")
                    or _child_text(node, "published")
                    or _child_text(node, "date")
                ),
                summary=summary[:400],
            )
        )
    return items


# ---------------------------------------------------------------------------
# 合并：过期剔除、同题去重、按源轮流取
# ---------------------------------------------------------------------------


def _norm_title(title: str) -> str:
    return re.sub(r"[^0-9a-z一-鿿]+", "", title.lower())


def merge_items(
    groups: list[list[NewsItem]],
    *,
    hours: int,
    limit: int,
    now: datetime | None = None,
) -> list[NewsItem]:
    """多源合并：丢过期、去重同题，按源轮流取保证一家不霸屏。"""
    now = now or datetime.now(timezone.utc)
    cutoff = now.timestamp() - hours * 3600

    by_source: dict[str, list[NewsItem]] = {}
    seen: set[str] = set()
    for group in groups:
        for item in group:
            if item.published is not None:
                published = item.published
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                if published.timestamp() < cutoff:
                    continue
            key = _norm_title(item.title)
            if not key or key in seen:
                continue
            seen.add(key)
            by_source.setdefault(item.source, []).append(item)

    merged: list[NewsItem] = []
    while len(merged) < limit:
        progressed = False
        for source in sorted(by_source):
            if len(merged) >= limit:
                break
            queue = by_source[source]
            if queue:
                merged.append(queue.pop(0))
                progressed = True
        if not progressed:
            break
    return merged


def pick_details(items: list[NewsItem], count: int) -> list[NewsItem]:
    """挑要抓原文的头条：尽量一家外媒一篇，源不够再同源补位。"""
    picked: list[NewsItem] = []
    used: set[str] = set()
    for item in items:
        if len(picked) >= count:
            break
        if item.source in used:
            continue
        used.add(item.source)
        picked.append(item)
    for item in items:
        if len(picked) >= count:
            break
        if item not in picked:
            picked.append(item)
    return picked


# ---------------------------------------------------------------------------
# 抓取
# ---------------------------------------------------------------------------

_BING_NEWS_RSS = (
    "https://www.bing.com/news/search?q=site%3A{site}&format=RSS"
    "&setmkt=en-US&setlang=en-US"
)


def _real_bing_url(raw: str) -> str:
    """Bing News RSS 的链接包在 apiclick 跳转里，解出真实文章地址。"""
    if "bing.com" in raw and "apiclick" in raw:
        target = parse_qs(urlparse(raw).query).get("url")
        if target:
            return target[0]
    return raw


async def _fetch_one(client: httpx2.AsyncClient, feed: Feed) -> list[NewsItem]:
    try:
        response = await client.get(feed.url)
        response.raise_for_status()
        items = parse_feed(response.content, feed.name)
        if items:
            return items
    except Exception:
        pass  # 官方源抓不动就走下面的 Bing 备胎
    if not feed.bing_site:
        return []
    response = await client.get(_BING_NEWS_RSS.format(site=feed.bing_site))
    response.raise_for_status()
    items = parse_feed(response.content, feed.name)
    for item in items:
        item.url = _real_bing_url(item.url)
    return items


async def collect_items(
    extra_feeds: list[str] | None = None,
    *,
    hours: int,
    limit: int,
    timeout: float,
) -> list[NewsItem]:
    feeds = [
        *BUILTIN_FEEDS,
        *(Feed(urlparse(url).hostname or "RSS", url) for url in extra_feeds or []),
    ]
    async with httpx2.AsyncClient(
        timeout=timeout, follow_redirects=True, headers=_HEADERS
    ) as client:
        results = await asyncio.gather(
            *(_fetch_one(client, feed) for feed in feeds), return_exceptions=True
        )
    groups: list[list[NewsItem]] = []
    for feed, result in zip(feeds, results):
        if isinstance(result, BaseException):
            logger.warning(f"外媒源「{feed.name}」抓取失败：{result}")
            continue
        groups.append(result)
    return merge_items(groups, hours=hours, limit=limit)


async def fetch_excerpts(
    items: list[NewsItem], *, excerpt_chars: int, timeout: float
) -> list[tuple[NewsItem, str]]:
    """抓原文正文做详细摘录；某篇失败就跳过，不拖垮整个汇总。"""
    from plugins.claude_chat.web_search import fetch_page  # 懒加载防插件顺序问题

    async def _one(item: NewsItem) -> tuple[NewsItem, str] | None:
        try:
            page = await fetch_page(item.url, max_chars=excerpt_chars, timeout=timeout)
            return item, page.text
        except Exception:
            logger.warning(f"原文抓取失败（{item.source}）：{item.url}")
            return None

    pages = await asyncio.gather(*(_one(item) for item in items))
    return [pair for pair in pages if pair is not None]


def _store_knowledge(items: list[NewsItem], excerpts: list[tuple[NewsItem, str]]) -> None:
    """顺手存进本地知识库，之后聊天里查资料能搜到今天的外媒报道。"""
    try:
        from plugins.claude_chat.handlers import knowledge
        from plugins.claude_chat.handlers import plugin_config as cc_config

        if not cc_config.knowledge_enabled:
            return
        for item in items:
            knowledge.upsert(
                url=item.url,
                title=item.title,
                source=item.source,
                published=item.published.isoformat() if item.published else "",
                content=item.summary,
                query="国际新闻",
            )
        for item, text in excerpts:
            knowledge.upsert(
                url=item.url,
                title=item.title,
                source=f"{item.source}正文",
                content=text,
                query="国际新闻",
            )
    except Exception:
        logger.warning("外媒新闻入库失败", exc_info=True)


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------


def _short(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_digest(
    items: list[NewsItem],
    excerpts: list[tuple[NewsItem, str]],
    *,
    title: str = "📰 今日外媒头条",
) -> str:
    lines = [title]
    for index, item in enumerate(items, 1):
        lines.append(f"{index}. [{item.source}] {_short(item.title, 80)}")
    if excerpts:
        # 摘录总预算：QQ 一条消息太长会被吞，全文控制在 3400 字上下
        budget = max(400, (3400 - sum(len(line) for line in lines)) // len(excerpts))
        lines.append("")
        lines.append("📖 原文摘录")
        for index, (item, text) in enumerate(excerpts, 1):
            lines.append("")
            lines.append(f"{index}. [{item.source}] {_short(item.title, 60)}")
            lines.append(f"「{_short(text, budget)}」")
    return "\n".join(lines)


async def build_digest(
    *,
    hours: int | None = None,
    limit: int | None = None,
    detail_count: int | None = None,
    excerpt_chars: int | None = None,
    timeout: float | None = None,
    extra_feeds: list[str] | None = None,
    title: str = "📰 今日外媒头条",
) -> str:
    """跑一整轮：抓头条 → 挑几篇抓原文 → 格式化 → 顺手入库。"""
    hours = _config.world_news_hours if hours is None else hours
    limit = _config.world_news_headline_limit if limit is None else limit
    detail_count = _config.world_news_detail_count if detail_count is None else detail_count
    excerpt_chars = _config.world_news_excerpt_chars if excerpt_chars is None else excerpt_chars
    timeout = _config.world_news_fetch_timeout if timeout is None else timeout
    extra_feeds = _config.world_news_feeds if extra_feeds is None else extra_feeds

    items = await collect_items(extra_feeds, hours=hours, limit=limit, timeout=timeout)
    if not items:
        return "这会儿外媒源一个都没抓到，稍后再试。"
    picked = pick_details(items, detail_count)
    excerpts: list[tuple[NewsItem, str]] = []
    if picked:
        try:
            excerpts = await fetch_excerpts(
                picked, excerpt_chars=excerpt_chars, timeout=timeout
            )
        except Exception:
            logger.warning("原文摘录批量失败", exc_info=True)
    _store_knowledge(items, excerpts)
    return format_digest(items, excerpts, title=title)


def hours_ago(hours: float, *, now: datetime | None = None) -> datetime:
    """测试辅助：now 往前推几小时。"""
    return (now or datetime.now(timezone.utc)) - timedelta(hours=hours)
