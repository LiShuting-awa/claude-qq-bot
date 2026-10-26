"""点歌语音插件：输入歌名，搜到歌转成 QQ 语音消息发回来。"""

from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="点歌语音",
    description="说「来一首 xxx」或发 /点歌 <歌名>，搜到歌就下载并以语音消息发到群里。",
    usage="/点歌 晴天；或直接说「来一首晴天」「放首歌 稻香」。",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

from . import handlers as _handlers  # noqa: E402,F401
