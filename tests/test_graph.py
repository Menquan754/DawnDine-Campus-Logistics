"""LangGraph 强制触发词测试。"""

from __future__ import annotations

import pytest

from dawndine.agent.graph import _matches_forced_trigger


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("这样可以吗", False),
        ("确认一下", False),
        ("调用一下工具", False),
        ("好的", False),
        ("帮我生成日管控台账", True),
        ("留样 125g 够不够", True),
        ("冷库温度 8 度怎么办", True),
        ("帮我看看水印怎么弄", True),
        ("验收需要注意什么标准", True),
        ("今天食堂人多吗", False),
    ],
)
def test_matches_forced_trigger(text: str, expected: bool) -> None:
    assert _matches_forced_trigger(text) is expected
