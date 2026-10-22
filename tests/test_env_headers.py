"""ANTHROPIC_CUSTOM_HEADERS 的两种写法都要能用。

原来是纯 `dict[str, str]`，NoneBot 的配置源对复杂字段强制 json.loads，读到
`x-provider: relay` 这种（也有人在 shell 里就这么设）直接 SettingsError，
整个插件加载不起来。这里同时锁住解析器和配置源的取数路径。
"""

from __future__ import annotations

import pytest
from nonebot.config import BaseSettings
from pydantic import ValidationError

from plugins.claude_chat.config import Config
from plugins.common.env import parse_header_map


def test_json_object_is_accepted() -> None:
    assert parse_header_map('{"x-provider": "relay"}') == {"x-provider": "relay"}


def test_header_lines_are_accepted() -> None:
    assert parse_header_map("x-provider: relay") == {"x-provider": "relay"}


def test_multiple_headers_split_on_comma_or_newline() -> None:
    expected = {"x-provider": "relay", "x-team": "bot"}
    assert parse_header_map("x-provider: relay, x-team: bot") == expected
    assert parse_header_map("x-provider: relay\nx-team: bot") == expected


def test_value_keeps_its_colons() -> None:
    assert parse_header_map("x-url: https://relay.example.com") == {
        "x-url": "https://relay.example.com"
    }


def test_empty_means_no_headers() -> None:
    assert parse_header_map("") == {}
    assert parse_header_map("   ") == {}


def test_dict_passes_through_untouched() -> None:
    headers = {"x-provider": "relay"}
    assert parse_header_map(headers) is headers


def test_unparsable_value_is_reported() -> None:
    # 写错了要报出来，不能被当成「没配请求头」静悄悄吞掉
    with pytest.raises(ValueError):
        parse_header_map("relay")


def test_broken_json_names_the_problem() -> None:
    with pytest.raises(ValueError):
        parse_header_map('{"x-provider": ')


def test_config_accepts_both_forms() -> None:
    assert Config(anthropic_custom_headers={"x-provider": "relay"}).anthropic_custom_headers == {
        "x-provider": "relay"
    }
    assert Config(anthropic_custom_headers="x-provider: relay").anthropic_custom_headers == {
        "x-provider": "relay"
    }
    assert Config().anthropic_custom_headers == {}


def test_broken_json_in_env_var_fails_loudly() -> None:
    with pytest.raises(ValidationError):
        Config(anthropic_custom_headers='{"x-provider": ')


def test_env_var_in_header_form_reaches_the_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """走一遍 NoneBot 读环境变量的真实路径：不能抛 SettingsError，且结果是 dict。"""
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", "x-provider: relay\nx-team: bot")

    values = BaseSettings._settings_build_values(
        Config,
        {},
        env_file=None,
        env_file_encoding="utf-8",
        env_nested_delimiter=None,
    )
    config = Config(**{k: v for k, v in values.items() if k in Config.model_fields})

    assert config.anthropic_custom_headers == {"x-provider": "relay", "x-team": "bot"}


def test_json_env_var_still_reaches_the_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", '{"x-provider": "relay"}')

    values = BaseSettings._settings_build_values(
        Config,
        {},
        env_file=None,
        env_file_encoding="utf-8",
        env_nested_delimiter=None,
    )
    config = Config(**{k: v for k, v in values.items() if k in Config.model_fields})

    assert config.anthropic_custom_headers == {"x-provider": "relay"}