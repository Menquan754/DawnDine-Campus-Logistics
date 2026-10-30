"""不联网的工具函数测试。"""

from __future__ import annotations

import pytest

from dawndine.agent.tools.abnormal import (
    _closure_status,
    _deadline,
    _report_targets,
    _temporary_action,
)
from dawndine.agent.tools.checklist import _match_category, _status_for_category
from dawndine.agent.tools.compliance import _sensory_only
from dawndine.agent.tools.inspection import _detect_area, _limit_answer, _scene_focus
from dawndine.agent.tools.ledger import generate_ledger_entry
from dawndine.enums import (
    CHECKLIST_ACCEPTANCE,
    CHECKLIST_MEAL,
    CHECKLIST_PLATFORM_DUAL,
    CHECKLIST_PREP_KNIFE,
    AbnormalSource,
    ChecklistStatus,
    ClosureStatus,
)


def test_closure_status_human_and_ai() -> None:
    assert (
        _closure_status(AbnormalSource.HUMAN, had_temp_action=True)
        == ClosureStatus.RECTIFYING.value
    )
    assert (
        _closure_status(AbnormalSource.AI_CAPTURE, had_temp_action=True)
        == ClosureStatus.PENDING.value
    )


def test_sensory_only_rule() -> None:
    assert _sensory_only("有异味", None) is True
    assert _sensory_only("温度 8 度", None) is False


@pytest.mark.parametrize(
    ("abnormal", "undone", "done", "expected"),
    [
        (["异常"], ["未完成"], ["已完成"], ChecklistStatus.ABNORMAL.value),
        ([], ["未完成"], ["已完成"], ChecklistStatus.NOT_DONE.value),
        ([], [], ["已完成"], ChecklistStatus.DONE.value),
        ([], [], [], ChecklistStatus.UNFILLED.value),
    ],
)
def test_status_priority(
    abnormal: list[str],
    undone: list[str],
    done: list[str],
    expected: str,
) -> None:
    assert _status_for_category(abnormal, undone, done) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("验收票证", CHECKLIST_ACCEPTANCE),
        ("平台资料上传", CHECKLIST_PLATFORM_DUAL),
        ("刀具菜板消毒", CHECKLIST_PREP_KNIFE),
        ("陪餐拍照", CHECKLIST_MEAL),
    ],
)
def test_match_category_four_areas(text: str, expected: str) -> None:
    assert _match_category(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("双人双锁钥匙怎么保管", "dual_lock"),
        ("留样 125g 够不够", "sample"),
        ("AI 预警抓拍怎么复核", "ai"),
    ],
)
def test_detect_inspection_area(text: str, expected: str) -> None:
    assert _detect_area(text, None) == expected


def test_limit_answer_truncates_to_30_chars() -> None:
    answer = _limit_answer("这是一段很长的检查应对口径" * 5)
    assert len(answer) <= 30
    assert answer.endswith("。")


@pytest.mark.parametrize(
    ("abnormal_type", "description", "keyword"),
    [
        ("异物", "学生餐盘里发现塑料片", "保留异物原物"),
        ("虫鼠害", "库房发现鼠粪", "封存可能被污染"),
        ("变质", "冷鲜肉发酸", "隔离该批次"),
        ("消毒不合格", "餐具消毒时间不足", "重新清洗消毒"),
        ("人员健康", "员工发热", "暂停该人员"),
        ("疑似食物中毒", "多人呕吐", "立即停止供餐"),
    ],
)
def test_abnormal_action_covers_new_types(
    abnormal_type: str,
    description: str,
    keyword: str,
) -> None:
    action = _temporary_action(abnormal_type, description, None)
    assert keyword in action


def test_abnormal_targets_and_deadline_for_pest() -> None:
    targets = _report_targets("虫鼠害", "后厨发现蟑螂", AbnormalSource.HUMAN)
    assert "专业消杀机构（必要时）" in targets
    assert "24 小时" in _deadline("虫鼠害", "后厨发现蟑螂")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("餐具消毒记录怎么答", "disinfection"),
        ("后厨地面有积水", "hygiene"),
        ("防鼠板要不要检查", "pest"),
        ("采购台账和临期食材", "purchase"),
        ("停水了怎么办", "emergency"),
    ],
)
def test_detect_inspection_new_areas(text: str, expected: str) -> None:
    assert _detect_area(text, None) == expected


def test_scene_focus_for_market_supervision() -> None:
    focus = _scene_focus("市场监管局检查")
    assert "许可证与健康证" in focus
    assert "当日菜单与留样" in _scene_focus("家长开放日")
    assert _scene_focus("未知场景") == []


@pytest.mark.parametrize(
    ("ledger_type", "process_info", "expected_field"),
    [
        ("采购", "向老张供货商采购冷鲜肉 20kg，票证齐全，已验收", "供货商"),
        ("消毒", "餐具煮沸消毒 100℃ 持续 10 分钟，已入保洁柜", "消毒方式"),
    ],
)
def test_generate_new_ledger_types(
    tmp_db: None,
    ledger_type: str,
    process_info: str,
    expected_field: str,
) -> None:
    result = generate_ledger_entry.invoke(
        {
            "ledger_type": ledger_type,
            "date_time": "2026-03-02 10:30",
            "persons": ["张老师"],
            "process_info": process_info,
        }
    )

    assert result["ok"] is True
    fields = {item["field"] for item in result["ledger_items"]}
    assert expected_field in fields
