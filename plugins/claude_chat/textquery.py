"""中文查询切词：给 FTS5 的 trigram 索引生成真正能命中的检索词。

背景：trigram 索引把正文切成所有相邻的三字窗口，所以**查询词也必须至少三个字**
才可能命中。中文没有空格，原来的实现把整句中文当成一个短语去匹配，
「战争雷霆最新版本」这种正常问法一条都搜不到，只有用户自己敲了空格才行。

这里把中文长串拆成重叠的三字窗口，短词（两个字）交给 LIKE 兜底。
英文/数字按 ≥3 个字符进 FTS，两个字符的同样走 LIKE。
"""

from __future__ import annotations

import re

# 基本区 + 扩展 A 区的汉字
_CJK = r"一-鿿㐀-䶿"
_LATIN = r"A-Za-z0-9_"
_TOKEN_RE = re.compile(rf"[{_CJK}]+|[{_LATIN}]+")

GRAM = 3
"""FTS5 trigram 索引能命中的最小长度。"""

MAX_FTS_TERMS = 12
"""最多送多少个检索词给 FTS，防止长句拼出上百个 OR。"""

MAX_LIKE_TERMS = 4
"""LIKE 兜底最多用几个短词。"""

MAX_KEYWORD_TERMS = 2
"""一段连续中文里最多挑几个二字词给 LIKE 兜底（保留首尾，长句两头都照顾）。"""

# 疑问/功能词的二字组合。它们在中文里出现频率极高、信息量为零，
# 却能跟任何一篇文档凑出「重叠」，导致「老六是什么意思」这种问句
# 命中的是随便一篇写着「是什么意思」的资料（实测命中了 DeepSeek 那篇）。
# 这些组合不进 FTS 检索词，也不作为 LIKE 兜底词。
_STOP_GRAMS = frozenset(
    {
        # 疑问词
        "什么",
        "是什",
        "么意",
        "意思",
        "是谁",
        "怎么",
        "么样",
        "怎样",
        "为什",
        "如何",
        "哪些",
        "哪个",
        "哪里",
        "多少",
        "几个",
        # 指代 / 判断 / 口语填充
        "这是",
        "这个",
        "那个",
        "了是",
        "就是",
        "不是",
        "一样",
        "这样",
        "那样",
        "的话",
        # 高频虚词组合，做检索词只会召回噪音
        "可以",
        "不能",
        "没有",
        "我们",
        "你们",
        "他们",
        "自己",
        "一起",
        "一下",
        "一点",
        "一直",
        "已经",
        "需要",
        "觉得",
        "时候",
        "现在",
        "然后",
        "而且",
        "但是",
        "因为",
        "所以",
        "如果",
        "虽然",
        "可是",
        "不过",
        "其实",
    }
)


def _windows(run: str, size: int = GRAM) -> list[str]:
    """把一段连续中文切成重叠的定长窗口；短于窗口长度就整段返回。"""
    if len(run) <= size:
        return [run]
    return [run[index : index + size] for index in range(len(run) - size + 1)]


# 单字虚词/指代。二字词里沾上它们基本都是问句的壳（「这游」「很抽」）。
# 有实义的字一律不进这张表：「更新」「模型」「弹药」「要塞」「和平」都得留住。
_FUNCTION_CHARS = frozenset("这那哪我你他她它们的是在了么什怎吗呢吧啊呀很就都还也")


def _is_question_fragment(gram: str) -> bool:
    """三字窗口里只要含一个疑问/功能词组合，就认为它是问句的壳。

    「有什么」「什么新」「怎么玩」这类窗口出现在几乎每篇资料里，
    留着它们只会让「老六是什么意思」命中一篇写着「是什么」的无关资料。
    真正的关键词（「塔科夫」）在窗口里的相邻两个字都不是功能词，不会被误伤。
    """
    return any(pair in _STOP_GRAMS for pair in _windows(gram, 2))


def _informative_windows(run: str) -> list[str]:
    """切三字窗口，并去掉问句框架拼出来的那些。"""
    return [gram for gram in _windows(run, GRAM) if not _is_question_fragment(gram)]


def _keyword_terms(run: str, limit: int) -> list[str]:
    """给一段中文挑 LIKE 兜底用的二字词。

    两个汉字凑不出 trigram，FTS 一定搜不到，只能靠 LIKE。挑的是**有实义的**
    二字组合：「老六是什么意思」该搜的是「老六」，而从整段开头硬切会切出
    「这游」这种问句壳碎片。取样保留首尾，长句两头都能照顾到。
    """
    candidates = [
        gram
        for gram in _windows(run, 2)
        if gram not in _STOP_GRAMS and not any(char in _FUNCTION_CHARS for char in gram)
    ]
    if not candidates:
        return []
    if len(candidates) <= limit:
        return candidates
    return [candidates[0], *_sample(candidates[1:], limit - 1)]


def _sample(items: list[str], limit: int) -> list[str]:
    """均匀取样，保留首尾，避免长句只取到开头几个词。"""
    if len(items) <= limit:
        return items
    if limit <= 1:
        return items[:1]
    step = (len(items) - 1) / (limit - 1)
    picked = [items[round(index * step)] for index in range(limit)]
    seen: list[str] = []
    for item in picked:
        if item not in seen:
            seen.append(item)
    return seen


def build(query: str, *, max_terms: int = MAX_FTS_TERMS) -> tuple[str, list[str]]:
    """把一句话拆成 (FTS 表达式, LIKE 兜底词)。

    FTS 表达式形如 ``"战争雷" OR "争雷霆"``；取不到可命中的词时返回空串。

    中文长句除了三字窗口，还会挑出开头的二字词给 LIKE 兜底：
    「老六是什么意思」里真正该搜的是「老六」，而两个字进不了 trigram 索引。
    """
    text = query or ""
    fts_terms: list[str] = []
    short_terms: list[str] = []

    for token in _TOKEN_RE.findall(text):
        if _TOKEN_RE.fullmatch(token) is None:  # pragma: no cover - 正则已保证
            continue
        if token[0].isascii():
            # 英文/数字：三个字符以上才能进 trigram 索引
            if len(token) >= GRAM:
                fts_terms.append(token)
            elif len(token) >= 2:
                short_terms.append(token)
            continue

        if len(token) >= GRAM:
            fts_terms.extend(_informative_windows(token))
            # 长句里的二字词（尤其句首那个）trigram 一定搜不到，得留一条后路
            short_terms.extend(_keyword_terms(token, MAX_KEYWORD_TERMS))
        elif len(token) >= 2:
            short_terms.append(token)

    fts_terms = _sample(fts_terms, max_terms)
    like_terms = _sample(short_terms, MAX_LIKE_TERMS)

    expression = " OR ".join(f'"{term}"' for term in fts_terms)
    return expression, like_terms


def gram_hits(query: str, text: str) -> int:
    """查询里的三字窗口在 text 中出现了几个——用来做粗排相关度。"""
    if not query or not text:
        return 0
    grams: list[str] = []
    for token in _TOKEN_RE.findall(query):
        if token[0].isascii():
            if len(token) >= 2:
                grams.append(token.casefold())
        elif len(token) >= 2:
            grams.extend(_windows(token, 2))
    if not grams:
        return 0
    haystack = text.casefold()
    return sum(1 for gram in grams if gram in haystack)