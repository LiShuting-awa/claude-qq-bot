"""图片生成插件：用免费 Pollinations 接口把文字描述变成图片并发送到 QQ。"""

from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="图片生成",
    description="通过 /draw 描述生成图片，支持群聊和私聊，带冷却和每日限额。",
    usage="发送 /draw 一只在雨里打伞的猫；别名 /画图、/生成图片。",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

from . import handlers as _handlers  # noqa: E402,F401
