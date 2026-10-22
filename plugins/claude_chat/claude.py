"""Anthropic Claude 异步客户端：重试、错误翻译、用量统计。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from nonebot import logger

from .config import Config
from .token_source import read_token_file

_RETRYABLE = (
    anthropic.RateLimitError,
    anthropic.OverloadedError,
    anthropic.InternalServerError,
    anthropic.APIConnectionError,
)


@dataclass(slots=True)
class ClaudeReply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    truncated: bool = False


class ClaudeError(RuntimeError):
    """可以直接展示给 QQ 用户的错误。"""


class ClaudeClient:
    def __init__(self, config: Config, *, sdk_client: AsyncAnthropic | None = None) -> None:
        self._config = config
        self._sdk = sdk_client
        self._token = config.anthropic_auth_token.strip()
        self._token_file = config.anthropic_auth_token_file.strip()
        self._semaphore = asyncio.Semaphore(max(1, config.claude_concurrency))

    def _sdk_client(self) -> AsyncAnthropic:
        if self._sdk is not None:
            return self._sdk

        api_key = self._config.anthropic_api_key.strip()
        auth_token = self._token or self._config.anthropic_auth_token.strip()
        if self._token_file and not api_key:
            # settings.json 里的 token 由 Claude Code 登录自动续期，通常比 .env 里的新；
            # 不一致时直接用新的，省掉每次重启后第一句话先撞一次 401 的往返
            file_token = read_token_file(self._token_file)
            if file_token and file_token != auth_token:
                auth_token = file_token
                self._token = file_token
        if not api_key and not auth_token:
            raise ClaudeError(
                "还没有配置 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。"
                "请打开 .env 填写后重启机器人。"
            )

        auth_kwargs: dict[str, Any] = (
            {"auth_token": auth_token} if auth_token else {"api_key": api_key}
        )
        self._sdk = AsyncAnthropic(
            base_url=self._config.anthropic_base_url.strip() or None,
            timeout=self._config.claude_timeout_seconds,
            max_retries=0,
            default_headers=dict(self._config.anthropic_custom_headers) or None,
            **auth_kwargs,
        )
        return self._sdk

    def _refresh_token(self) -> bool:
        if not self._token_file:
            return False
        token = read_token_file(self._token_file)
        if not token or token == self._token:
            return False
        self._token = token
        self._sdk = None
        logger.info("Anthropic token 已从 settings 文件自动刷新")
        return True

    async def complete(self, messages: list[dict[str, Any]], system: str) -> ClaudeReply:
        sdk = self._sdk_client()
        model = self._config.claude_model

        async with self._semaphore:
            response = await self._request(sdk, model, messages, system)

        text = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text" and getattr(block, "text", None)
        ).strip()
        if not text:
            text = "……这次没组织出话来，换个说法再说一次。"

        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        truncated = getattr(response, "stop_reason", None) == "max_tokens"

        return ClaudeReply(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            truncated=truncated,
        )

    async def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        system: str,
        *,
        tools: list[dict[str, Any]],
        executor: Any,
        max_rounds: int = 3,
    ) -> ClaudeReply:
        """带工具循环的对话：模型自己决定查什么、读哪一页。"""
        sdk = self._sdk_client()
        model = self._config.claude_model
        working = list(messages)
        input_tokens = 0
        output_tokens = 0
        last_text = ""

        async with self._semaphore:
            for _ in range(max(1, max_rounds) + 1):
                sdk = self._sdk_client()
                response = await self._request(
                    sdk, model, working, system, tools=tools
                )
                usage = getattr(response, "usage", None)
                input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
                output_tokens += int(getattr(usage, "output_tokens", 0) or 0)

                blocks = list(response.content)
                text = "".join(
                    getattr(block, "text", "")
                    for block in blocks
                    if getattr(block, "type", None) == "text"
                ).strip()
                if text:
                    last_text = text

                tool_uses = [
                    block for block in blocks if getattr(block, "type", None) == "tool_use"
                ]
                if getattr(response, "stop_reason", None) != "tool_use" or not tool_uses:
                    if not last_text:
                        last_text = "……这次没组织出话来，换个说法再说一次。"
                    return ClaudeReply(
                        text=last_text,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        truncated=getattr(response, "stop_reason", None) == "max_tokens",
                    )

                working.append(
                    {
                        "role": "assistant",
                        "content": [self._block_to_dict(block) for block in blocks],
                    }
                )
                results: list[dict[str, Any]] = []
                for block in tool_uses:
                    name = getattr(block, "name", "")
                    arguments = getattr(block, "input", {}) or {}
                    try:
                        result = await executor(name, arguments)
                        is_error = False
                    except Exception as exc:
                        result = f"工具执行失败：{type(exc).__name__}: {str(exc)[:300]}"
                        is_error = True
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": getattr(block, "id", ""),
                            "content": str(result)[:12000],
                            "is_error": is_error,
                        }
                    )
                working.append({"role": "user", "content": results})

        raise ClaudeError("工具调用轮数过多，本次先停。")

    @staticmethod
    def _block_to_dict(block: Any) -> dict[str, Any]:
        if hasattr(block, "model_dump"):
            try:
                return block.model_dump(exclude_none=True)
            except Exception:
                pass
        if hasattr(block, "dict"):
            try:
                return block.dict(exclude_none=True)
            except Exception:
                pass
        if isinstance(block, dict):
            return block
        return {"type": getattr(block, "type", "text"), "text": str(block)}

    async def _request(
        self,
        sdk: AsyncAnthropic,
        model: str,
        messages: list[dict[str, Any]],
        system: str,
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "max_tokens": self._config.claude_max_tokens,
                    "system": system,
                    "messages": messages,
                    "timeout": self._config.claude_timeout_seconds,
                }
                if tools:
                    kwargs["tools"] = tools
                return await sdk.messages.create(**kwargs)
            except anthropic.AuthenticationError as exc:
                if self._refresh_token():
                    sdk = self._sdk_client()
                    logger.warning("Anthropic 鉴权失败，已刷新 token，重试一次")
                    continue
                logger.error(f"Anthropic 鉴权失败：{exc}")
                raise ClaudeError(
                    "Anthropic API Key/凭据无效或已失效，自动刷新也没成功；"
                    "请检查 .env 和 settings 文件。"
                ) from exc
            except anthropic.PermissionDeniedError as exc:
                logger.error(f"Anthropic 权限不足：{exc}")
                raise ClaudeError("当前 API Key 没有访问该模型的权限，请检查账户设置。") from exc
            except anthropic.NotFoundError as exc:
                logger.error(f"Anthropic 模型不存在：{model}：{exc}")
                raise ClaudeError(
                    f"模型 `{model}` 不存在或当前账号不可用，请修改 .env 中的 CLAUDE_MODEL。"
                ) from exc
            except anthropic.BadRequestError as exc:
                logger.error(f"Anthropic 请求参数错误：{exc}")
                raise ClaudeError("请求被 Claude 拒绝了，可能是图片太大或内容不合规。") from exc
            except _RETRYABLE as exc:
                if attempt >= attempts:
                    logger.error(f"Claude 请求重试 {attempts} 次仍失败：{exc}")
                    raise ClaudeError("Claude 服务暂时不可用（限流或网络异常），请稍后再试。") from exc
                delay = min(2**attempt, 8)
                logger.warning(f"Claude 请求失败（第 {attempt} 次），{delay}s 后重试：{exc}")
                await asyncio.sleep(delay)
            except anthropic.APIStatusError as exc:
                logger.error(f"Anthropic 返回异常状态码 {exc.status_code}：{exc}")
                raise ClaudeError(f"Claude API 返回异常（HTTP {exc.status_code}），请稍后再试。") from exc
            except anthropic.AnthropicError as exc:
                logger.error(f"Anthropic SDK 错误：{exc}")
                raise ClaudeError("连接 Claude 失败，请检查网络或代理设置。") from exc

        raise ClaudeError("Claude 请求失败，请稍后再试。")
