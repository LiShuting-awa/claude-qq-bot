from __future__ import annotations

import asyncio
import io

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.exception import FinishedException
from PIL import Image

from plugins.image_search import handlers, search as search_mod
from plugins.image_search.search import (
    ImageHit,
    _normalize_image,
    collect_images,
    is_unsafe,
    parse_baidu,
    parse_bing,
    parse_img_marker,
    parse_openverse,
    parse_safebooru,
    parse_so,
    parse_wallhaven,
)
from plugins.image_search.verify import _downscale, parse_verdicts


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


def test_parse_so() -> None:
    payload = {
        "list": [
            {
                "img": "https://img.example.com/a.jpg",
                "link": "https://news.example.com/x",
                "title": "a cat",
                "width": 800,
                "height": "600",
            },
            {"img": "not-a-url"},
            "garbage",
        ]
    }
    hits = parse_so(payload)
    assert len(hits) == 1
    assert hits[0].image_url == "https://img.example.com/a.jpg"
    assert hits[0].width == 800
    assert hits[0].height == 600
    assert hits[0].source == "360"


def test_parse_baidu() -> None:
    body = (
        "/*?*/({"
        '"data":[{"middleURL":"https://img1.baidu.com/it/u=1?w=500","thumbURL":"'
        'https://img1.baidu.com/it/u=1?w=200","fromURL":"https://page.example.com/1",'
        '"fromPageTitle":"a <em>cat</em> page","width":1200,"height":800},'
        '{"thumbURL":""},null]'
        "})/*zz*/"
    )
    hits = parse_baidu(body)
    assert len(hits) == 1
    assert hits[0].image_url == "https://img1.baidu.com/it/u=1?w=500"
    assert hits[0].page_url == "https://page.example.com/1"
    assert hits[0].title == "a cat page"
    assert hits[0].source == "baidu"
    assert parse_baidu("no json here") == []


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


def test_parse_wallhaven() -> None:
    payload = {
        "data": [
            {
                "path": "https://w.wallhaven.cc/full/gj/wallhaven-gjyv2l.jpg",
                "url": "https://wallhaven.cc/w/gjyv2l",
                "source": "https://origin.example.com/post",
                "dimension_x": 1920,
                "dimension_y": "1080",
                "tags": [{"name": "shiba"}, {"name": "dog"}, 3],
            },
            {"path": "javascript:0"},
            "garbage",
        ]
    }
    hits = parse_wallhaven(payload)
    assert len(hits) == 1
    assert hits[0].image_url == "https://w.wallhaven.cc/full/gj/wallhaven-gjyv2l.jpg"
    assert hits[0].page_url == "https://origin.example.com/post"
    assert hits[0].title == "shiba dog"
    assert hits[0].width == 1920
    assert hits[0].height == 1080
    assert hits[0].source == "wallhaven"
    assert parse_wallhaven({"data": "nope"}) == []


def test_parse_openverse() -> None:
    payload = {
        "results": [
            {
                "url": "https://live.staticflickr.com/1/1_b.jpg",
                "foreign_landing_url": "https://flickr.com/photos/x",
                "title": "a <em>shiba</em> photo",
                "width": 1024,
                "height": 768,
            },
            {"url": ""},
            None,
        ]
    }
    hits = parse_openverse(payload)
    assert len(hits) == 1
    assert hits[0].image_url == "https://live.staticflickr.com/1/1_b.jpg"
    assert hits[0].page_url == "https://flickr.com/photos/x"
    assert hits[0].title == "a shiba photo"
    assert hits[0].source == "openverse"
    assert parse_openverse([]) == []


def test_parse_safebooru() -> None:
    posts = [
        {
            "directory": "e7",
            "image": "e72cdcbd448d33f17a5885213a65b436743fa881.jpg",
            "id": "123",
            "tags": "shiba_inu dog",
            "width": 800,
            "height": 600,
        },
        {"image": "", "directory": "x"},
        "garbage",
    ]
    hits = parse_safebooru(posts)
    assert len(hits) == 1
    assert hits[0].image_url == "https://safebooru.org/images/e7/e72cdcbd448d33f17a5885213a65b436743fa881.jpg"
    assert hits[0].page_url.endswith("id=123")
    assert hits[0].title == "shiba_inu dog"
    assert hits[0].source == "safebooru"
    assert parse_safebooru(None) == []


def test_parse_verdicts() -> None:
    assert parse_verdicts("1:是 2:否 3:yes", 3) == [True, False, True]
    assert parse_verdicts("1、否 2. no", 2) == [False, False]
    assert parse_verdicts("1 是 2 是", 2) == [True, True]
    assert parse_verdicts("1:是", 2) is None  # 编号不全
    assert parse_verdicts("看不出", 1) is None


def test_downscale() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (2000, 1000), (10, 200, 30)).save(buf, "PNG")
    data, media_type = _downscale(buf.getvalue())
    assert media_type == "image/jpeg"
    with Image.open(io.BytesIO(data)) as image:
        assert max(image.size) <= 768
    assert _downscale(b"not an image") is None


def test_collect_images_without_verify(monkeypatch) -> None:
    async def fake_download_hit(hit, *, timeout, max_bytes):
        # 前两张是同一张图（字节相同），第三张不同
        return (_png_bytes(), "image/png") if hit.image_url != "https://x/3.jpg" else (
            b"\xff\xd8\xffother",
            "image/jpeg",
        )

    monkeypatch.setattr(search_mod, "download_hit", fake_download_hit)
    hits = [
        ImageHit(image_url="https://x/1.jpg"),
        ImageHit(image_url="https://x/2.jpg"),  # 与 1 相同字节 → 去重
        ImageHit(image_url="https://x/3.jpg"),
    ]
    images, rejected = asyncio.run(collect_images("柴犬", hits, 2))
    assert len(images) == 2  # 1 和 3（2 被去重）
    assert rejected is False


def test_collect_images_with_verify(monkeypatch) -> None:
    async def fake_download_hit(hit, *, timeout, max_bytes):
        return (hit.image_url.encode(), "image/png")

    async def fake_verify(query, batch):
        return [item[0] == b"https://x/1.jpg" for item in batch]  # 只有第 1 张对得上

    monkeypatch.setattr(search_mod, "download_hit", fake_download_hit)
    hits = [ImageHit(image_url=f"https://x/{i}.jpg") for i in range(3)]
    images, rejected = asyncio.run(collect_images("柴犬", hits, 1, verify_fn=fake_verify))
    assert [data for data, _ in images] == [b"https://x/1.jpg"]
    assert rejected is True


def test_collect_images_verify_error_falls_back(monkeypatch) -> None:
    async def fake_download_hit(hit, *, timeout, max_bytes):
        buf = io.BytesIO()
        # 每张颜色不同，避免被字节级去重合并
        Image.new("RGB", (2, 2), (int(hit.image_url[-5]) * 40, 0, 0)).save(buf, "PNG")
        return (buf.getvalue(), "image/png")

    async def broken_verify(query, batch):
        raise RuntimeError("api down")

    monkeypatch.setattr(search_mod, "download_hit", fake_download_hit)
    hits = [ImageHit(image_url=f"https://x/{i}.jpg") for i in range(2)]
    images, rejected = asyncio.run(collect_images("柴犬", hits, 2, verify_fn=broken_verify))
    assert len(images) == 2  # 核对挂了也照发
    assert rejected is False


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
        buf = io.BytesIO()
        Image.new("RGB", (2, 2), (hit.image_url.count("0"), 0, 0)).save(buf, "PNG")
        return buf.getvalue(), "image/png"

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
    monkeypatch.setattr(search_mod, "download_hit", fake_download_hit)
    monkeypatch.setattr(handlers, "send_image_bytes", fake_send_image_bytes)
    monkeypatch.setattr(handlers, "verify_fn", None)
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
