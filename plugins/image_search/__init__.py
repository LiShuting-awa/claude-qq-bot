"""网图搜索插件：搜互联网上的真实图片并发送到 QQ，支持 /img 命令和聊天里的 [IMG:] 标记。"""

from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="网图搜索",
    description="搜网上的真实图片并发送：/img 命令 + 聊天里的 [IMG:关键词] 标记，双源检索带冷却和限额。",
    usage="发送 /img 柴犬；别名 /找图、/搜图。聊天里 Claude 也会在合适的时机自动用 [IMG:关键词] 发图。",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

from . import handlers as _handlers  # noqa: E402,F401
