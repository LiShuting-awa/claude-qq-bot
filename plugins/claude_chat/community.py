"""游戏社群与热榜抓取：B站热搜、抖音热榜、快手热榜 + 游戏情报搜索。"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from urllib.parse import quote

import httpx2

from .web_search import SearchResult, search_web

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"}

_HOT_TTL = 600
_GAME_TTL = 900
_hot_cache: tuple[float, dict[str, list["HotItem"]]] | None = None
_game_cache: dict[str, tuple[float, list[SearchResult]]] = {}

GAME_ALIASES: dict[str, tuple[str, ...]] = {
    "战争雷霆": ("战争雷霆", "战雷", "war thunder", "warthunder"),
    "逃离塔科夫": ("逃离塔科夫", "塔科夫", "escape from tarkov", "tarkov"),
    "三角洲行动": ("三角洲行动", "delta force"),
    "暗区突围": ("暗区突围", "arena breakout"),
    "坦克世界": ("坦克世界", "world of tanks"),
    "战舰世界": ("战舰世界", "world of warships"),
    "使命召唤": ("使命召唤", "call of duty"),
    "战地": ("战地", "battlefield"),
    "反恐精英": ("反恐精英", "counter-strike"),
    "无畏契约": ("无畏契约", "valorant"),
    "英雄联盟": ("英雄联盟", "league of legends"),
    "王者荣耀": ("王者荣耀", "honor of kings"),
    "原神": ("原神", "genshin"),
    "绝区零": ("绝区零", "zenless zone zero"),
    "鸣潮": ("鸣潮", "wuthering waves"),
    "永劫无间": ("永劫无间", "naraka"),
    "彩虹六号": ("彩虹六号", "rainbow six", "r6"),
    "Apex英雄": ("apex英雄", "apex legends"),
    "绝地求生": ("绝地求生", "pubg"),
    "DOTA2": ("dota2", "dota 2"),
    "魔兽世界": ("魔兽世界", "world of warcraft"),
    "命运2": ("命运2", "destiny 2"),
    "绝地潜兵2": ("绝地潜兵2", "helldivers 2"),
    "艾尔登法环": ("艾尔登法环", "elden ring"),
    "黑神话悟空": ("黑神话悟空", "black myth wukong"),
    "我的世界": ("我的世界", "minecraft"),
}


@dataclass(slots=True)
class HotItem:
    title: str
    url: str
    source: str
    hot: str = ""


def detect_game(text: str) -> str:
    lowered = (text or "").casefold()
    for game, aliases in GAME_ALIASES.items():
        for alias in aliases:
            needle = alias.casefold()
            if not needle:
                continue
            if needle.isascii() and len(needle) <= 4:
                if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", lowered):
                    return game
            elif needle in lowered:
                return game
    return ""


async def _jina_get(url: str, timeout: float = 40) -> str:
    async with httpx2.AsyncClient(
        timeout=timeout, follow_redirects=True, headers=_HEADERS
    ) as client:
        response = await client.get("https://r.jina.ai/" + url)
        response.raise_for_status()
        return response.text


def _json_after_marker(text: str) -> dict:
    start = text.find('{"code"')
    if start < 0:
        start = text.find('{"status_code"')
    if start < 0:
        start = text.find("{")
    if start < 0:
        raise RuntimeError("热榜接口没有返回 JSON")
    return json.loads(text[start:])


async def fetch_bilibili_hot(limit: int = 8) -> list[HotItem]:
    text = await _jina_get("https://api.bilibili.com/x/web-interface/search/square?limit=20")
    data = _json_after_marker(text)
    trending = ((data.get("data") or {}).get("trending") or {}).get("list") or []
    items: list[HotItem] = []
    for entry in trending[:limit]:
        title = str(entry.get("show_name") or entry.get("keyword") or "").strip()
        if not title:
            continue
        keyword = str(entry.get("keyword") or title)
        items.append(
            HotItem(
                title=title,
                url=f"https://search.bilibili.com/all?keyword={quote(keyword)}",
                source="B站热搜",
                hot=str(entry.get("heat_score") or ""),
            )
        )
    return items


async def fetch_douyin_hot(limit: int = 8) -> list[HotItem]:
    url = "https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/word/"
    data: dict = {}
    try:
        async with httpx2.AsyncClient(
            timeout=20, follow_redirects=True, headers=_HEADERS
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
    except Exception:
        text = await _jina_get(url)
        data = _json_after_marker(text)
    words = data.get("word_list") or []
    items: list[HotItem] = []
    for entry in words[:limit]:
        title = str(entry.get("word") or "").strip()
        if not title:
            continue
        items.append(
            HotItem(
                title=title,
                url=f"https://www.douyin.com/search/{quote(title)}",
                source="抖音热榜",
                hot=str(entry.get("hot_value") or ""),
            )
        )
    return items


async def fetch_kuaishou_hot(limit: int = 8) -> list[HotItem]:
    text = await _jina_get("https://www.kuaishou.com/brilliant")
    items: list[HotItem] = []
    seen: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"^#{3,6}\s+(.+)$", line.strip())
        if not match:
            continue
        title = match.group(1).strip()
        if not title or title in seen:
            continue
        seen.add(title)
        items.append(
            HotItem(
                title=title,
                url="https://www.kuaishou.com/brilliant",
                source="快手热榜",
            )
        )
        if len(items) >= limit:
            break
    return items


async def fetch_all_hot(limit: int = 8) -> dict[str, list[HotItem]]:
    global _hot_cache
    now = time.time()
    if _hot_cache and now - _hot_cache[0] < _HOT_TTL:
        return _hot_cache[1]

    tasks = [
        asyncio.create_task(fetch_bilibili_hot(limit)),
        asyncio.create_task(fetch_douyin_hot(limit)),
        asyncio.create_task(fetch_kuaishou_hot(limit)),
    ]
    raw = await asyncio.gather(*tasks, return_exceptions=True)
    result: dict[str, list[HotItem]] = {}
    for group in raw:
        if isinstance(group, Exception) or not group:
            continue
        source = group[0].source
        result[source] = group
    _hot_cache = (now, result)
    return result


def format_hot(data: dict[str, list[HotItem]]) -> str:
    if not data:
        return ""
    lines = [f"🔥 热榜速报（{time.strftime('%Y-%m-%d %H:%M')}）"]
    for source in ("B站热搜", "抖音热榜", "快手热榜"):
        items = data.get(source)
        if not items:
            continue
        lines.append(f"\n【{source}】")
        for index, item in enumerate(items, 1):
            hot = f"  🔥{item.hot}" if item.hot else ""
            lines.append(f"{index}. {item.title}{hot}")
    return "\n".join(lines)


def _queries_for(game: str) -> list[str]:
    aliases = GAME_ALIASES.get(game, (game,))
    english = next((alias for alias in aliases if alias.isascii()), "")
    queries = [
        f"{game} 最新",
        f"site:bilibili.com {game}",
        f"site:tieba.baidu.com {game}",
        f"site:nga.178.com {game}",
    ]
    if english:
        queries.append(f"{english} update")
        queries.append(f"site:reddit.com {english}")
    else:
        queries.append(f"{game} 贴吧 攻略")
    return queries


async def game_intel(game: str, limit: int = 8) -> list[SearchResult]:
    now = time.time()
    cached = _game_cache.get(game)
    if cached and now - cached[0] < _GAME_TTL:
        return cached[1]

    queries = _queries_for(game)
    tasks = [
        asyncio.create_task(search_web(query, limit=3, timeout=15)) for query in queries
    ]
    raw = await asyncio.gather(*tasks, return_exceptions=True)
    results: list[SearchResult] = []
    seen: set[str] = set()
    for group in raw:
        if isinstance(group, Exception) or not group:
            continue
        for item in group:
            key = item.url.split("#", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            results.append(item)
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break
    _game_cache[game] = (now, results)
    return results


def format_game(game: str, results: list[SearchResult]) -> str:
    if not results:
        return ""
    lines = [f"🎮 {game} 近期社群/资讯（{time.strftime('%Y-%m-%d')}）"]
    for index, item in enumerate(results, 1):
        meta = " / ".join(part for part in (item.source, item.date) if part)
        lines.append(
            f"[{index}] {item.title}" + (f"（{meta}）" if meta else "") + f"\n{item.url}"
        )
        if item.snippet:
            lines.append(item.snippet[:180])
    return "\n".join(lines)
