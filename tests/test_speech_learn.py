from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.exception import FinishedException

from plugins.speech_learn import handlers, style as style_mod
from plugins.speech_learn.config import Config
from plugins.speech_learn.learn import collect_samples
from plugins.speech_learn.log import SpeechLog


# ---------------------------------------------------------------------------
# 采样过滤
# ---------------------------------------------------------------------------

def test_speech_learning_is_opt_in_by_default() -> None:
    config = Config()
    assert config.speech_learn_enabled is False
    assert config.speech_learn_auto_enabled is False


def _record(text: str, nickname: str = "群友") -> dict:
    return {"t": 0, "g": 1, "u": 2, "n": nickname, "x": text}


def test_collect_samples_filters_noise() -> None:
    records = [
        _record("/img 柴犬"),                       # 命令
        _record("看看这个 https://example.com"),     # 链接
        _record("[CQ:at,qq=123] 来了"),             # CQ 码
        _record("6"),                               # 太短
        _record("长消息" * 150),                    # 超长
        _record("哈哈哈", "A"),
        _record("哈哈哈", "B"),
        _record("哈哈哈", "C"),                     # 同文本第 3 次 → 丢弃
        _record("✨ 签到成功啦！F币+1508", "普通群友"),  # 机器人模板腔
        _record("投食成功，获得8好感度", "某智能体"),     # 机器人名字
        _record("今天天气真不错啊", "D"),
        _record("这把稳了兄弟们", "E"),
    ]
    samples = collect_samples(records, max_messages=100, max_chars=10000)
    assert samples == [
        "A: 哈哈哈",
        "B: 哈哈哈",
        "D: 今天天气真不错啊",
        "E: 这把稳了兄弟们",
    ]


def test_collect_samples_caps() -> None:
    records = [_record(f"消息{i}号内容", f"U{i}") for i in range(50)]
    samples = collect_samples(records, max_messages=10, max_chars=10000)
    assert len(samples) == 10
    assert samples[-1] == "U49: 消息49号内容"  # 取最近的

    records2 = [_record(f"很长一点的记录内容{i}", f"U{i}") for i in range(50)]
    samples2 = collect_samples(records2, max_messages=100, max_chars=200)
    assert sum(len(line) for line in samples2) <= 200


# ---------------------------------------------------------------------------
# 落盘日志
# ---------------------------------------------------------------------------


def test_speech_log_roundtrip(tmp_path) -> None:
    log = SpeechLog(tmp_path / "speech_log", retention_days=14)
    log.append(123, 555001, "小明", "早上好")
    log.append(123, 555002, "小红", "早")
    records = log.recent(10)
    assert [r["x"] for r in records] == ["早上好", "早"]
    assert records[0]["n"] == "小明"
    assert log.count() == 2
    assert log.recent(1) == [records[1]]  # 只取最新一条


def test_speech_log_cleanup(tmp_path) -> None:
    root = tmp_path / "speech_log"
    log = SpeechLog(root, retention_days=3)
    old = root / "2020-01-01.jsonl"
    old.write_text('{"t":0,"g":1,"u":2,"n":"a","x":"旧消息"}\n', encoding="utf-8")
    log.cleanup()
    assert not old.exists()


# ---------------------------------------------------------------------------
# 风格档案
# ---------------------------------------------------------------------------


@pytest.fixture()
def style_file(tmp_path, monkeypatch):
    path = tmp_path / "speech_style.md"
    monkeypatch.setattr(style_mod, "STYLE_PATH", path)
    monkeypatch.setattr(style_mod, "_cache", None)
    monkeypatch.setattr(style_mod._config, "speech_learn_enabled", True)
    monkeypatch.setattr(style_mod._config, "speech_learn_inject", True)
    return path


def test_style_block_lifecycle(style_file) -> None:
    assert style_mod.style_block() == ""  # 还没学过
    style_mod.write_style("## 说话特征\n- 短句多，经常不带标点")
    block = style_mod.style_block()
    assert "群友说话方式参考" in block
    assert "短句多" in block
    # mtime 热更新
    style_mod.write_style("## 说话特征\n- 新学的")
    assert "新学的" in style_mod.style_block()
    # 关闭注入
    monkey_off = pytest.MonkeyPatch()
    monkey_off.setattr(style_mod._config, "speech_learn_inject", False)
    assert style_mod.style_block() == ""
    monkey_off.undo()
    assert style_mod.remove_style() is True
    assert style_mod.style_block() == ""
    assert style_mod.remove_style() is False


def test_style_block_truncates_at_line(style_file) -> None:
    style_mod.write_style("第一行内容\n" * 50)
    block = style_mod.style_block(max_chars=60)
    assert len(style_mod._load(60)) <= 60


# ---------------------------------------------------------------------------
# /learn_speech 命令
# ---------------------------------------------------------------------------


def _admin_event(group: bool = True) -> GroupMessageEvent:
    sender = {"user_id": 555001, "nickname": "测试", "role": "admin" if group else "member"}
    return GroupMessageEvent(
        time=1700000000,
        self_id=10000,
        post_type="message",
        sub_type="normal",
        user_id=555001,
        message_type="group",
        message_id=1,
        message=Message("/learn_speech"),
        original_message=Message("/learn_speech"),
        raw_message="/learn_speech",
        font=0,
        sender=sender,
        group_id=123456,
        to_me=False,
    )


class FakeMatcher:
    def __init__(self) -> None:
        self.sent: list = []
        self.final = None

    async def send(self, message):
        self.sent.append(message)

    async def finish(self, message=None):
        self.final = message
        raise FinishedException


def test_learn_command_runs_and_writes(style_file, monkeypatch) -> None:
    records = [_record(f"群友的话{i}", f"U{i}") for i in range(30)]

    class FakeLog:
        def recent(self, n):
            return records

        def count(self):
            return len(records)

    async def fake_learner(persona, samples):
        assert persona  # 带上了人格文件
        assert len(samples) >= 10
        return "## 说话特征\n- 学到了"

    monkeypatch.setattr(handlers, "log", FakeLog())
    monkeypatch.setattr(handlers, "learner", fake_learner)
    monkeypatch.setattr(handlers, "_last_learn", 0.0)
    monkeypatch.setattr(handlers.plugin_config, "speech_learn_enabled", True)
    monkeypatch.setattr(handlers.plugin_config, "speech_learn_min_messages", 10)
    monkeypatch.setattr(handlers.plugin_config, "speech_learn_cooldown_seconds", 0)

    matcher = FakeMatcher()
    with pytest.raises(FinishedException):
        asyncio.run(handlers._handle_learn(_admin_event(), matcher, Message("")))
    assert "学完了" in matcher.final
    assert style_file.read_text(encoding="utf-8").strip().endswith("学到了")


def test_learn_command_needs_more_data(style_file, monkeypatch) -> None:
    class FakeLog:
        def recent(self, n):
            return []

    monkeypatch.setattr(handlers, "log", FakeLog())
    monkeypatch.setattr(handlers, "learner", None)
    monkeypatch.setattr(handlers.plugin_config, "speech_learn_enabled", True)
    monkeypatch.setattr(handlers.plugin_config, "speech_learn_min_messages", 100)

    matcher = FakeMatcher()
    with pytest.raises(FinishedException):
        asyncio.run(handlers._handle_learn(_admin_event(), matcher, Message("")))
    assert "还不够" in matcher.final


def test_learn_command_off(style_file, monkeypatch) -> None:
    style_mod.write_style("旧档案")
    monkeypatch.setattr(handlers.plugin_config, "speech_learn_enabled", True)
    matcher = FakeMatcher()
    with pytest.raises(FinishedException):
        asyncio.run(handlers._handle_learn(_admin_event(), matcher, Message("off")))
    assert "停止参考" in matcher.final
    assert not style_file.exists()


# ---------------------------------------------------------------------------
# 每日自动学说话
# ---------------------------------------------------------------------------


def test_auto_due_gate() -> None:
    due = datetime(2026, 10, 24, 4, 30)
    assert handlers._auto_due(due, "", 4) is True
    assert handlers._auto_due(due, "2026-10-24", 4) is False  # 今天学过了
    assert handlers._auto_due(due, "2026-10-23", 5) is False  # 钟点不对
    assert handlers._auto_due(datetime(2026, 10, 24, 3, 59), "2026-10-23", 4) is False


def test_auto_learn_once_writes_style(style_file, monkeypatch) -> None:
    records = [_record(f"群友的话{i}", f"U{i}") for i in range(30)]

    class FakeLog:
        def recent(self, n):
            return records

    async def fake_learner(persona, samples):
        assert persona  # 带上了人格文件
        assert len(samples) >= 10
        return "## 说话特征\n- 自动学到的"

    monkeypatch.setattr(handlers, "log", FakeLog())
    monkeypatch.setattr(handlers, "learner", fake_learner)
    monkeypatch.setattr(handlers.plugin_config, "speech_learn_min_messages", 10)

    result = asyncio.run(handlers._auto_learn_once())
    assert "30 条" in result
    assert style_file.read_text(encoding="utf-8").strip().endswith("自动学到的")


def test_auto_learn_once_skips_when_sparse(style_file, monkeypatch) -> None:
    class FakeLog:
        def recent(self, n):
            return []

    async def fail_learner(persona, samples):  # 不该被调到
        raise AssertionError("记录不够就不该学")

    monkeypatch.setattr(handlers, "log", FakeLog())
    monkeypatch.setattr(handlers, "learner", fail_learner)
    monkeypatch.setattr(handlers.plugin_config, "speech_learn_min_messages", 100)

    result = asyncio.run(handlers._auto_learn_once())
    assert "跳过" in result
    assert not style_file.exists()
