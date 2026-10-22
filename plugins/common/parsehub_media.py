"""判断一个链接是否已经由 nonebot-plugin-parsehub 接管，避免本地兜底重复发送。"""

from __future__ import annotations

import json
import os

_HUB = None


def parsehub_handles(url: str) -> bool:
    allowed: set[str] | None = None
    try:
        from nonebot import get_plugin_config

        from nonebot_plugin_parsehub.config import Config

        configured = get_plugin_config(Config).parsehub_platforms
        allowed = {str(item).strip().lower() for item in configured if str(item).strip()}
    except Exception:
        raw = (os.getenv("PARSEHUB_PLATFORMS") or "").strip()
        if raw:
            try:
                values = json.loads(raw)
                if isinstance(values, list):
                    allowed = {
                        str(item).strip().lower()
                        for item in values
                        if str(item).strip()
                    }
            except (ValueError, TypeError):
                allowed = None

    try:
        from parsehub import ParseHub
    except Exception:
        return False

    global _HUB
    if _HUB is None:
        _HUB = ParseHub()
    try:
        platform = _HUB.get_platform(url)
    except Exception:
        return False
    if platform is None:
        return False
    if platform.id.lower() == "bilibili":
        # B 站固定走本地 Jina/信息卡链路，不交给 ParseHub
        return False
    return allowed is None or platform.id.lower() in allowed
