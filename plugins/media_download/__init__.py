"""链接视频下载插件：用 yt-dlp 解析链接，转 MP4 后发回 QQ。"""

from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="视频下载",
    description="发送 /mp4 <链接>，下载链接里的视频并转成 MP4 发到群里。",
    usage="/mp4 https://www.bilibili.com/video/BVxxxx；别名 /视频、/转mp4。",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

from . import handlers as _handlers  # noqa: E402,F401
