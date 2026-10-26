"""推特/X 链接解析插件：视频转 MP4、图集原图发回 QQ。"""

from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="推特视频",
    description="群里发 X/Twitter 链接自动解析：视频转 MP4 发回，纯图推文发原图；镜像 API 优先，yt-dlp 兜底。",
    usage="直接发 https://x.com/用户/status/123 即可；手动：/推文 <链接>，别名 /推特、/tweet。",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

from . import handlers as _handlers  # noqa: E402,F401
