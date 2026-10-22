# Claude QQ Bot

一个用 **Python + NoneBot2 + OneBot 11 + Anthropic Claude** 搭起来的 QQ 机器人：私聊直接聊天，群聊 @ 一下就能用，支持多轮上下文、图片理解、长回复自动拆条。

> 默认模型：`claude-sonnet-4-6`（可在 `.env` 里换成其他兼容模型）。
> 可通过 Anthropic API 或兼容服务连接模型；请根据所选服务配置凭据、模型名和接口地址，并确认服务支持所需的图片能力。

---

## 功能

- **私聊 / 群聊**：私聊直接发消息；群聊 @机器人 或回复机器人的消息即可触发。
- **多轮上下文**：私聊按用户隔离；群聊默认按 **QQ 号分开记忆**，不会把 A 说过的话算到 B 头上。
- **长期记忆**：跨会话记住“这个人是谁、在玩什么、说过什么”，下次接着聊；用户可用 `/forget` 清掉。
- **拟人节奏**：回复前有阅读停顿、按字数模拟打字时间、长回复自动分几条短消息发出，不是一口气吐一大段。
- **实时检索**：遇到“最新/最近/2026”等时效问题会自动联网查；也可以 `/search 关键词`。
- **游戏社群/热榜**：`/game 战争雷霆` 查近期资讯和社区内容；`/hot` 抓 B站/抖音/快手热榜。
- **自主工具调用**：模型会自己判断要不要搜、要不要打开网页、要不要查本地知识库/热榜/游戏情报。
- **图片理解**：把 QQ 图片下载后以 base64 发给模型，支持 JPEG / PNG / GIF / WebP。
- **图片自动识别/解题**：主动发言开启的群里，发图后自动识别；是题目就复述、解答、验算，其他图片按附言提供服务。
- **表情包**：从本号收藏里挑图，模型可按语境在文字后配一个表情包，也可以单独发。
- **图片生成**：发送 `/draw 描述`，用免费文生图服务生成图片并发回 QQ。
- **视频下载**：群里直接发视频链接就自动下载并转 MP4；B 站链接会先发一张信息卡（封面/标题/UP 主/数据），再发视频。
- **链接分享解析**：抖音、快手、微博、小红书、贴吧、知乎、豆瓣、头条、微信视频号、酷安、皮皮虾等国内平台分享链接自动解析成视频/图集/图文。
- **入群彩蛋**：被拉进新群时，第一句固定说“听说你们都说我死了?”
- **网页阅读**：群里发普通网页链接，自动抓正文，用 Claude 的口吻写一段感慨/点评。
- **引用消息**：回复某条消息时，会把被引用的文字一起作为上下文。
- **回复整理**：自动去掉 Markdown 标记、拆分超长消息，代码块保持完整。
- **防刷屏**：用户冷却、全局并发限制、群/用户白名单、历史裁剪。
- **中文错误提示**：Key 失效、模型不存在、限流、超时都会给出可读的提示。
- 命令：`/reset`、`/forget`、`/help`、`/stats`、`/model`、`/ping`
- 主动发言：像群友一样接话、冷场时主动起话，可 @ 最近发过言的人；支持免打扰、冷却、每日上限和 `/proactive` 管理

---

## 目录结构

```text
qqbot/
├─ bot.py                    # 入口：初始化 NoneBot、注册 OneBot 适配器、加载插件
├─ check_claude.py           # 不依赖 QQ，单独测试 Anthropic Key/模型
├─ persona.md                # 当前人格：Claude（漂洋过海的高级人才）
├─ qqbot_stickers.py         # 本号表情包库（读取/选择/发送）
├─ qqbot_filters.py          # 全局 QQ 屏蔽名单
├─ pyproject.toml            # 项目元数据 + NoneBot 插件目录配置
├─ requirements.txt          # 运行依赖
├─ requirements-dev.txt      # 测试依赖
├─ .env                      # 你的配置（含 API Key，不要提交到 git）
├─ .env.example              # 配置模板
├─ start.ps1 / start.bat     # Windows 一键启动
├─ plugins/
│  ├─ common/
│  │  ├─ access.py          # 共享的用户/群组访问控制
│  │  ├─ media.py           # 图片媒体类型识别
│  │  ├─ network.py         # 公网主机检查
│  │  └─ text.py            # 按边界拆分长文本
│  ├─ claude_chat/
│  │  ├─ __init__.py         # 插件元数据
│  │  ├─ config.py           # 所有配置项
│  │  ├─ handlers.py         # 触发规则、图片下载、消息处理
│  │  ├─ claude.py           # Anthropic 客户端、重试、错误翻译
│  │  ├─ session.py          # 会话历史 + JSON 持久化
│  │  ├─ textquery.py        # 中文查询切词（FTS5 trigram 的必需前置）
│  │  ├─ knowledge.py        # 本地知识库：写入、检索、去重、新鲜度排序
│  │  ├─ memory.py           # 长期记忆：记住群友是谁 + 自动抽取
│  │  ├─ rhythm.py           # 拟人节奏：阅读/打字延迟、长回复分条
│  │  └─ formatting.py       # Markdown 清理、长消息拆分
│  ├─ proactive_chat/
│  │  ├─ __init__.py         # 主动发言插件元数据
│  │  ├─ config.py           # 主动发言配置
│  │  ├─ activity.py         # 群聊缓冲 + 免打扰时间
│  │  ├─ formatting.py       # LaTeX / Markdown 清理、长答案拆分
│  │  ├─ llm.py              # 接话判断 + 图片识图/解题
│  │  └─ handlers.py         # 定时器、图片下载、频率限制、/proactive 命令
│  ├─ image_gen/
│  │  ├─ __init__.py         # 文生图插件元数据
│  │  ├─ config.py           # 生成服务、尺寸、限额
│  │  └─ handlers.py         # /draw 命令、生成、发送
│  └─ media_download/
│     ├─ __init__.py         # 链接视频下载插件元数据
│     ├─ config.py           # 大小/时长/冷却/cookies
│     └─ handlers.py         # yt-dlp 下载、ffmpeg 转 MP4、发送
├─ seeds/                    # 手工整理的资料，用 tools/kb_seed.py 投喂进知识库
│  ├─ war-thunder/           # 战争雷霆：基础机制、群聊黑话对照
│  ├─ tarkov/                # 逃离塔科夫：核心机制、弹药与护甲
│  ├─ deepseek/              # DeepSeek 公司与模型线
│  └─ net/                   # 网络黑话 / 梗对照
├─ tools/
│  └─ kb_seed.py             # 知识库投喂 / 检索自检 / 清理工具（不经 NoneBot）
├─ data/
│  ├─ sessions.json          # 对话历史
│  ├─ knowledge.db           # 本地知识库（SQLite FTS5）
│  ├─ memory.db              # 长期记忆（SQLite FTS5）
│  └─ stickers.json          # 本号表情包 URL + 标签
└─ tests/                    # 单元测试 + 消息处理集成测试
```

---

## 快速开始

### 1. 环境

- Windows 10/11（macOS / Linux 同理，改一下启动脚本即可）
- Python **3.10+**（本项目在 3.13 上测试通过）
- 一个 QQ 账号（建议用小号，见文末“风控”）
- Anthropic API Key：[console.anthropic.com](https://console.anthropic.com/settings/keys)

### 2. 安装依赖

在 `qqbot` 目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

或者直接运行 `start.ps1`，它会自动建虚拟环境、装依赖。

### 3. 填写配置

打开 `.env`，至少填这一行：

```dotenv
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
```

其他常用项：

```dotenv
# 模型
CLAUDE_MODEL=claude-sonnet-4-6

# 群聊必须 @ 才回复（强烈建议保持 true）
CLAUDE_GROUP_REQUIRE_AT=true

# 只允许指定群 / 用户，留空为不限制
CLAUDE_ALLOWED_GROUPS=[]
CLAUDE_ALLOWED_USERS=[]

# 单次回复最大 token
CLAUDE_MAX_TOKENS=2048
```

> `.env` 里有 API Key，**不要**把文件发给别人或提交到 Git。项目已经把它写进 `.gitignore`。

### 4. 配置 NapCat

机器人通过 **OneBot 11 协议**连接 QQ，需要先跑一个 [NapCat](https://github.com/NapNeko/NapCatQQ)。

1. 从 [NapCat Releases](https://github.com/NapNeko/NapCatQQ/releases) 下载 Windows 版并解压/安装。
2. 启动 NapCat，扫码登录 QQ。
3. 打开 WebUI：`http://127.0.0.1:6099/webui`。登录 token 在 NapCat 启动日志里，形如 `WebUi User Panel Url: http://127.0.0.1:6099/webui?token=xxxxx`。
4. 首次登录后按提示修改 WebUI 密码。
5. 进入 **网络配置** → **新建** → 选择 **WebSocket 服务器**（正向 WS）：
   - 名称：随便，例如 `qqbot`
   - Host：`127.0.0.1`
   - 端口：`3001`
   - Token：`qqbot-local-token`（必须和 `.env` 的 `ONEBOT_ACCESS_TOKEN` 一致）
   - 消息格式：`array`
   - 勾选 **保存时启用**
6. 保存后确认该配置处于“启用”状态。

`.env` 里对应的两行：

```dotenv
ONEBOT_WS_URLS=["ws://127.0.0.1:3001"]
ONEBOT_ACCESS_TOKEN=qqbot-local-token
```

> NapCat 和机器人在同一台电脑时用 `127.0.0.1` 即可。如果分开部署，把 `127.0.0.1` 换成 NapCat 机器的局域网 IP，并注意防火墙和 Token 安全。

### 5. 启动机器人

先单独验证 API Key（不需要 NapCat）：

```powershell
.\.venv\Scripts\python.exe check_claude.py
```

看到 `✅ Claude 回复：...` 说明 Key 和模型都没有问题。

再启动机器人：

```powershell
.\start.ps1
```

如果 PowerShell 提示“禁止运行脚本”，可以直接双击 `start.bat`，或执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

或者：

```powershell
.\.venv\Scripts\python.exe bot.py
```

看到类似日志就成功了：

```text
[SUCCESS] nonebot | Succeeded to load plugin "claude_chat"
[SUCCESS] nonebot | Running NoneBot...
[SUCCESS] nonebot | Loaded adapters: OneBot V11
```

然后在 QQ 私聊机器人发一句“你好”，或者在群里 @它 试试。

---

## 使用方式

| 场景 | 怎么触发 |
| --- | --- |
| 私聊 | 直接发消息 |
| 群聊 | @机器人，或回复机器人的一条消息 |
| 图片 | 私聊/群聊里发图，@机器人 并附上问题 |
| 清空上下文 | `/reset`（别名 `/重置对话`、`/新对话`、`/清空对话`）——只清上下文，长期记忆还在 |
| 忘掉长期记忆 | `/forget`（别名 `/忘掉我`、`/清除记忆`、`/别记得我`） |
| 帮助 | `/help` |
| 用量 | `/stats`（本会话累计 token） |
| 模型 | `/model` |
| 连通性 | `/ping` |
| 主动发言 | 群内 `/proactive status \| on \| off \| test \| id` |
| 表情包 | `/sticker`（随机发一个本号收藏的表情） |
| 图片生成 | `/draw 一只在雨里打伞的猫`（别名 `/画图`、`/生成图片`） |
| 视频下载 | 群里直接发视频链接即自动处理；也可用 `/mp4 <链接>` |
| 链接解析 | 直接发抖音/快手/微博/小红书/YouTube/TikTok/X/AcFun/NGA 链接 |
| 网页阅读 | 群里直接发网页链接即自动读；也可用 `/read <链接>` |
| 联网检索 | `/search 最近两年 DeepSeek 发生了什么` |
| 深度研究 | `/research 战争雷霆 2026 最新更新` |
| 本地知识库 | `/kb 战争雷霆` |
| 游戏社群 | `/game 战争雷霆`（别名 `/游戏`、`/游戏圈`） |
| 热榜/热梗 | `/hot`（别名 `/热榜`、`/热梗`） |

群聊上下文默认按 QQ 号隔离；可通过 `CLAUDE_GROUP_MEMORY_MODE=shared` 改为全群共享。私聊按用户隔离。历史里会带上发言人昵称，方便模型区分。

---

## 当前人格：Claude

机器人当前使用 [`persona.md`](persona.md) 里的「Claude」：

- 美国人，早年做工程/产品/咨询，漂洋过海来中国做独立高级顾问；
- 开朗、直接、爱接梗，愿意帮忙，什么活都能接：技术、产品、方案、文案、查资料、看图、陪聊、整活；
- 说话像 Claude：正经问题先给判断再给理由、词往平里走、不确定就说不确定、错了就认、不表演热情、该不同意就不同意；闲聊就好好闲聊；
- 聪明落在内容上：先想后答、答完顺手多给一步、有观点、不确定就承诺去查（用工具查完再回）；
- 带一点傲气（轻微）：难活接得轻、不轻易被唬住、敢下判断、看不上糙活；但**只改语气不改事实**，也不改话的长短，不贬低人、不吹履历、不懂也不装懂；
- 标准高，遇到敷衍、甩锅、吹牛、爹味、无理要求时会冷下来，话变短（低频，一场对话最多一两次），但不无理由拒绝；
- `persona.md` 里有专门的「别僵硬」一节管最容易翻车的几件事：问候要接住、别审问（含糊问题先按最可能的意思答）、别拿命令句收尾、自我介绍像聊天不像背简历、别套模板句式、说完就停等对方接话（不连问、不预答、不自顾自接着说）；闲聊里修饰词能省就省，说大白话；
- 不是客服，不端着，也不拿“美国专家”身份压人；
- **核心对话原则优先于人格**：事实与连贯性 > 回应当前意图 > 已做出的承诺/决定 > 角色设定 > 表达风格；不为了冷淡或金句改口、曲解或编造；
- 不按国籍、地域或 IP 贬低任何人；被要求这样做时会冷淡拒绝。

除了性格本身，`persona.md` 还管三件“像不像活人”的事：

- **说话的样子**：长短要有变化（上一轮说三句，这一轮可能只回“嗯。”）、按条发而不是写成小作文、
  不是每句都反问、不主动报功能、不说“有什么可以帮你的吗 / 希望能帮到你 / 总结一下”这类助手腔；
- **时间和状态**：提示词里会带上当前时间和时段（凌晨/早上/中午/下午/晚上/深夜），
  深夜更懒、话更少，白天愿意多聊；但不会每轮都把时间说出来；
- **长期记忆**：见下一节。提示词里若出现「你记得的事」，他要当成自己本来就知道的事自然使用，
  不许一条条念出来、不许说“根据我的记忆”、更不许编造没记着的。

人格文件通过 `.env` 的 `CLAUDE_SYSTEM_PROMPT_FILE=persona.md` 加载。修改 `persona.md` 后，**下一条消息就会生效**（按文件 mtime 自动重载），不需要重启。

---

## 拟人节奏

`plugins/claude_chat/rhythm.py` 让回复的**形状**像人打字，而不是像接口返回：

1. **阅读延迟**：收到消息后先停一下再回。消息越长，停顿越久（上限 `CLAUDE_READ_DELAY_MAX_SECONDS`）。
2. **打字延迟**：每条回复按字数模拟打字时间（`CLAUDE_TYPING_PER_CHAR_SECONDS`，上限 `CLAUDE_TYPING_MAX_SECONDS`）。
3. **分条发送**：超过 `CLAUDE_BURST_MIN_CHARS` 的回复会按句号切开、每条约 `CLAUDE_BURST_TARGET_CHARS` 字，
   分几条发出去，中间还有 `CLAUDE_BURST_GAP_MIN_SECONDS`～`MAX` 的间隔。

分条时会避开两类内容：**代码块**（永远不切）和**列表/引用行**（切了会散架）。
一条回复最多额外拆 `CLAUDE_BURST_MAX_EXTRA` 条，防刷屏。

全部关掉：

```dotenv
CLAUDE_RHYTHM_ENABLED=false
```

> 这些延迟是真的 `asyncio.sleep`，会占用一次请求的处理时间，但**不占并发槽**（槽在等待前就释放了）。
> 如果觉得回得太慢，先调小 `CLAUDE_READ_DELAY_MAX_SECONDS` 和 `CLAUDE_TYPING_MAX_SECONDS`。

---

## QQ 身份与记忆

群聊里每个人都有自己的 QQ 号。默认 `CLAUDE_GROUP_MEMORY_MODE=per_user`：

- 每个群友的对话记忆单独存，键是 `group:<群号>:user:<QQ号>`；
- 历史里每条用户消息都带 `[昵称 | QQ号]`；
- 系统提示词会写明“当前对你说话的是谁（昵称 + QQ）”，并明确不要混淆不同群友；
- 引用消息也会带上发送者 QQ；
- `/reset`、`/stats` 只作用于当前这位群友。

如果想让整个群共用一段记忆，把它改成 `shared`：

```dotenv
CLAUDE_GROUP_MEMORY_MODE=shared
```

共享模式下历史仍然每条都带 QQ 号，模型会被告知注意区分发言人。

---

## 长期记忆

上面那节讲的是**上下文**（20 条消息的滑动窗口，过期就忘）。长期记忆是另一套东西：
`plugins/claude_chat/memory.py` 把“这个人是谁、在玩什么、说过什么”写进 `data/memory.db`，
跨会话、跨天都还在。

### 怎么工作

1. 每 `MEMORY_EXTRACT_EVERY` 轮对话，后台异步调一次模型，从最近这段对话里抽
   “值得记住的事实”，最多记 `MEMORY_MAX_FACTS_PER_SCOPE` 条；
2. 下次这个人说话时，按话题从库里捞出最多 `MEMORY_INJECT_LIMIT` 条，
   以「你记得的事」的形式塞进系统提示词；
3. 抽出来的事实里，**身份类（叫什么）永远优先返回**，不然会显得不记得人；
4. 明确禁止记录敏感信息：身份证号、银行卡、手机号、住址、密码这类内容会在入库前被丢掉。

### 存储范围

| 场景 | 存到哪 |
| --- | --- |
| 群里学到的 | 只留在那个群（`group:<群号>`），不会带到别的群 |
| 私聊学到的 | 跟着这个人走，跨群可用 |

这样安排是因为：群里的梗和话题出了群没有意义，但“这个人是谁”应该跟着人走。

### 用户能清掉

- `/forget`（别名 `/忘掉我`、`/清除记忆`、`/别记得我`）：删掉这个人的全部长期记忆，并重置上下文。
- `/reset`：**只清上下文，不清长期记忆**——回复里会明说这一点，免得用户以为已经忘干净了。

自动抽取的记忆如果超过 `MEMORY_PRUNE_STALE_DAYS` 天而且从没被检索命中过，
启动时会被清掉；手动写进去的（`source='manual'`）永远不自动删。

彻底关掉：

```dotenv
MEMORY_ENABLED=false
```

---

## 屏蔽用户

在 `.env` 里把 QQ 号加进全局屏蔽名单：

```dotenv
BLOCKED_USERS=[]
```

被屏蔽的人：

- 不会触发正常对话、@ 回复、命令；
- 不会被主动发言/图片识别记录；
- 不能使用 `/draw`、`/sticker`、`/proactive`；
- 不会进入任何新会话。

> NoneBot 仍会把收到的原始事件写进日志，但不会做任何处理。需要连日志都不显示，可以调高日志级别或再加适配层过滤。

---

## 主动发言

总开关默认是开的（`PROACTIVE_ENABLED=true`），但**不会对任何群主动说话**，必须先显式开启目标群。

在目标群里发送（群主/管理员权限）：

```text
/proactive on
```

然后机器人会像群里的真人成员一样参与聊天：

1. 每条群消息先记入内存缓冲（不落盘）；
2. 等 1 秒，如果群里没有新消息接力，才考虑接话——有人连续说话时它会先听着；
3. 不接 @ / 回复它的消息（那些交给 `claude_chat` 正常处理），避免双回复；
4. 以 100% 概率让模型判断要不要接；模型可以只回 `SKIP`；
5. 接话时输出 1–2 句（最多 180 字），不会每句都回；同一群两次主动接话至少间隔 10 秒；
6. 群里安静 10 分钟后，有 50% 概率主动起个话头或追问之前的事；
7. 可以 @ 最近发过言的群友，一次最多一个；不会 @ 全体，也不会乱 @；
8. 本群两次主动发言冷却 1 分钟，每天最多 20 条，全局最多 60 条；
9. 23:00–08:00 免打扰；
10. 消息里出现 `Claude` / `克劳德` 时走快速通道：0.6 秒防抖 + 模型，通常 2–3 秒内出现；模型判断不适合也会回一句“在。说事。”。

其他命令：

| 命令 | 作用 |
| --- | --- |
| `/proactive status` | 查看本群状态、模式、最近消息数、今日用量、冷却 |
| `/proactive on` / `off` | 开启/关闭本群（群主/管理员） |
| `/proactive test` | 立即试发一条，跳过概率和冷却（群主/管理员） |
| `/proactive id` | 查看本群群号 |

也可以把固定群号写进 `.env`：

```dotenv
PROACTIVE_GROUPS=[123456789, 987654321]
```

主动发言使用同一个 [`persona.md`](persona.md)，所以是 Claude 的口气；聊到技术或游戏时也会主动凑上来。群聊缓冲只在内存，重启即清空；只有“开启了哪些群”会写入 `data/proactive.json`。

常用配置：

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `PROACTIVE_ENABLED` | `true` | 总开关 |
| `PROACTIVE_MODE` | `conversation` | `conversation` 接话/起话；`random` 旧随机模式 |
| `PROACTIVE_GROUPS` | `[]` | 固定开启的群 |
| `PROACTIVE_REPLY_DELAY_SECONDS` | `1` | 有人说话后等几秒再判断 |
| `PROACTIVE_GENERATE_TIMEOUT_SECONDS` | `25` | 单次接话模型超时 |
| `PROACTIVE_REPLY_PROBABILITY` | `1.0` | 接话判断概率 |
| `PROACTIVE_MIN_REPLY_INTERVAL_SECONDS` | `10` | 同群两次接话最小间隔 |
| `PROACTIVE_INITIATIVE_AFTER_MINUTES` | `10` | 安静多久后主动起话 |
| `PROACTIVE_INITIATIVE_PROBABILITY` | `0.5` | 起话概率 |
| `PROACTIVE_GROUP_COOLDOWN_MINUTES` | `1` | 同群主动发言冷却 |
| `PROACTIVE_DAILY_LIMIT_PER_GROUP` | `20` | 每群每日上限 |
| `PROACTIVE_DAILY_LIMIT_TOTAL` | `60` | 全局每日上限 |
| `PROACTIVE_MAX_CHARS` | `180` | 单条主动发言字数 |
| `PROACTIVE_ALLOW_AT` | `true` | 允许 @ 最近发过言的群友（最多一个） |
| `PROACTIVE_QUIET_HOURS` | `23:00-08:00` | 免打扰时段 |
| `PROACTIVE_PERSONA_FILE` | `persona.md` | 人格文件 |

> 只有 `/proactive on` 开启的群才会被记录最近消息；记录只存在内存、自动过期，不会落盘。关闭群后不再记录。如果不想让插件记录某群，直接用 `/proactive off` 关闭即可。

> “自主”是行为上的主动和有自己的判断，不是宣称有真人意识；被直接问身份时仍会承认是 AI。@ 只能点最近发过言的人，且不能 @ 全体。踢人、禁言等群管理动作没有自动加，需要你在 QQ 里把机器人设为群管理员并明确授权。

### 图片识别 / 解题

在已开启的群里，**直接发图片，不用 @**：

1. 等 4 秒，避免连续发图重复解答；
2. 下载图片（最多 4 张，单张 5MB）并转成 base64；
3. 模型先识别、复述题目；
4. 如果是题目/作业：给完整步骤、最终答案并验算；
5. 如果是其他图片：按附言翻译、总结、读表格、分析等；
6. 如果只是表情包/无信息图：输出 `SKIP`，不刷屏；
7. 答案回复到那张图片上，太长会自动拆成多条；
8. 同群两次图片解答间隔 30 秒，每天最多 20 张。

@ 机器人的图片仍然走普通对话逻辑，不会重复解答；**回复一张图片并 @ 机器人**时，会把被引用的图片一起识别。当前中转模型已验证支持图片输入；看不清的内容模型会说明，不会硬编。

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `PROACTIVE_IMAGE_ENABLED` | `true` | 是否自动识图/解题 |
| `PROACTIVE_IMAGE_DELAY_SECONDS` | `4` | 收到图片后等待秒数 |
| `PROACTIVE_IMAGE_COOLDOWN_SECONDS` | `30` | 同群图片解答冷却 |
| `PROACTIVE_IMAGE_DAILY_LIMIT_PER_GROUP` | `20` | 每群每天最多解答几张 |
| `PROACTIVE_IMAGE_MAX_MB` | `5` | 单张图片大小上限 |
| `PROACTIVE_IMAGE_MAX_COUNT` | `4` | 单条消息最多几张 |
| `PROACTIVE_IMAGE_MAX_CHARS` | `6000` | 答案总字数上限 |
| `PROACTIVE_IMAGE_CHUNK_CHARS` | `1200` | 每条 QQ 消息字数 |
| `PROACTIVE_IMAGE_MAX_TOKENS` | `1500` | 图片回答最大输出 token |

> 图片解题是模型输出，重要作业/考试答案建议自己再核对一遍。

---

## 表情包

机器人会从当前登录 QQ 的收藏表情里抓取表情包（通过 NapCat 的 `fetch_custom_face`），保存到 `data/stickers.json`，并用视觉模型给每个表情打上“情绪/适用场景”标签。

- 模型在回复最后单独写 `[STICKER:编号]`，Bot 就会在文字后补一个表情包；
- 如果模型只写了标记，就只发表情包，不发文字；
- 不是每条都配，同一会话（群/私聊）两次表情包至少间隔 60 秒；
- 主动发言和正常 @ 对话都支持；
- `/sticker` 可以随机发一个，用来测试；
- 收藏表情更新后，需要重新抓取并标注，直接告诉我即可。

常用配置：

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `STICKER_ENABLED` | `true` | 是否允许模型配表情包 |
| `STICKER_COOLDOWN_SECONDS` | `60` | 同一会话两次表情包最小间隔 |
| `STICKER_CATALOG_MAX` | `48` | 提示词里最多展示多少个表情 |

> 表情包 URL 属于本号收藏资源，`data/stickers.json` 只在本地使用，已加入 `.gitignore` 的 `data/` 目录。

---

## 图片生成

在群里或私聊发送：

```text
/draw 一只在雨里打伞的猫，赛博朋克风格
```

别名：`/画图`、`/生成图片`、`/画一张`。

- 使用免费的 Pollinations 文生图接口，**不需要额外 API Key**；
- 默认 1024×1024，生成约 5–15 秒，先回“正在画”，完成后把图片回复到原消息；
- 免费服务可能带 `pollinations.ai` 水印；
- 有基础的安全过滤（色情、裸露、血腥、未成年人等关键词），并附加安全后缀；
- 同一用户 30 秒冷却，每天最多 10 张；全局每天 50 张；
- 默认所有群/用户可用，可用白名单限制；
- 提示词会发送给 Pollinations 第三方服务，不要画敏感内容。

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `IMAGE_GEN_ENABLED` | `true` | 总开关 |
| `IMAGE_GEN_API_URL` | Pollinations | 生成服务地址 |
| `IMAGE_GEN_MODEL` | `flux` | 模型名 |
| `IMAGE_GEN_WIDTH` / `HEIGHT` | `1024` | 图片尺寸 |
| `IMAGE_GEN_COOLDOWN_SECONDS` | `30` | 同一用户冷却 |
| `IMAGE_GEN_DAILY_LIMIT_PER_USER` | `10` | 每人每日上限 |
| `IMAGE_GEN_DAILY_LIMIT_TOTAL` | `50` | 全局每日上限 |
| `IMAGE_GEN_MAX_PROMPT_CHARS` | `400` | 提示词长度上限 |
| `IMAGE_GEN_ALLOWED_GROUPS` | `[]` | 群白名单，空为全部 |
| `IMAGE_GEN_ALLOWED_USERS` | `[]` | 用户白名单，空为全部 |

---

## 视频下载

**直接在群里或私聊发视频链接就会自动处理，不需要打命令；带不带 @ 都行。** 例如：

```text
https://www.bilibili.com/video/BVxxxx
```

会自动识别、下载、转 MP4，然后把视频发回群里。

也支持手动命令（私聊/群聊都行）：

```text
/mp4 https://www.bilibili.com/video/BVxxxx
```

别名：`/视频`、`/转mp4`、`/下载视频`。

社交平台分享链接优先由 `nonebot-plugin-parsehub` 解析（抖音、快手、微博、小红书、贴吧、知乎、豆瓣、头条、微信、酷安、皮皮虾、最右、小黑盒、Bangumi 等）；B 站、直链视频和 `/mp4` 手动命令仍走本地下载链路。自动模式会先回“收到视频链接”，下载失败也会提示；如果不想被提示，把 `MEDIA_AUTO_NOTIFY_ERRORS` 改成 `false`。

- 使用 **yt-dlp** 解析链接，**ffmpeg** 合并/转码成 MP4（需要系统 PATH 里有 ffmpeg，本机已安装）；
- **B 站链接**会先用 Jina Reader 取视频信息，发一张信息卡：封面、标题、UP 主、观看/点赞/投币/收藏/转发/弹幕；然后再发 480P 视频；
- B 站接口对本机返回 412 时，信息卡和视频流都走 Jina Reader，不需要额外 API Key；Jina 不可用时会回退 yt-dlp；
- 默认下载 **480P**，兼顾速度和 QQ 上传大小；需要更高画质可以改 `BILIBILI_MAX_HEIGHT`；
- 默认最大 **80MB / 15 分钟**，超过会拒绝；
- 同一用户 30 秒冷却，每天最多 10 个；
- 同一个群同一链接 10 分钟内只下一次；
- 文件只落到临时目录，发完立即删除；
- 只允许 http/https，并拒绝 localhost/内网地址；
- 需要登录/年龄验证的站点，可以在 `.env` 填 `MEDIA_COOKIES_FILE`（Netscape 格式 cookies.txt）；
- 直播、付费、DRM 内容不支持；下载版权内容请确保你有权保存。

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `MEDIA_DOWNLOAD_ENABLED` | `true` | 总开关 |
| `MEDIA_AUTO_ENABLED` | `true` | 群里发链接自动下载 |
| `MEDIA_AUTO_GROUPS` | `[]` | 自动下载生效的群，空为全部 |
| `MEDIA_AUTO_NOTIFY_ERRORS` | `true` | 自动下载失败是否提示 |
| `MEDIA_AUTO_DEDUP_SECONDS` | `600` | 同群同链接去重时间 |
| `MEDIA_MAX_MB` | `80` | 文件大小上限 |
| `MEDIA_MAX_DURATION_SECONDS` | `900` | 视频时长上限 |
| `MEDIA_COOLDOWN_SECONDS` | `30` | 同一用户冷却 |
| `MEDIA_DAILY_LIMIT_PER_USER` | `10` | 每人每日上限 |
| `MEDIA_ALLOWED_GROUPS` | `[]` | 群白名单 |
| `MEDIA_ALLOWED_USERS` | `[]` | 用户白名单 |
| `MEDIA_COOKIES_FILE` | 空 | Netscape cookies.txt 路径 |
| `MEDIA_PROXY` | 空 | 下载代理 |
| `BILIBILI_CARD_ENABLED` | `true` | B 站链接先发信息卡 |
| `BILIBILI_MAX_HEIGHT` | `480` | B 站视频高度上限 |
| `BILIBILI_JINA_BASE` | `https://r.jina.ai/` | B 站 412 时用的 Reader 代理 |
| `PARSEHUB_AUTO` | `true` | 自动解析开关 |
| `PARSEHUB_PLATFORMS` | 国内平台白名单 | 只解析这些平台 |
| `PARSEHUB_MAX_FILE_MB` | `100` | 单文件大小上限 |
| `PARSEHUB_MAX_SECONDS` | `300` | 视频时长上限 |
| `PARSEHUB_CONCURRENCY` | `2` | 并发解析数 |
| `PARSEHUB_CARD` | `true` | 是否发信息卡片 |
| `PARSEHUB_DELIVERY` | `file` | 媒体投递方式 |

---

## 链接分享解析

现在用 [ByteColtX/nonebot-plugin-parsehub](https://github.com/ByteColtX/nonebot-plugin-parsehub)，底层是 [z-mio/ParseHub](https://github.com/z-mio/ParseHub)：

- 24 个平台，优先国内：抖音、快手、微博、小红书、贴吧、知乎、豆瓣、头条、微信公众号、微信视频号、酷安、皮皮虾、最右、小黑盒、Bangumi；
- 自动识别链接/分享文案，输出视频/图集/图文和 App Store 风格卡片；
- 支持 `/解析 <链接>`、`/解析平台`、`/解析开关`；
- 同一作品 24 小时媒体缓存，命中直接发；
- B 站不交给它：本机 B 站接口 412，B 站继续走本地 Jina 信息卡 + 480P 下载；
- 海外平台（YouTube/TikTok/X 等）默认不在白名单，避免没代理时超时。

> 旧 `nonebot-plugin-parser` 和 `nonebot-plugin-resolver` 都已卸载；旧 `PARSER_*` / `RESOLVER_*` 配置不要再写。

---

## 网页链接阅读

群里（或私聊）直接发普通网页链接：

```text
https://example.com/some-article
```

机器人会自动抓取网页正文，然后用 Claude 的口吻写一段 80–180 字的感慨/点评，而不是干巴巴的摘要。

也可以手动：

```text
/read https://example.com/some-article
```

别名：`/读链接`、`/总结链接`、`/解读链接`。

- 只抓取 http/https 网页的 HTML/纯文本，不执行 JavaScript，所以重前端、登录墙、付费墙页面可能读不到；
- 自动跳过视频站、图片、PDF、压缩包等链接（视频交给 `/mp4`）；
- 网页正文最多取 6000 字，页面最多 2MB；
- 会拒绝 localhost/内网地址，避免 SSRF；
- 网页内容只作为资料，系统提示词明确要求模型不执行网页里的指令；
- 自动模式失败默认静默，只写日志；需要提示就设 `LINK_READER_NOTIFY_ERRORS=true`；
- 同一用户 30 秒冷却，每天最多 10 篇；同一会话同一链接 10 分钟内只读一次；
- 只写短评，不整篇转载网页内容。

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `LINK_READER_ENABLED` | `true` | 总开关 |
| `LINK_READER_GROUPS` | `[]` | 自动读链接生效的群，空为全部 |
| `LINK_READER_COOLDOWN_SECONDS` | `30` | 同一用户冷却 |
| `LINK_READER_DAILY_LIMIT_PER_USER` | `10` | 每人每日上限 |
| `LINK_READER_TIMEOUT_SECONDS` | `20` | 抓网页超时 |
| `LINK_READER_MAX_BYTES` | `2000000` | 页面大小上限 |
| `LINK_READER_MAX_CHARS` | `6000` | 送给模型的正文长度 |
| `LINK_READER_NOTIFY_ERRORS` | `false` | 自动失败是否在群里提示 |

---

## 实时检索 / 近两年知识

模型本身不能“在线重训”，所以这里用的是**实时检索补充**：

- 遇到需要最新事实的问题，模型会自己决定是否搜索；`/search` 是强制搜索；
- 搜索源：Google News RSS + DuckDuckGo，**不需要 API Key**；
- 检索结果会带日期、来源和链接，模型必须优先依据结果，并标注 `[编号]`；
- 查不到就明确说查不到，不允许编；
- 也可以手动：

```text
/search 最近两年 DeepSeek 有哪些重要更新
```

- 默认 **不按关键词强制预搜索**，交给模型自主判断；想让它在命中“最新/最近/2026”时先自动搜，可设 `WEB_SEARCH_AUTO=true`；
- 搜索内容会发送给 Google/DuckDuckGo 第三方服务，敏感问题不要用它查。

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `WEB_SEARCH_ENABLED` | `true` | 总开关 |
| `WEB_SEARCH_AUTO` | `false` | 关键词命中时是否先自动预搜索 |
| `WEB_SEARCH_MAX_RESULTS` | `6` | 最多几条结果 |
| `WEB_SEARCH_TIMEOUT_SECONDS` | `15` | 搜索超时 |

---

## 深度研究 / 本地知识库

实时检索原来只看搜索摘要，现在升级成两层：

1. **搜索**：Google News RSS + DuckDuckGo；
2. **抓正文**：对排名靠前的真实网页继续抓正文（B站、贴吧等抓不到时自动走 Jina Reader），再交给模型；
3. **本地知识库**：抓到的标题、摘要和正文写入 SQLite FTS5，之后会自动检索复用。

```text
/research 战争雷霆 2026 最新更新
/kb 战争雷霆
```

- `/research` 会搜索多源、抓取前几篇正文，给出带 `[编号]` / `[P编号]` 来源的回答；
- 普通时效问题也会自动补 2 篇网页正文，不只靠摘要；
- `/kb` 可以查看本地缓存里已经学到的东西（不带参数时显示库内概况：总数、空壳数、最早一条多久前）；
- 数据库：`data/knowledge.db`，FTS5 trigram；
- 抓取只限公网 http/https，内网/本机地址会被拒绝；
- 不是把整个互联网灌进模型，而是“用到哪、抓到哪、存下来”，越用越厚。

### 中文检索为什么以前是坏的

FTS5 的 `trigram` 分词器把文本切成**所有重叠的三字窗口**，所以：

- 查询词**短于 3 个字符就永远匹配不上**（凑不出一个 trigram）；
- 中文没有空格，旧代码按空格切词，`战争雷霆最新版本` 整句被当成**一个短语**去匹配，
  而语料里不存在这个 8 字连续片段 → **0 命中**。

结果就是知识库里明明有资料，任何一句自然中文提问都搜不到。现在由 `textquery.py` 统一处理：

1. 中文按**重叠三字窗口**切开，再用 `OR` 连起来（`战争雷霆最新版本` → `"战争雷" OR "争雷霆" OR …`）；
2. 词太多时**均匀采样**而不是只取前几个，避免只匹配到句子开头；
3. 只有 2 个字的中文词（trigram 一定搜不到）退化成 SQL `LIKE` 兜底；
4. 命中的候选再按「标题命中 ×3 + 正文命中 + 新鲜度」重新排序，
   并按归一化标题**去重**（同一篇文章被多家转载只留一条）；
5. 正文抓空、标题也没信息量的「空壳」记录直接不参与排序。

回归测试在 `tests/test_knowledge_search.py::test_natural_chinese_question_hits`。

### 主动投喂资料

机器人自己抓的资料质量参差（Google News 经常只给一句摘要，偶尔还会带回无关广告）。
想让它**稳懂**某些内容，就把整理好的材料放进 `seeds/`，用 `tools/kb_seed.py` 投喂：

```powershell
# 看库里现在有什么（带 id，方便删）
python tools/kb_seed.py --list

# 导入 seeds/ 下的 .md（可先 --dry-run 看会写什么）
python tools/kb_seed.py --dir seeds

# 自检：中文自然问句到底能不能命中
python tools/kb_seed.py --search 战争雷霆最新版本

# 联网搜一次并落库（相当于手动触发一次深度检索）
python tools/kb_seed.py --query "逃离塔科夫 1.0" --pages 3

# 按 id 删掉抓歪的资料
python tools/kb_seed.py --forget-id 15

# 清空壳和过期资料
python tools/kb_seed.py --prune
```

`seeds/` 里现有：战争雷霆（基础机制、群聊黑话对照）、逃离塔科夫（核心机制、弹药与护甲）、
DeepSeek（公司与模型线）、网络黑话梗对照。每个文件带一段头信息，标明来源和日期：

```markdown
---
title: 战争雷霆 · 基础机制与分房规则
source: 整理（非实时，具体数值以游戏内为准）
published: 2026-10
url: curated://war-thunder/basics
---
```

> 整理的资料只写**不会过期的机制和术语**，不写具体数值（BR、弹药穿深、任务要求这些每期都在改）。
> 涉及数字的问题仍然走实时检索——`persona.md` 里也明确要求“不确定就说不确定”。

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `WEB_SEARCH_DEEP` | `true` | 时效问题是否继续抓网页正文 |
| `WEB_SEARCH_DEEP_PAGES` | `2` | 自动抓几篇 |
| `KNOWLEDGE_ENABLED` | `true` | 本地知识库开关 |
| `KNOWLEDGE_DB_PATH` | `data/knowledge.db` | SQLite 路径 |
| `KNOWLEDGE_MAX_RESULTS` | `3` | 每次注入几条缓存 |
| `KNOWLEDGE_MIN_CONTENT_CHARS` | `40` | 正文短于这个长度、标题也没信息量的抓取结果不入库 |
| `KNOWLEDGE_STALE_DAYS` | `120` | 超过这么多天的旧资料启动时清掉；`0` 为不清理 |
| `KNOWLEDGE_FRESHNESS_HALF_LIFE_DAYS` | `30` | 排序里新鲜度的半衰期，越小越偏向新抓的 |

---

## 游戏社群 / 热榜

不能把“全互联网所有游戏社群”真的灌进模型，所以这里做的是**按需抓取 + 检索 + 缓存**：

```text
/game 战争雷霆
/game 逃离塔科夫
/hot
```

- `/game` 会同时查：Google News、Bilibili、百度贴吧、NGA、Reddit 等来源；
- 支持中文名/常用别名，例如 `战雷`、`塔科夫`、`战地`、`三角洲行动`；
- 在聊天里直接提游戏名也会自动补充近期社群上下文；
- `/hot` 抓：
  - **B站热搜**（Bilibili 热搜接口）；
  - **抖音热榜**（抖音热点词接口）；
  - **快手热榜/热门视频**（快手发现页）；
- 热榜缓存 10 分钟，游戏情报缓存 15 分钟；
- 只抓公开内容，不登录、不爬私密社群；
- 社区内容会有传闻和旧版本攻略，模型被告知要区分事实/传闻，并标注来源；
- 支持列表会继续加，没在列表里的游戏也可以直接 `/game 游戏名`。

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `COMMUNITY_ENABLED` | `true` | 总开关 |
| `COMMUNITY_HOT_LIMIT` | `8` | 每个榜单最多几条 |
| `COMMUNITY_TIMEOUT_SECONDS` | `20` | 抓取超时 |

---

## 自主工具调用

它不再只是“先预搜索再回答”，而是模型自己决定下一步：

- `web_search`：搜实时信息；
- `fetch_url`：打开具体网页读正文；
- `search_knowledge`：查本地知识库；
- `get_hot`：抓 B站/抖音/快手热榜；
- `game_intel`：查游戏社群/版本资讯。

简单聊天它可以直接答；需要最新事实或具体页面时，它会自己调用工具，拿到结果后再回答。工具结果只作为资料，不当指令；引用来源；查不到就说查不到。

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `CLAUDE_TOOLS_ENABLED` | `true` | 是否允许模型自主调用工具 |
| `CLAUDE_MAX_TOOL_ROUNDS` | `3` | 最多几轮工具调用 |

---

## 配置项

所有配置都可以写在 `.env`，字段名大写。完整列表见 [`plugins/claude_chat/config.py`](plugins/claude_chat/config.py)。

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | 空 | 官方 Anthropic Key（`sk-ant-...`） |
| `ANTHROPIC_AUTH_TOKEN` | 空 | 中转站 Bearer Token，设置后优先于 API_KEY |
| `ANTHROPIC_AUTH_TOKEN_FILE` | 空 | Claude Code `settings.json` 路径；401 时自动刷新 token |
| `ANTHROPIC_BASE_URL` | 空 | 中转/代理地址；官方留空 |
| `ANTHROPIC_CUSTOM_HEADERS` | `{}` | 额外请求头；JSON 对象或 `名称: 值`（多条用逗号/换行分隔） |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | 模型名/中转模型 ID |
| `CLAUDE_SYSTEM_PROMPT` | 内置人设 | 系统提示词 |
| `CLAUDE_SYSTEM_PROMPT_FILE` | 空 | 从文件读取人格，优先级更高；相对项目根目录 |
| `CLAUDE_MAX_TOKENS` | `2048` | 单次最大输出 token |
| `CLAUDE_GROUP_REQUIRE_AT` | `true` | 群聊是否必须 @ |
| `CLAUDE_GROUP_MEMORY_MODE` | `per_user` | 群记忆按 QQ 分开；`shared` 为全群共享（历史仍带 QQ 号） |
| `CLAUDE_ALLOWED_GROUPS` | `[]` | 群白名单，空为全部 |
| `CLAUDE_ALLOWED_USERS` | `[]` | 用户白名单，空为全部 |
| `BLOCKED_USERS` | `[]` | 全局屏蔽的 QQ 号；消息、命令、图片/表情包/生成全部忽略 |
| `CLAUDE_HISTORY_MESSAGES` | `20` | 历史消息条数上限 |
| `CLAUDE_HISTORY_MAX_CHARS` | `48000` | 历史字符上限 |
| `CLAUDE_SESSION_TTL_MINUTES` | `180` | 会话空闲过期时间 |
| `CLAUDE_COOLDOWN_SECONDS` | `3` | 同一用户冷却 |
| `CLAUDE_CONCURRENCY` | `4` | Claude 并发上限 |
| `CLAUDE_TIMEOUT_SECONDS` | `180` | 请求超时 |
| `CLAUDE_MAX_IMAGES` | `4` | 单条消息最多图片数 |
| `CLAUDE_IMAGE_MAX_MB` | `4` | 单张图片大小上限 |
| `CLAUDE_CONVERT_MARKDOWN` | `true` | 是否清理 Markdown |
| `CLAUDE_REPLY_CHUNK_CHARS` | `1200` | 单条 QQ 消息字符上限 |
| `CLAUDE_MAX_CHUNKS` | `4` | 一条回复最多拆成几条 |
| `CLAUDE_ACK_TEXT` | 空 | 慢请求提示；**默认留空不发**（“正在思考，请稍等”是最出戏的一句） |
| `CLAUDE_ACK_AFTER_SECONDS` | `8` | 超过多久发提示（仅在 ack 文案非空时生效） |
| `CLAUDE_DATA_DIR` | `data` | 会话文件目录 |
| `CLAUDE_RHYTHM_ENABLED` | `true` | 拟人节奏总开关 |
| `CLAUDE_READ_DELAY_MAX_SECONDS` | `3.0` | “读完再回”的最长停顿 |
| `CLAUDE_TYPING_PER_CHAR_SECONDS` | `0.11` | 每字模拟打字时间 |
| `CLAUDE_TYPING_MAX_SECONDS` | `4.5` | 单条消息打字时间上限 |
| `CLAUDE_BURST_ENABLED` | `true` | 长回复是否分条发送 |
| `CLAUDE_BURST_MIN_CHARS` | `60` | 短于这个长度不分条 |
| `CLAUDE_BURST_TARGET_CHARS` | `90` | 分条时每条约多少字 |
| `CLAUDE_BURST_MAX_EXTRA` | `2` | 最多额外拆几条 |
| `CLAUDE_BURST_GAP_MIN_SECONDS` | `0.5` | 两条消息最小间隔 |
| `CLAUDE_BURST_GAP_MAX_SECONDS` | `1.6` | 两条消息最大间隔 |
| `MEMORY_ENABLED` | `true` | 长期记忆总开关 |
| `MEMORY_DB_PATH` | `data/memory.db` | 长期记忆 SQLite 路径 |
| `MEMORY_INJECT_LIMIT` | `6` | 每次回答最多注入几条记忆 |
| `MEMORY_EXTRACT_EVERY` | `3` | 每几轮抽取一次（抽取要额外调模型） |
| `MEMORY_MAX_FACTS_PER_SCOPE` | `200` | 每个会话/每人最多保留几条 |
| `MEMORY_PRUNE_STALE_DAYS` | `90` | 自动记忆多久没用上就清掉 |

---

## 它是怎么工作的

```text
QQ 客户端
   ↕
NapCat（登录 QQ，OneBot 11 WebSocket 服务端 :3001）
   ↕  ws://127.0.0.1:3001
NoneBot2 + OneBot 适配器
   ↕
claude_chat 插件
   ├─ 触发规则：私聊 / 群聊 @ / 回复机器人
   ├─ 收集文字、引用、图片（下载并转 base64）
   ├─ 读取该会话历史（JSON 持久化 + TTL/长度裁剪）
   ├─ 调用 Anthropic Messages API
   └─ Markdown 清理 → 按 1200 字拆条 → 回复 QQ
```

几个设计取舍：

- **非流式**：QQ 不支持可靠的消息编辑，因此等 Claude 生成完整回复后一次发出；超过 8 秒会先发一条“正在思考”提示。
- **图片不落库**：历史里只保存 `[图片×N]` 占位，不保存 base64，避免会话文件膨胀；追问图片内容时需要重新发图。
- **群聊上下文**：默认按 QQ 号隔离，也可配置为全群共享；群消息会发送到所配置的模型服务，敏感群请使用白名单或不要接入。
- **单进程**：会话存储在进程内 + JSON 文件，不要用多 worker 同时跑同一个数据目录。

---

## 成本与限流

- Claude 按 token 计费，群聊里每句话都会带上最近的历史，长会话成本更高。可以用 `/stats` 看本会话用量，或调小 `CLAUDE_HISTORY_MESSAGES`。
- 建议在 Anthropic Console 里设置 **spend limit**，防止 Key 泄露或群友刷屏。
- 内置三层保护：用户冷却（默认 3 秒）、全局并发（默认 4）、群/用户白名单。

---

## 常见问题

**Q：日志里一直 `ConnectionRefusedError` / `Cannot connect to host 127.0.0.1:3001`**

NapCat 没启动，或 WebSocket 服务器没启用，或端口/Token 不一致。先确认 NapCat WebUI 里那个 WS 服务端是“启用”状态，再核对 `.env` 的 `ONEBOT_WS_URLS` 和 `ONEBOT_ACCESS_TOKEN`。

**Q：提示 `Current driver ~fastapi does not support websocket client connections`**

本项目需要支持 WebSocket **客户端**的驱动，`.env` 里必须是：

```dotenv
DRIVER=~aiohttp
```

不要用 `~fastapi`，它只能做 WebSocket 服务端。

**Q：提示 API Key 无效（401/403）**

- 配置了 `ANTHROPIC_AUTH_TOKEN_FILE` 时，机器人会从指定的 Claude Code `settings.json` 读取 token；请求遇到 401 时会尝试刷新一次。
- 如果仍然 401，请确认 token 是否有效，或更新 `.env` 中的 `ANTHROPIC_AUTH_TOKEN` 后重启。

- 官方 Anthropic Key 形如 `sk-ant-api03-...`；`sk-` 开头但只有 30 多位的通常不是官方 Key。
- 403 `Request not allowed` 常见于 Key 不对、账号/地区受限，或把中转 Key 发到了官方地址。
- 用中转站时，除了 `ANTHROPIC_AUTH_TOKEN`，还必须设置 `ANTHROPIC_BASE_URL`，并确认中转协议是 Anthropic Messages（`/v1/messages`），不是 OpenAI 协议。
- 改完 `.env` 要重启机器人。

**Q：提示模型不存在（404）**

`CLAUDE_MODEL` 写错了，或者账号没有该模型权限。官方默认用 `claude-sonnet-4-6`；兼容服务要填它提供的模型 ID。模型列表见 [Anthropic 文档](https://platform.claude.com/docs/en/about-claude/models/overview)。

**Q：启动报 `SettingsError: error parsing env var "anthropic_custom_headers"`**

系统环境变量里已经有一个 `ANTHROPIC_CUSTOM_HEADERS`，而且不是 JSON——比如 Claude Code 这类工具用的是 `名称: 值` 写法。环境变量优先级高于 `.env`，所以插件读到的不是你在 `.env` 里写的那份。

两种写法现在都认，通常不用管；要彻底消掉就清掉系统里那个变量：

```powershell
Remove-Item Env:ANTHROPIC_CUSTOM_HEADERS   # 只影响当前终端
```

或者在 `.env` 里按 `名称: 值` 写，效果一样。

**Q：能换成 Claude Code 订阅额度吗？**

当前版本走 Anthropic 兼容 API。想复用 Claude Code 订阅，需要把 `claude.py` 的调用层换成 `claude` CLI 子进程（`claude -p`），会话和限流逻辑可以保留；这不是官方 API，稳定性和条款需自行评估。

---

## 使用官方 Claude API

要使用官方 Anthropic API，在 `.env` 中配置官方 API Key，并清空兼容服务的地址和 Token：

```dotenv
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxx
ANTHROPIC_AUTH_TOKEN=
ANTHROPIC_BASE_URL=
ANTHROPIC_CUSTOM_HEADERS={}
CLAUDE_MODEL=claude-sonnet-4-6
```

然后重启：

```powershell
.\stop-all.ps1
.\start-all.ps1
```

或者只重启 Bot（NapCat 保持运行），删除旧的 Bot 进程后执行 `.\start-all.ps1` 即可。

**Q：群里 @ 了没反应**

- 确认 `CLAUDE_GROUP_REQUIRE_AT=true` 时确实是 **@机器人**，不是只发文字。
- 检查 `CLAUDE_ALLOWED_GROUPS` / `CLAUDE_ALLOWED_USERS` 是否把该群/该用户排除了。
- 看控制台有没有 `Claude 请求失败` 的日志。

**Q：图片没反应 / 提示图片读取失败**

QQ 图片链接有时效，且部分格式（如 BMP）不支持。重新发一次图；或把 `CLAUDE_MAX_IMAGES` 调大、`CLAUDE_IMAGE_MAX_MB` 调大。超时/失败不会影响纯文字聊天。

**Q：中文日志乱码**

用 `start.ps1` / `start.bat` 启动（已设置 `PYTHONUTF8=1`），或在 PowerShell 里先执行：

```powershell
$env:PYTHONUTF8 = "1"
```

**Q：QQ 被风控 / 冻结**

不要用主号高频刷屏；新号先正常聊天养几天；控制群发频率；避免重复发送相同内容。NapCat 属于非官方协议实现，账号风险需要自己承担。

**Q：能换成 Claude Code 订阅额度吗？**

当前版本走 Anthropic API Key。想复用 Claude Code 订阅，需要把 `claude.py` 的调用层换成 `claude` CLI 子进程（`claude -p`），会话和限流逻辑可以保留；这不是官方 API，稳定性和条款需自行评估。

---

## 开发与测试

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

另外有个知识库自检工具，不需要跑 bot：

```powershell
.\.venv\Scripts\python.exe tools\kb_seed.py --search 战争雷霆最新版本
```

测试覆盖：

- Markdown → QQ 文本转换、代码块保留、长消息拆分、代码围栏自动闭合
- 会话裁剪、TTL、JSON 持久化
- Anthropic 请求体、用量解析、401 错误翻译
- 群聊 @ 触发规则
- 从群消息到 Claude 回复、写回会话的完整链路（mock 掉 Claude 和发送）
- **中文检索**（`test_textquery.py`、`test_knowledge_search.py`）：
  自然中文问句必须命中，短词退化成 `LIKE`，长查询要截断，重复转载要去重，旧资料要排在后面
- **长期记忆**（`test_memory.py`）：按话题召回、身份优先、作用域隔离、写入限额、
  敏感信息不落库、模型报错不能影响对话
- **拟人节奏**（`test_rhythm.py`）：短回复不分条、长回复分条且能拼回原文、
  代码块和列表永不切开、延迟有上下界、关掉之后完全不等待
- **附加请求头**（`test_env_headers.py`）：JSON 和 `名称: 值` 两种写法都能读进来，
  空值等于不加头，写错要报错而不是静悄悄不生效

> 这几组测试是这次改动加的回归网。特别是 `test_natural_chinese_question_hits`——
> 它守着那个「知识库里有资料但中文问句 0 命中」的老 bug，别删。

---

## 开机自启

`start-bot.vbs` 会静默调用 `start-all.ps1`。如需登录 Windows 后自动启动，可将它的快捷方式放入启动文件夹（在运行对话框输入 `shell:startup` 打开）。

```text
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
```

启动前设置 `NAPCAT_HOME` 环境变量指向 NapCat 安装目录；可选设置 `QQ_ACCOUNT` 指定启动账号。也可以手动运行 `.\start-all.ps1 -NapCatHome <NapCat目录> -QQ <QQ号>`。脚本会检查 NapCat 和 Bot，已经在运行就跳过。

- 取消自启：从启动文件夹删除快捷方式。
- 换机器人 QQ：修改 `start-all.ps1` 里的 `-QQ` 参数，或删除 `.lnk` 后手动运行。
- 手动停止：`.\stop-all.ps1`（只停 Bot 和 NapCat 的 QQ 进程，不影响其他 QQ 客户端）。

---

## 安全提醒

1. `.env` 含密钥，不要截图、不要提交、不要发群。
2. `ONEBOT_ACCESS_TOKEN` 不要用默认值暴露到公网；NapCat 的 3001 端口只监听 `127.0.0.1` 或做防火墙限制。
3. 群聊内容会发送到 Anthropic API；不要在涉密群使用。
4. 给 API Key 设置消费上限，定期轮换。
5. 本项目不包含任何工具调用/代码执行能力，模型只能“说话”，不会操作你的电脑。
