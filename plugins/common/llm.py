"""共用的 Anthropic 凭据读取与客户端构建。

claude_chat 有自己的 client；这里服务的是那些只需要「发一次性请求」的小模块
（图片核对、说话学习等）。凭据与 claude_chat / proactive_chat 共用同一组 .env 变量。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic


def read_token_file(raw_path: str) -> str:
    """读取 token 文件：支持 `{"env": {"ANTHROPIC_AUTH_TOKEN": ...}}` 或平铺 JSON。"""
    path = Path((raw_path or "").strip())
    if not raw_path or not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    env = data.get("env") if isinstance(data, dict) else None
    if isinstance(env, dict):
        value = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY")
        if value:
            return str(value).strip()
    value = data.get("ANTHROPIC_AUTH_TOKEN") if isinstance(data, dict) else ""
    return str(value).strip() if value else ""


def has_credentials(
    *,
    api_key: str,
    auth_token: str,
    auth_token_file: str,
) -> bool:
    return bool(api_key.strip() or auth_token.strip() or auth_token_file.strip())


def build_client(
    *,
    api_key: str = "",
    auth_token: str = "",
    auth_token_file: str = "",
    base_url: str = "",
    custom_headers: dict[str, str] | None = None,
    timeout: float = 60,
    max_retries: int = 1,
) -> AsyncAnthropic:
    """按 .env 里的同一套变量构建 AsyncAnthropic；token 文件只在缺失时兜底读取。"""
    api_key = api_key.strip()
    auth_token = auth_token.strip()
    if not api_key and not auth_token:
        auth_token = read_token_file(auth_token_file)
    if not api_key and not auth_token:
        raise RuntimeError("未配置 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN")
    auth_kwargs: dict[str, Any] = (
        {"auth_token": auth_token} if auth_token else {"api_key": api_key}
    )
    return AsyncAnthropic(
        base_url=base_url.strip() or None,
        timeout=timeout,
        max_retries=max_retries,
        default_headers=dict(custom_headers) or None,
        **auth_kwargs,
    )
