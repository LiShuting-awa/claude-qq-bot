"""知识库检索的回归测试。

最重要的那条：中文自然问句必须能命中。以前「战争雷霆最新版本」是 0 命中，
因为整句中文被当成一个短语去匹配 trigram 索引。
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from plugins.claude_chat.knowledge import KnowledgeStore


def _store(**kwargs) -> KnowledgeStore:
    path = Path(tempfile.mkdtemp()) / "knowledge.db"
    return KnowledgeStore(path, **kwargs)


def _seed(store: KnowledgeStore) -> None:
    store.upsert(
        url="https://example.com/wt",
        title="战争雷霆新版本更新 - 16.09.2026 - Sky Odyssey",
        source="17173",
        published="2026-09-16",
        content="战争雷霆推出了新的版本更新，加入 Sky Odyssey 载具与海战模式调整。",
    )
    store.upsert(
        url="https://example.com/tarkov",
        title="逃离塔科夫 M855 子弹购买指南",
        source="攻略",
        content="M855 可以在跳蚤市场购买，也可以从 Peacekeeper 商人处获得。",
    )


def test_natural_chinese_question_hits() -> None:
    store = _store()
    _seed(store)

    for query in ["战争雷霆最新版本", "战争雷霆有什么新内容", "最新版本", "战争雷霆 版本更新"]:
        rows = store.search(query, limit=3)
        assert rows, f"{query!r} 应该能命中知识库"
        assert "战争雷霆" in rows[0]["title"]


def test_unrelated_query_returns_nothing() -> None:
    store = _store()
    _seed(store)
    assert store.search("完全不存在的内容") == []


def test_short_keyword_inside_natural_question_is_found() -> None:
    """「老六是什么意思」要命中写着「老六」的资料。

    回归：以前整句中文按三字窗口进 FTS，命中是那篇写着「是什么意思」的
    无关资料；真正讲「老六」的那篇因为只有两个字，一条都搜不到。
    """
    store = _store()
    store.upsert(
        url="https://example.com/meme",
        title="群聊黑话对照表",
        content="老六：阴人、蹲人，源自射击游戏。",
    )
    store.upsert(
        url="https://example.com/unrelated",
        title="DeepSeek 是什么",
        content="DeepSeek 是一家中国 AI 公司，这里解释它是什么意思。",
    )

    rows = store.search("老六是什么意思", limit=3)
    assert [row["url"] for row in rows] == ["https://example.com/meme"]


def test_pure_question_words_hit_nothing() -> None:
    """整句都是问句壳时应该搜不到东西，而不是抓一篇随便写着「是什么」的。"""
    store = _store()
    _seed(store)
    assert store.search("这是什么意思") == []


def test_search_returns_expected_keys() -> None:
    store = _store()
    _seed(store)
    row = store.search("战争雷霆", limit=1)[0]
    assert set(row) == {"title", "url", "source", "published", "content"}


def test_duplicate_titles_are_collapsed() -> None:
    """同一篇文章被多个站点转载时只返回一条。"""
    store = _store()
    for index, host in enumerate(["a.com", "b.com", "c.com"]):
        store.upsert(
            url=f"https://{host}/war-thunder",
            title="战争雷霆新版本更新说明",
            content=f"战争雷霆新版本更新说明正文 {index}",
        )
    rows = store.search("战争雷霆新版本更新说明", limit=5)
    assert len(rows) == 1


def test_fresher_doc_ranks_first() -> None:
    store = _store()
    store.upsert(
        url="https://old.example.com/wt",
        title="战争雷霆版本更新",
        content="战争雷霆版本更新的旧说明。",
    )
    store.upsert(
        url="https://new.example.com/wt",
        title="战争雷霆版本更新",
        content="战争雷霆版本更新的新说明。",
    )
    # 同标题会被去重，所以换个能区分的标题重来
    store.conn.execute("DELETE FROM docs")
    store.conn.commit()
    store.upsert(
        url="https://old.example.com/wt2",
        title="战争雷霆版本更新一览（旧）",
        content="战争雷霆版本更新的旧说明。",
    )
    store.upsert(
        url="https://new.example.com/wt2",
        title="战争雷霆版本更新一览（新）",
        content="战争雷霆版本更新的新说明。",
    )
    store.conn.execute(
        "UPDATE docs SET fetched_at = ? WHERE url = ?",
        (time.time() - 400 * 86400, "https://old.example.com/wt2"),
    )
    store.conn.commit()

    rows = store.search("战争雷霆版本更新", limit=2)
    assert len(rows) == 2
    assert rows[0]["url"] == "https://new.example.com/wt2"


def test_empty_shells_are_skipped_in_ranking() -> None:
    store = _store()
    store.upsert(url="https://shell.example.com", title="", content="")
    store.upsert(
        url="https://real.example.com/wt",
        title="战争雷霆新版本",
        content="战争雷霆新版本内容。",
    )
    rows = store.search("战争雷霆新版本", limit=5)
    assert [row["url"] for row in rows] == ["https://real.example.com/wt"]


def test_min_content_chars_skips_thin_fetches() -> None:
    store = _store(min_content_chars=40)
    assert store.upsert(url="https://thin.example.com", title="短", content="太短") is False
    assert store.count() == 0
    assert (
        store.upsert(
            url="https://ok.example.com",
            title="战争雷霆新版本说明",
            content="战争雷霆新版本的正文内容足够长，可以入库用于后续回答。" * 2,
        )
        is True
    )
    assert store.count() == 1


def test_prune_removes_shells_and_stale_docs() -> None:
    # 用默认设置入库（否则空壳在 upsert 阶段就被挡掉了），再显式指定清理阈值
    store = _store()
    store.upsert(url="https://shell.example.com", title="", content="")
    store.upsert(
        url="https://fresh.example.com",
        title="战争雷霆新版本说明",
        content="战争雷霆新版本的正文内容足够长，可以入库。" * 3,
    )
    store.upsert(
        url="https://stale.example.com",
        title="战争雷霆旧版本说明",
        content="战争雷霆旧版本的正文内容足够长，可以入库。" * 3,
    )
    store.conn.execute(
        "UPDATE docs SET fetched_at = ? WHERE url = ?",
        (time.time() - 500 * 86400, "https://stale.example.com"),
    )
    store.conn.commit()

    removed = store.prune(min_content_chars=40, stale_days=120)
    assert removed == 2
    assert store.count() == 1
    assert store.search("战争雷霆", limit=5)[0]["url"] == "https://fresh.example.com"


def test_stats_reports_shells() -> None:
    store = _store()
    _seed(store)
    store.upsert(url="https://shell.example.com", title="", content="")
    info = store.stats()
    assert info["total"] == 3
    assert info["thin"] == 1