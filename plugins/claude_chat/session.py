"""按会话保存聊天历史，带 TTL、条数/字符上限和 JSON 持久化。"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nonebot import logger

Message = dict[str, Any]


def _content_chars(content: Any) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                total += len(str(block.get("text", "")))
            elif isinstance(block, dict):
                total += 20
        return total
    return len(str(content))


@dataclass
class Session:
    key: str
    messages: list[Message] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def chars(self) -> int:
        return sum(_content_chars(m.get("content", "")) for m in self.messages)

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "updated_at": self.updated_at,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "messages": self.messages,
        }


class SessionStore:
    """线程/协程安全（在单进程事件循环内）的会话仓库。"""

    def __init__(
        self,
        path: Path,
        *,
        ttl_seconds: float,
        max_messages: int,
        max_chars: int,
        max_sessions: int = 300,
    ) -> None:
        self.path = Path(path)
        self.ttl_seconds = float(ttl_seconds)
        self.max_messages = max(2, int(max_messages))
        self.max_chars = max(1000, int(max_chars))
        self.max_sessions = max(10, int(max_sessions))

        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()
        self._loaded = False

    # ---------- 对外接口 ----------

    async def get(self, key: str) -> Session:
        async with self._lock:
            await self._ensure_loaded()
            self._purge_expired()
            session = self._sessions.get(key)
            if session is None:
                session = Session(key=key)
                self._sessions[key] = session
            return session

    async def append_exchange(
        self,
        key: str,
        user_text: str,
        assistant_text: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> Session:
        async with self._lock:
            await self._ensure_loaded()
            session = self._sessions.get(key)
            if session is None:
                session = Session(key=key)
                self._sessions[key] = session

            if user_text.strip():
                session.messages.append({"role": "user", "content": user_text})
            if assistant_text.strip():
                session.messages.append({"role": "assistant", "content": assistant_text})

            session.updated_at = time.time()
            session.input_tokens += max(0, int(input_tokens))
            session.output_tokens += max(0, int(output_tokens))

            self._trim(session)
            self._evict_sessions()
            await asyncio.to_thread(self._save_sync)
            return session

    async def reset(self, key: str) -> None:
        async with self._lock:
            await self._ensure_loaded()
            self._sessions.pop(key, None)
            await asyncio.to_thread(self._save_sync)

    async def stats(self, key: str) -> dict[str, Any]:
        async with self._lock:
            await self._ensure_loaded()
            session = self._sessions.get(key)
            if session is None:
                return {"messages": 0, "input_tokens": 0, "output_tokens": 0}
            return {
                "messages": len(session.messages),
                "input_tokens": session.input_tokens,
                "output_tokens": session.output_tokens,
            }

    # ---------- 内部 ----------

    def _trim(self, session: Session) -> None:
        while len(session.messages) > self.max_messages and len(session.messages) >= 2:
            del session.messages[:2]
        while session.chars > self.max_chars and len(session.messages) >= 2:
            del session.messages[:2]
        # 正常情况下始终 user/assistant 交替，从头部整对删除即可
        while session.messages and session.messages[0].get("role") != "user":
            del session.messages[0]

    def _purge_expired(self) -> None:
        if self.ttl_seconds <= 0:
            return
        deadline = time.time() - self.ttl_seconds
        expired = [k for k, v in self._sessions.items() if v.updated_at < deadline]
        for key in expired:
            self._sessions.pop(key, None)

    def _evict_sessions(self) -> None:
        if len(self._sessions) <= self.max_sessions:
            return
        overflow = len(self._sessions) - self.max_sessions
        oldest = sorted(self._sessions.items(), key=lambda item: item[1].updated_at)[:overflow]
        for key, _ in oldest:
            self._sessions.pop(key, None)

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning(f"会话文件读取失败，将重新开始：{exc}")
            self._backup_broken_file()
            return

        sessions = raw.get("sessions") if isinstance(raw, dict) else None
        if not isinstance(sessions, dict):
            return

        now = time.time()
        for key, item in sessions.items():
            if not isinstance(key, str) or not isinstance(item, dict):
                continue
            messages = item.get("messages")
            if not isinstance(messages, list):
                continue
            clean: list[Message] = []
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                content = msg.get("content")
                if role not in ("user", "assistant"):
                    continue
                if not isinstance(content, (str, list)):
                    continue
                clean.append({"role": role, "content": content})
            if not clean:
                continue
            try:
                self._sessions[key] = Session(
                    key=key,
                    messages=clean,
                    updated_at=float(item.get("updated_at") or now),
                    input_tokens=int(item.get("input_tokens") or 0),
                    output_tokens=int(item.get("output_tokens") or 0),
                )
            except (TypeError, ValueError):
                logger.warning(f"跳过损坏的会话记录：{key}")
                continue
        self._purge_expired()
        logger.info(f"已载入 {len(self._sessions)} 个会话：{self.path}")

    def _backup_broken_file(self) -> None:
        try:
            if self.path.exists():
                backup = self.path.with_suffix(self.path.suffix + f".broken-{int(time.time())}")
                self.path.replace(backup)
        except OSError:
            pass

    def _save_sync(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "saved_at": time.time(),
                "sessions": {key: session.to_json() for key, session in self._sessions.items()},
            }
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)
        except OSError as exc:
            logger.warning(f"会话写入失败：{exc}")
