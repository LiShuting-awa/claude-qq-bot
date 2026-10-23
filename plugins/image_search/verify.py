"""搜图结果核对：下载到的图先让模型确认内容和关键词对得上，再发出去。

核对失败一律降级为「不核对直接发」，绝不卡住发图。
"""

from __future__ import annotations

import asyncio
import base64
import io
import re
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from nonebot import logger

from plugins.common.llm import build_client, has_credentials

from .config import Config

_VERIFY_SYSTEM = (
    "你是图片匹配审核器。给你若干张图片（按传入顺序是第 1、2、… 张）和一个查询词，"
    "逐张判断图片的主体内容是否就是查询词所指的东西。\n"
    "判断标准：主体对得上才算匹配；只有相关文字、logo、界面截图、梗图排版、"
    "或者只是沾边的联想，都算不匹配。\n"
    "只输出一行判断，格式如：1:是 2:否 3:是。不要解释。"
)

# 兼容「1:是」「2、否」「3. yes」「4 是」这类写法
_VERDICT_RE = re.compile(
    r"(\d+)\s*[.、:：,，)）]?\s*(是|否|yes|no|true|false|y|n|✓|✗|√|×)",
    re.IGNORECASE,
)
_YES_WORDS = {"是", "yes", "true", "y", "✓", "√"}


def parse_verdicts(text: str, count: int) -> list[bool] | None:
    """解析模型输出的一行判断；编号不全或解析不动返回 None（按未核对处理）。"""
    results: dict[int, bool] = {}
    for match in _VERDICT_RE.finditer(text or ""):
        try:
            index = int(match.group(1))
        except ValueError:
            continue
        if 1 <= index <= count and index not in results:
            results[index] = match.group(2).lower() in _YES_WORDS
    if len(results) < count:
        return None
    return [results[index + 1] for index in range(count)]


def _downscale(data: bytes, max_side: int = 768) -> tuple[bytes, str] | None:
    """缩成小尺寸 JPEG 再发给模型，省 token；缩不动返回 None。"""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            image.load()
            image = image.convert("RGB")
            image.thumbnail((max_side, max_side))
            out = io.BytesIO()
            image.save(out, "JPEG", quality=85)
            return out.getvalue(), "image/jpeg"
    except Exception:
        return None


class ImageVerifier:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._sdk: AsyncAnthropic | None = None

    def available(self) -> bool:
        return has_credentials(
            api_key=self._config.anthropic_api_key,
            auth_token=self._config.anthropic_auth_token,
            auth_token_file=self._config.anthropic_auth_token_file,
        )

    def _sdk_client(self) -> AsyncAnthropic:
        if self._sdk is not None:
            return self._sdk
        self._sdk = build_client(
            api_key=self._config.anthropic_api_key,
            auth_token=self._config.anthropic_auth_token,
            auth_token_file=self._config.anthropic_auth_token_file,
            base_url=self._config.anthropic_base_url,
            custom_headers=dict(self._config.anthropic_custom_headers),
            timeout=60,
        )
        return self._sdk

    async def _create_message(self, **kwargs: Any) -> Any:
        return await self._sdk_client().messages.create(**kwargs)

    async def verify_batch(
        self, query: str, images: list[tuple[bytes, str]]
    ) -> list[bool] | None:
        """核对一批（最多 4 张）；返回每张是否匹配，解析不了返回 None。"""
        downscaled = await asyncio.to_thread(_downscale_batch, images)
        if downscaled is None:
            return None

        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.b64encode(data).decode("ascii"),
                },
            }
            for data, media_type in downscaled
        ]
        content.append({"type": "text", "text": f"查询词：{query.strip()}"})

        model = self._config.image_search_verify_model.strip() or self._config.claude_model
        response = await self._create_message(
            model=model,
            max_tokens=100,
            system=_VERIFY_SYSTEM,
            messages=[{"role": "user", "content": content}],
            timeout=60,
        )
        raw = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text" and getattr(block, "text", None)
        )
        return parse_verdicts(raw, len(downscaled))


def _downscale_batch(images: list[tuple[bytes, str]]) -> list[tuple[bytes, str]] | None:
    downscaled: list[tuple[bytes, str]] = []
    for data, _media_type in images:
        small = _downscale(data)
        if small is None:
            return None
        downscaled.append(small)
    return downscaled


def build_verify_fn(config: Config):
    """开启核对且配了模型凭据时返回核对函数；否则返回 None（不核对）。"""
    if not config.image_search_verify:
        return None
    verifier = ImageVerifier(config)
    if not verifier.available():
        logger.info("未配置模型凭据，图片搜索跳过内容核对")
        return None
    return verifier.verify_batch
