from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path

from plugins.claude_chat.session import SessionStore


def _store(path: Path, **kwargs) -> SessionStore:
    defaults = dict(ttl_seconds=3600, max_messages=6, max_chars=10000)
    defaults.update(kwargs)
    return SessionStore(path, **defaults)


def test_trimming_keeps_alternation() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(Path(tmp) / "sessions.json")
            for i in range(10):
                await store.append_exchange("group:1", f"问题 {i}", f"回答 {i}")
            session = await store.get("group:1")
            assert len(session.messages) <= 6
            assert session.messages[0]["role"] == "user"
            assert session.messages[-1]["role"] == "assistant"
            roles = [m["role"] for m in session.messages]
            assert roles == ["user", "assistant"] * (len(roles) // 2)
            assert session.messages[-1]["content"] == "回答 9"

    asyncio.run(scenario())


def test_persistence_roundtrip() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sessions.json"
            store = _store(path)
            await store.append_exchange("private:42", "你好", "你好呀", input_tokens=7, output_tokens=3)

            raw = json.loads(path.read_text(encoding="utf-8"))
            assert "private:42" in raw["sessions"]

            reloaded = _store(path)
            session = await reloaded.get("private:42")
            assert [m["content"] for m in session.messages] == ["你好", "你好呀"]
            assert session.input_tokens == 7
            assert session.output_tokens == 3

    asyncio.run(scenario())


def test_ttl_expiry_and_reset() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(Path(tmp) / "sessions.json", ttl_seconds=1)
            session = await store.get("group:2")
            session.messages.append({"role": "user", "content": "旧消息"})
            session.updated_at = time.time() - 10
            fresh = await store.get("group:2")
            assert fresh.messages == []

            await store.append_exchange("group:2", "a", "b")
            assert (await store.stats("group:2"))["messages"] == 2
            await store.reset("group:2")
            assert (await store.stats("group:2"))["messages"] == 0

    asyncio.run(scenario())


def test_char_budget_trims_oldest_pairs() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(Path(tmp) / "sessions.json", max_messages=100, max_chars=1000)
            for i in range(6):
                await store.append_exchange("group:3", "长" * 300, "短" * 300)
            session = await store.get("group:3")
            assert session.chars <= 1000
            assert session.messages[-1]["role"] == "assistant"

    asyncio.run(scenario())
