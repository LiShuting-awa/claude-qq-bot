"""点歌语音插件配置。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Config(BaseModel):
    music_voice_enabled: bool = True
    """总开关。"""

    music_auto_enabled: bool = True
    """群里说「来一首 xxx」这类话时自动点歌，不需要 /点歌。"""

    music_auto_groups: list[int] = Field(default_factory=list)
    """自动点歌生效的群；留空表示所有群。"""

    music_allowed_groups: list[int] = Field(default_factory=list)
    """群白名单；留空表示所有群可用。"""

    music_allowed_users: list[int] = Field(default_factory=list)
    """用户白名单；留空表示所有用户可用。"""

    music_source: str = "netease"
    """曲库来源，对应聚合 API 的 source 参数（netease / tencent / kugou 等）。"""

    music_api_base: str = "https://music-api.gdstudio.xyz/api.php"
    """聚合音乐搜索/取链 API。"""

    music_search_count: int = Field(default=5, ge=1, le=20)
    """每次搜索取几条候选，按匹配度挑一条。"""

    music_bitrate: int = Field(default=320, ge=64, le=999)
    """音质上限（kbps）。"""

    music_max_mb: int = Field(default=15, ge=1, le=100)
    """下载文件大小上限（MB）。"""

    music_max_duration_seconds: int = Field(default=600, ge=30, le=1800)
    """超过这个时长就截断，避免语音消息太长。"""

    music_cooldown_seconds: int = Field(default=20, ge=0, le=3600)
    music_daily_limit_per_user: int = Field(default=20, ge=0, le=200)
    music_dedup_seconds: int = Field(default=180, ge=0, le=86400)
    """同一个群同一首歌的点歌去重时间；0 为不去重。"""

    music_timeout_seconds: int = Field(default=30, ge=5, le=120)
    """接口请求和下载的超时（秒）。"""

    music_cache_dir: str = ""
    """歌曲缓存目录；留空用 data/music_cache。"""

    music_cache_hours: float = Field(default=6.0, ge=0.5, le=168.0)
    """缓存保留时长，过期文件在下次点歌时清掉。"""
