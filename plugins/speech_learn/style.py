"""学到的风格档案：data/speech_style.md 的读写与注入。

跟 persona.md 一样按 mtime 热加载；claude_chat 和 proactive_chat 都从这里取。
"""

from __future__ import annotations

from pathlib import Path

from nonebot import get_plugin_config

from .config import Config

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
STYLE_PATH = _PROJECT_ROOT / "data" / "speech_style.md"

_config = get_plugin_config(Config)
_cache: tuple[float, str] | None = None


def write_style(text: str) -> None:
    global _cache
    STYLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STYLE_PATH.write_text((text or "").strip() + "\n", encoding="utf-8")
    _cache = None


def remove_style() -> bool:
    global _cache
    _cache = None
    try:
        STYLE_PATH.unlink()
        return True
    except FileNotFoundError:
        return False


def _load(max_chars: int) -> str:
    global _cache
    try:
        mtime = STYLE_PATH.stat().st_mtime
    except OSError:
        return ""
    if _cache and _cache[0] == mtime:
        text = _cache[1]
    else:
        try:
            text = STYLE_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        _cache = (mtime, text)
    if len(text) > max_chars:
        cut = text.rfind("\n", 0, max_chars)
        text = text[: cut if cut > 200 else max_chars].rstrip()
    return text


def style_block(max_chars: int | None = None) -> str:
    """注入提示词的风格段落；没学过或关闭注入时返回空串。"""
    if not _config.speech_learn_enabled or not _config.speech_learn_inject:
        return ""
    text = _load(max_chars or _config.speech_learn_max_style_chars)
    if not text:
        return ""
    return (
        "\n\n[群友说话方式参考（从本群真实聊天记录里学来）]\n"
        f"{text}\n"
        "（参考这里的语气和节奏，但保持你自己的人格和判断；例句是语感参考，不是台词，别照抄。）"
    )
