"""拟人节奏：看消息要时间，打字要时间，长回复拆成几条发。

机器人最明显的「非人感」不在用词，而在时间结构：秒回、一次甩出上千字。
这里给回复加上阅读延迟、按字数估算的输入延迟，并把长回复拆成几条短消息。
"""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass

_FENCE = re.compile(r"^\s*```", re.MULTILINE)
# 句末标点：优先在这些位置断开，断出来的才像一条条发出的消息
_SENTENCE_END = re.compile(r"(?<=[。！？!?…；;])")


@dataclass(slots=True)
class RhythmConfig:
    enabled: bool = True
    read_base: float = 0.6
    read_per_char: float = 0.035
    read_max: float = 3.0
    typing_per_char: float = 0.11
    typing_min: float = 0.4
    typing_max: float = 4.5
    burst_enabled: bool = True
    burst_min_chars: int = 60
    burst_target_chars: int = 90
    burst_max_extra: int = 2
    burst_gap_min: float = 0.5
    burst_gap_max: float = 1.6
    jitter: float = 0.25


class Rhythm:
    """把「等待多久」「要不要分段」这类判断集中在一处。"""

    def __init__(self, config: RhythmConfig, *, rng: random.Random | None = None) -> None:
        self.config = config
        self._rng = rng or random.Random()

    def _jitter(self, seconds: float) -> float:
        if seconds <= 0 or self.config.jitter <= 0:
            return max(0.0, seconds)
        spread = 1.0 + self._rng.uniform(-self.config.jitter, self.config.jitter)
        return max(0.0, seconds * spread)

    def read_delay(self, incoming: str) -> float:
        """收到消息后「读完再回」的延迟；消息越长，停顿越久。"""
        cfg = self.config
        seconds = cfg.read_base + cfg.read_per_char * len(incoming or "")
        return self._jitter(min(seconds, cfg.read_max))

    def typing_delay(self, outgoing: str) -> float:
        """按回复长度估算的「打字」时间。"""
        cfg = self.config
        seconds = cfg.typing_per_char * len(outgoing or "")
        seconds = min(max(seconds, cfg.typing_min), cfg.typing_max)
        return self._jitter(seconds)

    def burst_gap(self) -> float:
        cfg = self.config
        return self._jitter(self._rng.uniform(cfg.burst_gap_min, cfg.burst_gap_max))

    def split(self, chunks: list[str]) -> list[str]:
        """把过长的段落拆成几条更像手打的消息；代码块不动。"""
        cfg = self.config
        if not cfg.burst_enabled or not chunks:
            return chunks

        out: list[str] = []
        extra = 0
        for chunk in chunks:
            if extra >= cfg.burst_max_extra or not self._splittable(chunk):
                out.append(chunk)
                continue
            pieces = self._split_one(chunk)
            if len(pieces) <= 1:
                out.append(chunk)
                continue
            room = cfg.burst_max_extra - extra
            if len(pieces) > room + 1:
                head, tail = pieces[:room], pieces[room:]
                pieces = [*head, "\n".join(tail)]
            extra += len(pieces) - 1
            out.extend(pieces)

        return [piece for piece in out if piece.strip()]

    def _splittable(self, chunk: str) -> bool:
        if len(chunk) <= self.config.burst_min_chars:
            return False
        # 代码块和列表整段保留，拆开会散架
        if _FENCE.search(chunk):
            return False
        if any(line.lstrip().startswith(("·", "｜", "-", "*", ">")) for line in chunk.splitlines()):
            return False
        return True

    def _split_one(self, chunk: str) -> list[str]:
        """按句子边界贪心拼到目标长度附近。"""
        target = max(20, self.config.burst_target_chars)
        sentences = [part for part in _SENTENCE_END.split(chunk) if part]
        pieces: list[str] = []
        buffer = ""
        for sentence in sentences:
            if buffer and len(buffer) + len(sentence) > target:
                pieces.append(buffer.strip())
                buffer = sentence
            else:
                buffer += sentence
        if buffer.strip():
            pieces.append(buffer.strip())
        return pieces

    async def wait(self, seconds: float) -> None:
        if not self.config.enabled or seconds <= 0:
            return
        await asyncio.sleep(seconds)

    async def wait_read(self, incoming: str) -> None:
        await self.wait(self.read_delay(incoming))

    async def wait_typing(self, outgoing: str) -> None:
        await self.wait(self.typing_delay(outgoing))

    async def wait_burst_gap(self) -> None:
        await self.wait(self.burst_gap())