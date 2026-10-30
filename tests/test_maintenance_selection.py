"""后勤维修：勾选列表、待删除清单与删除/补录刷新测试。"""

from __future__ import annotations

import pytest

import dawndine.ui.handlers.maintenance as appmod
from dawndine.config import MAINTENANCE_TABLE_HEADERS
from dawndine.db import create_maintenance

pytestmark = pytest.mark.usefixtures("tmp_db")


def _create(location: str, issue: str) -> int:
    record = create_maintenance(location=location, issue=issue)
    return int(record["id"])


def test_maintenance_table_header_uses_numbering() -> None:
    assert MAINTENANCE_TABLE_HEADERS[0] == "编号"


def test_overview_counts_records_locations_and_pending() -> None:
    _create("一食堂", "蒸箱漏气")
    _create("二食堂", "灯管不亮")

    markdown = appmod._maintenance_overview_md()

    assert "共 **2** 条维修记录" in markdown
    assert "覆盖 **2** 个地点" in markdown
    assert "待处理 **2** 条" in markdown


def test_pick_labels_use_numbering() -> None:
    first = _create("一食堂", "蒸箱漏气")

    choices = appmod._maintenance_choices()

    assert [value for _, value in choices] == [first]
    assert choices[0][0] == f"编号 {first} · 一食堂 · 蒸箱漏气 · 待处理"


def test_pick_update_uses_empty_list_when_nothing_selected() -> None:
    update = appmod._maintenance_pick_update()
    assert update["value"] == []
    assert isinstance(update["choices"], list)


def test_selection_summary_lists_selected_rows() -> None:
    first = _create("一食堂", "蒸箱漏气")
    second = _create("二食堂", "灯管不亮")

    summary = appmod._maintenance_selection_summary([first, second])

    assert "待删除清单（2 条）" in summary
    assert f"编号 {first}" in summary
    assert "蒸箱漏气" in summary
    assert f"编号 {second}" in summary


def test_selection_summary_empty_explains_interaction() -> None:
    summary = appmod._maintenance_selection_summary([])

    assert "待删除清单（0 条）" in summary
    assert "框选" in summary


def test_select_all_checks_every_record() -> None:
    ids = [_create("一食堂", "蒸箱漏气"), _create("二食堂", "灯管不亮")]

    update, summary = appmod.select_all_maintenance()

    assert sorted(update["value"]) == sorted(ids)
    assert "待删除清单（2 条）" in summary


def test_clear_selection_resets_summary() -> None:
    update, summary = appmod.clear_maintenance_selection()

    assert update["value"] == []
    assert "待删除清单（0 条）" in summary


def test_delete_selected_returns_six_outputs() -> None:
    keep = _create("一食堂", "蒸箱漏气")
    drop = _create("二食堂", "灯管不亮")

    table, stats, overview, pick_update, summary, status = appmod.delete_selected_maintenance(
        [drop]
    )

    assert len(table) == 1
    assert int(table[0][0]) == keep
    assert stats == [["一食堂", 1]]
    assert "共 **1** 条维修记录" in overview
    assert pick_update["value"] == []
    assert "待删除清单（0 条）" in summary
    assert status.startswith("✅ 已删除 1 条维修记录")


def test_delete_without_selection_is_rejected() -> None:
    result = appmod.delete_selected_maintenance([])

    assert len(result) == 6
    assert result[-1].startswith("⚠️")


def test_clear_all_requires_confirmation() -> None:
    _create("一食堂", "蒸箱漏气")

    result = appmod.clear_all_maintenance(False)

    assert len(result) == 6
    assert result[-1].startswith("⚠️")
    assert len(appmod._maintenance_choices()) == 1


def test_clear_all_with_confirmation_empties_tables() -> None:
    _create("一食堂", "蒸箱漏气")
    _create("二食堂", "灯管不亮")

    table, stats, overview, pick_update, summary, status = appmod.clear_all_maintenance(True)

    assert table == []
    assert stats == []
    assert "暂无维修记录" in overview
    assert pick_update["value"] == []
    assert "待删除清单（0 条）" in summary
    assert status.startswith("✅ 已清空 2 条维修记录")


def test_add_manual_maintenance_refreshes_outputs() -> None:
    result = appmod.add_manual_maintenance("一食堂", "蒸箱漏气", "张三", "2026-10-30")

    assert len(result) == 6
    assert result[0].startswith("✅ 已添加维修单（编号 1）")
    assert len(result[1]) == 1
    assert result[2] == [["一食堂", 1]]


def test_add_manual_maintenance_requires_issue() -> None:
    result = appmod.add_manual_maintenance("一食堂", "   ", "张三", "2026-10-30")

    assert len(result) == 6
    assert result[0].startswith("⚠️")
