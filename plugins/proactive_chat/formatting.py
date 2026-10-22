"""把图片解题结果整理成适合 QQ 的纯文本。"""

from __future__ import annotations

import re

from plugins.common.text import split_at_boundaries

_SUPERSCRIPTS = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
_SUBSCRIPTS = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")

_SYMBOLS = {
    r"\times": "×",
    r"\cdot": "·",
    r"\pm": "±",
    r"\mp": "∓",
    r"\Delta": "Δ",
    r"\delta": "δ",
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\theta": "θ",
    r"\lambda": "λ",
    r"\mu": "μ",
    r"\pi": "π",
    r"\infty": "∞",
    r"\neq": "≠",
    r"\leq": "≤",
    r"\geq": "≥",
    r"\approx": "≈",
    r"\sum": "Σ",
    r"\int": "∫",
    r"\angle": "∠",
    r"\triangle": "△",
    r"\because": "∵",
    r"\therefore": "∴",
}


def _latex_to_text(text: str) -> str:
    text = text.replace("\\\\", "\n")
    text = (
        text.replace("\\(", "")
        .replace("\\)", "")
        .replace("\\[", "")
        .replace("\\]", "")
        .replace("$$", "")
    )

    # 嵌套的 \frac / \sqrt 多跑几轮
    for _ in range(4):
        new = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", text)
        new = re.sub(r"\\sqrt\{([^{}]*)\}", r"√(\1)", new)
        if new == text:
            break
        text = new

    for command, symbol in _SYMBOLS.items():
        text = text.replace(command, symbol)

    text = re.sub(r"\\(?:left|right|,|;|!|quad|qquad|displaystyle)", "", text)
    text = re.sub(r"\\(?:text|mathrm|mathbf|boxed)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\(?:begin|end)\{[^{}]*\}", "", text)
    text = re.sub(
        r"\^\{?([0-9+\-=()n]+)\}?",
        lambda m: m.group(1).translate(_SUPERSCRIPTS),
        text,
    )
    text = re.sub(
        r"_\{?([0-9]+)\}?",
        lambda m: m.group(1).translate(_SUBSCRIPTS),
        text,
    )
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    text = text.replace("{", "").replace("}", "")
    return text


def clean_solution(raw: str, limit: int = 6000) -> str:
    """清理 Markdown / LaTeX，保留换行和解题步骤。"""
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?m)^\s*```.*$", "", text)
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)
    text = text.replace("**", "").replace("__", "")
    text = _latex_to_text(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if len(text) > limit:
        text = text[: max(0, limit - 20)].rstrip() + "\n…（内容过长，已截断）"
    return text


def split_solution(
    text: str,
    *,
    limit: int = 1200,
    max_chunks: int = 8,
) -> list[str]:
    chunks = split_at_boundaries(
        text or "",
        limit,
        minimum_limit=100,
        sentence_marks=("。", "；", "！", "？"),
    )

    if len(chunks) > max_chunks:
        chunks = chunks[:max_chunks]
        note = "\n…（回复过长，已截断）"
        last = chunks[-1]
        if len(last) + len(note) > limit:
            last = last[: max(0, limit - len(note))].rstrip()
        chunks[-1] = last + note
    return chunks
