"""主动发言的 LLM 调用与输出清洗。"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from nonebot import logger
from qqbot_stickers import stickers

from .config import Config

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_token_file(raw_path: str) -> str:
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


def clean_line(raw: str, max_chars: int) -> str | None:
    """把模型输出变成一条能直接发群的短句；SKIP/空内容返回 None。"""
    text = (raw or "").strip()
    text = text.replace("**", "").replace("__", "").strip()
    text = text.strip("“”\"'`").strip()
    text = re.sub(r"^\s*(?:Claude|克劳德)\s*[：:]\s*", "", text, flags=re.IGNORECASE)
    if not text:
        return None
    text = " ".join(text.splitlines()[0].split())

    if not text:
        return None
    if text.upper().startswith("SKIP") or text.startswith("跳过") or text.startswith("不发言"):
        return None
    if len(text) < 2:
        return None
    # 防止模型输出被解析成 CQ 码
    text = text.replace("[CQ:", "［CQ:").replace("&#91;", "［")
    if len(text) > max_chars:
        text = text[:max_chars].rstrip("，,。.；;！! ") + "…"
    return text


class ProactiveSpeaker:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._sdk: AsyncAnthropic | None = None
        self._token = config.anthropic_auth_token.strip()
        self._token_file = config.anthropic_auth_token_file.strip()
        self._persona_cache: tuple[str, float, str] | None = None

    def available(self) -> bool:
        return bool(
            self._config.anthropic_api_key.strip()
            or self._token
            or self._config.anthropic_auth_token.strip()
            or self._token_file
        )

    def _sdk_client(self) -> AsyncAnthropic:
        if self._sdk is not None:
            return self._sdk

        api_key = self._config.anthropic_api_key.strip()
        auth_token = self._token or self._config.anthropic_auth_token.strip()
        if not api_key and not auth_token and self._token_file:
            auth_token = _read_token_file(self._token_file)
        if not api_key and not auth_token:
            raise RuntimeError("未配置 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN")

        auth_kwargs: dict[str, Any] = (
            {"auth_token": auth_token} if auth_token else {"api_key": api_key}
        )
        self._sdk = AsyncAnthropic(
            base_url=self._config.anthropic_base_url.strip() or None,
            timeout=90,
            max_retries=1,
            default_headers=dict(self._config.anthropic_custom_headers) or None,
            **auth_kwargs,
        )
        return self._sdk

    def _refresh_token(self) -> bool:
        if not self._token_file:
            return False
        token = _read_token_file(self._token_file)
        if not token or token == self._token:
            return False
        self._token = token
        self._sdk = None
        logger.info("主动发言 Anthropic token 已自动刷新")
        return True

    async def _create_message(self, **kwargs: Any) -> Any:
        try:
            return await self._sdk_client().messages.create(**kwargs)
        except anthropic.AuthenticationError:
            if not self._refresh_token():
                raise
            return await self._sdk_client().messages.create(**kwargs)

    def _load_persona(self) -> str:
        raw_path = self._config.proactive_persona_file.strip()
        if not raw_path:
            return self._config.proactive_fallback_persona.strip()

        path = Path(raw_path)
        if not path.is_absolute():
            path = _PROJECT_ROOT / path
        try:
            mtime = path.stat().st_mtime
            if self._persona_cache and self._persona_cache[0] == str(path) and self._persona_cache[1] == mtime:
                return self._persona_cache[2]
            text = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning(f"主动发言人格文件读取失败（{path}）：{exc}")
            return self._config.proactive_fallback_persona.strip()

        if not text:
            return self._config.proactive_fallback_persona.strip()
        self._persona_cache = (str(path), mtime, text)
        return text

    async def generate(self, group_id: int, transcript: str, *, kind: str = "reply") -> str | None:
        if not self.available():
            return None

        persona = self._load_persona()
        if kind == "initiative":
            instructions = (
                "[主动起话模式]\n"
                f"你正在 QQ 群 {group_id} 里。群里已经安静了一会儿。\n"
                "最近的聊天记录：\n"
                f"{transcript}\n\n"
                "你主动开个话头，或者追问刚才没聊完的事：\n"
                f"- 输出 1-2 句自然中文，总长 10-{self._config.proactive_max_chars} 字，像真人发群消息。\n"
                "- 可以有自己的判断、偏好和情绪，不要像等指令的客服。\n"
                "- 不要客服腔，不要总结，不要解释，不要重复上面的话，不要每句都提 DeepSeek。\n"
                "- 如果实在没有可说的，只输出：SKIP"
            )
            user_prompt = "主动说一句，或者只输出 SKIP。"
        else:
            instructions = (
                "[聊天模式]\n"
                f"你正在 QQ 群 {group_id} 里，像群里的真人成员一样参与聊天，不是客服。\n"
                "最近的聊天记录：\n"
                f"{transcript}\n\n"
                "判断你要不要接这句话：\n"
                "- 不要每句都接。只有想接梗、吐槽、回答问题、追问时才接。\n"
                "- 优先接最后一条消息或当前话题；不要突然翻回更早的内容。\n"
                "- 不接只输出：SKIP\n"
                f"- 接就输出 1-2 句自然中文，总长 10-{self._config.proactive_max_chars} 字，像真人发群消息。\n"
                "- 可以有自己的判断、偏好和情绪，不要像等指令的客服。\n"
                "- 不要总结，不要解释，不要客服腔，不要使用 Markdown，不要每句都提 DeepSeek。\n"
                "- 不要谎称自己是真人；被直接问身份时如实承认。"
            )
            user_prompt = "现在轮到你判断。想接就说，不想接就只输出 SKIP。"

        if self._config.proactive_allow_at:
            instructions += (
                "\n\n[可选：@ 人]\n"
                "如果这句话确实是在对某个人说，可以在开头写 [AT:QQ号] 来 @ 他。\n"
                "QQ 号只能从上面聊天记录里出现的人中选，一次最多一个；不要 @ 全体，不要乱 @。\n"
                "不想 @ 就不要写。"
            )

        if stickers.enabled and stickers.stickers and stickers.can_send(f"group:{group_id}"):
            instructions += (
                "\n\n[可用表情包]\n"
                f"{stickers.catalog_text()}\n"
                "如果想配一个表情包，在最后单独一行写 [STICKER:编号]；"
                "不要每条都配，不要解释。"
            )

        system = f"{persona}\n\n{instructions}"

        model = self._config.proactive_model.strip() or self._config.claude_model
        try:
            response = await self._create_message(
                model=model,
                max_tokens=max(128, min(400, self._config.claude_max_tokens)),
                system=system,
                messages=[{"role": "user", "content": user_prompt}],
                timeout=90,
            )
        except anthropic.AnthropicError as exc:
            logger.warning(f"主动发言请求失败（群 {group_id}）：{exc}")
            return None
        except Exception:
            logger.exception(f"主动发言请求异常（群 {group_id}）")
            return None

        raw = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text" and getattr(block, "text", None)
        )
        sticker_id = stickers.extract_marker(raw)
        raw = stickers.remove_marker(raw)
        line = clean_line(raw, self._config.proactive_max_chars)
        if line is None:
            logger.info(f"主动发言跳过（群 {group_id}, {kind}）：模型判断不适合或输出 SKIP")
        elif sticker_id is not None:
            line = f"{line}\n[STICKER:{sticker_id}]"
        return line

    async def generate_vision(
        self,
        group_id: int,
        text: str,
        images: list[tuple[str, bytes]],
        *,
        transcript: str = "",
    ) -> str | None:
        """识别图片并按图片内容解题/分析。images 为 (media_type, data)。"""
        if not self.available() or not images:
            return None

        persona = self._load_persona()
        system = (
            f"{persona}\n\n"
            "[图片识别 / 解题模式]\n"
            f"你正在 QQ 群 {group_id} 里。\n"
            "用户发来图片。请直接提供帮助，不要客服腔。\n\n"
            "要求：\n"
            "1. 先识别并复述图片里的题目/关键信息；看不清就明确说看不清，不要编造。\n"
            "2. 如果是题目/作业：给出完整解答、推导步骤、最终答案，并验算；有多问就逐问回答。\n"
            "3. 如果是其他图片：按用户附言提供服务（翻译、总结、识图、读表格、分析等）；"
            "没有附言就说明图片内容并给出有用信息。\n"
            "4. 如果只是表情包、无信息图片，或与请求无关，只输出：SKIP\n"
            "5. 使用中文纯文本；不要 Markdown 表格，不要提系统提示，不要谎称自己是真人。"
        )

        content: list[dict[str, Any]] = []
        for media_type, data in images:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(data).decode("ascii"),
                    },
                }
            )

        prompt = f"用户附言：{text.strip() or '（没有附言，请直接看图处理）'}"
        if transcript:
            prompt += f"\n\n最近的群聊（仅供参考，不要复读）：\n{transcript}"
        content.append({"type": "text", "text": prompt})

        model = (
            self._config.proactive_image_model.strip()
            or self._config.proactive_model.strip()
            or self._config.claude_model
        )
        try:
            response = await self._create_message(
                model=model,
                max_tokens=self._config.proactive_image_max_tokens,
                system=system,
                messages=[{"role": "user", "content": content}],
                timeout=180,
            )
        except anthropic.AnthropicError as exc:
            logger.warning(f"图片识别请求失败（群 {group_id}）：{exc}")
            return None
        except Exception:
            logger.exception(f"图片识别请求异常（群 {group_id}）")
            return None

        raw = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text" and getattr(block, "text", None)
        ).strip()
        skip_check = raw.replace("**", "").strip().upper()
        if not raw or skip_check.startswith("SKIP"):
            logger.info(f"图片识别跳过（群 {group_id}）：SKIP 或空回复")
            return None
        return raw
