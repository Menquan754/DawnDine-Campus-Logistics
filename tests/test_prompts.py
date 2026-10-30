"""系统提示词与工具注册表测试。"""

from __future__ import annotations

from datetime import datetime

from dawndine.agent.tools import TOOLS
from dawndine.enums import TOOL_KNOWLEDGE, TOOL_NAMES, LedgerType
from dawndine.prompts import SYSTEM_PROMPT, build_system_prompt


def test_prompt_covers_seven_domains() -> None:
    for keyword in (
        "食材与食品安全",
        "台账、记录、打卡与系统操作",
        "后厨操作与环境卫生",
        "采购、库存与成本",
        "师生反馈与陪餐",
        "制度、规范、整改与闭环",
        "日常基础咨询",
    ):
        assert keyword in SYSTEM_PROMPT


def test_prompt_separates_compliance_and_operation_answers() -> None:
    assert "合规 / 不合规 / 存疑 / 需现场确认" in SYSTEM_PROMPT
    assert "结论/要点" in SYSTEM_PROMPT
    assert "硬性要求" in SYSTEM_PROMPT
    assert "管理建议" in SYSTEM_PROMPT


def test_prompt_requires_knowledge_priority_and_no_fabrication() -> None:
    assert "本地知识库摘录" in SYSTEM_PROMPT
    assert "不得编造条款号" in SYSTEM_PROMPT
    assert TOOL_KNOWLEDGE in SYSTEM_PROMPT


def test_build_system_prompt_injects_date() -> None:
    prompt = build_system_prompt(datetime(2026, 10, 28, 9, 30))
    assert "2026-10-28" in prompt
    assert "09:30" in prompt
    assert "星期三" in prompt


def test_tool_registry_includes_knowledge_tool() -> None:
    names = {tool.name for tool in TOOLS}
    assert set(TOOL_NAMES) == names
    assert TOOL_KNOWLEDGE in names


def test_ledger_type_includes_purchase_and_disinfection() -> None:
    values = {item.value for item in LedgerType}
    assert {"采购", "消毒"} <= values
