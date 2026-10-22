"""Claude QQ 聊天插件。

在群聊中 @机器人 即可对话；私聊直接发消息。
"""

from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="Claude 聊天",
    description="把 Anthropic Claude 接入 QQ，支持多轮上下文、图片理解和长回复自动拆条。",
    usage="私聊直接对话；群聊 @机器人。发送 /reset 清空上下文，/help 查看帮助。",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

# 导入即注册 matcher；必须放在 __plugin_meta__ 之后
from . import handlers as _handlers  # noqa: E402,F401
