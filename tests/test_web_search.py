from __future__ import annotations

from plugins.claude_chat import web_search


def test_should_search() -> None:
    assert web_search.should_search("最近 DeepSeek 有什么新消息") is True
    assert web_search.should_search("2026 年发生了什么") is True
    assert web_search.should_search("你好，今天吃什么") is True
    assert web_search.should_search("帮我写个 Python 排序") is False
    assert web_search.should_search("https://example.com/2026") is False


def test_parse_google_news() -> None:
    xml = """<?xml version="1.0"?>
    <rss><channel>
      <item><title>DeepSeek V4.1 发布</title><link>https://example.com/a</link>
      <pubDate>Wed, 21 Oct 2026 10:00:00 GMT</pubDate><source>Example</source>
      <description>test description</description></item>
    </channel></rss>""".encode("utf-8")
    results = web_search.parse_google_news(xml)
    assert len(results) == 1
    assert results[0].title == "DeepSeek V4.1 发布"
    assert results[0].date == "2026-10-21"
    assert results[0].url == "https://example.com/a"


def test_parse_ddg() -> None:
    html = """
    <div class="result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">标题</a>
      <a class="result__snippet">摘要内容</a>
    </div>
    """
    results = web_search.parse_ddg(html)
    assert len(results) == 1
    assert results[0].url == "https://example.com/a"
    assert results[0].title == "标题"


def test_format_results() -> None:
    results = [
        web_search.SearchResult(
            title="标题",
            url="https://example.com",
            snippet="摘要",
            source="来源",
            date="2026-10-21",
        )
    ]
    text = web_search.format_results(results)
    assert "[1] 标题" in text
    assert "https://example.com" in text
    assert "2026-10-21" in text
