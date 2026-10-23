"""群聊记录的落盘与读取：按天分文件的 JSONL，供说话学习采样。

每行：{"t": 时间戳, "g": 群号, "u": QQ号, "n": 昵称, "x": 文本}
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path


class SpeechLog:
    def __init__(self, root: Path, retention_days: int = 14) -> None:
        self._root = root
        self._retention_days = retention_days
        root.mkdir(parents=True, exist_ok=True)

    def _day_file(self, day: date) -> Path:
        return self._root / f"{day.isoformat()}.jsonl"

    def append(self, group_id: int, user_id: int, nickname: str, text: str) -> None:
        record = {
            "t": int(time.time()),
            "g": group_id,
            "u": user_id,
            "n": nickname[:24],
            "x": text,
        }
        path = self._day_file(date.today())
        if not path.exists():
            self.cleanup()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def recent(self, max_messages: int) -> list[dict]:
        """从今天往回读，最多 max_messages 条；时间正序返回（旧 → 新）。"""
        collected: list[dict] = []
        day = date.today()
        for _ in range(365):
            path = self._day_file(day)
            if path.exists():
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                except OSError:
                    lines = []
                for line in reversed(lines):
                    try:
                        collected.append(json.loads(line))
                    except ValueError:
                        continue
                    if len(collected) >= max_messages:
                        break
            if len(collected) >= max_messages:
                break
            day -= timedelta(days=1)
        collected.reverse()
        return collected

    def count(self) -> int:
        total = 0
        for path in self._root.glob("*.jsonl"):
            try:
                total += sum(1 for _ in path.open(encoding="utf-8"))
            except OSError:
                continue
        return total

    def cleanup(self) -> None:
        expire_before = date.today() - timedelta(days=self._retention_days)
        for path in self._root.glob("*.jsonl"):
            try:
                day = date.fromisoformat(path.stem)
            except ValueError:
                continue
            if day < expire_before:
                try:
                    path.unlink()
                except OSError:
                    pass
