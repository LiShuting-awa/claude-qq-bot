from __future__ import annotations

import asyncio
import random
import time

from plugins.claude_chat.rhythm import Rhythm, RhythmConfig


def _rhythm(**kwargs) -> Rhythm:
    config = RhythmConfig(**kwargs)
    # 固定随机种子，测试结果可复现
    return Rhythm(config, rng=random.Random(1234))


def test_short_reply_stays_one_message() -> None:
    rhythm = _rhythm()
    assert rhythm.split(["说事。"]) == ["说事。"]


def test_long_reply_is_split_into_bursts() -> None:
    rhythm = _rhythm()
    # 要长过分条目标（默认 90 字）才会拆开
    text = "".join(f"这是第{index}句话，写得稍微长一点。" for index in range(12))
    assert len(text) > 90
    pieces = rhythm.split([text])
    assert len(pieces) > 1
    assert "".join(pieces).replace("\n", "") == text


def test_code_blocks_are_never_split() -> None:
    rhythm = _rhythm()
    code = "```python\n" + "print('这是一段很长的代码行，用来把长度撑过阈值')\n" * 6 + "```"
    assert rhythm.split([code]) == [code]


def test_lists_are_not_split() -> None:
    rhythm = _rhythm()
    listing = "· 第一条有点长的内容说明\n· 第二条有点长的内容说明\n· 第三条有点长的内容说明"
    assert rhythm.split([listing]) == [listing]


def test_burst_count_is_capped() -> None:
    rhythm = _rhythm(burst_max_extra=2)
    text = "。".join(f"这是第 {index} 句比较长的话用来撑长度" for index in range(40)) + "。"
    pieces = rhythm.split([text])
    assert len(pieces) <= 3


def test_burst_disabled_keeps_chunks() -> None:
    rhythm = _rhythm(burst_enabled=False)
    text = "第一句话在这里。第二句话也在。第三句话跟着来。第四句话收尾了。第五句话补充一下。"
    assert rhythm.split([text]) == [text]


def test_read_delay_grows_with_length_and_is_capped() -> None:
    rhythm = _rhythm(read_max=3.0)
    short = rhythm.read_delay("在")
    long = rhythm.read_delay("很长的消息" * 100)
    assert 0 <= short <= 3.0
    assert long <= 3.0
    assert long >= short


def test_typing_delay_is_bounded() -> None:
    rhythm = _rhythm(typing_min=0.4, typing_max=4.5)
    assert 0.4 * 0.75 <= rhythm.typing_delay("一句话") <= 4.5 * 1.25
    assert rhythm.typing_delay("很长的话" * 200) <= 4.5 * 1.25


def test_wait_is_noop_when_disabled() -> None:
    rhythm = _rhythm(enabled=False)

    async def scenario() -> float:
        started = time.monotonic()
        await rhythm.wait_read("很长很长的消息" * 50)
        await rhythm.wait_typing("很长很长的回复" * 50)
        return time.monotonic() - started

    assert asyncio.run(scenario()) < 0.1


def test_wait_actually_waits_when_enabled() -> None:
    rhythm = _rhythm(enabled=True, read_max=0.2, typing_max=0.2, typing_min=0.15, jitter=0)

    async def scenario() -> float:
        started = time.monotonic()
        await rhythm.wait_read("你好")
        return time.monotonic() - started

    assert asyncio.run(scenario()) >= 0.1