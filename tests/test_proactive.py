from __future__ import annotations

import asyncio
import time
from datetime import datetime

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.exception import FinishedException

from plugins.proactive_chat import handlers
from plugins.proactive_chat.activity import Activity, ActivityBuffer, in_quiet_hours
from plugins.proactive_chat.llm import clean_line


def test_in_quiet_hours_cross_midnight() -> None:
    assert in_quiet_hours("23:00-08:00", now=datetime(2026, 1, 1, 23, 30)) is True
    assert in_quiet_hours("23:00-08:00", now=datetime(2026, 1, 1, 7, 59)) is True
    assert in_quiet_hours("23:00-08:00", now=datetime(2026, 1, 1, 8, 0)) is False
    assert in_quiet_hours("23:00-08:00", now=datetime(2026, 1, 1, 12, 0)) is False
    assert in_quiet_hours("08:00-23:00", now=datetime(2026, 1, 1, 12, 0)) is True
    assert in_quiet_hours("", now=datetime(2026, 1, 1, 12, 0)) is False
    assert in_quiet_hours("bad", now=datetime(2026, 1, 1, 12, 0)) is False


def test_activity_buffer_recent_and_limit() -> None:
    buffer = ActivityBuffer(ttl_seconds=600, max_per_group=5)
    for i in range(8):
        buffer.record(1, "群友", f"消息 {i}", now=1000 + i)
    recent = buffer.recent(1, minutes=1, limit=3, now=1010)
    assert [item.text for item in recent] == ["消息 5", "消息 6", "消息 7"]
    assert buffer.count(1, minutes=1, now=1010) == 5
    assert buffer.recent(1, minutes=1, limit=10, now=2000) == []


def test_activity_buffer_purges_empty_groups() -> None:
    buffer = ActivityBuffer(ttl_seconds=60)
    buffer.record(1, "群友", "旧消息", now=0)
    buffer.purge(now=1000)
    assert buffer.recent(1, minutes=10, limit=10, now=1000) == []


def test_clean_line() -> None:
    assert clean_line("SKIP", 120) is None
    assert clean_line("**SKIP**", 120) is None
    assert clean_line("SKIP，不适合", 120) is None
    assert clean_line("跳过", 120) is None
    assert clean_line("“这味儿不对，散散。”", 120) == "这味儿不对，散散。"
    assert clean_line("Claude：说重点。", 120) == "说重点。"
    assert clean_line("hi [CQ:at,qq=1]", 120) == "hi ［CQ:at,qq=1]"
    assert clean_line("", 120) is None
    long_line = clean_line("字" * 200, 30)
    assert long_line is not None
    assert len(long_line) <= 31
    assert long_line.endswith("…")


def test_tick_sends_proactive_message(monkeypatch) -> None:
    class FakeBot:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def call_api(self, api: str, **data):
            self.calls.append((api, data))
            return {"message_id": 1}

    fake_bot = FakeBot()
    buffer = ActivityBuffer(ttl_seconds=900)
    for i in range(4):
        buffer.record(123, "群友", f"消息 {i}", now=time.time())

    async def fake_generate(group_id: int, transcript: str, *, kind: str = "reply") -> str:
        assert group_id == 123
        assert "消息 3" in transcript
        return "这味儿不对，散散。"

    monkeypatch.setattr(handlers, "buffer", buffer)
    monkeypatch.setattr(handlers, "_state_groups", {123})
    monkeypatch.setattr(handlers, "_last_spoke", {})
    monkeypatch.setattr(handlers, "_daily_by_group", {})
    monkeypatch.setattr(handlers, "_daily_total", 0)
    monkeypatch.setattr(handlers, "_speaking", set())
    monkeypatch.setattr(handlers.speaker, "available", lambda: True)
    monkeypatch.setattr(handlers.speaker, "generate", fake_generate)
    monkeypatch.setattr(handlers.nonebot, "get_bots", lambda: {"bot": fake_bot})
    monkeypatch.setattr(handlers.plugin_config, "proactive_enabled", True)
    monkeypatch.setattr(handlers.plugin_config, "proactive_mode", "random")
    monkeypatch.setattr(handlers.plugin_config, "proactive_probability", 1.0)
    monkeypatch.setattr(handlers.plugin_config, "proactive_min_messages", 1)
    monkeypatch.setattr(handlers.plugin_config, "proactive_quiet_hours", "")

    asyncio.run(handlers._tick())

    assert len(fake_bot.calls) == 1
    api, data = fake_bot.calls[0]
    assert api == "send_group_msg"
    assert data["group_id"] == 123
    assert data["message"].extract_plain_text() == "这味儿不对，散散。"


def test_try_join_replies_like_group_member(monkeypatch) -> None:
    class FakeBot:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def call_api(self, api: str, **data):
            self.calls.append((api, data))
            return {"message_id": 1}

    fake_bot = FakeBot()
    buffer = ActivityBuffer(ttl_seconds=900)
    buffer.record(456, "小花生", "你觉得你和deepseek比谁厉害", now=time.time())
    buffer.record(456, "Katastrophe", "看干什么活", now=time.time())

    async def fake_generate(group_id: int, transcript: str, *, kind: str = "reply") -> str:
        assert group_id == 456
        assert kind == "reply"
        assert "小花生" in transcript
        return "那就摆任务，别光比。"

    monkeypatch.setattr(handlers, "buffer", buffer)
    monkeypatch.setattr(handlers, "_state_groups", {456})
    monkeypatch.setattr(handlers, "_last_spoke", {})
    monkeypatch.setattr(handlers, "_daily_by_group", {})
    monkeypatch.setattr(handlers, "_daily_total", 0)
    monkeypatch.setattr(handlers, "_speaking", set())
    monkeypatch.setattr(handlers.speaker, "available", lambda: True)
    monkeypatch.setattr(handlers.speaker, "generate", fake_generate)
    monkeypatch.setattr(handlers.nonebot, "get_bots", lambda: {"bot": fake_bot})
    monkeypatch.setattr(handlers.plugin_config, "proactive_enabled", True)
    monkeypatch.setattr(handlers.plugin_config, "proactive_mode", "conversation")
    monkeypatch.setattr(handlers.plugin_config, "proactive_reply_probability", 1.0)
    monkeypatch.setattr(handlers.plugin_config, "proactive_min_messages", 1)
    monkeypatch.setattr(handlers.plugin_config, "proactive_min_reply_interval_seconds", 10)
    monkeypatch.setattr(handlers.plugin_config, "proactive_quiet_hours", "")
    monkeypatch.setattr(handlers.random, "uniform", lambda a, b: 0.0)

    asyncio.run(handlers._try_join(456))

    assert len(fake_bot.calls) == 1
    api, data = fake_bot.calls[0]
    assert api == "send_group_msg"
    assert data["group_id"] == 456
    assert data["message"].extract_plain_text() == "那就摆任务，别光比。"
    assert buffer.last(456)[-1].nickname == "Claude"


def test_command_on_adds_group(monkeypatch) -> None:
    class FakeMatcher:
        def __init__(self) -> None:
            self.message = None

        async def finish(self, message=None):
            self.message = message
            raise FinishedException

    async def no_save() -> None:
        return None

    event = GroupMessageEvent(
        time=1700000000,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=555001,
        message_type="group",
        message_id=1,
        message=Message("/proactive on"),
        original_message=Message("/proactive on"),
        raw_message="/proactive on",
        font=0,
        sender={"user_id": 555001, "nickname": "群主", "role": "admin"},
        group_id=123456,
        to_me=False,
    )
    matcher = FakeMatcher()
    monkeypatch.setattr(handlers, "_state_groups", set())
    monkeypatch.setattr(handlers, "_save_state", no_save)

    with pytest.raises(FinishedException):
        asyncio.run(handlers._handle_command(None, event, matcher, Message("on")))

    assert 123456 in handlers._state_groups
    assert "已开启" in str(matcher.message)


def test_extract_at_only_allows_recent_users(monkeypatch) -> None:
    activities = [
        Activity(at=1.0, nickname="甲", text="在", user_id=111),
        Activity(at=2.0, nickname="乙", text="嗯", user_id=222),
    ]
    monkeypatch.setattr(handlers.plugin_config, "proactive_allow_at", True)
    line, target = handlers._extract_at("[AT:111] 你来", activities, 999)
    assert target == 111
    assert line == "你来"

    _, target = handlers._extract_at("[AT:999] 你来", activities, 999)
    assert target is None
    _, target = handlers._extract_at("[AT:111] [AT:222] 你来", activities, 999)
    assert target == 111


def test_send_line_adds_at_segment(monkeypatch) -> None:
    class FakeBot:
        def __init__(self) -> None:
            self.calls = []

        async def call_api(self, api, **data):
            self.calls.append((api, data))
            return {"message_id": 1}

    bot = FakeBot()
    monkeypatch.setattr(handlers, "_daily_total", 0)
    monkeypatch.setattr(handlers, "_daily_by_group", {})
    monkeypatch.setattr(handlers, "_last_spoke", {})
    assert asyncio.run(handlers._send_line(bot, 123, "你来", at_qq=111)) is True
    message = bot.calls[0][1]["message"]
    assert any(seg.type == "at" and str(seg.data.get("qq")) == "111" for seg in message)
