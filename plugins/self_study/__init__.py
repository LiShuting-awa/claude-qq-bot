"""每日自学：每天自动联网充电，热榜 + 群里聊到的话题进知识库。"""

from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="每日自学",
    description="每天定时联网：收热榜、按群里最近聊的话题查资料，存进知识库。",
    usage="自动运行，无需命令；用 SELF_STUDY_ENABLED / SELF_STUDY_HOUR 配置。",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

# 导入即注册启动任务；必须放在 __plugin_meta__ 之后
from . import study as _study  # noqa: E402,F401
