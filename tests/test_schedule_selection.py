"""我的日程：勾选列表、待删除清单与删除刷新测试。"""

from __future__ import annotations

import pytest

import dawndine.ui.handlers.schedule as appmod
from dawndine.config import SCHEDULE_TABLE_HEADERS
from dawndine.db import create_schedule

pytestmark = pytest.mark.usefixtures("tmp_db")


def _create(date: str, time: str, content: str) -> int:
    record = create_schedule(date=date, time=time, content=content, source="手动")
    return int(record["id"])


def test_schedule_table_header_uses_numbering() -> None:
    assert SCHEDULE_TABLE_HEADERS[0] == "编号"


def test_pick_labels_use_numbering() -> None:
    first = _create("2026-10-30", "09:00", "检查冷库温度")

    choices = appmod._schedule_choices("全部")

    assert [value for _, value in choices] == [first]
    assert choices[0][0] == f"编号 {first} · 2026-10-30 09:00 · 检查冷库温度"


def test_pick_update_uses_empty_list_when_nothing_selected() -> None:
    update = appmod._schedule_pick_update("全部")
    assert update["value"] == []
    assert isinstance(update["choices"], list)


def test_selection_summary_lists_selected_rows() -> None:
    first = _create("2026-10-30", "09:00", "检查冷库温度")
    second = _create("2026-10-31", "14:00", "核对留样记录")

    summary = appmod._schedule_selection_summary([first, second], "全部")

    assert "待删除清单（2 条）" in summary
    assert f"编号 {first}" in summary
    assert "检查冷库温度" in summary
    assert f"编号 {second}" in summary


def test_selection_summary_empty_explains_interaction() -> None:
    summary = appmod._schedule_selection_summary([], "全部")

    assert "待删除清单（0 条）" in summary
    assert "框选" in summary


def test_select_all_checks_every_visible_schedule() -> None:
    ids = [_create("2026-10-30", "08:00", "晨检"), _create("2026-10-30", "11:00", "陪餐")]

    update, summary = appmod.select_all_schedules("全部")

    assert sorted(update["value"]) == sorted(ids)
    assert "待删除清单（2 条）" in summary


def test_clear_selection_resets_choices_and_summary() -> None:
    update, summary = appmod.clear_schedule_selection("全部")

    assert update["value"] == []
    assert "待删除清单（0 条）" in summary


def test_delete_selected_schedules_returns_four_outputs() -> None:
    keep = _create("2026-10-30", "09:00", "保留的日程")
    drop = _create("2026-10-30", "10:00", "要删除的日程")

    table, pick_update, summary, status = appmod.delete_selected_schedules([drop], "全部")

    assert len(table) == 1
    assert int(table[0][0]) == keep
    assert pick_update["value"] == []
    assert "待删除清单（0 条）" in summary
    assert status.startswith("✅ 已删除 1 条日程")


def test_delete_without_selection_is_rejected() -> None:
    result = appmod.delete_selected_schedules([], "全部")

    assert len(result) == 4
    assert result[3].startswith("⚠️")
