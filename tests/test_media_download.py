from __future__ import annotations

import asyncio
import tempfile

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.exception import FinishedException

from plugins.media_download import handlers
from plugins.media_download import bilibili


def test_extract_url() -> None:
    assert (
        handlers._extract_url("看这个 https://www.bilibili.com/video/BV1xx，")
        == "https://www.bilibili.com/video/BV1xx"
    )
    assert (
        handlers._extract_url("www.youtube.com/watch?v=abc")
        == "https://www.youtube.com/watch?v=abc"
    )
    assert handlers._extract_url("没有链接") == ""


def test_private_hosts_are_blocked() -> None:
    assert handlers._blocked_host("127.0.0.1") is True
    assert handlers._blocked_host("localhost") is True
    assert handlers._blocked_host("example.local") is True
    assert handlers._blocked_host("10.0.0.1") is True
    assert handlers._blocked_host("192.168.1.1") is True
    assert handlers._blocked_host("example.com") is False

    async def check() -> None:
        with pytest.raises(ValueError):
            await handlers._validate_url("http://127.0.0.1/video.mp4")

    asyncio.run(check())


def test_pick_video_file(tmp_path) -> None:
    small = tmp_path / "small.mp4"
    small.write_bytes(b"x" * 10)
    large = tmp_path / "large.mp4"
    large.write_bytes(b"x" * 100)
    (tmp_path / "notes.txt").write_text("x")
    assert handlers._pick_video_file(tmp_path) == large


def test_bilibili_card_helpers() -> None:
    assert bilibili._extract_bvid("https://www.bilibili.com/video/BV1xx") == ""
    assert bilibili._extract_bvid("https://www.bilibili.com/video/BV19SJf6kEyk/") == "BV19SJf6kEyk"
    assert bilibili.is_bilibili_url("https://www.bilibili.com/video/BV19SJf6kEyk/") is True
    assert bilibili.is_bilibili_url("https://example.com/video") is False
    assert bilibili._fmt_count(12345) == "1.2万"
    info = bilibili.BilibiliInfo(
        bvid="BV19SJf6kEyk",
        title="测试视频",
        author="测试 UP",
        cover_url="",
        view=12345,
        like=678,
        coin=9,
        favorite=10,
        share=11,
        danmaku=12,
        duration=100,
        cid=1,
    )
    png = bilibili.build_card(info, b"")
    assert png.startswith(b"\x89PNG")
    assert len(png) > 1000


def test_looks_like_video() -> None:
    assert handlers._looks_like_video("https://www.bilibili.com/video/BV1xx") is True
    assert handlers._looks_like_video("https://youtu.be/abc") is True
    assert handlers._looks_like_video("https://cdn.example.com/a.mp4") is True
    assert handlers._looks_like_video("https://example.com/article") is False


def test_download_command_sends_video(monkeypatch) -> None:
    class FakeMatcher:
        def __init__(self) -> None:
            self.sent = []
            self.final = None

        async def send(self, message):
            self.sent.append(message)

        async def finish(self, message=None):
            self.final = message
            raise FinishedException

    def fake_download(url: str, tmpdir):
        path = tmpdir / "video.mp4"
        path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)
        return path, "test", 3.0

    async def fake_validate(url: str) -> None:
        return None

    event = GroupMessageEvent(
        time=1700000000,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=555001,
        message_type="group",
        message_id=1,
        message=Message("/mp4 https://example.com/video"),
        original_message=Message("/mp4 https://example.com/video"),
        raw_message="/mp4 https://example.com/video",
        font=0,
        sender={"user_id": 555001, "nickname": "测试", "role": "member"},
        group_id=123456,
        to_me=False,
    )
    matcher = FakeMatcher()
    monkeypatch.setattr(handlers, "_validate_url", fake_validate)
    monkeypatch.setattr(handlers, "_download_sync", fake_download)
    monkeypatch.setattr(handlers, "_last_request", {})
    monkeypatch.setattr(handlers, "_daily_user", {})
    monkeypatch.setattr(handlers.plugin_config, "media_download_enabled", True)
    monkeypatch.setattr(handlers.plugin_config, "media_allowed_groups", [])
    monkeypatch.setattr(handlers.plugin_config, "media_allowed_users", [])

    with pytest.raises(FinishedException):
        asyncio.run(
            handlers._handle_download(
                None, event, matcher, Message("https://example.com/video")
            )
        )

    assert matcher.sent
    assert matcher.final is not None
    assert matcher.final.type == "video"


def test_auto_rule_and_handler(monkeypatch) -> None:
    class FakeMatcher:
        def __init__(self) -> None:
            self.sent = []
            self.final = None

        async def send(self, message):
            self.sent.append(message)

        async def finish(self, message=None):
            self.final = message
            raise FinishedException

    def fake_download(url: str, tmpdir):
        path = tmpdir / "video.mp4"
        path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)
        return path, "test", 3.0

    async def fake_validate(url: str) -> None:
        return None

    event = GroupMessageEvent(
        time=1700000000,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=555001,
        message_type="group",
        message_id=2,
        message=Message("看这个 https://www.bilibili.com/video/BV1xx"),
        original_message=Message("看这个 https://www.bilibili.com/video/BV1xx"),
        raw_message="看这个 https://www.bilibili.com/video/BV1xx",
        font=0,
        sender={"user_id": 555001, "nickname": "测试", "role": "member"},
        group_id=123456,
        to_me=False,
    )
    monkeypatch.setattr(handlers.plugin_config, "media_auto_enabled", True)
    monkeypatch.setattr(handlers.plugin_config, "media_auto_groups", [])
    monkeypatch.setattr(handlers.plugin_config, "media_allowed_groups", [])
    monkeypatch.setattr(handlers.plugin_config, "media_allowed_users", [])
    assert handlers._auto_rule(event) is True

    matcher = FakeMatcher()
    monkeypatch.setattr(handlers, "_validate_url", fake_validate)
    monkeypatch.setattr(handlers, "_download_sync", fake_download)
    monkeypatch.setattr(handlers, "_recent_links", {})
    monkeypatch.setattr(handlers, "_last_request", {})
    monkeypatch.setattr(handlers, "_daily_user", {})

    with pytest.raises(FinishedException):
        asyncio.run(handlers._handle_auto(event, matcher))

    assert matcher.final is not None
    assert matcher.final.type == "video"
