"""说话学习（speech_learn）：从群聊记录里提炼大家的说话方式，注入回话风格。"""

from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="说话学习",
    description="记录群聊，用 /learn_speech 提炼群友的说话方式，让回话更像真人。",
    usage="/learn_speech 分析最近的群聊记录（群主/管理员）；/learn_speech off 停止参考。",
)

from . import handlers as _handlers  # noqa: E402,F401
