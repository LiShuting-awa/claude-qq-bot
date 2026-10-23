"""说话学习：从群聊记录采样，提炼出一份「这群人怎么说话」的风格档案。"""

from __future__ import annotations

import re

from nonebot import logger

from plugins.common.llm import build_client, has_credentials

from .config import Config

_CQ_RE = re.compile(r"\[CQ:[^\]]+\]")

# 其他机器人：名字带 bot/智能体，或者发的是签到/运势这类模板腔
_BOT_NAME_RE = re.compile(r"(?i)bot|机器人|智能体")
_BOT_TEXT_MARKERS = (
    "签到",
    "运势",
    "好感度",
    "投食",
    "F币",
    "雷币",
    "SteamID",
    "连签",
    "载具数据",
)


def collect_samples(
    records: list[dict], *, max_messages: int, max_chars: int
) -> list[str]:
    """把原始记录洗成学习采样：去噪音、压重复、控制总量。

    过滤：命令、链接、CQ 码、超长转贴、一个字的消息、其他机器人
    （名字带 bot/智能体，或签到运势这类模板腔）；同一条文本最多保留 2 次
    （重复是语气信号，刷屏不是）。
    """
    counts: dict[str, int] = {}
    samples: list[str] = []
    total = 0
    for record in records[-max_messages:]:
        text = str(record.get("x") or "").strip()
        if not 2 <= len(text) <= 200:
            continue
        if text.startswith("/"):
            continue
        if "http://" in text or "https://" in text:
            continue
        if _CQ_RE.search(text):
            continue
        nickname = str(record.get("n") or record.get("u") or "群友").strip() or "群友"
        if _BOT_NAME_RE.search(nickname):
            continue
        if any(marker in text for marker in _BOT_TEXT_MARKERS):
            continue
        if counts.get(text, 0) >= 2:
            continue
        counts[text] = counts.get(text, 0) + 1
        line = f"{nickname}: {text}"
        samples.append(line)
        total += len(line)
        if total >= max_chars:
            samples.pop()
            break
    return samples


def _style_system() -> str:
    return (
        "你是说话方式分析师。你会拿到一位 AI 角色的人格说明，以及它所在 QQ 群的"
        "群友真实聊天记录采样。任务：从记录里提炼「这群人平时怎么说话、常聊什么」，"
        "写成一份风格档案，供这个角色回话时参考。\n\n"
        "要求：\n"
        "- 提炼的是说话的节奏、用词、温度和习惯：句长、标点（或不打标点）的习惯、"
        "语气词、中英混用、表情和梗的用法、怎么附和、怎么开玩笑、怎么表达不同意。\n"
        "- 观察要写具体行为（例如「短句多，经常不带标点」「附和时爱用单字+哈哈」），"
        "不要空话（「活泼大方」这种没有信息量）。\n"
        "- 常聊话题写这群人最近真实在聊的方向和圈内梗，让角色能自然接上话头；"
        "只记话题方向，不要写成新闻摘要。\n"
        "- 例句要像这个群的人说话的味道，但不要整句照抄记录里的原话；"
        "它们是给角色培养语感的，角色说出口要自然。\n"
        "- 脏话、人身攻击和刷屏玩梗不进特征、不进例句；要提就抽象地写进「别学」。\n"
        "- 观察的是全群的整体习惯，不要把某个人的口头禅当成全群的。\n"
        "- 全部用中文输出，直接输出档案本身，不要开场白、解释和总结。"
        "全文（含标题）控制在 1000 字以内，超了注入时会被截断。\n\n"
        "输出格式：\n"
        "## 说话特征\n"
        "- （6-10 条）\n"
        "## 常聊话题\n"
        "- （3-6 条）\n"
        "## 例句\n"
        "- （12-18 条，每条不超过 25 字）\n"
        "## 别学\n"
        "- （2-4 条记录里看到的坏习惯：刷屏、无意义复读、满屏表情、过多脏话等）"
    )


async def distill_style(
    config: Config, persona_text: str, samples: list[str]
) -> str:
    """调用模型提炼风格档案；失败抛异常，由调用方决定怎么提示。"""
    client = build_client(
        api_key=config.anthropic_api_key,
        auth_token=config.anthropic_auth_token,
        auth_token_file=config.anthropic_auth_token_file,
        base_url=config.anthropic_base_url,
        custom_headers=dict(config.anthropic_custom_headers),
        timeout=150,
    )
    persona = (persona_text or "").strip()
    if len(persona) > 1500:
        persona = persona[:1500]
    transcript = "\n".join(samples)
    user_prompt = (
        f"[角色人格说明（提取风格时要兼容这个身份）]\n{persona}\n\n"
        f"[群聊记录采样（共 {len(samples)} 条）]\n{transcript}"
    )
    response = await client.messages.create(
        model=config.claude_model.strip() or "claude-sonnet-4-6",
        max_tokens=1800,
        system=_style_system(),
        messages=[{"role": "user", "content": user_prompt}],
        timeout=150,
    )
    text = "".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text" and getattr(block, "text", None)
    ).strip()
    if "##" not in text or len(text) < 200:
        raise RuntimeError(f"模型输出不像风格档案（{len(text)} 字）")
    return text


def build_learner(config: Config):
    """返回 distill 函数；没配凭据返回 None。"""
    if not has_credentials(
        api_key=config.anthropic_api_key,
        auth_token=config.anthropic_auth_token,
        auth_token_file=config.anthropic_auth_token_file,
    ):
        logger.info("未配置模型凭据，说话学习不可用")
        return None
    return lambda persona, samples: distill_style(config, persona, samples)
