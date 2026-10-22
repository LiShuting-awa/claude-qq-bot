from __future__ import annotations

from plugins.claude_chat import community


def test_detect_game() -> None:
    assert community.detect_game("最近战争雷霆有什么新载具") == "战争雷霆"
    assert community.detect_game("塔科夫这周 wipe 了吗") == "逃离塔科夫"
    assert community.detect_game("战地新作怎么样") == "战地"
    assert community.detect_game("wtf lol") == ""
    assert community.detect_game("普通聊天") == ""


def test_format_hot() -> None:
    data = {
        "B站热搜": [community.HotItem("测试热搜", "https://example.com", "B站热搜", "123")],
        "抖音热榜": [community.HotItem("测试抖音", "https://example.com/dy", "抖音热榜")],
    }
    text = community.format_hot(data)
    assert "B站热搜" in text
    assert "测试热搜" in text
    assert "抖音热榜" in text


def test_format_game() -> None:
    from plugins.claude_chat.web_search import SearchResult

    results = [
        SearchResult(
            title="战争雷霆新版本",
            url="https://example.com/wt",
            snippet="新载具",
            source="Bilibili",
            date="2026-10-21",
        )
    ]
    text = community.format_game("战争雷霆", results)
    assert "战争雷霆" in text
    assert "新版本" in text
    assert "https://example.com/wt" in text
