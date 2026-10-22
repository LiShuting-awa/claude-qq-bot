"""链接视频下载转 MP4 插件配置。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Config(BaseModel):
    media_download_enabled: bool = True
    """总开关。"""

    media_auto_enabled: bool = True
    """群里直接发视频链接时，是否自动下载并转 MP4（不需要 /mp4）。"""

    media_auto_groups: list[int] = Field(default_factory=list)
    """自动下载生效的群；留空表示所有群。"""

    media_auto_notify_errors: bool = True
    """自动下载失败时是否在群里提示；默认提示，避免用户以为没反应。"""

    media_auto_dedup_seconds: int = Field(default=600, ge=10, le=86400)
    """同一个群同一链接的去重时间。"""

    media_max_mb: int = Field(default=80, ge=1, le=500)
    """下载文件大小上限（MB）。"""

    media_max_duration_seconds: int = Field(default=900, ge=10, le=7200)
    """视频时长上限（秒）。"""

    media_cooldown_seconds: int = Field(default=30, ge=0, le=3600)
    media_daily_limit_per_user: int = Field(default=10, ge=0, le=100)
    media_socket_timeout_seconds: int = Field(default=30, ge=5, le=120)

    media_allowed_groups: list[int] = Field(default_factory=list)
    """留空表示所有群可用。"""

    media_allowed_users: list[int] = Field(default_factory=list)
    """留空表示所有用户可用。"""

    blocked_users: list[int] = Field(default_factory=list)
    """全局屏蔽的 QQ 号。"""

    media_cookies_file: str = ""
    """可选：Netscape 格式 cookies.txt，供需要登录/年龄验证的站点使用。"""

    media_proxy: str = ""
    """可选：下载代理，例如 http://127.0.0.1:7890。"""

    bilibili_card_enabled: bool = True
    """B 站链接是否先发一张信息卡（封面/标题/UP 主/数据）。"""

    bilibili_native_auto: bool = True
    """true：B 站走本地 Jina 链路；false：交给通用链接解析插件（当前 parser 已禁用 bilibili，不建议关闭）。"""

    bilibili_max_height: int = Field(default=480, ge=360, le=1080)
    """B 站视频下载高度上限；480 兼顾速度和 QQ 上传。"""

    bilibili_jina_base: str = "https://r.jina.ai/"
    """B 站接口被 412 时走的 Reader 代理。"""
