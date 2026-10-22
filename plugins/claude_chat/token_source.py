"""从 Claude Code 的 settings.json 读取最新中转 token，用于 401 自动刷新。"""

from __future__ import annotations

import json
from pathlib import Path


def read_token_file(raw_path: str) -> str:
    path = Path((raw_path or "").strip())
    if not raw_path or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text.strip()
    if not isinstance(data, dict):
        return ""
    env = data.get("env")
    if isinstance(env, dict):
        token = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY")
        if token:
            return str(token).strip()
    token = data.get("ANTHROPIC_AUTH_TOKEN") or data.get("ANTHROPIC_API_KEY")
    return str(token).strip() if token else ""
