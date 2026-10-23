"""自学插件配置。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from plugins.common.env import HeaderMap


class Config(BaseModel):
    # ---- LLM（提炼话题用，与 claude_chat / speech_learn 共用同一组 .env 变量）----
    anthropic_api_key: str = ""
    anthropic_auth_token: str = ""
    anthropic_auth_token_file: str = ""
    anthropic_base_url: str = ""
    anthropic_custom_headers: HeaderMap = Field(default_factory=dict)
    claude_model: str = "claude-sonnet-4-6"

    speech_learn_enabled: bool = False
    """是否允许每日自学从本机的说话学习日志提炼群聊话题。"""

    self_study_enabled: bool = True
    """总开关：每天自动联网充电（热榜 + 群聊话题进知识库）。"""

    self_study_hour: int = Field(default=5, ge=0, le=23)
    """每天几点自学（本机时区），建议放在没人聊天的时段。"""

    self_study_max_topics: int = Field(default=4, ge=0, le=10)
    """每次从群聊里提炼几个话题去查；0 表示只收热榜。"""

    self_study_hot_limit: int = Field(default=10, ge=0, le=30)
    """每天收多少条热榜进知识库；0 表示不收热榜。"""

    self_study_min_messages: int = Field(default=60, ge=10, le=2000)
    """群聊采样少于这个数就跳过话题提炼，只收热榜。"""

    self_study_days_back: int = Field(default=3, ge=1, le=14)
    """话题提炼往前读几天的群聊记录。"""
