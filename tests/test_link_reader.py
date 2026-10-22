from __future__ import annotations

import asyncio

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.exception import FinishedException

from plugins.claude_chat import handlers


def make_event(text: str, user_id: int = 555001) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=1700000000,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=user_id,
        message_type="group",
        message_id=1,
        message=Message(text),
        original_message=Message(text),
        raw_message=text,
        font=0,
        sender={"user_id": user_id, "nickname": "测试", "role": "member"},
        group_id=123456,
        to_me=False,
    )


def test_link_extraction_and_media_skip() -> None:
    assert (
        handlers._extract_link_url("看看这个 https://example.com/a，")
        == "https://example.com/a"
    )
    assert handlers._looks_like_media_link("https://www.bilibili.com/video/BV1xx") is True
    assert handlers._looks_like_media_link("https://cdn.example.com/a.mp4") is True
    assert handlers._looks_like_media_link("https://example.com/article") is False


def test_parse_html_extracts_main_text() -> None:
    html = """
    <html><head><title>测试标题</title>
    <meta name="description" content="这是摘要">
    <script>bad()</script></head>
    <body><nav>导航</nav><p>这是正文第一段。</p><p>这是正文第二段。</p></body></html>
    """
    page = handlers._parse_html(html, "https://example.com/a", "https://example.com/a")
    assert page.title == "测试标题"
    assert page.description == "这是摘要"
    assert "正文第一段" in page.text
    assert "bad()" not in page.text
    assert "导航" not in page.text


def test_link_rule_skips_video_and_commands(monkeypatch) -> None:
    monkeypatch.setattr(handlers.plugin_config, "link_reader_enabled", True)
    monkeypatch.setattr(handlers.plugin_config, "link_reader_groups", [])
    assert handlers._link_rule(make_event("https://example.com/article")) is True
    assert handlers._link_rule(make_event("https://www.bilibili.com/video/BV1xx")) is False
    assert handlers._link_rule(make_event("/read https://example.com/article")) is False


def test_read_command_sends_commentary(monkeypatch) -> None:
    class FakeMatcher:
        def __init__(self) -> None:
            self.sent = []
            self.final = None

        async def send(self, message):
            self.sent.append(message)

        async def finish(self, message=None):
            self.final = message
            raise FinishedException

    async def fake_fetch(url: str):
        return handlers.PageContent(
            url=url,
            final_url=url,
            title="标题",
            description="摘要",
            text="这是一段足够长的网页正文，用来测试感慨功能是否正常工作。" * 3,
        )

    async def fake_comment(bot, event, page):
        return "结论先说：这页有点意思。\n理由也简单，信息够，态度清楚。"

    event = make_event("/read https://example.com/article")
    matcher = FakeMatcher()
    monkeypatch.setattr(handlers, "_fetch_page", fake_fetch)
    monkeypatch.setattr(handlers, "_comment_on_page", fake_comment)
    monkeypatch.setattr(handlers, "_link_last", {})
    monkeypatch.setattr(handlers, "_link_daily", {})
    monkeypatch.setattr(handlers.plugin_config, "link_reader_enabled", True)

    with pytest.raises(FinishedException):
        asyncio.run(
            handlers._handle_read(
                None, event, matcher, Message("https://example.com/article")
            )
        )

    assert matcher.final is not None
    assert "这页有点意思" in str(matcher.final)
