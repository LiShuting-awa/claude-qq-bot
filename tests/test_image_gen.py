from __future__ import annotations

import asyncio

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.exception import FinishedException

from plugins.image_gen import handlers


def test_unsafe_and_image_type() -> None:
    assert handlers._unsafe("a cute cat") is False
    assert handlers._unsafe("nsfw nude") is True
    assert handlers._sniff_media_type(b"\xff\xd8\xff\xe0" + b"0" * 8) == "image/jpeg"
    assert handlers._sniff_media_type(b"\x89PNG\r\n\x1a\n" + b"0" * 8) == "image/png"
    assert handlers._sniff_media_type(b"not an image") is None


def test_draw_command_sends_image(monkeypatch) -> None:
    class FakeMatcher:
        def __init__(self) -> None:
            self.sent = []
            self.final = None

        async def send(self, message):
            self.sent.append(message)

        async def finish(self, message=None):
            self.final = message
            raise FinishedException

    async def fake_generate(prompt: str):
        assert "cat" in prompt
        return b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png"

    event = GroupMessageEvent(
        time=1700000000,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=555001,
        message_type="group",
        message_id=1,
        message=Message("/draw a cat"),
        original_message=Message("/draw a cat"),
        raw_message="/draw a cat",
        font=0,
        sender={"user_id": 555001, "nickname": "测试", "role": "member"},
        group_id=123456,
        to_me=False,
    )
    matcher = FakeMatcher()
    monkeypatch.setattr(handlers, "_generate", fake_generate)
    monkeypatch.setattr(handlers, "_last_request", {})
    monkeypatch.setattr(handlers, "_daily_user", {})
    monkeypatch.setattr(handlers, "_daily_total", 0)
    monkeypatch.setattr(handlers.plugin_config, "image_gen_enabled", True)
    monkeypatch.setattr(handlers.plugin_config, "image_gen_allowed_groups", [])
    monkeypatch.setattr(handlers.plugin_config, "image_gen_allowed_users", [])

    with pytest.raises(FinishedException):
        asyncio.run(handlers._handle_draw(None, event, matcher, Message("a cat")))

    assert matcher.sent
    assert matcher.final is not None
    assert any(seg.type == "image" for seg in matcher.final)
