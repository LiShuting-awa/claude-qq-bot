"""群聊活动缓冲与时间判断。"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, time as dt_time


@dataclass(slots=True, frozen=True)
class Activity:
    at: float
    nickname: str
    text: str
    user_id: int = 0


class ActivityBuffer:
    """只存在内存里的轻量群聊缓冲，不落盘。"""

    def __init__(self, ttl_seconds: float, max_per_group: int = 80) -> None:
        self.ttl_seconds = max(60.0, float(ttl_seconds))
        self.max_per_group = max(2, int(max_per_group))
        self._groups: dict[int, deque[Activity]] = {}

    def record(
        self,
        group_id: int,
        nickname: str,
        text: str,
        *,
        user_id: int = 0,
        now: float | None = None,
    ) -> None:
        text = " ".join(str(text).split()).strip()
        if not text:
            return
        timestamp = time.time() if now is None else now
        bucket = self._groups.setdefault(group_id, deque())
        bucket.append(
            Activity(
                at=timestamp,
                nickname=" ".join(str(nickname).split())[:40] or "群友",
                text=text[:300],
                user_id=int(user_id or 0),
            )
        )
        while len(bucket) > self.max_per_group:
            bucket.popleft()
        self._purge_group(bucket, timestamp)

    def recent(
        self,
        group_id: int,
        *,
        minutes: int,
        limit: int,
        now: float | None = None,
    ) -> list[Activity]:
        timestamp = time.time() if now is None else now
        bucket = self._groups.get(group_id)
        if not bucket:
            return []
        cutoff = timestamp - minutes * 60
        items = [item for item in bucket if item.at >= cutoff]
        return items[-max(1, limit) :]

    def count(self, group_id: int, *, minutes: int, now: float | None = None) -> int:
        return len(self.recent(group_id, minutes=minutes, limit=1000, now=now))

    def last(self, group_id: int, *, limit: int = 20) -> list[Activity]:
        """返回缓冲里最后几条，不受 window 限制（用于冷场起话）。"""
        bucket = self._groups.get(group_id)
        if not bucket:
            return []
        return list(bucket)[-max(1, limit) :]

    def purge(self, *, now: float | None = None) -> None:
        timestamp = time.time() if now is None else now
        empty: list[int] = []
        for group_id, bucket in self._groups.items():
            self._purge_group(bucket, timestamp)
            if not bucket:
                empty.append(group_id)
        for group_id in empty:
            self._groups.pop(group_id, None)

    def _purge_group(self, bucket: deque[Activity], now: float) -> None:
        cutoff = now - self.ttl_seconds
        while bucket and bucket[0].at < cutoff:
            bucket.popleft()


def in_quiet_hours(spec: str, *, now: datetime | None = None) -> bool:
    """支持跨午夜，例如 23:00-08:00。格式错误时视为不静音。"""
    raw = (spec or "").strip()
    if not raw:
        return False
    try:
        start_raw, end_raw = raw.split("-", 1)
        start = dt_time.fromisoformat(start_raw.strip())
        end = dt_time.fromisoformat(end_raw.strip())
    except (ValueError, TypeError):
        return False

    current = (now or datetime.now()).time()
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def format_clock(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%H:%M")
