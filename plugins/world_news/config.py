"""国际新闻插件配置。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Config(BaseModel):
    world_news_enabled: bool = True
    """总开关：外媒头条聚合 + 原文摘录。"""

    world_news_allowed_users: list[int] = Field(default_factory=list)
    """允许查新闻的 QQ 号；空 = 不限制。"""

    world_news_allowed_groups: list[int] = Field(default_factory=list)
    """允许查新闻的群；空 = 不限制。"""

    world_news_cooldown_seconds: int = Field(default=600, ge=0, le=86400)
    """同一个群两次查新闻的最小间隔（抓外媒比较费时）。"""

    world_news_headline_limit: int = Field(default=10, ge=3, le=20)
    """一次汇总列多少条外媒头条。"""

    world_news_detail_count: int = Field(default=3, ge=0, le=6)
    """其中几条要抓原文做详细摘录。"""

    world_news_excerpt_chars: int = Field(default=1000, ge=200, le=4000)
    """每篇原文摘录多少字。"""

    world_news_hours: int = Field(default=36, ge=1, le=168)
    """只保留最近多少小时内的新闻。"""

    world_news_fetch_timeout: float = Field(default=12.0, gt=0, le=60)
    """单个源的超时秒数。"""

    world_news_feeds: list[str] = Field(default_factory=list)
    """额外的 RSS 源地址，追加到内置外媒列表后面。"""

    world_news_broadcast_enabled: bool = True
    """每天纽约时间早上到点向群里播报外媒早报。"""

    world_news_broadcast_hour_ny: int = Field(default=8, ge=0, le=23)
    """几点播报（纽约当地时间，自动跟随冬夏令时）。"""

    world_news_broadcast_groups: list[int] = Field(default_factory=list)
    """播报目标群号；空 = 不播报。"""
