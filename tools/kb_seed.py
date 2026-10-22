#!/usr/bin/env python
"""本地知识库投喂 / 维护工具。

机器人在聊天里抓到的资料会自动进 `data/knowledge.db`，那个库平时只能等它自己长。
这个脚本用来主动往里放东西，以及检查它到底存了什么、检索能不能命中。

用法（在项目根目录执行）：

    python tools/kb_seed.py --stats
    python tools/kb_seed.py --search 战争雷霆最新版本
    python tools/kb_seed.py --dir seeds            # 导入 seeds/ 下的 .md
    python tools/kb_seed.py --url https://... --source 官网
    python tools/kb_seed.py --query "战争雷霆 新版本" --pages 3   # 联网搜索后落库
    python tools/kb_seed.py --prune                # 清空壳和过期资料
    python tools/kb_seed.py --dir seeds --dry-run  # 只看会写什么

`--dir` 的每个文件可以带一段头信息（没有就用一级标题和文件名）：

    ---
    title: 战争雷霆 · 基础机制
    source: 整理
    published: 2026-10
    url: curated://war-thunder/basics
    ---

    正文……

注意：`--dir` / `--url` / `--query` 是**有意投喂**，所以默认不套用
`KNOWLEDGE_MIN_CONTENT_CHARS`（那条规则是防搜索抓回空摘要的，不是防你自己写的东西）。
要卡长度就显式给 `--min-chars`。

这个脚本直接按文件路径加载插件模块，不经过 NoneBot 初始化，
所以不会因为没跑 bot 就报 “NoneBot has not been initialized”。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import re
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = ROOT / "plugins" / "claude_chat"
DEFAULT_DB = ROOT / "data" / "knowledge.db"
DEFAULT_SEEDS = ROOT / "seeds"

_HEADER_SPLIT = re.compile(r"^---\s*$", re.MULTILINE)


# ---------- 加载插件模块（绕开 NoneBot） ----------


def _load_plugin_modules() -> tuple[types.ModuleType, types.ModuleType]:
    """把 knowledge / web_search 及其依赖按路径加载进来。"""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    package = types.ModuleType("_kbseed")
    package.__path__ = [str(PLUGIN_DIR)]  # type: ignore[attr-defined]
    sys.modules["_kbseed"] = package

    def load(name: str) -> types.ModuleType:
        spec = importlib.util.spec_from_file_location(
            f"_kbseed.{name}", PLUGIN_DIR / f"{name}.py"
        )
        if spec is None or spec.loader is None:  # pragma: no cover - 只会在文件缺失时出现
            raise RuntimeError(f"加载不了 {name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"_kbseed.{name}"] = module
        spec.loader.exec_module(module)
        return module

    load("textquery")  # knowledge 依赖它
    knowledge = load("knowledge")
    web_search = load("web_search")
    return knowledge, web_search


# ---------- 文件解析 ----------


def parse_document(path: Path, fallback_url: str) -> dict[str, str] | None:
    """读一个 .md/.txt，返回 upsert 需要的字段；内容为空则返回 None。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"  跳过（不是 UTF-8）：{path}")
        return None

    meta: dict[str, str] = {}
    body = raw
    if raw.lstrip().startswith("---"):
        parts = _HEADER_SPLIT.split(raw.lstrip(), maxsplit=2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                meta[key.strip().casefold()] = value.strip()
            body = parts[2]

    body = body.strip()
    if not body:
        print(f"  跳过（正文为空）：{path}")
        return None

    title = meta.get("title", "")
    if not title:
        for line in body.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
    if not title:
        title = path.stem

    return {
        "url": meta.get("url") or fallback_url,
        "title": title,
        "source": meta.get("source", "整理"),
        "published": meta.get("published", ""),
        "content": body,
    }


def collect_dir(root: Path) -> list[dict[str, str]]:
    if not root.is_dir():
        print(f"目录不存在：{root}")
        return []
    docs: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        relative = path.relative_to(root).as_posix()
        doc = parse_document(path, fallback_url=f"curated://{relative}")
        if doc:
            doc["__file"] = relative
            docs.append(doc)
    return docs


# ---------- 动作 ----------


def cmd_stats(store) -> int:
    info = store.stats()
    print("📚 本地知识库")
    print(f"  资料总数：{info['total']}")
    print(f"  空壳（正文抓空、标题也没信息）：{info['thin']}")
    print(f"  最早一条：{info['oldest_days']} 天前")
    rows = store.conn.execute(
        "SELECT source, COUNT(*) FROM docs GROUP BY source ORDER BY COUNT(*) DESC LIMIT 10"
    ).fetchall()
    if rows:
        print("  来源分布：")
        for source, count in rows:
            print(f"    {source or '（未标）'}：{count}")
    return 0


def cmd_search(store, query: str, limit: int) -> int:
    rows = store.search(query, limit=limit)
    if not rows:
        print(f"「{query}」没有命中。")
        return 1
    print(f"「{query}」命中 {len(rows)} 条：")
    for index, row in enumerate(rows, 1):
        preview = " ".join(row["content"].split())[:70]
        print(f"  [{index}] {row['title']}")
        print(f"      {row['url']}（{row['source'] or '未标'} {row['published'] or '无日期'}）")
        if preview:
            print(f"      {preview}…")
    return 0


def cmd_list(store, limit: int) -> int:
    rows = store.conn.execute(
        """
        SELECT id, title, url, source, published, length(content) AS n, fetched_at
        FROM docs ORDER BY fetched_at DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    if not rows:
        print("库是空的。")
        return 0
    for row in rows:
        age_hours = (time.time() - float(row[6] or 0)) / 3600.0
        print(f"{row[0]:>4} | {row[5]:>5}字 | {age_hours:>6.1f}h前 | {row[3] or '未标'}")
        print(f"       {row[1] or '（无标题）'}")
        print(f"       {row[2]}")
    print(f"共 {store.count()} 条，上面是最近 {len(rows)} 条。")
    return 0


def cmd_forget(store, ids: list[int]) -> int:
    removed = 0
    for doc_id in ids:
        row = store.conn.execute("SELECT title FROM docs WHERE id = ?", (doc_id,)).fetchone()
        if row is None:
            print(f"  id {doc_id}：不存在")
            continue
        store.conn.execute("DELETE FROM docs WHERE id = ?", (doc_id,))
        print(f"  ✓ 删除 id {doc_id}：{row[0] or '（无标题）'}")
        removed += 1
    store.conn.commit()
    print(f"删除 {removed} 条，剩余 {store.count()} 条。")
    return 0


def cmd_prune(store, min_chars: int | None, stale_days: float | None) -> int:
    before = store.count()
    removed = store.prune(min_content_chars=min_chars, stale_days=stale_days)
    print(f"清理完成：删除 {removed} 条，{before} → {store.count()} 条")
    return 0


def cmd_import(store, docs: list[dict[str, str]], min_chars: int, dry_run: bool) -> int:
    if not docs:
        print("没有可导入的文件。")
        return 1
    written = 0
    skipped = 0
    for doc in docs:
        label = doc.pop("__file", doc["url"])
        if len(doc["content"]) < min_chars and len(doc["title"]) < 8:
            print(f"  跳过（太短）：{label}")
            skipped += 1
            continue
        if dry_run:
            print(f"  [dry-run] {label} → {doc['title']}（{len(doc['content'])} 字）")
            written += 1
            continue
        saved = store.upsert(
            url=doc["url"],
            title=doc["title"],
            source=doc["source"],
            published=doc["published"],
            content=doc["content"],
            query=doc.get("query", ""),
        )
        if saved:
            print(f"  ✓ {label} → {doc['title']}")
            written += 1
        else:
            print(f"  ✗ 未入库：{label}")
            skipped += 1
    verb = "将写入" if dry_run else "已写入"
    print(f"{verb} {written} 条，跳过 {skipped} 条。当前库内 {store.count()} 条。")
    return 0


async def cmd_url(store, web_search, url: str, source: str, published: str) -> int:
    page = await web_search.fetch_page(url, max_chars=6000, timeout=30)
    saved = store.upsert(
        url=page.url,
        title=page.title,
        source=source or "手动抓取",
        published=published,
        content=page.text,
    )
    print(f"{'✓ 已入库' if saved else '✗ 未入库'}：{page.title or page.url}（{len(page.text)} 字）")
    return 0 if saved else 1


async def cmd_query(store, web_search, query: str, pages: int, timeout: float) -> int:
    print(f"搜索：{query}")
    results = await web_search.search_web(query, limit=max(pages * 2, 6), timeout=timeout)
    if not results:
        print("没有搜到结果。")
        return 1
    for item in results:
        store.upsert(
            url=item.url,
            title=item.title,
            source=item.source or "搜索",
            published=item.date,
            content=item.snippet,
            query=query,
        )
    print(f"  摘要入库 {len(results)} 条")

    fetched = 0
    if pages > 0:
        deep = await web_search.deep_research(query, results, pages=pages, max_chars=6000)
        for page in deep:
            if store.upsert(
                url=page.url,
                title=page.title,
                source="网页正文",
                content=page.text,
                query=query,
            ):
                fetched += 1
                print(f"  ✓ 正文：{page.title or page.url}")
    print(f"完成：摘要 {len(results)} 条、正文 {fetched} 篇。当前库内 {store.count()} 条。")
    return 0


# ---------- 入口 ----------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="投喂 / 检查本地知识库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"知识库路径（默认 {DEFAULT_DB}）")
    parser.add_argument("--dir", type=Path, help="导入这个目录下的 .md/.txt")
    parser.add_argument("--url", help="抓取并入库单个网页")
    parser.add_argument("--query", help="联网搜索并入库")
    parser.add_argument("--pages", type=int, default=2, help="--query 时抓几篇正文（默认 2）")
    parser.add_argument("--source", default="", help="--url 的来源标注")
    parser.add_argument("--published", default="", help="--url 的发布日期标注")
    parser.add_argument("--search", help="在库里检索一个词，看能不能命中")
    parser.add_argument("--list", action="store_true", help="列出最近入库的资料（带 id）")
    parser.add_argument("--forget-id", type=int, nargs="+", help="按 id 删除资料（配合 --list 用）")
    parser.add_argument("--limit", type=int, default=5, help="--search 返回条数")
    parser.add_argument("--stats", action="store_true", help="看库内概况")
    parser.add_argument("--prune", action="store_true", help="清掉空壳和过期资料")
    parser.add_argument("--min-chars", type=int, help="导入时的正文长度下限")
    parser.add_argument("--stale-days", type=float, help="--prune 时超过多少天算过期")
    parser.add_argument("--timeout", type=float, default=20.0, help="联网超时（秒）")
    parser.add_argument("--dry-run", action="store_true", help="只显示会写什么，不落库")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        # Windows 控制台默认 GBK，中文输出会直接炸
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)

    if not any(
        [
            args.dir,
            args.url,
            args.query,
            args.search,
            args.stats,
            args.prune,
            args.list,
            args.forget_id,
        ]
    ):
        build_parser().print_help()
        return 0

    knowledge, web_search = _load_plugin_modules()

    if args.prune and not args.dry_run:
        store = knowledge.KnowledgeStore(args.db, stale_days=args.stale_days or 0.0)
        return cmd_prune(store, args.min_chars, args.stale_days)

    # 有意投喂时不套 KNOWLEDGE_MIN_CONTENT_CHARS，除非显式指定
    store = knowledge.KnowledgeStore(args.db, min_content_chars=args.min_chars or 0)

    if args.stats:
        cmd_stats(store)
    if args.list:
        cmd_list(store, args.limit if args.limit != 5 else 40)
    if args.forget_id:
        cmd_forget(store, args.forget_id)
    if args.search:
        code = cmd_search(store, args.search, args.limit)
        if code:
            return code
    if args.dir:
        print(f"导入目录：{args.dir}")
        cmd_import(store, collect_dir(args.dir), args.min_chars or 0, args.dry_run)
    if args.url:
        return asyncio.run(cmd_url(store, web_search, args.url, args.source, args.published))
    if args.query:
        return asyncio.run(cmd_query(store, web_search, args.query, args.pages, args.timeout))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())