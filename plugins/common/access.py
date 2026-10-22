from collections.abc import Collection

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from qqbot_filters import is_blocked


def event_is_allowed(
    event: MessageEvent,
    *,
    allowed_users: Collection[int],
    allowed_groups: Collection[int],
) -> bool:
    if is_blocked(event.user_id):
        return False
    if allowed_users and event.user_id not in allowed_users:
        return False
    if isinstance(event, GroupMessageEvent) and allowed_groups and event.group_id not in allowed_groups:
        return False
    return True
