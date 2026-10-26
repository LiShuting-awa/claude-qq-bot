from __future__ import annotations

import time

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment

from plugins.music_voice import handlers, music


def _group_event(text: str, segments: list | None = None) -> GroupMessageEvent:
    message = Message(segments) if segments is not None else Message(text)
    return GroupMessageEvent(
        time=1700000000,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=555001,
        message_type="group",
        message_id=1,
        message=message,
        original_message=message,
        raw_message=text,
        font=0,
        sender={"user_id": 555001, "nickname": "测试", "role": "member"},
        group_id=123456,
        to_me=False,
    )


def test_auto_rule_passes_on_song_request() -> None:
    # 回归：_auto_rule 一度漏 import GroupMessageEvent，群里任何消息都让它崩
    assert handlers._auto_rule(_group_event("来一首晴天")) is True
    assert handlers._auto_rule(_group_event("放首歌 稻香")) is True
    assert handlers._auto_rule(_group_event("今天天气不错")) is False
    assert handlers._auto_rule(_group_event("/点歌 晴天")) is False
    assert handlers._auto_rule(_group_event("来一首 https://example.com")) is False


def test_auto_rule_allows_at_me_only() -> None:
    # @机器人点歌也要接；@别人的不抢
    at_me = MessageSegment.at(10000)
    at_other = MessageSegment.at(999)
    assert handlers._auto_rule(_group_event("", segments=[at_me, MessageSegment.text("来一首晴天")])) is True
    assert (
        handlers._auto_rule(_group_event("", segments=[at_other, MessageSegment.text("来一首晴天")]))
        is False
    )
    # 带图的不是口令
    image = MessageSegment.image("https://example.com/a.jpg")
    assert handlers._auto_rule(_group_event("", segments=[at_me, image])) is False


def test_parse_auto_title() -> None:
    assert handlers._parse_auto_title("来一首晴天") == "晴天"
    assert handlers._parse_auto_title("放首歌 稻香") == "稻香"
    assert handlers._parse_auto_title("点歌：孤勇者") == "孤勇者"
    assert handlers._parse_auto_title("播一首 铁血丹心 ") == "铁血丹心"
    assert handlers._parse_auto_title("来一首吧") == ""
    assert handlers._parse_auto_title("来一首") == ""
    assert handlers._parse_auto_title("来一首 https://example.com") == ""
    # 带 / 的是命令，不走自动口令
    assert handlers._parse_auto_title("/点歌 晴天") == ""


def test_pick_song_prefers_exact_match() -> None:
    covers = [
        {"id": "1", "name": "晴天(深情版)", "artist": ["Lucky小爱"]},
        {"id": "2", "name": "晴天", "artist": ["周杰伦"]},
        {"id": "3", "name": "晴天 (女声版)", "artist": ["路人"]},
    ]
    assert music.pick_song(covers, "晴天")["id"] == "2"


def test_pick_song_uses_artist_hint() -> None:
    candidates = [
        {"id": "1", "name": "晴天", "artist": ["另一个人"]},
        {"id": "2", "name": "晴天", "artist": ["周杰伦"]},
    ]
    assert music.pick_song(candidates, "晴天 周杰伦")["id"] == "2"


def test_pick_song_empty() -> None:
    assert music.pick_song([], "晴天") is None


def test_song_label() -> None:
    assert music.song_label({"name": "晴天", "artist": ["周杰伦"]}) == "《晴天》 - 周杰伦"
    assert music.song_label({"name": "无名"}) == "《无名》"


def test_cache_cleanup_removes_expired(tmp_path) -> None:
    import os

    old = tmp_path / "old.mp3"
    fresh = tmp_path / "fresh.mp3"
    not_audio = tmp_path / "note.txt"
    for item in (old, fresh, not_audio):
        item.write_bytes(b"x")
    stale = time.time() - 10 * 3600
    os.utime(old, (stale, stale))

    # 直接调内部逻辑：只该删过期的音频文件
    original = handlers._CACHE_DIR
    handlers._CACHE_DIR = tmp_path
    try:
        handlers._cache_cleanup()
    finally:
        handlers._CACHE_DIR = original

    assert not old.exists()
    assert fresh.exists()
    assert not_audio.exists()
