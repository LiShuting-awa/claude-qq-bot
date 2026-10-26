from __future__ import annotations

import pytest

from plugins.common.video_url import is_video_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://x.com/shinonomemeto", False),
        ("https://x.com/user/status/1870484479980052921", True),
        ("https://twitter.com/user", False),
        ("https://www.youtube.com/@user", False),
        ("https://www.youtube.com/watch?v=abc", True),
        ("https://youtu.be/abc", True),
        ("https://www.bilibili.com/video/BV1xx", True),
        ("https://space.bilibili.com/123", False),
        ("https://www.instagram.com/someone/", False),
        ("https://www.instagram.com/reel/abc/", True),
        ("https://www.tiktok.com/@user", False),
        ("https://www.tiktok.com/@user/video/123", True),
        ("https://www.douyin.com/user/abc", False),
        ("https://www.douyin.com/video/123", True),
        ("https://weibo.com/u/123", False),
        ("https://weibo.com/123/status/abc", True),
        ("https://www.xiaohongshu.com/user/profile/abc", False),
        ("https://www.xiaohongshu.com/explore/abc", True),
        ("https://cdn.example.com/a.mp4", True),
    ],
)
def test_is_video_url(url: str, expected: bool) -> None:
    assert is_video_url(url) is expected
