from __future__ import annotations

from qqbot_filters import blocked_users, configure, is_blocked


def test_blocked_users_are_matched() -> None:
    configure([123456789, "999999999"])
    assert is_blocked(123456789) is True
    assert is_blocked("123456789") is True
    assert is_blocked(999999999) is True
    assert is_blocked(123456) is False
    assert is_blocked(999) is False
    assert is_blocked(None) is False
    assert 123456789 in blocked_users()
