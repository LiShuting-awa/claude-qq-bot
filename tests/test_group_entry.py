from __future__ import annotations

import asyncio

from nonebot.adapters.onebot.v11 import GroupIncreaseNoticeEvent

from plugins.claude_chat import handlers


def _event(*, user_id: int, group_id: int) -> GroupIncreaseNoticeEvent:
    return GroupIncreaseNoticeEvent(
        time=1,
        self_id=10000,
        post_type="notice",
        notice_type="group_increase",
        sub_type="invite",
        group_id=group_id,
        user_id=user_id,
        operator_id=99999,
    )


def test_group_entry_greeting(monkeypatch) -> None:
    sent: list[tuple[int, str]] = []

    class FakeBot:
        self_id = "10000"

        async def send_group_msg(self, *, group_id, message, **kwargs):
            sent.append((group_id, str(message)))
            return {"message_id": 1}

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(handlers.asyncio, "sleep", no_sleep)
    asyncio.run(handlers._handle_group_added(FakeBot(), _event(user_id=10000, group_id=800001)))

    assert sent == [(800001, "听说你们都说我死了?")]


def test_group_entry_ignores_other_members(monkeypatch) -> None:
    sent: list[int] = []

    class FakeBot:
        self_id = "10000"

        async def send_group_msg(self, *, group_id, message, **kwargs):
            sent.append(group_id)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(handlers.asyncio, "sleep", no_sleep)
    asyncio.run(handlers._handle_group_added(FakeBot(), _event(user_id=10001, group_id=800002)))

    assert sent == []
