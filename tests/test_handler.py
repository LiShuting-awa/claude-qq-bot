from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment

from plugins.claude_chat import handlers
from plugins.claude_chat.claude import ClaudeReply
from plugins.claude_chat.session import SessionStore


def _make_event(*, to_me: bool = True, user_id: int = 123456, text: str = "你好") -> GroupMessageEvent:
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
        sender={"user_id": user_id, "nickname": "测试用户"},
        group_id=987654,
        to_me=to_me,
    )


def test_chat_rule_requires_at_in_group() -> None:
    assert handlers._chat_rule(_make_event(to_me=True)) is True
    assert handlers._chat_rule(_make_event(to_me=False)) is False


def test_chat_rule_detects_at_in_middle() -> None:
    message = Message(MessageSegment.at(10000)) + Message(" 你好")
    event = _make_event(to_me=False)
    event.message = message
    event.original_message = message
    assert handlers._chat_rule(event) is True


def test_blocked_user_is_ignored(monkeypatch) -> None:
    monkeypatch.setattr(handlers, "is_blocked", lambda user_id: int(user_id) == 123456789)
    event = _make_event(user_id=123456789)
    assert handlers._chat_rule(event) is False
    assert handlers._is_allowed(event) is False


def test_group_memory_is_separated_per_qq(monkeypatch) -> None:
    monkeypatch.setattr(handlers.plugin_config, "claude_group_memory_mode", "per_user")
    key_a = handlers._session_key(_make_event(user_id=111))
    key_b = handlers._session_key(_make_event(user_id=222))
    assert key_a == "group:987654:user:111"
    assert key_b == "group:987654:user:222"
    assert key_a != key_b

    monkeypatch.setattr(handlers.plugin_config, "claude_group_memory_mode", "shared")
    assert handlers._session_key(_make_event(user_id=111)) == "group:987654"


def test_handler_end_to_end(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(
            Path(tmp) / "sessions.json",
            ttl_seconds=3600,
            max_messages=20,
            max_chars=10000,
        )
        monkeypatch.setattr(handlers, "store", store)

        captured: dict = {}

        async def fake_complete(messages, system):
            captured["messages"] = messages
            captured["system"] = system
            return ClaudeReply("**你好**，我是 Claude。", input_tokens=20, output_tokens=10)

        monkeypatch.setattr(handlers.claude, "complete", fake_complete)
        monkeypatch.setattr(handlers.plugin_config, "claude_tools_enabled", False)

        sent: list = []

        async def fake_send(self, event, message, **kwargs):
            sent.append(message)
            return {"message_id": 999}

        monkeypatch.setattr(Bot, "send", fake_send)

        bot = object.__new__(Bot)
        bot.self_id = "10000"
        event = _make_event(user_id=555001)

        asyncio.run(handlers._handle_chat(bot, event))

        assert len(sent) == 1
        assert "你好，我是 Claude。" in sent[0].extract_plain_text()
        assert "**" not in sent[0].extract_plain_text()

        assert captured["messages"][0] == {"role": "user", "content": [{"type": "text", "text": "你好"}]}
        assert "QQ 群聊（群号 987654）" in captured["system"]

        session = asyncio.run(store.get("group:987654:user:555001"))
        assert [m["role"] for m in session.messages] == ["user", "assistant"]
        assert session.input_tokens == 20
        assert session.output_tokens == 10
