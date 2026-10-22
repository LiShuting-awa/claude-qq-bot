from __future__ import annotations

from nonebot.adapters.onebot.v11 import MessageSegment

from plugins.proactive_chat.formatting import clean_solution, split_solution
from plugins.proactive_chat.handlers import _is_sticker, _sniff_media_type


def test_clean_solution_converts_latex_and_markdown() -> None:
    raw = """### 解
**方程：** \\(x^2 - 5x + 6 = 0\\)

\\[\\frac{1}{2} \\times 6 = 3\\]

根为 \\(x_1=2, x_2=3\\)。
"""
    text = clean_solution(raw)
    assert "###" not in text
    assert "**" not in text
    assert "\\(" not in text
    assert "x² - 5x + 6 = 0" in text
    assert "(1)/(2) × 6 = 3" in text
    assert "x₁=2, x₂=3" in text


def test_split_solution_respects_limit() -> None:
    text = "步骤。\n" * 500
    chunks = split_solution(text, limit=300, max_chunks=4)
    assert chunks
    assert all(len(chunk) <= 310 for chunk in chunks)
    assert len(chunks) <= 4


def test_sniff_image_types() -> None:
    assert _sniff_media_type(b"\xff\xd8\xff\xe0" + b"0" * 8) == "image/jpeg"
    assert _sniff_media_type(b"\x89PNG\r\n\x1a\n" + b"0" * 8) == "image/png"
    assert _sniff_media_type(b"GIF89a" + b"0" * 8) == "image/gif"
    assert _sniff_media_type(b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 8) == "image/webp"
    assert _sniff_media_type(b"BM" + b"0" * 8) is None


def test_sticker_detection() -> None:
    sticker = MessageSegment("image", {"url": "https://x", "sub_type": "1", "summary": "动画表情"})
    normal = MessageSegment("image", {"url": "https://x", "sub_type": "0", "summary": ""})
    assert _is_sticker(sticker) is True
    assert _is_sticker(normal) is False
