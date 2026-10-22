"""环境变量解析小工具：`.env` 里写附加请求头不必非得是 JSON。"""

from __future__ import annotations

import json
import re
from typing import Annotated, Any

from pydantic import BeforeValidator

_HEADER_SEPARATOR = re.compile(r"[\n,]+")


def parse_header_map(value: Any) -> Any:
    """把附加请求头解析成 dict[str, str]。

    支持 `.env` 里常见的三种写法：
        ANTHROPIC_CUSTOM_HEADERS={"x-provider":"relay"}
        ANTHROPIC_CUSTOM_HEADERS=x-provider: relay
        ANTHROPIC_CUSTOM_HEADERS=x-provider: relay, x-team: bot

    空值表示不加任何头；解析不出东西就报错，免得写错了还静悄悄不生效。
    """
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return {}
    if text.startswith("{"):
        # 交给 json 抛错，这样语法写错时能看到具体位置
        return json.loads(text)

    headers: dict[str, str] = {}
    for part in _HEADER_SEPARATOR.split(text):
        name, separator, val = part.partition(":")
        if separator and name.strip():
            headers[name.strip()] = val.strip()

    if not headers:
        raise ValueError(f"无法解析请求头 {value!r}，应为 JSON 对象或 `名称: 值` 形式")

    return headers


HeaderMap = Annotated[dict[str, str] | str, BeforeValidator(parse_header_map)]
"""允许 dict 与 `.env` 字符串两种写法的请求头字段类型。

联合类型里带着 dict，NoneBot 的配置源才会在 JSON 解析失败时把原始字符串交给
BeforeValidator；否则读到 `x-provider: relay` 这类值时，直接就以
`error parsing env var` 崩在插件加载阶段（有些终端/工具本来就用这种格式设置该变量）。
"""