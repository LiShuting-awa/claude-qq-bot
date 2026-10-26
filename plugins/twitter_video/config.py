"""推特视频解析插件配置。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Config(BaseModel):
    twitter_enabled: bool = True
    """总开关。"""

    twitter_auto_enabled: bool = True
    """群里直接发 X/Twitter 链接时是否自动解析（不需要 /推文）。"""

    twitter_auto_groups: list[int] = Field(default_factory=list)
    """自动解析生效的群；留空表示所有群。"""

    twitter_send_caption: bool = True
    """发媒体前是否先发一条作者 + 推文摘要。"""

    twitter_send_photos: bool = True
    """纯图推文是否把图片发出来。"""

    twitter_max_photos: int = Field(default=4, ge=1, le=9)
    """单条推文最多发几张图。"""

    twitter_max_mb: int = Field(default=80, ge=1, le=500)
    """视频大小上限（MB）。"""

    twitter_max_duration_seconds: int = Field(default=600, ge=10, le=7200)
    """视频时长上限（秒）。"""

    twitter_max_height: int = Field(default=720, ge=144, le=2160)
    """视频高度上限；720 兼顾清晰度和 QQ 上传速度。"""

    twitter_timeout_seconds: int = Field(default=30, ge=5, le=120)
    """接口请求和下载超时。"""

    twitter_api_bases: list[str] = Field(
        default_factory=lambda: ["https://api.fxtwitter.com", "https://api.vxtwitter.com"]
    )
    """镜像解析 API，按顺序尝试；URL 带 vxtwitter 走 vx 格式，其余按 fx 格式解析。"""

    twitter_use_ytdlp: bool = True
    """镜像 API 解析不到时是否回退 yt-dlp（也能兜底各种怪链接）。"""

    twitter_cookies_file: str = ""
    """可选：Netscape 格式 cookies.txt，仅 yt-dlp 兜底时使用。"""

    twitter_proxy: str = ""
    """可选：解析和下载代理，例如 http://127.0.0.1:7890；留空依次回退 MEDIA_PROXY / PARSEHUB_PROXY。"""

    twitter_cooldown_seconds: int = Field(default=15, ge=0, le=3600)
    twitter_daily_limit_per_user: int = Field(default=20, ge=0, le=100)
    twitter_dedup_seconds: int = Field(default=600, ge=10, le=86400)
    """同一个群同一条推文的去重时间。"""

    twitter_allowed_groups: list[int] = Field(default_factory=list)
    """留空表示所有群可用。"""

    twitter_allowed_users: list[int] = Field(default_factory=list)
    """留空表示所有用户可用。"""

    twitter_notify_errors: bool = True
    """自动解析失败时是否在群里提示；默认提示，避免用户以为没反应。"""
