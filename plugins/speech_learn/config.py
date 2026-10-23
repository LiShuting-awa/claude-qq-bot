"""说话学习插件配置。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from plugins.common.env import HeaderMap


class Config(BaseModel):
    # ---- LLM（与 claude_chat / proactive_chat 共用同一组 .env 变量）----
    anthropic_api_key: str = ""
    anthropic_auth_token: str = ""
    anthropic_auth_token_file: str = ""
    anthropic_base_url: str = ""
    anthropic_custom_headers: HeaderMap = Field(default_factory=dict)
    claude_model: str = "claude-sonnet-4-6"

    speech_learn_enabled: bool = False
    """总开关：关闭后既不记录群聊，也不响应 /learn_speech。"""

    speech_learn_inject: bool = True
    """是否把学到的风格档案注入到回话提示词里（claude_chat + 主动发言）。"""

    speech_learn_min_messages: int = Field(default=100, ge=10, le=5000)
    """至少积累多少条群聊记录才允许学习，少了学不出东西。"""

    speech_learn_max_messages: int = Field(default=1200, ge=100, le=10000)
    """每次学习最多用最近多少条记录。"""

    speech_learn_max_sample_chars: int = Field(default=30000, ge=2000, le=100000)
    """发给模型的记录采样总字数上限。"""

    speech_learn_max_style_chars: int = Field(default=1200, ge=200, le=4000)
    """注入提示词的风格档案最大字数。"""

    speech_learn_cooldown_seconds: int = Field(default=300, ge=0, le=86400)
    """两次学习之间的最小间隔。"""

    speech_learn_retention_days: int = Field(default=14, ge=1, le=180)
    """群聊记录保留天数，过期清理。"""

    speech_learn_auto_enabled: bool = False
    """每日自动学说话：到点用最近的群聊记录重新提炼风格档案，不用手动敲命令。"""

    speech_learn_auto_hour: int = Field(default=4, ge=0, le=23)
    """每天几点自动学（本机时区），建议放在没人聊天的时段。"""

    blocked_users: list[int] = Field(default_factory=list)
    """全局屏蔽的 QQ 号；这些人的消息不进学习记录。"""
