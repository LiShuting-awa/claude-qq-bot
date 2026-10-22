from __future__ import annotations

from plugins.claude_chat.formatting import markdown_to_text, render_reply, split_text
from plugins.proactive_chat.formatting import split_solution


def test_markdown_basics() -> None:
    md = """# 标题

这是 **加粗**、*斜体* 和 [链接](https://example.com)。

- 第一项
- 第二项

> 引用一句

| 名称 | 数量 |
| --- | ---: |
| 苹果 | 3 |
"""
    text = markdown_to_text(md)
    assert "【标题】" in text
    assert "加粗" in text and "**" not in text
    assert "链接 (https://example.com)" in text
    assert "· 第一项" in text
    assert "｜引用一句" in text
    assert "| ---" not in text
    assert "苹果  3" in text


def test_code_block_is_preserved() -> None:
    md = "说明：\n\n```python\nprint('**not bold**')\n```\n"
    text = markdown_to_text(md)
    assert "```python" in text
    assert "**not bold**" in text


def test_split_respects_limit_and_boundaries() -> None:
    text = "第一段。" * 100 + "\n\n" + "第二段。" * 100
    chunks = split_text(text, 200)
    assert len(chunks) > 1
    assert all(len(c) <= 210 for c in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_splitters_keep_their_distinct_limits_and_sentence_rules() -> None:
    text = "x" * 60 + ". " + "y" * 70
    claude_chunks = split_text(text, 100)
    solution_chunks = split_solution("x" * 120, limit=99)

    assert len(claude_chunks[0]) == 61
    assert len(solution_chunks[0]) == 100


def test_split_balances_code_fences() -> None:
    code = "```python\n" + "\n".join(f"print({i})" for i in range(200)) + "\n```"
    chunks = split_text(code, 200)
    assert len(chunks) > 1
    for chunk in chunks:
        assert sum(1 for line in chunk.splitlines() if line.strip().startswith("```")) % 2 == 0


def test_render_reply_truncates() -> None:
    text = "字" * 5000
    chunks = render_reply(text, limit=500, max_chunks=3)
    assert len(chunks) == 3
    assert "已截断" in chunks[-1]
    assert all(len(c) <= 510 for c in chunks)
