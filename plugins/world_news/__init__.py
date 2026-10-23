"""国际新闻：外媒头条聚合、原文详细摘录、纽约时间每天早 8 点群播报。"""

from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="国际新闻",
    description=(
        "外媒头条聚合（纽约每日新闻/BBC/卫报/半岛/纽约时报等），"
        "带原文详细摘录；每天纽约时间早 8 点向群里播报早报。"
    ),
    usage="发 /news 或「今日新闻」；也可以直接问机器人今天的国际新闻（走模型工具调用）。",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

# 导入即注册命令和播报任务；必须放在 __plugin_meta__ 之后
from . import handlers as _handlers  # noqa: E402,F401
