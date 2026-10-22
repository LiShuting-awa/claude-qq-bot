"""本地知识库：把检索到的网页/结果存进 SQLite，供后续回答复用。

检索走 FTS5 的 trigram 索引，查询词由 :mod:`.textquery` 负责切成中文三字窗口；
索引命不中时再用 LIKE 兜底。命中结果按「相关度 + 新鲜度」重排，并去掉重复转载。
"""

from __future__ import annotations

import math
import re
import sqlite3
import time
from pathlib import Path

from .textquery import build, gram_hits

_DOC_LIMIT = 12_000
_LIKE_ESCAPE = "\\"


class KnowledgeStore:
    def __init__(
        self,
        path: Path,
        *,
        min_content_chars: int = 0,
        stale_days: float = 0.0,
        freshness_half_life_days: float = 30.0,
        freshness_weight: float = 1.5,
    ) -> None:
        self.path = path
        # 正文短于这个长度的抓取结果直接不存（搜索结果常带回空摘要）
        self.min_content_chars = max(0, int(min_content_chars))
        # 超过这些天的旧资料在 prune() 时清掉；0 表示不按时间清理
        self.stale_days = max(0.0, float(stale_days))
        self.freshness_half_life_days = max(0.1, float(freshness_half_life_days))
        self.freshness_weight = max(0.0, float(freshness_weight))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init()

    def _init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                published TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                query TEXT NOT NULL DEFAULT '',
                fetched_at REAL NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
                title, content, content='docs', content_rowid='id', tokenize='trigram'
            );
            CREATE INDEX IF NOT EXISTS docs_fetched_idx ON docs(fetched_at);
            CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON docs BEGIN
                INSERT INTO docs_fts(rowid, title, content)
                VALUES (new.id, new.title, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON docs BEGIN
                INSERT INTO docs_fts(docs_fts, rowid, title, content)
                VALUES ('delete', old.id, old.title, old.content);
            END;
            CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON docs BEGIN
                INSERT INTO docs_fts(docs_fts, rowid, title, content)
                VALUES ('delete', old.id, old.title, old.content);
                INSERT INTO docs_fts(rowid, title, content)
                VALUES (new.id, new.title, new.content);
            END;
            """
        )
        self.conn.commit()

    # ---------- 写入 ----------

    def upsert(
        self,
        *,
        url: str,
        title: str = "",
        source: str = "",
        published: str = "",
        content: str = "",
        query: str = "",
    ) -> bool:
        """写入或覆盖一条资料；正文太短而标题也没信息量时跳过，返回是否入库。"""
        url = (url or "").strip()
        if not url:
            return False

        content = " ".join((content or "").split())[:_DOC_LIMIT]
        title = (title or "").strip()[:300]
        if len(content) < self.min_content_chars and len(title) < 8:
            return False

        self.conn.execute(
            """
            INSERT INTO docs(url, title, source, published, content, query, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title=excluded.title,
                source=excluded.source,
                published=excluded.published,
                content=excluded.content,
                query=excluded.query,
                fetched_at=excluded.fetched_at
            """,
            (
                url,
                title,
                (source or "")[:80],
                (published or "")[:40],
                content,
                (query or "")[:200],
                time.time(),
            ),
        )
        self.conn.commit()
        return True

    # ---------- 检索 ----------

    def search(self, query: str, limit: int = 3) -> list[dict]:
        query = (query or "").strip()
        if not query or limit <= 0:
            return []

        expression, like_terms = build(query)
        candidates = self._search_fts(expression, max(limit * 4, 12))
        if len(candidates) < limit:
            candidates.extend(self._search_like(query, like_terms, max(limit * 4, 12)))

        ranked = self._rank(query, candidates)
        return ranked[:limit]

    def _search_fts(self, expression: str, limit: int) -> list[dict]:
        if not expression:
            return []
        try:
            rows = self.conn.execute(
                """
                SELECT d.title, d.url, d.source, d.published, d.content, d.fetched_at
                FROM docs_fts
                JOIN docs d ON d.id = docs_fts.rowid
                WHERE docs_fts MATCH ?
                ORDER BY bm25(docs_fts)
                LIMIT ?
                """,
                (expression, limit),
            ).fetchall()
        except sqlite3.Error:
            return []
        return [self._row_to_dict(row) for row in rows]

    def _search_like(self, query: str, like_terms: list[str], limit: int) -> list[dict]:
        needles = [query[:80], *like_terms]
        clauses: list[str] = []
        params: list[str] = []
        for needle in needles:
            if not needle:
                continue
            pattern = "%" + _escape_like(needle) + "%"
            clauses.append(
                f"(title LIKE ? ESCAPE '{_LIKE_ESCAPE}' OR content LIKE ? ESCAPE '{_LIKE_ESCAPE}')"
            )
            params.extend([pattern, pattern])
        if not clauses:
            return []

        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT title, url, source, published, content, fetched_at
            FROM docs
            WHERE {' OR '.join(clauses)}
            ORDER BY fetched_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    @staticmethod
    def _row_to_dict(row: tuple) -> dict:
        return {
            "title": row[0],
            "url": row[1],
            "source": row[2],
            "published": row[3],
            "content": row[4],
            "fetched_at": float(row[5] or 0.0),
        }

    def _rank(self, query: str, candidates: list[dict]) -> list[dict]:
        """相关度为主、新鲜度为辅地重排，并去掉同标题的重复转载。"""
        now = time.time()
        scored: list[tuple[float, dict]] = []

        for row in candidates:
            title = str(row.get("title") or "")
            content = str(row.get("content") or "")
            title_hits = gram_hits(query, title)
            content_hits = gram_hits(query, content)

            # 正文空白、标题也对不上的，基本是抓取失败留下的空壳
            if not content.strip() and not title_hits:
                continue

            relevance = title_hits * 3 + content_hits
            age_days = max(0.0, (now - float(row.get("fetched_at") or now)) / 86400.0)
            freshness = 0.5 ** (age_days / self.freshness_half_life_days)
            score = relevance + self.freshness_weight * freshness
            scored.append((score, row))

        scored.sort(key=lambda item: item[0], reverse=True)

        seen_titles: set[str] = set()
        results: list[dict] = []
        for _, row in scored:
            key = _title_key(str(row.get("title") or ""))
            if key and key in seen_titles:
                continue
            if key:
                seen_titles.add(key)
            row.pop("fetched_at", None)
            results.append(row)
        return results

    # ---------- 维护 ----------

    def prune(self, *, min_content_chars: int | None = None, stale_days: float | None = None) -> int:
        """清掉空壳资料和过期资料，返回删除条数。"""
        floor = self.min_content_chars if min_content_chars is None else max(0, int(min_content_chars))
        cutoff_days = self.stale_days if stale_days is None else max(0.0, float(stale_days))

        removed = 0
        if floor > 0:
            cursor = self.conn.execute(
                "DELETE FROM docs WHERE length(content) < ? AND length(title) < 8",
                (floor,),
            )
            removed += cursor.rowcount or 0
        if cutoff_days > 0:
            deadline = time.time() - cutoff_days * 86400.0
            cursor = self.conn.execute("DELETE FROM docs WHERE fetched_at < ?", (deadline,))
            removed += cursor.rowcount or 0
        self.conn.commit()
        return removed

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0])

    def stats(self) -> dict:
        """给 /kb 用的一点点库内概况。"""
        total = self.count()
        thin = int(
            self.conn.execute(
                "SELECT COUNT(*) FROM docs WHERE length(content) < 80 AND length(title) < 8"
            ).fetchone()[0]
        )
        oldest = self.conn.execute("SELECT MIN(fetched_at) FROM docs").fetchone()[0]
        return {
            "total": total,
            "thin": thin,
            "oldest_days": (
                round((time.time() - float(oldest)) / 86400.0, 1) if oldest else 0.0
            ),
        }


def _escape_like(text: str) -> str:
    return (
        text.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )


def _title_key(title: str) -> str:
    """归一化标题，用来识别同一篇文章的重复转载。"""
    cleaned = re.sub(r"[\s\W_]+", "", title, flags=re.UNICODE).casefold()
    return cleaned if len(cleaned) >= 6 else ""