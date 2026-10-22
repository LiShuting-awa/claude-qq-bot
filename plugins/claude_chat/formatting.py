"""把 Claude 的 Markdown 回复整理成适合 QQ 显示的纯文本。"""

from __future__ import annotations

import re

from plugins.common.text import split_at_boundaries

_FENCE_LINE = re.compile(r"^\s*```")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?\s*$")
_HR = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC = re.compile(r"(?<![A-Za-z0-9*])\*(?!\s)(.+?)(?<!\s)\*(?![A-Za-z0-9*])")
_STRIKE = re.compile(r"~~(.+?)~~")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_BULLET = re.compile(r"^(\s*)[-*+]\s+")
_BLOCKQUOTE = re.compile(r"^\s*>\s?")


def _convert_inline(line: str) -> str:
    """处理行内 Markdown 标记。"""
    line = _IMAGE.sub(lambda m: m.group(1) or "图片", line)
    line = _LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})", line)
    line = _BOLD.sub(lambda m: m.group(1) or m.group(2), line)
    line = _STRIKE.sub(r"\1", line)
    line = _ITALIC.sub(r"\1", line)
    line = _INLINE_CODE.sub(r"\1", line)
    return line


def markdown_to_text(text: str) -> str:
    """轻量 Markdown -> QQ 文本转换，保留代码块内容不动。"""
    if not text:
        return ""

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    in_code = False

    for raw in lines:
        line = raw.rstrip()

        if _FENCE_LINE.match(line):
            if in_code:
                in_code = False
                out.append("```")
            else:
                in_code = True
                info = line.strip()[3:].strip()
                out.append(f"```{info}".rstrip())
            continue

        if in_code:
            # 代码块里的内容原样保留
            out.append(raw)
            continue

        if _TABLE_SEP.match(line):
            # 去掉 Markdown 表格的分隔行
            continue

        heading = _HEADING.match(line)
        if heading:
            title = _convert_inline(heading.group(2)).strip()
            if title:
                out.append(f"【{title}】")
            continue

        if _HR.match(line):
            out.append("————")
            continue

        if line.lstrip().startswith("|") and line.count("|") >= 2:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if any(cells):
                out.append("  ".join(cells))
            continue

        line = _BLOCKQUOTE.sub("｜", line)
        line = _BULLET.sub(r"\1· ", line)
        line = _convert_inline(line)
        out.append(line)

    result = "\n".join(out)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def _fence_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if _FENCE_LINE.match(line))


def _balance_fences(chunks: list[str]) -> list[str]:
    """拆分后如果代码块被截断，自动补上闭合/重新打开围栏。"""
    balanced: list[str] = []
    reopen = False
    for chunk in chunks:
        if reopen:
            chunk = "```\n" + chunk
        if _fence_count(chunk) % 2 == 1:
            chunk = chunk.rstrip() + "\n```"
            reopen = True
        else:
            reopen = False
        balanced.append(chunk)
    return balanced


def split_text(text: str, limit: int) -> list[str]:
    """按段落/句子边界把长文本拆成不超过 limit 的若干段。"""
    chunks = split_at_boundaries(
        text,
        limit,
        minimum_limit=50,
        sentence_marks=("。", "！", "？", "；", ". "),
    )
    return _balance_fences(chunks)


def render_reply(
    text: str,
    *,
    convert_markdown: bool = True,
    limit: int = 1200,
    max_chunks: int = 4,
) -> list[str]:
    """转换 + 拆分，并在超过条数上限时给出截断提示。"""
    if convert_markdown:
        text = markdown_to_text(text)
    else:
        text = text.strip()

    chunks = split_text(text, limit)
    if not chunks:
        return []
    if len(chunks) <= max_chunks:
        return chunks

    chunks = chunks[:max_chunks]
    note = "\n…（回复过长，已截断）"
    last = chunks[-1]
    if len(last) + len(note) > limit:
        last = last[: max(0, limit - len(note))].rstrip()
    chunks[-1] = last + note
    return chunks
