from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.exception import FinishedException

from plugins.proactive_chat import handlers
from qqbot_stickers import StickerLibrary, stickers


def _library() -> StickerLibrary:
    return StickerLibrary(Path("data/stickers.json"))


def test_sticker_library_loads_and_parses_markers() -> None:
    lib = _library()
    assert lib.stickers
    assert lib.catalog_text(limit=3).count("\n") == 2
    assert lib.get(lib.stickers[0].id) is not None
    assert lib.extract_marker("好，配一个 [STICKER:3]") == 3
    text, sticker_id = lib.parse_marker("好，配一个 [STICKER:3]")
    assert text == "好，配一个"
    assert sticker_id == 3
    assert lib.parse_marker("没有表情") == ("没有表情", None)


def test_sticker_send_uses_image_segment() -> None:
    class FakeBot:
        def __init__(self) -> None:
            self.calls = []

        async def call_api(self, api, **data):
            self.calls.append((api, data))
            return {"message_id": 1}

    lib = _library()
    sticker = lib.stickers[0]
    bot = FakeBot()
    ok = asyncio.run(lib.send(bot, sticker, group_id=123, reply_to=456))
    assert ok is True
    assert bot.calls[0][0] == "send_group_msg"
    assert bot.calls[0][1]["group_id"] == 123
    message = bot.calls[0][1]["message"]
    assert any(seg.type == "reply" for seg in message)
    assert any(seg.type == "image" for seg in message)

    bot2 = FakeBot()
    assert asyncio.run(lib.send(bot2, sticker, user_id=789)) is True
    assert bot2.calls[0][0] == "send_private_msg"
    assert bot2.calls[0][1]["user_id"] == 789


def test_sticker_command_sends_one(monkeypatch) -> None:
    class FakeBot:
        def __init__(self) -> None:
            self.calls = []

        async def call_api(self, api, **data):
            self.calls.append((api, data))
            return {"message_id": 1}

    class FakeMatcher:
        def __init__(self) -> None:
            self.message = None

        async def finish(self, message=None):
            self.message = message
            raise FinishedException

    event = GroupMessageEvent(
        time=1700000000,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=555001,
        message_type="group",
        message_id=1,
        message=Message("/sticker"),
        original_message=Message("/sticker"),
        raw_message="/sticker",
        font=0,
        sender={"user_id": 555001, "nickname": "测试", "role": "member"},
        group_id=123456,
        to_me=False,
    )
    matcher = FakeMatcher()
    fake_bot = FakeBot()
    stickers._last_sent.clear()
    stickers.enabled = True

    with pytest.raises(FinishedException):
        asyncio.run(handlers._handle_sticker(fake_bot, event, matcher))

    assert fake_bot.calls and fake_bot.calls[0][0] == "send_group_msg"
    assert fake_bot.calls[0][1]["group_id"] == 123456
    assert "发了一个" in str(matcher.message)
