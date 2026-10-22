"""让机器人偶尔主动接话的插件。

默认只在通过 /proactive on 显式开启的群里生效，带免打扰、冷却和每日上限。
"""

from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="主动发言",
    description="根据群聊上下文，偶尔主动插一句话；支持群开关、免打扰、冷却和每日上限。",
    usage="群内发送 /proactive status | on | off | test | id。",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

from . import handlers as _handlers  # noqa: E402,F401
