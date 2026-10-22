"""全局 QQ 屏蔽名单。所有会主动说话/回复的插件都先查这里。"""

from __future__ import annotations

from collections.abc import Iterable

_blocked: set[int] = set()


def configure(user_ids: Iterable[int]) -> None:
    for raw in user_ids or []:
        try:
            _blocked.add(int(raw))
        except (TypeError, ValueError):
            continue


def is_blocked(user_id: int | str | None) -> bool:
    try:
        return int(user_id) in _blocked
    except (TypeError, ValueError):
        return False


def blocked_users() -> frozenset[int]:
    return frozenset(_blocked)
