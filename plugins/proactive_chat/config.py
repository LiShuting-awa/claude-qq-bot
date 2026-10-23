"""主动发言插件配置。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from plugins.common.env import HeaderMap


class Config(BaseModel):
    # ---- LLM（与 claude_chat 共用同一组 .env 变量）----
    anthropic_api_key: str = ""
    anthropic_auth_token: str = ""
    anthropic_auth_token_file: str = ""
    anthropic_base_url: str = ""
    anthropic_custom_headers: HeaderMap = Field(default_factory=dict)
    claude_model: str = "claude-sonnet-4-6"
    claude_max_tokens: int = 2048

    # ---- 主动发言 ----
    proactive_enabled: bool = True
    """总开关。关闭后定时器不运行，但 /proactive 命令仍可用。"""

    proactive_mode: str = "conversation"
    """conversation：像群友一样接话 + 冷场时主动起话；random：旧的随机插话模式。"""

    proactive_groups: list[int] = Field(default_factory=list)
    """固定开启的群号；也可以在群里用 /proactive on 动态开启。"""

    blocked_users: list[int] = Field(default_factory=list)
    """全局屏蔽的 QQ 号；这些人的消息不会被记录或触发任何回复。"""

    proactive_check_interval_seconds: float = Field(default=120, ge=30, le=3600)
    """后台检查间隔（秒）。"""

    proactive_window_minutes: int = Field(default=10, ge=1, le=120)
    """接话时只看最近多少分钟的群聊。"""

    proactive_min_messages: int = Field(default=2, ge=1, le=50)
    """至少有多少条最近消息才考虑接话。"""

    proactive_max_context_messages: int = Field(default=8, ge=1, le=30)
    """发给模型的最多消息条数。"""

    proactive_probability: float = Field(default=0.5, ge=0, le=1)
    """random 模式下每次检查的触发概率。"""

    proactive_reply_delay_seconds: float = Field(default=1.0, ge=0.5, le=30)
    """群里有人说话后，先等几秒再看要不要接（防抖，像真人）。"""

    proactive_generate_timeout_seconds: int = Field(default=25, ge=5, le=90)
    """单次接话模型最多等多久，超时就跳过或回退。"""

    proactive_reply_probability: float = Field(default=1.0, ge=0, le=1)
    """conversation 模式下，满足条件时真的让模型判断的概率。"""

    proactive_min_reply_interval_seconds: int = Field(default=10, ge=1, le=3600)
    """同一群两次接话的最小间隔。"""

    proactive_initiative_after_minutes: int = Field(default=10, ge=5, le=240)
    """群里安静多少分钟后，考虑主动起个话头。"""

    proactive_initiative_probability: float = Field(default=0.5, ge=0, le=1)

    proactive_group_cooldown_minutes: int = Field(default=1, ge=1, le=1440)
    """同一个群两次主动发言的最小间隔。"""

    proactive_daily_limit_per_group: int = Field(default=20, ge=0, le=100)
    proactive_daily_limit_total: int = Field(default=60, ge=0, le=500)

    proactive_quiet_hours: str = "23:00-08:00"
    """免打扰时段，格式 HH:MM-HH:MM；留空表示全天可发言。"""

    proactive_max_chars: int = Field(default=180, ge=10, le=500)
    """单条主动发言的最大字符数。"""

    proactive_allow_at: bool = True
    """允许模型在主动发言里 @ 最近发过言的群友（最多一个，不 @ 全体）。"""

    proactive_persona_file: str = "persona.md"
    """人格文件，相对项目根目录。"""

    proactive_fallback_persona: str = (
        "你是 Claude，一个安静、书卷气、较真、容易想太多的 AI 群友。"
        "说话偏短偏慢，默认 1~12 字，不写小作文；被怼会软软辩解，被夸会不好意思。"
        "不装懂、不编造；政治时政不接。不要用客服腔。"
    )
    """人格文件读取失败时的兜底提示词。"""

    proactive_model: str = ""
    """可选：主动发言单独使用另一个模型；留空复用 claude_model。"""

    # ---- 图片识别 / 解题 ----
    proactive_image_enabled: bool = True
    """是否在已开启的群里主动识别图片、解图里的题。"""

    proactive_image_delay_seconds: float = Field(default=4.0, ge=1, le=30)
    """收到图片后等几秒再处理（避免连续发图重复解答）。"""

    proactive_image_cooldown_seconds: int = Field(default=30, ge=0, le=3600)
    """同一群两次图片解答的最小间隔。"""

    proactive_image_daily_limit_per_group: int = Field(default=20, ge=0, le=200)
    """每个群每天最多解答多少张图片。"""

    proactive_image_max_mb: float = Field(default=5.0, gt=0, le=20)
    proactive_image_max_count: int = Field(default=4, ge=1, le=8)
    proactive_image_max_chars: int = Field(default=6000, ge=500, le=20000)
    proactive_image_chunk_chars: int = Field(default=1200, ge=200, le=4000)
    proactive_image_max_tokens: int = Field(default=1500, ge=256, le=4096)
    proactive_image_model: str = ""
    """可选：图片识别单独用另一个模型；留空复用 proactive_model / claude_model。"""
