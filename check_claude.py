r"""不依赖 QQ/NapCat，单独验证 Anthropic API Key 和模型是否可用。

用法：
    .\.venv\Scripts\python.exe check_claude.py
"""

from __future__ import annotations

import asyncio
import sys

import nonebot

nonebot.init()

from nonebot import get_plugin_config  # noqa: E402

from plugins.claude_chat.claude import ClaudeClient, ClaudeError  # noqa: E402
from plugins.claude_chat.config import Config  # noqa: E402


async def main() -> int:
    config = get_plugin_config(Config)
    if not config.anthropic_api_key.strip() and not config.anthropic_auth_token.strip():
        print("❌ .env 里还没有填写 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN")
        return 1

    print(f"模型：{config.claude_model}")
    print("正在请求 Claude …")
    client = ClaudeClient(config)
    try:
        reply = await client.complete(
            [{"role": "user", "content": "用一句话介绍一下你自己。"}],
            "你是一个用于连通性测试的助手，回答保持简短。",
        )
    except ClaudeError as exc:
        print(f"❌ {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 未预期的错误：{exc!r}")
        return 1

    print("\n✅ Claude 回复：")
    print(reply.text)
    print(f"\n输入 {reply.input_tokens} tokens / 输出 {reply.output_tokens} tokens")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
