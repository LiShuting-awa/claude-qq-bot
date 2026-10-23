"""每天一次的联网充电：热榜入知识库，再按群里最近聊的话题查一圈。

只写知识库和日志，不在群里说话。话题由模型从群聊采样里提炼，
搜索和入库复用 claude_chat 的检索与知识库。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from nonebot import get_driver, get_plugin_config, logger

from plugins.common.llm import build_client, has_credentials
from plugins.speech_learn.learn import collect_samples

from .config import Config

plugin_config = get_plugin_config(Config)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LOG_DIR = _PROJECT_ROOT / "data" / "speech_log"

_task: asyncio.Task | None = None
_last_day: str = ""


def load_records(log_dir: Path, *, days_back: int, max_messages: int) -> list[dict]:
    """直接读 speech_log 的每日 JSONL，取最近几天的原始记录。"""
    files = sorted(p for p in log_dir.glob("*.jsonl"))[-days_back:]
    records: list[dict] = []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
    return records[-max_messages:]


def parse_topics(text: str, limit: int) -> list[str]:
    """把模型输出洗成查询词：一行一个，去掉编号、引号和长短不合适的。"""
    if limit <= 0:
        return []
    topics: list[str] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        topic = raw.strip().strip("、,，;；.。 \t")
        topic = topic.lstrip("0123456789.-)）:： 、.，, ").strip()
        topic = topic.strip("\"'“”「」『』")
        if not 2 <= len(topic) <= 30 or topic in seen:
            continue
        seen.add(topic)
        topics.append(topic)
        if len(topics) >= limit:
            break
    return topics


def _topic_system() -> str:
    return (
        "你会拿到一个 QQ 群最近的聊天记录采样。挑出群里最近真正在聊、适合联网查证的具体话题："
        "某游戏的新版本/更新/活动、某条新闻、某个事件、某个产品型号都行。\n"
        "要求：\n"
        "- 每行一个查询词，直接能当搜索词用\n"
        "- 只挑群里出现过的内容，不要编话题\n"
        "- 不要「游戏」「新闻」这种泛词，要具体到「XX游戏 新版本」这个程度\n"
        "- 只输出查询词，每行一个，不要编号、解释和多余的话"
    )


async def extract_topics(config: Config, samples: list[str]) -> list[str]:
    client = build_client(
        api_key=config.anthropic_api_key,
        auth_token=config.anthropic_auth_token,
        auth_token_file=config.anthropic_auth_token_file,
        base_url=config.anthropic_base_url,
        custom_headers=dict(config.anthropic_custom_headers),
        timeout=60,
    )
    transcript = "\n".join(samples)[:20000]
    response = await client.messages.create(
        model=config.claude_model.strip() or "claude-sonnet-4-6",
        max_tokens=300,
        system=_topic_system(),
        messages=[{"role": "user", "content": transcript}],
        timeout=60,
    )
    text = "".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text" and getattr(block, "text", None)
    )
    return parse_topics(text, plugin_config.self_study_max_topics)


async def run_once() -> str:
    """跑一天的自学，返回结果摘要；各环节失败互不影响。"""
    # 懒加载：避免插件加载顺序牵出 claude_chat 的全部 matcher
    from plugins.claude_chat.community import fetch_all_hot
    from plugins.claude_chat.handlers import knowledge
    from plugins.claude_chat.web_search import deep_research, search_web

    stored = 0

    if plugin_config.self_study_hot_limit > 0:
        try:
            hot = await fetch_all_hot(plugin_config.self_study_hot_limit)
            seen_urls: set[str] = set()
            for items in hot.values():
                for item in items:
                    url = item.url
                    if url in seen_urls:
                        # 有些榜单整版共用一个地址，加个片段让每条都能入库
                        url = f"{url}#{len(seen_urls)}"
                    seen_urls.add(url)
                    if knowledge.upsert(
                        url=url,
                        title=item.title,
                        source=item.source,
                    ):
                        stored += 1
        except Exception as exc:
            logger.warning(f"自学收热榜失败：{exc}")

    topics: list[str] = []
    if (
        plugin_config.speech_learn_enabled
        and plugin_config.self_study_max_topics > 0
        and has_credentials(
        api_key=plugin_config.anthropic_api_key,
        auth_token=plugin_config.anthropic_auth_token,
        auth_token_file=plugin_config.anthropic_auth_token_file,
        )
    ):
        records = load_records(
            _LOG_DIR,
            days_back=plugin_config.self_study_days_back,
            max_messages=2000,
        )
        # 采样上限跟说话学习保持一个量级，够提炼话题就行
        samples = collect_samples(records, max_messages=1200, max_chars=20000)
        if len(samples) < plugin_config.self_study_min_messages:
            logger.info(f"自学跳过话题提炼：采样只有 {len(samples)} 条")
        else:
            try:
                topics = await extract_topics(plugin_config, samples)
            except Exception as exc:
                logger.warning(f"自学提炼话题失败：{exc}")

    for topic in topics:
        try:
            results = await search_web(topic, limit=4, timeout=15)
            for item in results:
                if knowledge.upsert(
                    url=item.url,
                    title=item.title,
                    source=item.source or "自学搜索",
                    published=item.date,
                    content=item.snippet,
                    query=topic,
                ):
                    stored += 1
            pages = await deep_research(topic, results, pages=1)
            for page in pages:
                if knowledge.upsert(
                    url=page.url,
                    title=page.title,
                    source="自学正文",
                    content=page.text,
                    query=topic,
                ):
                    stored += 1
        except Exception as exc:
            logger.warning(f"自学查「{topic}」失败：{exc}")
        await asyncio.sleep(2)

    pruned = knowledge.prune()
    return (
        f"存了 {stored} 条（清掉 {pruned} 条旧的），"
        f"话题：{'、'.join(topics) if topics else '无'}"
    )


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------

_driver = get_driver()


@_driver.on_startup
async def _startup() -> None:
    global _task
    if not plugin_config.self_study_enabled:
        logger.info("每日自学总开关关闭（SELF_STUDY_ENABLED=false）")
        return
    _task = asyncio.create_task(_loop(), name="self_study")
    logger.info(f"每日自学已启动：每天 {plugin_config.self_study_hour} 点前后联网充电")


async def _loop() -> None:
    global _last_day
    while True:
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            if now.hour == plugin_config.self_study_hour and _last_day != today:
                # 先占坑再跑：失败也别在同一个钟点里反复重试
                _last_day = today
                try:
                    summary = await run_once()
                    logger.info(f"每日自学：{summary}")
                except Exception:
                    logger.warning("每日自学失败", exc_info=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("自学循环异常", exc_info=True)
        await asyncio.sleep(1800)
