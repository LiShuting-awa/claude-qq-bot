"""长期记忆：记住群友是谁、在玩什么、聊过什么，跨会话保留。

会话历史只保留最近几十条，聊完就忘。这里把「以后还用得上」的稳定信息单独存下来，
回答前挑几条注入提示词，让 Claude 看起来像记得人，而不是每次重新认识。
"""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from nonebot import logger

from .textquery import build

_FACT_LIMIT = 200
_MAX_FACT_CHARS = 80
_LINE_PREFIX = re.compile(r"^\s*(?:事实|FACT|Fact)\s*[:：]\s*")

_FALLBACK = "（Claude 没有返回内容）"


class MemoryStore:
    """长期记忆的存储层；只管存取，不做模型调用。"""

    def __init__(self, path: Path, *, max_facts_per_scope: int = 200) -> None:
        self.path = path
        self.max_facts_per_scope = max(10, int(max_facts_per_scope))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init()

    def _init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                subject TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'fact',
                source TEXT NOT NULL DEFAULT 'auto',
                created_at REAL NOT NULL,
                last_used_at REAL NOT NULL DEFAULT 0,
                hits INTEGER NOT NULL DEFAULT 0
            );
            CREATE UNIQUE INDEX IF NOT EXISTS facts_identity
                ON facts(scope, scope_id, subject, text);
            CREATE INDEX IF NOT EXISTS facts_scope_idx
                ON facts(scope, scope_id, created_at);
            CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
                text, content='facts', content_rowid='id', tokenize='trigram'
            );
            CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
                INSERT INTO facts_fts(rowid, text) VALUES (new.id, new.text);
            END;
            CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
                INSERT INTO facts_fts(facts_fts, rowid, text)
                VALUES ('delete', old.id, old.text);
            END;
            CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
                INSERT INTO facts_fts(facts_fts, rowid, text)
                VALUES ('delete', old.id, old.text);
                INSERT INTO facts_fts(rowid, text) VALUES (new.id, new.text);
            END;
            """
        )
        self.conn.commit()

    # ---------- 写入 ----------

    def remember(
        self,
        *,
        scope: str,
        scope_id: str,
        text: str,
        subject: str = "",
        kind: str = "fact",
        source: str = "auto",
    ) -> bool:
        """记一条事实；重复内容会被忽略。"""
        cleaned = _normalize_fact(text)
        if not cleaned:
            return False

        now = time.time()
        try:
            self.conn.execute(
                """
                INSERT INTO facts(scope, scope_id, subject, text, kind, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope, scope_id, subject, text) DO NOTHING
                """,
                (scope, str(scope_id), str(subject), cleaned, kind, source, now),
            )
            self.conn.commit()
        except sqlite3.Error as exc:
            logger.warning(f"长期记忆写入失败：{exc}")
            return False

        self._enforce_limit(scope, scope_id)
        return True

    def _enforce_limit(self, scope: str, scope_id: str) -> None:
        """同一作用域只留最近 N 条，防止无限增长。"""
        rows = self.conn.execute(
            """
            SELECT id FROM facts
            WHERE scope = ? AND scope_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT -1 OFFSET ?
            """,
            (scope, str(scope_id), self.max_facts_per_scope),
        ).fetchall()
        if not rows:
            return
        self.conn.executemany("DELETE FROM facts WHERE id = ?", [(row[0],) for row in rows])
        self.conn.commit()

    # ---------- 读取 ----------

    def recall(
        self,
        *,
        scope: str,
        scope_id: str,
        subject: str = "",
        query: str = "",
        limit: int = 8,
    ) -> list[dict]:
        """取回和当前话题相关的记忆；身份类记忆永远优先带上。"""
        if limit <= 0:
            return []

        picked: list[dict] = []
        seen: set[str] = set()

        def take(rows: list[tuple]) -> None:
            for row in rows:
                key = str(row[1])
                if key in seen:
                    continue
                seen.add(key)
                picked.append(
                    {
                        "id": int(row[0]),
                        "text": key,
                        "subject": str(row[2] or ""),
                        "kind": str(row[3] or "fact"),
                        "created_at": float(row[4] or 0.0),
                    }
                )

        # 1) 身份类：称呼、是谁，和问什么无关，都值得带上
        take(
            self.conn.execute(
                """
                SELECT id, text, subject, kind, created_at FROM facts
                WHERE scope = ? AND scope_id = ? AND kind = 'identity'
                ORDER BY created_at DESC LIMIT ?
                """,
                (scope, str(scope_id), max(1, limit // 3)),
            ).fetchall()
        )

        # 2) 与本次话题相关的
        expression, like_terms = build(query)
        if expression:
            try:
                take(
                    self.conn.execute(
                        """
                        SELECT f.id, f.text, f.subject, f.kind, f.created_at
                        FROM facts_fts
                        JOIN facts f ON f.id = facts_fts.rowid
                        WHERE facts_fts MATCH ? AND f.scope = ? AND f.scope_id = ?
                        ORDER BY bm25(facts_fts)
                        LIMIT ?
                        """,
                        (expression, scope, str(scope_id), limit),
                    ).fetchall()
                )
            except sqlite3.Error:
                pass

        if like_terms:
            for term in like_terms:
                pattern = "%" + term + "%"
                take(
                    self.conn.execute(
                        """
                        SELECT id, text, subject, kind, created_at FROM facts
                        WHERE scope = ? AND scope_id = ? AND text LIKE ?
                        ORDER BY created_at DESC LIMIT ?
                        """,
                        (scope, str(scope_id), pattern, limit),
                    ).fetchall()
                )

        # 3) 还不够就用最近的补满
        if len(picked) < limit:
            take(
                self.conn.execute(
                    """
                    SELECT id, text, subject, kind, created_at FROM facts
                    WHERE scope = ? AND scope_id = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (scope, str(scope_id), limit),
                ).fetchall()
            )

        results = picked[:limit]
        self._mark_used([row["id"] for row in results])
        return results

    def _mark_used(self, ids: list[int]) -> None:
        if not ids:
            return
        try:
            self.conn.executemany(
                "UPDATE facts SET hits = hits + 1, last_used_at = ? WHERE id = ?",
                [(time.time(), fact_id) for fact_id in ids],
            )
            self.conn.commit()
        except sqlite3.Error:
            pass

    def format_for_prompt(self, rows: list[dict]) -> str:
        if not rows:
            return ""
        lines = [f"- {row['text']}" for row in rows]
        return "[你记得的事]\n" + "\n".join(lines)

    def count(self, *, scope: str | None = None, scope_id: str | None = None) -> int:
        if scope is None:
            return int(self.conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0])
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM facts WHERE scope = ? AND scope_id = ?",
                (scope, str(scope_id)),
            ).fetchone()[0]
        )

    def forget(self, *, scope: str, scope_id: str) -> int:
        cursor = self.conn.execute(
            "DELETE FROM facts WHERE scope = ? AND scope_id = ?",
            (scope, str(scope_id)),
        )
        self.conn.commit()
        return cursor.rowcount or 0

    def prune(self, *, stale_days: float) -> int:
        """清掉长期没用上的自动记忆；人工写入的（source != auto）不动。"""
        if stale_days <= 0:
            return 0
        deadline = time.time() - stale_days * 86400.0
        cursor = self.conn.execute(
            """
            DELETE FROM facts
            WHERE source = 'auto' AND hits = 0 AND created_at < ?
            """,
            (deadline,),
        )
        self.conn.commit()
        return cursor.rowcount or 0


_EXTRACT_SYSTEM = """\
你在帮一个 QQ 机器人整理「长期记忆」。会话记录里哪些信息值得以后长期记住？

只记录**稳定、以后还用得上**的信息：
- 身份与称呼：名字、昵称、职业、学生/工作在哪个城市、年级
- 长期偏好：常玩的游戏、喜欢什么、明确讨厌什么
- 长期状态：固定作息、正在准备的考试、长期项目
- 对机器人本人的明确要求：称呼习惯、希望被怎么称呼

不要记录：
- 一次性的闲聊、当下的情绪、玩笑和玩梗
- 你猜测或推断出来的东西（没明说就不要写）
- 敏感信息：身份证号、住址门牌、密码、手机号

每条一行，格式严格如下：
事实: <不超过 40 字的一句话，第三人称，主语省略>

没有任何值得记的就只输出：NONE
不要输出别的任何内容。"""


Complete = Callable[[list[dict[str, Any]], str], Awaitable[Any]]


class MemoryKeeper:
    """负责从对话里抽取长期记忆；模型调用由外部注入，方便测试。"""

    def __init__(
        self,
        store: MemoryStore,
        complete: Complete,
        *,
        enabled: bool = True,
        max_new_per_turn: int = 3,
    ) -> None:
        self.store = store
        self._complete = complete
        self.enabled = enabled
        self.max_new_per_turn = max(1, int(max_new_per_turn))

    async def observe(
        self,
        *,
        scope: str,
        scope_id: str,
        subject: str,
        transcript: str,
    ) -> int:
        """从一段对话里抽出事实并落库，返回新增条数。"""
        if not self.enabled or not transcript.strip():
            return 0

        try:
            reply = await self._complete(
                [{"role": "user", "content": transcript}], _EXTRACT_SYSTEM
            )
        except Exception as exc:
            logger.warning(f"长期记忆抽取失败：{exc}")
            return 0

        raw = getattr(reply, "text", "") or ""
        if raw.strip() in ("", "NONE", "None") or raw.strip().startswith("NONE"):
            return 0

        saved = 0
        for line in raw.splitlines():
            match = _LINE_PREFIX.match(line)
            if not match:
                continue
            fact = line[match.end() :].strip()
            if not fact or _looks_sensitive(fact):
                continue
            if self.store.remember(
                scope=scope, scope_id=scope_id, text=fact, subject=subject, kind=_classify(fact)
            ):
                saved += 1
            if saved >= self.max_new_per_turn:
                break

        if saved:
            logger.info(f"长期记忆新增 {saved} 条（{scope}:{scope_id}）")
        return saved


def _normalize_fact(text: str) -> str:
    cleaned = " ".join((text or "").split()).strip(" -—·。，,：:")
    if len(cleaned) < 2:
        return ""
    return cleaned[:_MAX_FACT_CHARS]


def _looks_sensitive(fact: str) -> bool:
    """明显是隐私或密钥的内容不进长期记忆。"""
    if re.search(r"\d{15,}", fact):  # 身份证、银行卡这类长数字
        return True
    if re.search(r"(密码|口令|验证码|身份证号|住址|手机号|电话)", fact):
        return True
    return bool(re.search(r"[A-Za-z0-9]{24,}", fact))


def _classify(fact: str) -> str:
    if re.search(r"(叫|称呼|名字|昵称|是学生|上班|工作|年级|岁)", fact):
        return "identity"
    if re.search(r"(喜欢|讨厌|偏愛|偏好|平时|经常|常玩|在玩|习惯)", fact):
        return "preference"
    return "fact"