"""本机 QQ 号的表情包库：读取、匹配、发送。"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from nonebot import logger

_MARKER = re.compile(r"\[STICKER\s*[:：]\s*(\d+)\]", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Sticker:
    id: int
    url: str
    description: str


class StickerLibrary:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.stickers: list[Sticker] = []
        self.enabled = True
        self.cooldown_seconds = 60
        self._last_sent: dict[str, float] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            logger.warning(f"表情包库不存在：{self.path}")
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            items = payload.get("stickers", [])
        except (OSError, ValueError) as exc:
            logger.warning(f"表情包库读取失败：{exc}")
            return

        stickers: list[Sticker] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                sticker_id = int(item["id"])
                url = str(item["url"])
                description = str(item.get("description") or "表情包")[:40]
            except (KeyError, TypeError, ValueError):
                continue
            if not url.startswith(("http://", "https://")):
                continue
            stickers.append(Sticker(sticker_id, url, description))
        self.stickers = sorted(stickers, key=lambda s: s.id)
        logger.info(f"已载入 {len(self.stickers)} 个表情包：{self.path}")

    def get(self, sticker_id: int | None) -> Sticker | None:
        if sticker_id is None:
            return None
        return next((s for s in self.stickers if s.id == sticker_id), None)

    def catalog_text(self, limit: int = 48) -> str:
        return "\n".join(
            f"{item.id}. {item.description}" for item in self.stickers[: max(1, limit)]
        )

    def can_send(self, key: str) -> bool:
        if not self.enabled:
            return False
        return time.time() - self._last_sent.get(key, 0.0) >= self.cooldown_seconds

    def mark_sent(self, key: str) -> None:
        self._last_sent[key] = time.time()

    @staticmethod
    def extract_marker(text: str) -> int | None:
        match = _MARKER.search(text or "")
        return int(match.group(1)) if match else None

    @staticmethod
    def remove_marker(text: str) -> str:
        return _MARKER.sub("", text or "").strip()

    @classmethod
    def parse_marker(cls, text: str) -> tuple[str, int | None]:
        return cls.remove_marker(text), cls.extract_marker(text)

    async def send(
        self,
        bot,
        sticker: Sticker,
        *,
        group_id: int | None = None,
        user_id: int | None = None,
        reply_to: int | None = None,
    ) -> bool:
        from nonebot.adapters.onebot.v11 import MessageSegment

        segment = MessageSegment("image", {"file": sticker.url, "url": sticker.url})
        if reply_to is not None:
            segment = MessageSegment.reply(reply_to) + segment

        try:
            if group_id is not None:
                await bot.call_api("send_group_msg", group_id=group_id, message=segment)
            elif user_id is not None:
                await bot.call_api("send_private_msg", user_id=user_id, message=segment)
            else:
                return False
        except Exception:
            logger.exception("表情包发送失败")
            return False
        return True


_PROJECT_ROOT = Path(__file__).resolve().parent
stickers = StickerLibrary(_PROJECT_ROOT / "data" / "stickers.json")
