from __future__ import annotations

import json

from plugins.self_study.study import load_records, parse_topics
from plugins.self_study.config import Config


def _line(text: str, nickname: str = "群友") -> str:
    return json.dumps({"t": 0, "g": 1, "u": 2, "n": nickname, "x": text}, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# 话题提炼结果的清洗
# ---------------------------------------------------------------------------

def test_self_study_does_not_use_group_logs_by_default() -> None:
    assert Config().speech_learn_enabled is False


def test_parse_topics_cleans_and_dedups() -> None:
    text = (
        "1. 战雷 新版本\n"
        "2）「商店插件 折扣」\n"
        "3、 COD 新赛季\n"
        "战雷 新版本\n"                                    # 重复
        "？\n"                                            # 太短
        "4. 这是一条特别长特别长特别长特别长特别长特别长已经超过三十字的查询词\n"  # 超长
    )
    assert parse_topics(text, limit=10) == [
        "战雷 新版本",
        "商店插件 折扣",
        "COD 新赛季",
    ]


def test_parse_topics_respects_limit() -> None:
    text = "甲话题\n乙话题\n丙话题\n丁话题"
    assert parse_topics(text, limit=2) == ["甲话题", "乙话题"]
    assert parse_topics("", limit=3) == []
    assert parse_topics("正常话题", limit=0) == []


# ---------------------------------------------------------------------------
# 群聊记录读取
# ---------------------------------------------------------------------------


def test_load_records_reads_recent_files(tmp_path) -> None:
    (tmp_path / "2026-10-22.jsonl").write_text(_line("前天的"), encoding="utf-8")
    (tmp_path / "2026-10-23.jsonl").write_text(
        _line("昨天的") + "{坏行\n",  # 坏行直接跳过
        encoding="utf-8",
    )
    (tmp_path / "notes.txt").write_text("不是记录", encoding="utf-8")

    assert [r["x"] for r in load_records(tmp_path, days_back=1, max_messages=100)] == [
        "昨天的"
    ]
    assert [
        r["x"] for r in load_records(tmp_path, days_back=2, max_messages=100)
    ] == ["前天的", "昨天的"]
    # 超出上限时只留最新的
    assert [r["x"] for r in load_records(tmp_path, days_back=2, max_messages=1)] == [
        "昨天的"
    ]
