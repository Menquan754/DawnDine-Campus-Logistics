"""快捷工具模板填充测试。"""

from __future__ import annotations

from datetime import datetime

import pytest

import dawndine.ui.handlers.chat as chatmod
from dawndine.ui.handlers.chat import _QUICK_PROMPTS, _make_quick_fill

REQUIRED_FIELDS = {
    "合规判断": ("监管环节", "检查对象", "现场现象", "关键数值"),
    "异常上报": ("异常类型", "发现时间", "发现人", "异常对象", "异常现象"),
    "生成台账": ("台账类型", "日期时间", "相关人员", "过程与结果", "消毒"),
    "知识查询": ("具体问题", "领域", "现场补充信息"),
    "每日清单": ("日期", "已完成事项", "未完成事项", "设备状态"),
    "检查应对": ("检查场景", "检查人员提出的问题", "涉及领域"),
}


@pytest.mark.parametrize(("label", "fields"), REQUIRED_FIELDS.items())
def test_quick_prompt_contains_tool_fields(label: str, fields: tuple[str, ...]) -> None:
    prompt = _QUICK_PROMPTS[label]
    for field in fields:
        assert f"{field}" in prompt


def test_fill_empty_input_box() -> None:
    prompt = _QUICK_PROMPTS["合规判断"]
    filled, status = _make_quick_fill("合规判断", prompt)("")

    assert filled == prompt
    assert "合规判断" in status
    assert "点击发送" in status


def test_daily_prompt_uses_current_date() -> None:
    filled, _ = _make_quick_fill("每日清单", _QUICK_PROMPTS["每日清单"])("")

    assert datetime.now().strftime("%Y-%m-%d") in filled
    assert "{today}" not in filled


def test_fill_keeps_existing_text() -> None:
    prompt = _QUICK_PROMPTS["合规判断"]
    filled, _ = _make_quick_fill("合规判断", prompt)("已测冷鲜猪肉中心温度 6℃")

    assert filled.startswith("已测冷鲜猪肉中心温度 6℃")
    assert prompt in filled


def test_fill_does_not_duplicate_same_prompt() -> None:
    prompt = _QUICK_PROMPTS["生成台账"]
    current = f"已确认现场\n\n{prompt}"
    filled, _ = _make_quick_fill("生成台账", prompt)(current)

    assert filled == current
    assert filled.count(prompt.strip()) == 1


def test_send_uses_key_typed_in_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_stream(state, config, stream_mode):
        captured["config"] = config
        return iter(())

    monkeypatch.setattr(chatmod.graph, "stream", fake_stream)
    monkeypatch.setattr(chatmod, "resolve_api_key", lambda key: key)
    list(chatmod.chat("验收冷鲜猪肉，中心温度 6℃", [], "test-thread", "", "sk-typed-key"))

    assert captured["config"]["configurable"]["api_key"] == "sk-typed-key"
