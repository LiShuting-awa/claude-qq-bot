from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from plugins.claude_chat.memory import MemoryKeeper, MemoryStore


def _store(**kwargs) -> MemoryStore:
    path = Path(tempfile.mkdtemp()) / "memory.db"
    return MemoryStore(path, **kwargs)


def test_remember_and_recall_by_topic() -> None:
    store = _store()
    store.remember(scope="group", scope_id="1", subject="111", text="在准备考研，晚上才有空")
    store.remember(scope="group", scope_id="1", subject="111", text="主玩战争雷霆苏系")

    rows = store.recall(scope="group", scope_id="1", subject="111", query="战争雷霆", limit=5)
    assert any("战争雷霆" in row["text"] for row in rows)
    assert store.count(scope="group", scope_id="1") == 2


def test_duplicate_facts_are_ignored() -> None:
    store = _store()
    assert store.remember(scope="user", scope_id="1", text="喜欢打游戏") is True
    assert store.remember(scope="user", scope_id="1", text="喜欢打游戏") is True  # 冲突时不报错
    assert store.count(scope="user", scope_id="1") == 1


def test_identity_facts_always_come_back() -> None:
    """问什么都会带上「他是谁」，不然显得不记得人。"""
    store = _store()
    store.remember(
        scope="group", scope_id="1", subject="111", text="叫小明", kind="identity"
    )
    store.remember(
        scope="group", scope_id="1", subject="111", text="喜欢看动漫", kind="preference"
    )
    rows = store.recall(scope="group", scope_id="1", subject="111", query="今天天气", limit=3)
    assert any(row["text"] == "叫小明" for row in rows)


def test_scopes_are_isolated() -> None:
    store = _store()
    store.remember(scope="group", scope_id="1", subject="111", text="一号群的事")
    store.remember(scope="group", scope_id="2", subject="111", text="二号群的事")

    rows = store.recall(scope="group", scope_id="2", subject="111", query="群", limit=5)
    texts = [row["text"] for row in rows]
    assert "二号群的事" in texts
    assert "一号群的事" not in texts


def test_forget_clears_scope() -> None:
    store = _store()
    store.remember(scope="group", scope_id="1", subject="111", text="在准备考研")
    assert store.forget(scope="group", scope_id="1") == 1
    assert store.count(scope="group", scope_id="1") == 0


def test_limit_keeps_newest() -> None:
    store = _store(max_facts_per_scope=20)
    for index in range(30):
        store.remember(scope="user", scope_id="1", text=f"第 {index} 条长期记忆内容")
    assert store.count(scope="user", scope_id="1") == 20
    rows = store.recall(scope="user", scope_id="1", query="记忆", limit=20)
    assert any("第 29 条" in row["text"] for row in rows)


def test_prune_drops_unused_auto_facts_only() -> None:
    store = _store()
    store.remember(scope="user", scope_id="1", text="很久以前的自动记忆")
    store.remember(scope="user", scope_id="1", text="手动写下的记忆", source="manual")
    store.conn.execute("UPDATE facts SET created_at = ?", (time.time() - 300 * 86400,))
    store.conn.commit()

    assert store.prune(stale_days=90) == 1
    remaining = store.recall(scope="user", scope_id="1", query="记忆", limit=5)
    assert [row["text"] for row in remaining] == ["手动写下的记忆"]


def test_format_for_prompt() -> None:
    store = _store()
    rows = [
        {"text": "叫小明", "subject": "1", "kind": "identity", "created_at": 0.0, "id": 1},
    ]
    text = store.format_for_prompt(rows)
    assert text.startswith("[你记得的事]")
    assert "- 叫小明" in text
    assert store.format_for_prompt([]) == ""


# ---------- 抽取 ----------


def _keeper(reply_text: str) -> tuple[MemoryKeeper, list]:
    store = _store()
    calls: list = []

    async def complete(messages, system):
        calls.append((messages, system))
        return SimpleNamespace(text=reply_text)

    return MemoryKeeper(store, complete), calls


def test_keeper_extracts_fact_lines() -> None:
    keeper, calls = _keeper("事实: 在准备考研\n事实: 主玩战争雷霆苏系\n废话一行")
    saved = asyncio.run(
        keeper.observe(scope="group", scope_id="1", subject="111", transcript="用户：我在考研")
    )
    assert saved == 2
    assert calls, "应该调用过模型"
    rows = keeper.store.recall(scope="group", scope_id="1", subject="111", query="考研", limit=5)
    assert any("考研" in row["text"] for row in rows)


def test_keeper_handles_none() -> None:
    keeper, _ = _keeper("NONE")
    assert (
        asyncio.run(keeper.observe(scope="group", scope_id="1", subject="111", transcript="随便聊聊"))
        == 0
    )
    assert keeper.store.count(scope="group", scope_id="1") == 0


def test_keeper_skips_sensitive_facts() -> None:
    keeper, _ = _keeper("事实: 身份证号是 110101199001011234\n事实: 喜欢打战争雷霆")
    asyncio.run(
        keeper.observe(scope="user", scope_id="1", subject="1", transcript="用户：这是我的身份证")
    )
    texts = [row["text"] for row in keeper.store.recall(scope="user", scope_id="1", query="喜欢", limit=5)]
    assert not any("110101199001011234" in text for text in texts)


def test_keeper_disabled_does_nothing() -> None:
    store = _store()
    calls: list = []

    async def complete(messages, system):  # pragma: no cover - 不该被调用
        calls.append(messages)
        return SimpleNamespace(text="事实: 不该出现")

    keeper = MemoryKeeper(store, complete, enabled=False)
    assert (
        asyncio.run(keeper.observe(scope="user", scope_id="1", subject="1", transcript="x")) == 0
    )
    assert not calls


def test_keeper_survives_model_failure() -> None:
    store = _store()

    async def complete(messages, system):
        raise RuntimeError("上游挂了")

    keeper = MemoryKeeper(store, complete)
    assert (
        asyncio.run(keeper.observe(scope="user", scope_id="1", subject="1", transcript="x")) == 0
    )