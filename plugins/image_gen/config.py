"""图片生成插件配置。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Config(BaseModel):
    image_gen_enabled: bool = True
    """总开关。"""

    image_gen_api_url: str = "https://image.pollinations.ai/prompt"
    """图片生成服务地址；默认用免费的 Pollinations。"""

    image_gen_model: str = "flux"
    """生成模型名，例如 flux / turbo。"""

    image_gen_width: int = Field(default=1024, ge=256, le=2048)
    image_gen_height: int = Field(default=1024, ge=256, le=2048)

    image_gen_timeout_seconds: float = Field(default=120, ge=10, le=300)
    image_gen_cooldown_seconds: int = Field(default=30, ge=0, le=3600)
    image_gen_daily_limit_per_user: int = Field(default=10, ge=0, le=200)
    image_gen_daily_limit_total: int = Field(default=50, ge=0, le=1000)
    image_gen_max_prompt_chars: int = Field(default=400, ge=10, le=1000)

    image_gen_allowed_groups: list[int] = Field(default_factory=list)
    """留空表示所有群可用。"""

    image_gen_allowed_users: list[int] = Field(default_factory=list)
    """留空表示所有用户可用。"""

    blocked_users: list[int] = Field(default_factory=list)
    """全局屏蔽的 QQ 号；这些人的 /draw 会被静默忽略。"""

    image_gen_safety_suffix: str = "safe for work, no nudity, no gore, no minors"
    image_gen_nologo: bool = True
