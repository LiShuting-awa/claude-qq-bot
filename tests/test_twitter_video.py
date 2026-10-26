from __future__ import annotations

import asyncio

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.exception import FinishedException

from plugins.twitter_video import handlers, resolver

# 下面两个 fixture 取自 2026-10 真实接口响应（x.com/TopHeroes_/status/2001950365332455490），
# 有删减，字段结构保持原样。
FX_VIDEO_TWEET = {
    "code": 200,
    "message": "OK",
    "tweet": {
        "url": "https://x.com/TopHeroes_/status/2001950365332455490",
        "id": "2001950365332455490",
        "text": "Forgot to close\nMy heroes solo level up in my phone\n\n✨Unlock the fog, discover new lands, expand your empire!",
        "author": {"screen_name": "TopHeroes_", "name": "Top Heroes"},
        "media": {
            "all": [
                {
                    "id": "2001841416071450628",
                    "url": "https://video.twimg.com/amplify_video/2001841416071450628/vid/avc1/720x720/1L5-pvqqQlx9qW8I.mp4?tag=14",
                    "thumbnail_url": "https://pbs.twimg.com/amplify_video_thumb/2001841416071450628/img/hpy5KpJh4pO17b65.jpg",
                    "duration": 30.278,
                    "width": 1080,
                    "height": 1080,
                    "format": "video/mp4",
                    "type": "video",
                    "formats": [
                        {
                            "url": "https://video.twimg.com/amplify_video/2001841416071450628/pl/vCiP2cksCHPAxSVw.m3u8?tag=14",
                            "container": "m3u8",
                        },
                        {
                            "url": "https://video.twimg.com/amplify_video/2001841416071450628/vid/avc1/720x720/1L5-pvqqQlx9qW8I.mp4?tag=14",
                            "bitrate": 1280000,
                            "container": "mp4",
                            "codec": "h264",
                        },
                        {
                            "url": "https://video.twimg.com/amplify_video/2001841416071450628/vid/avc1/540x540/fQMDaamZ4e37ZvAN.mp4?tag=14",
                            "bitrate": 832000,
                            "container": "mp4",
                            "codec": "h264",
                        },
                        {
                            "url": "https://video.twimg.com/amplify_video/2001841416071450628/vid/avc1/320x320/Ske1EBSEgRQqYVfx.mp4?tag=14",
                            "bitrate": 432000,
                            "container": "mp4",
                            "codec": "h264",
                        },
                    ],
                }
            ]
        },
    },
}

VX_VIDEO_TWEET = {
    "allSameType": True,
    "hasMedia": True,
    "mediaURLs": [
        "https://video.twimg.com/amplify_video/2001841416071450628/vid/avc1/720x720/1L5-pvqqQlx9qW8I.mp4"
    ],
    "media_extended": [
        {
            "altText": None,
            "duration_millis": 30278,
            "id_str": "2001841416071450628",
            "size": {"height": 1080, "width": 1080},
            "thumbnail_url": "https://pbs.twimg.com/amplify_video_thumb/2001841416071450628/img/hpy5KpJh4pO17b65.jpg",
            "type": "video",
            "url": "https://video.twimg.com/amplify_video/2001841416071450628/vid/avc1/720x720/1L5-pvqqQlx9qW8I.mp4",
        }
    ],
    "text": "Forgot to close\nMy heroes solo level up in my phone",
    "user_name": "Top Heroes",
    "user_screen_name": "TopHeroes_",
    "tweetID": "2001950365332455490",
}


def test_find_tweet_urls() -> None:
    assert resolver.find_tweet_urls("看这个 https://x.com/NASA/status/123，好玩") == [
        ("NASA", "123")
    ]
    assert resolver.find_tweet_urls("twitter.com/nasa/status/456?s=20") == [
        ("nasa", "456")
    ]
    assert resolver.find_tweet_urls("https://twitter.com/i/web/status/789") == [
        (None, "789")
    ]
    assert resolver.find_tweet_urls("https://mobile.twitter.com/a/status/1/video/1") == [
        ("a", "1")
    ]
    assert resolver.find_tweet_urls("https://fixupx.com/user/status/42?s=20&t=x") == [
        ("user", "42")
    ]
    # 同一条推文出现两次只留一个；不同推文都保留
    both = resolver.find_tweet_urls("x.com/a/status/11 和 https://x.com/b/status/22 x.com/a/status/11")
    assert [item[1] for item in both] == ["11", "22"]
    # 不是推文链接的不匹配
    assert resolver.find_tweet_urls("x.com/NASA") == []
    assert resolver.find_tweet_urls("https://example.com/user/status/1") == []
    # max.com 不算 x.com；邮箱也不算
    assert resolver.find_tweet_urls("max.com/user/status/33") == []
    assert resolver.find_tweet_urls("mail me at a@x.com/status/44") == []


def test_parse_fxtwitter() -> None:
    info = resolver.parse_fxtwitter(FX_VIDEO_TWEET)
    assert info is not None
    assert info.tweet_id == "2001950365332455490"
    assert info.screen_name == "TopHeroes_"
    assert info.author_name == "Top Heroes"
    assert info.text.startswith("Forgot to close")
    assert len(info.media) == 1
    media = info.media[0]
    assert media.kind == "video"
    assert media.duration == pytest.approx(30.278)
    # m3u8 变体被过滤，只剩 3 个 mp4
    assert len(media.variants) == 3
    assert resolver.pick_video_url(media, 720).endswith("720x720/1L5-pvqqQlx9qW8I.mp4?tag=14")


def test_parse_fxtwitter_not_found() -> None:
    assert resolver.parse_fxtwitter({"code": 404, "tweet": None}) is None


def test_parse_fxtwitter_quote_fallback() -> None:
    data = {
        "code": 200,
        "tweet": {
            "id": "1",
            "text": "看这个",
            "author": {"screen_name": "alice", "name": "Alice"},
            "media": None,
            "quote": {
                "id": "2",
                "author": {"screen_name": "bob", "name": "Bob"},
                "media": {
                    "all": [
                        {
                            "type": "video",
                            "url": "https://video.twimg.com/x/vid/avc1/720x720/abc.mp4?tag=14",
                        }
                    ]
                },
            },
        },
    }
    info = resolver.parse_fxtwitter(data)
    assert info is not None
    assert info.from_quote is True
    assert info.quoted_name == "Bob"
    assert info.media[0].kind == "video"
    assert "Alice" in resolver.build_caption(info)
    assert "Bob" in resolver.build_caption(info)


def test_parse_vxtwitter() -> None:
    info = resolver.parse_vxtwitter(VX_VIDEO_TWEET)
    assert info is not None
    assert info.tweet_id == "2001950365332455490"
    assert info.screen_name == "TopHeroes_"
    assert len(info.media) == 1
    media = info.media[0]
    assert media.kind == "video"
    assert media.duration == pytest.approx(30.278)
    assert media.height == 1080


def test_parse_vxtwitter_urls_fallback() -> None:
    data = {
        "tweetID": "9",
        "user_screen_name": "carol",
        "hasMedia": True,
        "mediaURLs": ["https://pbs.twimg.com/media/Gabc.jpg"],
        "media_extended": [],
    }
    info = resolver.parse_vxtwitter(data)
    assert info is not None
    assert info.media[0].kind == "photo"


def test_pick_video_url_height_cap() -> None:
    info = resolver.parse_fxtwitter(FX_VIDEO_TWEET)
    assert info is not None
    media = info.media[0]
    assert resolver.pick_video_url(media, 540).endswith("540x540/fQMDaamZ4e37ZvAN.mp4?tag=14")
    assert resolver.pick_video_url(media, 480).endswith("320x320/Ske1EBSEgRQqYVfx.mp4?tag=14")
    # 上限比所有变体都低时，取最小的那个而不是直接失败
    assert resolver.pick_video_url(media, 100).endswith("320x320/Ske1EBSEgRQqYVfx.mp4?tag=14")


def test_pick_video_url_no_variants() -> None:
    media = resolver.TweetMedia(kind="video", url="https://video.twimg.com/a.mp4")
    assert resolver.pick_video_url(media, 720) == "https://video.twimg.com/a.mp4"


def test_photo_url_appends_orig() -> None:
    media = resolver.TweetMedia(kind="photo", url="https://pbs.twimg.com/media/Gabc.jpg")
    assert resolver.photo_url(media) == "https://pbs.twimg.com/media/Gabc.jpg?name=orig"
    media2 = resolver.TweetMedia(
        kind="photo", url="https://pbs.twimg.com/media/Gabc?format=jpg&name=large"
    )
    assert resolver.photo_url(media2).endswith("name=large")


def test_build_caption_truncates() -> None:
    info = resolver.TweetInfo(
        tweet_id="1",
        screen_name="alice",
        author_name="Alice",
        text="很长的内容" * 100,
    )
    caption = resolver.build_caption(info, limit=60)
    assert caption.startswith("𝕏 Alice：")
    assert len(caption) <= 62
    assert caption.endswith("…")
    assert "t.co" not in resolver.build_caption(
        resolver.TweetInfo(text="看看 https://t.co/xyz", author_name="A")
    )


def test_api_urls() -> None:
    assert (
        resolver._api_url("https://api.fxtwitter.com", "fx", "NASA", "1")
        == "https://api.fxtwitter.com/NASA/status/1"
    )
    assert (
        resolver._api_url("https://api.fxtwitter.com", "fx", None, "1")
        == "https://api.fxtwitter.com/status/1"
    )
    assert (
        resolver._api_url("https://api.fxtwitter.com", "fx", "i", "1")
        == "https://api.fxtwitter.com/status/1"
    )
    assert (
        resolver._api_url("https://api.vxtwitter.com", "vx", None, "1")
        == "https://api.vxtwitter.com/i/status/1"
    )


def _group_event(text: str) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=1700000000,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=555001,
        message_type="group",
        message_id=3,
        message=Message(text),
        original_message=Message(text),
        raw_message=text,
        font=0,
        sender={"user_id": 555001, "nickname": "测试", "role": "member"},
        group_id=123456,
        to_me=False,
    )


class FakeMatcher:
    def __init__(self) -> None:
        self.sent: list = []
        self.final = None

    async def send(self, message) -> None:
        self.sent.append(message)

    async def finish(self, message=None):
        self.final = message
        raise FinishedException


def test_auto_rule(monkeypatch) -> None:
    monkeypatch.setattr(handlers.plugin_config, "twitter_enabled", True)
    monkeypatch.setattr(handlers.plugin_config, "twitter_auto_enabled", True)
    monkeypatch.setattr(handlers.plugin_config, "twitter_auto_groups", [])
    monkeypatch.setattr(handlers.plugin_config, "twitter_allowed_groups", [])
    monkeypatch.setattr(handlers.plugin_config, "twitter_allowed_users", [])
    assert handlers._auto_rule(_group_event("看这个 https://x.com/a/status/1")) is True
    assert handlers._auto_rule(_group_event("https://x.com/a")) is False
    assert handlers._auto_rule(_group_event("/推文 https://x.com/a/status/1")) is False
    monkeypatch.setattr(handlers.plugin_config, "twitter_auto_enabled", False)
    assert handlers._auto_rule(_group_event("https://x.com/a/status/1")) is False


def test_auto_handler_sends_video(monkeypatch) -> None:
    async def fake_fetch(tweet_id, screen_name, *, bases, proxy="", timeout=15.0):
        assert tweet_id == "2001950365332455490"
        assert screen_name == "TopHeroes_"
        return resolver.parse_fxtwitter(FX_VIDEO_TWEET)

    async def fake_download(url: str, tmpdir) -> object:
        assert "720x720" in url
        path = tmpdir / "video.mp4"
        path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)
        return path

    event = _group_event("看这个 https://x.com/TopHeroes_/status/2001950365332455490")
    matcher = FakeMatcher()
    monkeypatch.setattr(handlers.plugin_config, "twitter_enabled", True)
    monkeypatch.setattr(handlers.plugin_config, "twitter_auto_enabled", True)
    monkeypatch.setattr(handlers.plugin_config, "twitter_auto_groups", [])
    monkeypatch.setattr(handlers.plugin_config, "twitter_allowed_groups", [])
    monkeypatch.setattr(handlers.plugin_config, "twitter_allowed_users", [])
    monkeypatch.setattr(handlers.plugin_config, "twitter_send_caption", True)
    monkeypatch.setattr(handlers, "_recent_tweets", {})
    monkeypatch.setattr(handlers, "_last_request", {})
    monkeypatch.setattr(handlers, "_daily_user", {})
    monkeypatch.setattr(handlers.resolver, "fetch_tweet", fake_fetch)
    monkeypatch.setattr(handlers, "_download_video", fake_download)

    with pytest.raises(FinishedException):
        asyncio.run(handlers._handle_auto(event, matcher))

    # 第一条是提示，第二条是摘要，最后发视频
    assert len(matcher.sent) == 2
    assert "正在解析" in matcher.sent[0]
    assert "Top Heroes" in matcher.sent[1]
    assert matcher.final is not None
    assert matcher.final.type == "video"


def test_auto_handler_reports_no_media(monkeypatch) -> None:
    async def fake_fetch(tweet_id, screen_name, *, bases, proxy="", timeout=15.0):
        return resolver.TweetInfo(tweet_id=tweet_id, screen_name=screen_name or "", text="纯文字")

    event = _group_event("https://x.com/a/status/5")
    matcher = FakeMatcher()
    monkeypatch.setattr(handlers.plugin_config, "twitter_enabled", True)
    monkeypatch.setattr(handlers.plugin_config, "twitter_auto_enabled", True)
    monkeypatch.setattr(handlers.plugin_config, "twitter_auto_groups", [])
    monkeypatch.setattr(handlers.plugin_config, "twitter_allowed_groups", [])
    monkeypatch.setattr(handlers.plugin_config, "twitter_allowed_users", [])
    monkeypatch.setattr(handlers.plugin_config, "twitter_send_caption", False)
    monkeypatch.setattr(handlers.plugin_config, "twitter_use_ytdlp", False)
    monkeypatch.setattr(handlers, "_recent_tweets", {})
    monkeypatch.setattr(handlers, "_last_request", {})
    monkeypatch.setattr(handlers, "_daily_user", {})
    monkeypatch.setattr(handlers.resolver, "fetch_tweet", fake_fetch)

    with pytest.raises(FinishedException):
        asyncio.run(handlers._handle_auto(event, matcher))

    assert matcher.final == "❌ 推特解析失败：这条推文里没有视频或图片。"


def test_dedup_skips_repeat(monkeypatch) -> None:
    event = _group_event("https://x.com/a/status/7")
    monkeypatch.setattr(handlers.plugin_config, "twitter_enabled", True)
    monkeypatch.setattr(handlers.plugin_config, "twitter_auto_enabled", True)
    monkeypatch.setattr(handlers.plugin_config, "twitter_auto_groups", [])
    monkeypatch.setattr(handlers.plugin_config, "twitter_allowed_groups", [])
    monkeypatch.setattr(handlers.plugin_config, "twitter_allowed_users", [])
    import time as time_mod

    monkeypatch.setattr(
        handlers, "_recent_tweets", {("group:123456", "7"): time_mod.time()}
    )

    called = False

    async def fake_run(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(handlers, "_run_tweet", fake_run)
    asyncio.run(handlers._handle_auto(event, FakeMatcher()))
    assert called is False
