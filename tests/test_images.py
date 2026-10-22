from __future__ import annotations

import base64

from plugins.claude_chat.handlers import _DownloadedImage, _build_content, _sniff_media_type


def test_sniff_supported_image_types() -> None:
    assert _sniff_media_type(b"\xff\xd8\xff\xe0" + b"0" * 10) == "image/jpeg"
    assert _sniff_media_type(b"\x89PNG\r\n\x1a\n" + b"0" * 10) == "image/png"
    assert _sniff_media_type(b"GIF89a" + b"0" * 10) == "image/gif"
    assert _sniff_media_type(b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 10) == "image/webp"
    assert _sniff_media_type(b"BM" + b"0" * 10) is None


def test_build_content_includes_base64_image_and_notes() -> None:
    image = _DownloadedImage(media_type="image/png", data=b"fake-png")
    blocks = _build_content("这是什么？", [image], "上一条消息", ["（提示）"])

    assert blocks[0]["type"] == "text"
    assert "上一条消息" in blocks[0]["text"]
    assert blocks[1]["text"].startswith("这是什么？")
    assert blocks[2]["type"] == "image"
    assert blocks[2]["source"]["media_type"] == "image/png"
    assert base64.b64decode(blocks[2]["source"]["data"]) == b"fake-png"


def test_build_content_adds_default_prompt_for_image_only() -> None:
    image = _DownloadedImage(media_type="image/jpeg", data=b"x")
    blocks = _build_content("", [image], "", [])
    assert blocks[0]["type"] == "text"
    assert "图片" in blocks[0]["text"]
