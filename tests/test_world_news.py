from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from nonebot.exception import FinishedException

from plugins.world_news import handlers as wn_handlers
from plugins.world_news.news import (
    NewsItem,
    _real_bing_url,
    format_digest,
    merge_items,
    parse_feed,
    pick_details,
)

RSS2 = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item><title>Storm hits &lt;b&gt;coast&lt;/b&gt;</title>
<link>https://example.com/a</link>
<pubDate>Tue, 23 Oct 2026 08:00:00 GMT</pubDate>
<description>&lt;p&gt;First para&lt;/p&gt;&lt;p&gt;Second para&lt;/p&gt;</description></item>
<item><title>Second story</title><link>https://example.com/b</link></item>
</channel></rss>"""

RDF = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns="http://purl.org/rss/1.0/"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
<item><title>Deutsche Welle story</title>
<link>https://example.com/c</link>
<dc:date>2026-10-23T09:30:00Z</dc:date></item>
</rdf:RDF>"""


# ---------------------------------------------------------------------------
# RSS 解析
# ---------------------------------------------------------------------------


def test_parse_feed_rss2() -> None:
    items = parse_feed(RSS2, "Example")
    assert [i.title for i in items] == ["Storm hits coast", "Second story"]
    assert items[0].url == "https://example.com/a"
    assert items[0].summary == "First para Second para"
    assert items[0].published is not None
    assert items[1].published is None  # 没给时间就保留，不按过期丢


def test_parse_feed_rdf_with_namespaces() -> None:
    items = parse_feed(RDF, "DW")
    assert len(items) == 1
    assert items[0].title == "Deutsche Welle story"
    assert items[0].published is not None


def test_real_bing_url_decodes_apiclick() -> None:
    wrapped = (
        "http://www.bing.com/news/apiclick.aspx?ref=FexRss&aid=&tid=x"
        "&url=https%3a%2f%2fwww.nydailynews.com%2f2026%2f10%2f23%2fstory%2f"
        "&c=1&mkt=en-us"
    )
    assert _real_bing_url(wrapped) == "https://www.nydailynews.com/2026/10/23/story/"
    assert _real_bing_url("https://example.com/direct") == "https://example.com/direct"


# ---------------------------------------------------------------------------
# 合并去重
# ---------------------------------------------------------------------------


def _item(title: str, source: str = "BBC", age_hours: float = 1.0) -> NewsItem:
    return NewsItem(
        title=title,
        url=f"https://x.com/{title}",
        source=source,
        published=datetime.now(timezone.utc) - timedelta(hours=age_hours),
    )


def test_merge_dedupes_and_expires() -> None:
    groups = [
        [_item("Big story", "BBC"), _item("Old news", "BBC", age_hours=72)],
        [_item("Big  story!", "卫报"), _item("Fresh", "卫报", age_hours=2)],
    ]
    merged = merge_items(groups, hours=36, limit=10)
    titles = [i.title for i in merged]
    assert "Old news" not in titles            # 过期剔除
    assert titles.count("Big story") == 1      # 同题去重（归一化后相同）
    assert "Fresh" in titles
    assert merged[0].source != merged[1].source  # 按源轮流，一家不霸屏


def test_merge_respects_limit() -> None:
    groups = [[_item(f"故事{i}", "S") for i in range(5)]]
    assert len(merge_items(groups, hours=36, limit=3)) == 3


def test_pick_details_prefers_distinct_sources() -> None:
    items = [
        _item("A", "BBC"),
        _item("B", "BBC"),
        _item("C", "卫报"),
        _item("D", "NPR"),
    ]
    assert [i.source for i in pick_details(items, 3)] == ["BBC", "卫报", "NPR"]


# ---------------------------------------------------------------------------
# 汇总格式
# ---------------------------------------------------------------------------


def test_format_digest_shows_excerpts_and_caps_length() -> None:
    items = [_item("Headline one"), _item("Headline two", "卫报")]
    excerpts = [(items[0], "很长很长的原文" * 600)]
    digest = format_digest(items, excerpts)
    assert "Headline one" in digest
    assert "原文摘录" in digest
    assert len(digest) < 3600  # QQ 单条消息的安全范围


def test_format_digest_without_excerpts() -> None:
    digest = format_digest([_item("Headline one")], [])
    assert "原文摘录" not in digest


# ---------------------------------------------------------------------------
# 纽约早报排班 + /news 命令
# ---------------------------------------------------------------------------


def test_broadcast_due_gate() -> None:
    now = datetime(2026, 10, 23, 8, 5)
    assert wn_handlers._broadcast_due(now, "", 8) is True
    assert wn_handlers._broadcast_due(now, "2026-10-23", 8) is False  # 今天播过了
    assert wn_handlers._broadcast_due(now, "2026-10-22", 9) is False  # 钟点不对
    assert wn_handlers._broadcast_due(datetime(2026, 10, 23, 7, 59), "", 8) is False


class _FakeEvent:
    group_id = 123456


class _FakeMatcher:
    def __init__(self) -> None:
        self.sent: list = []
        self.final = None

    async def send(self, message):
        self.sent.append(message)

    async def finish(self, message=None):
        self.final = message
        raise FinishedException


@pytest.fixture()
def fast_digest(monkeypatch):
    async def fake_digest(*args, **kwargs):
        return "📰 假汇总"

    monkeypatch.setattr(wn_handlers, "build_digest", fake_digest)
    monkeypatch.setattr(wn_handlers.plugin_config, "world_news_enabled", True)
    monkeypatch.setattr(wn_handlers.plugin_config, "world_news_cooldown_seconds", 600)
    monkeypatch.setattr(wn_handlers, "_last_run", {})
    return fake_digest


def test_news_command_runs_then_cooldowns(fast_digest) -> None:
    matcher = _FakeMatcher()
    with pytest.raises(FinishedException):
        asyncio.run(wn_handlers._handle_news(_FakeEvent(), matcher))
    assert matcher.final == "📰 假汇总"

    # 冷却期内直接拒绝
    matcher2 = _FakeMatcher()
    with pytest.raises(FinishedException):
        asyncio.run(wn_handlers._handle_news(_FakeEvent(), matcher2))
    assert "歇" in matcher2.final
