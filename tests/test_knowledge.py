from __future__ import annotations

import tempfile
from pathlib import Path

from plugins.claude_chat.knowledge import KnowledgeStore


def test_knowledge_store() -> None:
    path = Path(tempfile.mkdtemp()) / "knowledge.db"
    store = KnowledgeStore(path)
    store.upsert(
        url="https://example.com/a",
        title="战争雷霆 新版本",
        source="测试",
        published="2026-10-21",
        content="战争雷霆 天空奥德赛 更新 载具",
        query="战争雷霆",
    )
    assert store.count() == 1
    rows = store.search("战争雷霆 更新")
    assert rows
    assert "战争雷霆" in rows[0]["title"]

    store.upsert(
        url="https://example.com/a",
        title="战争雷霆 新版本（更新）",
        source="测试",
        content="修正后的正文",
    )
    assert store.count() == 1
    assert "更新" in store.search("战争雷霆")[0]["title"]

    assert store.search("完全不存在的内容") == []
