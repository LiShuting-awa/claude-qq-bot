from __future__ import annotations

import asyncio
import json

import anthropic
import httpx2
import pytest

from plugins.claude_chat.claude import ClaudeClient, ClaudeError
from plugins.claude_chat.config import Config

MESSAGE_PAYLOAD = {
    "id": "msg_test",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-4-6",
    "content": [{"type": "text", "text": "你好，我是 Claude。"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 12, "output_tokens": 8},
}


def _make_client(handler, **config_kwargs):
    transport = httpx2.MockTransport(handler)
    http_client = httpx2.AsyncClient(transport=transport)
    sdk = anthropic.AsyncAnthropic(
        api_key="test-key",
        base_url="http://mock.local",
        http_client=http_client,
        max_retries=0,
    )
    config_kwargs.setdefault("claude_max_tokens", 512)
    config = Config(anthropic_api_key="test-key", **config_kwargs)
    return ClaudeClient(config, sdk_client=sdk), sdk


def test_complete_sends_expected_request_and_parses_usage() -> None:
    captured = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = json.loads(request.content)
        captured["url"] = str(request.url)
        return httpx2.Response(200, json=MESSAGE_PAYLOAD)

    async def scenario() -> None:
        client, sdk = _make_client(handler)
        reply = await client.complete([{"role": "user", "content": "你好"}], "系统提示")
        await sdk.close()
        assert reply.text == "你好，我是 Claude。"
        assert reply.input_tokens == 12
        assert reply.output_tokens == 8
        assert reply.truncated is False

    asyncio.run(scenario())
    assert captured["url"].endswith("/v1/messages")
    assert captured["body"]["model"] == "claude-sonnet-4-6"
    assert captured["body"]["max_tokens"] == 512
    assert captured["body"]["system"] == "系统提示"
    assert captured["body"]["messages"] == [{"role": "user", "content": "你好"}]


def test_thinking_enabled_sends_budget() -> None:
    captured = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json=MESSAGE_PAYLOAD)

    async def scenario() -> None:
        client, sdk = _make_client(
            handler,
            claude_max_tokens=2048,
            claude_thinking_enabled=True,
            claude_thinking_budget_tokens=1024,
        )
        await client.complete([{"role": "user", "content": "hi"}], "sys")
        await sdk.close()

    asyncio.run(scenario())
    assert captured["body"]["thinking"] == {"type": "enabled", "budget_tokens": 1024}


def test_thinking_budget_is_clamped_under_max_tokens() -> None:
    captured = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json=MESSAGE_PAYLOAD)

    async def scenario() -> None:
        # 预算 4096 > max_tokens 512：钳到 511，仍大于 1024 的下限不成立 → 直接关闭思考
        client, sdk = _make_client(
            handler, claude_thinking_enabled=True, claude_thinking_budget_tokens=4096
        )
        await client.complete([{"role": "user", "content": "hi"}], "sys")
        await sdk.close()

    asyncio.run(scenario())
    assert "thinking" not in captured["body"]


def test_thinking_disabled_omits_param() -> None:
    captured = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json=MESSAGE_PAYLOAD)

    async def scenario() -> None:
        client, sdk = _make_client(handler)
        await client.complete([{"role": "user", "content": "hi"}], "sys")
        await sdk.close()

    asyncio.run(scenario())
    assert "thinking" not in captured["body"]


def test_authentication_error_is_translated() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            401,
            json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}},
        )

    async def scenario() -> None:
        client, sdk = _make_client(handler)
        with pytest.raises(ClaudeError, match="API Key"):
            await client.complete([{"role": "user", "content": "hi"}], "sys")
        await sdk.close()

    asyncio.run(scenario())


def test_auth_token_and_custom_headers_are_used() -> None:
    config = Config(
        anthropic_auth_token="relay-token",
        anthropic_base_url="https://relay.example.com",
        anthropic_custom_headers={"x-provider": "relay"},
    )
    client = ClaudeClient(config)
    sdk = client._sdk_client()
    assert sdk.auth_token == "relay-token"
    assert sdk.api_key is None
    assert sdk.base_url.host == "relay.example.com"
    assert sdk.default_headers["x-provider"] == "relay"


def test_missing_key_is_reported_without_network() -> None:
    config = Config(anthropic_api_key="")
    client = ClaudeClient(config)

    async def scenario() -> None:
        with pytest.raises(ClaudeError, match="ANTHROPIC_API_KEY"):
            await client.complete([{"role": "user", "content": "hi"}], "sys")

    asyncio.run(scenario())
