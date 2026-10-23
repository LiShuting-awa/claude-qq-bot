"""图片搜索插件配置。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from plugins.common.env import HeaderMap


class Config(BaseModel):
    # ---- LLM（与 claude_chat / proactive_chat 共用同一组 .env 变量，用于结果核对）----
    anthropic_api_key: str = ""
    anthropic_auth_token: str = ""
    anthropic_auth_token_file: str = ""
    anthropic_base_url: str = ""
    anthropic_custom_headers: HeaderMap = Field(default_factory=dict)
    claude_model: str = "claude-sonnet-4-6"

    image_search_enabled: bool = True
    """总开关。"""

    image_search_send_count: int = Field(default=2, ge=1, le=5)
    """一次搜索发几张图。"""

    image_search_max_candidates: int = Field(default=12, ge=1, le=40)
    """最多拿多少条候选结果去下载。"""

    image_search_timeout_seconds: float = Field(default=15, ge=5, le=60)
    """单次搜索/单张下载的超时。"""

    image_search_max_file_mb: float = Field(default=8.0, ge=0.5, le=20)
    """单张图片大小上限（MB），超出的换下一张。"""

    image_search_safe_search: bool = True
    """是否启用搜索引擎的安全过滤。"""

    image_search_verify: bool = True
    """发送前让模型核对图片内容是否真的对得上关键词；明显提高精准度。"""

    image_search_verify_model: str = ""
    """可选：核对单独用另一个（带视觉的）模型；留空复用 claude_model。"""

    image_search_cooldown_seconds: int = Field(default=15, ge=0, le=3600)
    """同一用户两次搜图的冷却。"""

    image_search_daily_limit_per_user: int = Field(default=30, ge=0, le=500)
    """每人每日搜图次数上限。"""

    image_search_daily_limit_total: int = Field(default=100, ge=0, le=2000)
    """全局每日搜图次数上限。"""

    image_search_allowed_groups: list[int] = Field(default_factory=list)
    """留空表示所有群可用（只限制 /img 命令；聊天里的 [IMG:] 跟随主聊天插件的权限）。"""

    image_search_allowed_users: list[int] = Field(default_factory=list)
    """留空表示所有用户可用。"""

    blocked_users: list[int] = Field(default_factory=list)
    """全局屏蔽的 QQ 号；这些人的 /img 会被静默忽略。"""
