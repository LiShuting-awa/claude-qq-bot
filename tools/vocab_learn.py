#!/usr/bin/env python
"""词汇投喂：给出一份短语清单，让机器人**自己说一遍**，再写进知识库。

和 kb_seed.py 的区别：这里的内容不是直接抄进去的，而是让机器人用自己的人设
（persona.md）把每个短语「说出口」——解释意思、给出他自己会怎么用的例句，
然后把这些他亲口说的话连同短语本身写进 data/knowledge.db。

用法（在项目根目录执行）：

    python tools/vocab_learn.py                       # 用内置的台湾常用语清单
    python tools/vocab_learn.py --file my_phrases.md  # 从文件读短语（每行「短语 — 简释」）
    python tools/vocab_learn.py --phrases "真的假的,齁,水啦"
    python tools/vocab_learn.py --dry-run             # 只看他要说的话，不落库
    python tools/vocab_learn.py --search 真的假的     # 落库后自检检索能不能命中

凭据读 .env；进程里已有的 ANTHROPIC_* 环境变量优先（跟 bot 行为一致）。
这个脚本不经过 NoneBot，单独跑。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.common.llm import build_client, has_credentials  # noqa: E402


def _load_knowledge():
    """按路径加载 knowledge 模块，绕开 plugins.claude_chat 包的 NoneBot 初始化。

    knowledge.py 用相对导入拿 textquery，所以要先造一个假包挂进去（同 kb_seed.py）。
    """
    plugin_dir = ROOT / "plugins" / "claude_chat"
    package = types.ModuleType("_vocab")
    package.__path__ = [str(plugin_dir)]  # type: ignore[attr-defined]
    sys.modules["_vocab"] = package

    def load(name: str):
        spec = importlib.util.spec_from_file_location(f"_vocab.{name}", plugin_dir / f"{name}.py")
        if spec is None or spec.loader is None:  # pragma: no cover - 只会在文件缺失时出现
            raise RuntimeError(f"加载不了 {name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"_vocab.{name}"] = module
        spec.loader.exec_module(module)
        return module

    load("textquery")
    return load("knowledge")

DEFAULT_DB = ROOT / "data" / "knowledge.db"
PERSONA_PATH = ROOT / "persona.md"

# 内置清单：常用台湾用语（含几句日常台语借词）。「—」后面是给模型的参考释义，
# 只用来保证意思不出错，例句和解释仍由机器人自己组织。
BUILTIN_PHRASES = """
真的假的 — 真的吗？表示惊讶、不敢相信
欸 — 语气词，叫人或表示惊讶
齁 — 表示受不了、有点无奈
有够 — 非常、很，如「有够夸张」
超扯 — 太离谱了
好尬 — 好尴尬
是哦 — 是这样啊，平静地接一句
干嘛啦 — 干什么啦
可以哦 — 不错嘛，有点认可的意思
好哦 — 好的
蛮的 — 「蛮……的」，挺……的
拍谢 — 台语「歹势」，不好意思、抱歉
呷饱没 — 台语问候，吃饱了吗
水啦 — 台语，漂亮、好棒
安呢 — 台语，这样啊
拢总 — 台语，总共
免客气 — 台语，不用客气
有影无 — 台语，真的假的？
""".strip()


# ---------- .env 与凭据 ----------


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_AUTH_TOKEN_FILE",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_CUSTOM_HEADERS",
    "CLAUDE_MODEL",
)


def load_credentials() -> dict[str, str]:
    """进程环境变量优先，.env 兜底——跟 bot 的取值顺序一致。"""
    import os

    env = read_dotenv(ROOT / ".env")
    return {key: os.environ.get(key, "").strip() or env.get(key, "") for key in _KEYS}


def parse_headers(raw: str) -> dict[str, str]:
    text = (raw or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        return {str(k): str(v) for k, v in json.loads(text).items()}
    headers: dict[str, str] = {}
    for part in re.split(r"[\n,]+", text):
        name, separator, value = part.partition(":")
        if separator and name.strip():
            headers[name.strip()] = value.strip()
    return headers


# ---------- 短语清单 ----------


def parse_phrases(text: str) -> list[dict[str, str]]:
    """每行一条：「短语 — 参考释义」，释义可省略。"""
    phrases: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip().lstrip("-*0123456789.、 ）(（").strip()
        if not line:
            continue
        if "—" in line:
            phrase, gloss = line.split("—", 1)
        elif "—" not in line and " - " in line:
            phrase, gloss = line.split(" - ", 1)
        else:
            phrase, gloss = line, ""
        phrase = phrase.strip()
        gloss = gloss.strip()
        if not 1 <= len(phrase) <= 20 or phrase in seen:
            continue
        seen.add(phrase)
        phrases.append({"phrase": phrase, "gloss": gloss})
    return phrases


# ---------- 让机器人自己说 ----------


def _system_prompt() -> str:
    return (
        "你是 persona 里描述的那个角色本人。现在有人给了你一份台湾常用短语清单，"
        "你想把它们学起来、以后在群里用得上。\n"
        "对每个短语，你要：\n"
        "1. 用自己的话说清这个短语是什么意思、什么场合用（一两句，口语一点，"
        "不要词典腔，不要「首先」「综上所述」）。\n"
        "2. 用你自己的口气造 1~2 句你会真的在群里发的话，把短语自然地用进去。"
        "例句要短，像平时聊天打字，不要小作文，不要感叹号刷屏。\n"
        "意思拿不准就老实说不确定，不要编。\n\n"
        "只输出 JSON 数组，不要别的解释。每个元素：\n"
        '{"phrase": "短语", "meaning": "你自己的解释", "examples": ["你说的例句1", "例句2"]}'
    )


def _user_prompt(phrases: list[dict[str, str]], persona: str) -> str:
    lines = [
        f"- {item['phrase']}" + (f"（参考释义：{item['gloss']}）" if item["gloss"] else "")
        for item in phrases
    ]
    return f"[你的人格说明]\n{persona[:2000]}\n\n[要学的短语]\n" + "\n".join(lines)


async def ask_bot(
    phrases: list[dict[str, str]], *, model: str
) -> list[dict]:
    creds = load_credentials()
    if not has_credentials(
        api_key=creds["ANTHROPIC_API_KEY"],
        auth_token=creds["ANTHROPIC_AUTH_TOKEN"],
        auth_token_file=creds["ANTHROPIC_AUTH_TOKEN_FILE"],
    ):
        raise RuntimeError("未配置 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN（.env 或环境变量）")

    persona = ""
    if PERSONA_PATH.is_file():
        persona = PERSONA_PATH.read_text(encoding="utf-8").strip()

    client = build_client(
        api_key=creds["ANTHROPIC_API_KEY"],
        auth_token=creds["ANTHROPIC_AUTH_TOKEN"],
        auth_token_file=creds["ANTHROPIC_AUTH_TOKEN_FILE"],
        base_url=creds["ANTHROPIC_BASE_URL"],
        custom_headers=parse_headers(creds["ANTHROPIC_CUSTOM_HEADERS"]),
        timeout=180,
    )
    response = await client.messages.create(
        model=model.strip() or "claude-sonnet-4-6",
        max_tokens=4000,
        system=_system_prompt(),
        messages=[{"role": "user", "content": _user_prompt(phrases, persona)}],
        timeout=180,
    )
    text = "".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text" and getattr(block, "text", None)
    ).strip()

    # 容忍模型把 JSON 包进代码围栏
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise RuntimeError(f"模型输出里没有 JSON 数组：{text[:200]}")
    items = json.loads(text[start : end + 1])
    if not isinstance(items, list):
        raise RuntimeError("模型输出不是 JSON 数组")
    return items


# ---------- 入库 ----------


def store_entries(store: KnowledgeStore, entries: list[dict], *, source: str, dry_run: bool) -> int:
    written = 0
    glossary_rows: list[tuple[str, str]] = []
    for item in entries:
        phrase = str(item.get("phrase") or "").strip()
        meaning = " ".join(str(item.get("meaning") or "").split())
        examples = [" ".join(str(e).split()) for e in item.get("examples") or [] if str(e).strip()]
        if not phrase or not meaning:
            continue

        lines = [f"「{phrase}」：{meaning}"]
        if examples:
            lines.append("他会这样说：")
            lines.extend(f"- {example}" for example in examples)
        content = "\n".join(lines)

        if dry_run:
            print(f"  [dry-run] {phrase}（{len(content)} 字）")
            print(f"      {content}")
            written += 1
        elif store.upsert(
            url=f"curated://vocab/taiwanese/{phrase}",
            title=f"台湾用语·{phrase}",
            source=source,
            content=content,
            query=f"台湾用语 {phrase}",
        ):
            print(f"  ✓ {phrase} → {len(content)} 字")
            written += 1
        else:
            print(f"  ✗ 未入库：{phrase}")
        glossary_rows.append((phrase, meaning))

    # 再存一份总表，方便「台湾用语怎么说」这类整体提问命中
    if glossary_rows:
        table = "\n".join(f"- 「{phrase}」{meaning}" for phrase, meaning in glossary_rows)
        index_content = "机器人自己学过一遍的台湾常用短语，他在群里会用：\n" + table
        if dry_run:
            print(f"  [dry-run] 总表（{len(glossary_rows)} 条）")
            written += 1
        elif store.upsert(
            url="curated://vocab/taiwanese/index",
            title="台湾常用短语·他自己的说法",
            source=source,
            content=index_content,
            query="台湾用语 台语 常用短语",
        ):
            print(f"  ✓ 总表（{len(glossary_rows)} 条）")
            written += 1
    return written


# ---------- 入口 ----------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="给出短语清单，让机器人自己说一遍并写进知识库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="知识库路径")
    parser.add_argument("--file", type=Path, help="从文件读短语，每行「短语 — 参考释义」")
    parser.add_argument("--phrases", help="逗号分隔的短语，覆盖内置清单")
    parser.add_argument("--source", default="词汇·台湾用语", help="来源标注")
    parser.add_argument("--model", default="", help="模型，默认读 CLAUDE_MODEL")
    parser.add_argument("--search", help="落库后用这个词自检检索")
    parser.add_argument("--dry-run", action="store_true", help="只看他要说的话，不落库")
    return parser


async def main_async(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    knowledge = _load_knowledge()

    if args.file:
        text = args.file.read_text(encoding="utf-8")
    elif args.phrases:
        text = "\n".join(args.phrases.split(","))
    else:
        text = BUILTIN_PHRASES

    phrases = parse_phrases(text)
    if not phrases:
        print("没有解析到短语。")
        return 1
    print(f"要学的短语 {len(phrases)} 个，让机器人自己说……")

    entries = await ask_bot(phrases, model=args.model or load_credentials()["CLAUDE_MODEL"])
    known = {item["phrase"] for item in phrases}
    entries = [item for item in entries if str(item.get("phrase") or "").strip() in known]
    if not entries:
        print("机器人没有说出可用的内容。")
        return 1
    print(f"他说了 {len(entries)} 个：\n")
    for item in entries:
        examples = " / ".join(str(e) for e in item.get("examples") or [])
        print(f"  「{item.get('phrase')}」{item.get('meaning', '')}")
        if examples:
            print(f"      例：{examples}")
    print()

    if args.dry_run:
        return 0

    store = knowledge.KnowledgeStore(args.db, min_content_chars=0)
    written = store_entries(store, entries, source=args.source, dry_run=False)
    print(f"\n入库 {written} 条，当前库内 {store.count()} 条。")

    if args.search:
        rows = store.search(args.search, limit=3)
        if rows:
            print(f"自检「{args.search}」命中 {len(rows)} 条，第一条：{rows[0]['title']}")
        else:
            print(f"自检「{args.search}」没命中。")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
