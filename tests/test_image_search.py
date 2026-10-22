from __future__ import annotations

import asyncio
import io

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.exception import FinishedException
from PIL import Image

from plugins.image_search import handlers
from plugins.image_search.search import (
    ImageHit,
    _normalize_image,
    is_unsafe,
    parse_bing,
    parse_img_marker,
    parse_sogou,
)


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (255, 0, 0)).save(buf, "PNG")
    return buf.getvalue()


def test_is_unsafe() -> None:
    assert is_unsafe("a cute corgi") is False
    assert is_unsafe("NSFW nude") is True
    assert is_unsafe("幼女") is True
    assert is_unsafe("") is False


def test_parse_img_marker() -> None:
    text, query = parse_img_marker("来了，柴犬图这就来 [IMG:柴犬]")
    assert query == "柴犬"
    assert text == "来了，柴犬图这就来"
    text, query = parse_img_marker("看看这个 [img: 晚霞 海边] 好看吧")
    assert query == "晚霞 海边"
    assert "[img" not in text.lower()
    assert parse_img_marker("没有标记") == ("没有标记", "")
    assert parse_img_marker("空的 [IMG:] 标记") == ("空的 标记", "")


def test_parse_bing() -> None:
    # 真实 Bing 页面：m 属性用单引号包裹，JSON 的双引号写作 &quot;，值内引号写作 \&quot;
    json_attr = (
        "{&quot;murl&quot;:&quot;https://img.example.com/dog.jpg&quot;,"
        "&quot;purl&quot;:&quot;https://page.example.com/1&quot;,"
        "&quot;t&quot;:&quot;a \\&quot;corgi\\&quot; pic&quot;}"
    )
    html_text = (
        '<div><a class="iusc" href="#" m=\'' + json_attr + "'></a>"
        '<a class="iusc" m=\'bad json\'></a>'
        '<a class="iusc" m=\'{"murl":"javascript:0"}\'></a>'
        "</div>"
    )
    hits = parse_bing(html_text)
    assert len(hits) == 1
    assert hits[0].image_url == "https://img.example.com/dog.jpg"
    assert hits[0].page_url == "https://page.example.com/1"
    assert hits[0].title == 'a "corgi" pic'
    assert hits[0].source == "bing"


def test_parse_sogou() -> None:
    payload = {
        "data": {
            "items": [
                {
                    "oriPicUrl": "https://img.example.com/a.jpg",
                    "picUrl": "https://thumb.example.com/a.jpg",
                    "linkUrl": "https://news.example.com/x",
                    "title": "a cat",
                    "width": 800,
                    "height": "600",
                },
                {"picUrl": "not-a-url"},
                "garbage",
            ]
        }
    }
    hits = parse_sogou(payload)
    assert len(hits) == 1
    assert hits[0].image_url == "https://img.example.com/a.jpg"
    assert hits[0].width == 800
    assert hits[0].height == 600
    assert hits[0].source == "sogou"


def test_normalize_image() -> None:
    png = _png_bytes()
    assert _normalize_image(png) == (png, "image/png")
    assert _normalize_image(b"<html>not an image</html>") is None
    assert _normalize_image(b"") is None

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (0, 128, 255)).save(buf, "WEBP")
    data, media_type = _normalize_image(buf.getvalue())
    assert media_type in ("image/png", "image/jpeg")
    assert data[:2] == b"\xff\xd8\xff"[:2] or data[:8] == b"\x89PNG\r\n\x1a\n"


def test_img_command_sends_images(monkeypatch) -> None:
    class FakeMatcher:
        def __init__(self) -> None:
            self.sent: list = []
            self.final = None

        async def send(self, message):
            self.sent.append(message)

        async def finish(self, message=None):
            self.final = message
            raise FinishedException

    async def fake_search_images(query, *, limit, timeout, safe):
        assert query == "柴犬"
        return [ImageHit(image_url=f"https://img.example.com/{i}.jpg") for i in range(3)]

    async def fake_download_hit(hit, *, timeout, max_bytes):
        return _png_bytes(), "image/png"

    sent_images: list[int] = []

    async def fake_send_image_bytes(bot, *, data, group_id=None, user_id=None, reply_to=None):
        sent_images.append(len(data))
        return True

    event = GroupMessageEvent(
        time=1700000000,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=555001,
        message_type="group",
        message_id=1,
        message=Message("/img 柴犬"),
        original_message=Message("/img 柴犬"),
        raw_message="/img 柴犬",
        font=0,
        sender={"user_id": 555001, "nickname": "测试", "role": "member"},
        group_id=123456,
        to_me=False,
    )
    matcher = FakeMatcher()
    monkeypatch.setattr(handlers, "search_images", fake_search_images)
    monkeypatch.setattr(handlers, "download_hit", fake_download_hit)
    monkeypatch.setattr(handlers, "send_image_bytes", fake_send_image_bytes)
    monkeypatch.setattr(handlers, "_last_request", {})
    monkeypatch.setattr(handlers, "_daily_user", {})
    monkeypatch.setattr(handlers, "_daily_total", 0)
    monkeypatch.setattr(handlers.plugin_config, "image_search_enabled", True)
    monkeypatch.setattr(handlers.plugin_config, "image_search_send_count", 2)
    monkeypatch.setattr(handlers.plugin_config, "image_search_allowed_groups", [])
    monkeypatch.setattr(handlers.plugin_config, "image_search_allowed_users", [])

    with pytest.raises(FinishedException):
        asyncio.run(handlers._handle_img(None, event, matcher, Message("柴犬")))

    assert matcher.sent  # 🔍 搜图里，稍等…
    assert len(sent_images) == 2
