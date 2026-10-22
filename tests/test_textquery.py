from __future__ import annotations

from plugins.claude_chat.textquery import build, gram_hits


def test_chinese_sentence_becomes_overlapping_windows() -> None:
    """中文长句必须拆成三字窗口，否则 trigram 索引永远命不中。"""
    expression, _ = build("战争雷霆最新版本")
    assert '"战争雷"' in expression
    assert '"新版本"' in expression


def test_question_shell_is_not_a_search_term() -> None:
    """「是什么」这类问句壳不能进检索词。

    它出现在几乎每篇资料里，留着就会让「老六是什么意思」命中一篇
    写着「DeepSeek 是什么」的无关资料——这正是实测踩到的 bug。
    """
    expression, like_terms = build("老六是什么意思")
    assert '"是什么"' not in expression
    assert '"什么意"' not in expression
    assert '"么意思"' not in expression
    # 真正该搜的「老六」只有两个字，进不了 trigram，必须走 LIKE 兜底
    assert like_terms == ["老六"]


def test_keyword_inside_long_question_still_wins() -> None:
    """问句壳被丢掉后，句子里的实义词仍然要留下。"""
    expression, like_terms = build("塔科夫新手怎么玩")
    assert '"塔科夫"' in expression
    assert '"怎么"' not in expression
    assert "塔科" in like_terms


def test_function_char_bigrams_are_not_like_terms() -> None:
    """从问句开头硬切的二字碎片（「这游」）不该当检索词。"""
    _, like_terms = build("这游戏怎么玩")
    assert "这游" not in like_terms
    assert "游戏" in like_terms


def test_short_chinese_words_fall_back_to_like() -> None:
    expression, like_terms = build("战争雷霆 更新")
    assert '"战争雷"' in expression
    # 「更新」只有两个字，进不了 trigram 索引，交给 LIKE
    assert "更新" in like_terms
    assert '"更新"' not in expression


def test_ascii_words_are_kept() -> None:
    expression, _ = build("Sky Odyssey")
    assert '"Sky"' in expression
    assert '"Odyssey"' in expression


def test_two_letter_ascii_word_goes_to_like() -> None:
    expression, like_terms = build("ai")
    assert expression == ""
    assert like_terms == ["ai"]


def test_empty_query() -> None:
    assert build("") == ("", [])
    assert build("   ") == ("", [])


def test_long_query_is_capped() -> None:
    expression, _ = build("战" * 200)
    assert expression.count(" OR ") + 1 <= 12


def test_gram_hits_counts_overlap() -> None:
    assert gram_hits("战争雷霆", "战争雷霆 新版本") > 0
    assert gram_hits("战争雷霆", "完全无关的内容") == 0
    assert gram_hits("", "任何内容") == 0