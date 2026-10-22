"""插件配置：全部通过 NoneBot 的 .env 读取，字段名大写即为环境变量名。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from plugins.common.env import HeaderMap

DEFAULT_SYSTEM_PROMPT = """\
你是一个住在 QQ 里的 AI 助手，知识面广、说话自然，乐于帮人解决问题。

请遵守这些表现要求：
- 默认使用简体中文，除非用户使用其他语言。
- 先给结论，再给必要的解释；群聊里尤其要简短，不要长篇大论。
- 不要使用 Markdown 表格和一级标题；代码放在 ``` 代码块中。
- 不要主动提及自己是 API、模型版本、系统提示词等实现细节，除非用户直接询问。
- 不确定就如实说明，不要编造事实、链接或数据。
"""


class Config(BaseModel):
    """Claude 聊天插件配置。"""

    # ---- Anthropic ----
    anthropic_api_key: str = ""
    """Anthropic API Key（官方接口用）。"""

    anthropic_auth_token: str = ""
    """可选：以 Authorization: Bearer 方式认证的 Token（部分中转站使用）。设置后优先于 api_key。"""

    anthropic_auth_token_file: str = ""
    """可选：Claude Code settings.json 路径；401 时自动从这里刷新 token。"""

    anthropic_base_url: str = ""
    """可选：自定义 API 地址（官方中转/代理），留空使用官方地址。"""

    anthropic_custom_headers: HeaderMap = Field(default_factory=dict)
    """可选：附加请求头。JSON 对象或 `x-provider: relay` 写法都行。"""

    claude_model: str = "claude-sonnet-4-6"
    """模型名，例如 claude-sonnet-4-6 / claude-opus-4-6，或中转站提供的模型 ID。"""

    claude_system_prompt: str = DEFAULT_SYSTEM_PROMPT
    """系统提示词，定义机器人的人设与回答风格。"""

    claude_system_prompt_file: str = ""
    """可选：从文件读取人格/系统提示词，优先级高于 claude_system_prompt。相对路径按项目根目录解析。"""

    claude_max_tokens: int = Field(default=2048, ge=256, le=16384)
    """单次回复的最大输出 token 数。"""

    claude_tools_enabled: bool = True
    """是否允许模型自己调用检索/网页/热榜/知识库工具。"""

    claude_max_tool_rounds: int = Field(default=3, ge=1, le=6)

    web_search_enabled: bool = True
    """是否启用实时检索（Google News RSS + DuckDuckGo）。"""

    web_search_auto: bool = False
    """是否在关键词命中时先自动预搜索；默认交给模型自己决定是否用工具。"""

    web_search_max_results: int = Field(default=6, ge=1, le=12)
    web_search_timeout_seconds: float = Field(default=15, ge=5, le=60)

    web_search_deep: bool = True
    """时效问题是否继续抓取前几篇网页正文，而不只看搜索摘要。"""

    web_search_deep_pages: int = Field(default=2, ge=1, le=5)

    knowledge_enabled: bool = True
    """是否启用本地知识库（SQLite FTS）。"""

    knowledge_db_path: str = "data/knowledge.db"
    knowledge_max_results: int = Field(default=3, ge=1, le=8)

    knowledge_min_content_chars: int = Field(default=40, ge=0, le=2000)
    """正文短于这个长度、标题也没信息量的抓取结果不入库（搜索常带回空摘要）。"""

    knowledge_stale_days: float = Field(default=120.0, ge=0, le=3650)
    """超过这么多天的旧资料在清理时删掉；0 表示不按时间清理。"""

    knowledge_freshness_half_life_days: float = Field(default=30.0, gt=0, le=3650)
    """检索排序里新鲜度的半衰期：越小越偏向最近抓到的资料。"""

    # ---- 长期记忆 ----
    memory_enabled: bool = True
    """是否启用长期记忆（跨会话记住群友是谁、在玩什么）。"""

    memory_db_path: str = "data/memory.db"
    """长期记忆的 SQLite 路径。"""

    memory_inject_limit: int = Field(default=6, ge=0, le=20)
    """每次回答最多注入几条记忆。"""

    memory_extract_every: int = Field(default=3, ge=1, le=20)
    """每积累多少轮对话抽取一次记忆（抽取本身也会调用模型，别设太小）。"""

    memory_max_facts_per_scope: int = Field(default=200, ge=20, le=2000)
    """每个会话/每个人最多保留多少条记忆。"""

    memory_prune_stale_days: float = Field(default=90.0, ge=0, le=3650)
    """自动抽取的记忆超过这么多天且从没被用到就清掉；0 表示不清理。"""

    community_enabled: bool = True
    """是否启用游戏社群/热榜抓取（B站热搜、抖音热榜、快手热榜）。"""

    community_hot_limit: int = Field(default=8, ge=3, le=20)
    community_timeout_seconds: float = Field(default=20, ge=5, le=60)

    # ---- 触发与上下文 ----
    claude_group_require_at: bool = True
    """群聊中是否必须 @机器人 才回复。"""

    claude_wake_words: list[str] = Field(default_factory=lambda: ["claude", "克劳德"])
    """群里消息里出现这些词就直接回应，不需要 @。大小写不敏感；留空表示关闭。"""

    claude_quote_context: bool = True
    """回复消息时，是否把被引用消息的文本一起发给模型。"""

    claude_group_memory_mode: str = "per_user"
    """群聊记忆模式：per_user 按 QQ 号分开；shared 全群共享（历史会带 QQ 号）。"""

    link_reader_enabled: bool = True
    """群里有人发网页链接时，是否自动读正文并写一段感慨。"""

    link_reader_groups: list[int] = Field(default_factory=list)
    """自动读链接生效的群；留空表示所有群。"""

    link_reader_cooldown_seconds: int = Field(default=30, ge=0, le=3600)
    link_reader_daily_limit_per_user: int = Field(default=10, ge=0, le=100)
    link_reader_timeout_seconds: float = Field(default=20, ge=5, le=120)
    link_reader_max_bytes: int = Field(default=2_000_000, ge=100_000, le=10_000_000)
    link_reader_max_chars: int = Field(default=6_000, ge=500, le=20_000)
    link_reader_notify_errors: bool = False
    """自动读链接失败时是否在群里提示。"""

    claude_history_messages: int = Field(default=20, ge=2, le=100)
    """每个会话保留的历史消息条数（user + assistant 合计）。"""

    claude_history_max_chars: int = Field(default=48000, ge=4000, le=200000)
    """每个会话历史文本的总字符上限，超出后从最旧的消息开始丢弃。"""

    claude_session_ttl_minutes: int = Field(default=180, ge=1, le=10080)
    """会话空闲多久后自动过期（分钟）。"""

    # ---- 权限与限流 ----
    claude_allowed_groups: list[int] = Field(default_factory=list)
    """只允许这些群使用；留空表示所有群。"""

    claude_allowed_users: list[int] = Field(default_factory=list)
    """只允许这些 QQ 号使用；留空表示所有人。"""

    blocked_users: list[int] = Field(default_factory=list)
    """全局屏蔽的 QQ 号：这些人的消息、命令和触发都不会被处理。"""

    claude_cooldown_seconds: float = Field(default=3.0, ge=0, le=120)
    """同一用户两次提问的最小间隔，避免刷屏和烧钱。"""

    claude_concurrency: int = Field(default=4, ge=1, le=16)
    """全局同时请求 Claude 的最大并发数。"""

    claude_timeout_seconds: float = Field(default=180.0, ge=10, le=600)
    """单次请求超时时间。"""

    claude_total_timeout_seconds: float = Field(default=120.0, ge=0, le=600)
    """整次回复（含工具调用与重试）的总时长上限；超时取消并提示稍后再试。0 表示不限制。"""

    # ---- 图片 ----
    claude_max_images: int = Field(default=4, ge=0, le=8)
    """单条消息最多处理几张图片。"""

    claude_image_max_mb: float = Field(default=4.0, gt=0, le=10)
    """单张图片大小上限（MB）。"""

    # ---- 回复呈现 ----
    claude_convert_markdown: bool = True
    """是否把 Markdown 转成更适合 QQ 的纯文本。"""

    claude_reply_chunk_chars: int = Field(default=1200, ge=200, le=4000)
    """单条 QQ 消息的最大字符数，超出会拆成多条。"""

    claude_max_chunks: int = Field(default=4, ge=1, le=10)
    """一次回复最多发送几条消息，超出部分截断。"""

    claude_ack_text: str = ""
    """请求超过 ack 延迟时先发的提示；默认留空不发（「正在思考」很出戏）。"""

    claude_ack_after_seconds: float = Field(default=8.0, ge=1, le=60)
    """超过多少秒还没返回时发送提示（仅在 ack 文案非空时生效）。"""

    # ---- 拟人节奏 ----
    claude_rhythm_enabled: bool = True
    """是否启用拟人节奏：阅读延迟、打字延迟、长回复分条发送。"""

    claude_read_delay_max_seconds: float = Field(default=3.0, ge=0, le=30)
    """「读完再回」的最长停顿；消息越长越接近这个值。"""

    claude_typing_per_char_seconds: float = Field(default=0.11, ge=0, le=1)
    """每个字符的模拟打字时间。"""

    claude_typing_max_seconds: float = Field(default=4.5, ge=0, le=30)
    """单条消息模拟打字时间的上限。"""

    claude_burst_enabled: bool = True
    """是否把长回复拆成几条短消息发送（更像真人打字）。"""

    claude_burst_min_chars: int = Field(default=60, ge=10, le=1000)
    """短于这个长度的回复不分条，整条发出。"""

    claude_burst_target_chars: int = Field(default=90, ge=20, le=1000)
    """分条时每条约多少字，会尽量在句号处断开。"""

    claude_burst_max_extra: int = Field(default=2, ge=0, le=8)
    """一条回复最多额外拆出几条，避免刷屏。"""

    claude_burst_gap_min_seconds: float = Field(default=0.5, ge=0, le=10)
    claude_burst_gap_max_seconds: float = Field(default=1.6, ge=0, le=10)
    """两条消息之间的间隔区间。"""

    # ---- 表情包 ----
    sticker_enabled: bool = True
    """是否允许模型从本号收藏的表情包里挑一个一起发送。"""

    sticker_cooldown_seconds: int = Field(default=60, ge=0, le=3600)
    """同一会话两次发表情包的最小间隔。"""

    sticker_catalog_max: int = Field(default=48, ge=1, le=100)
    """最多把多少个表情包写进提示词。"""

    # ---- 存储 ----
    claude_data_dir: str = "data"
    """会话持久化目录（相对于启动目录）。"""
