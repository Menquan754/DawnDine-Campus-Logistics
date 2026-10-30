"""后勤维修数据层与 Excel 导出测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from dawndine.db import (
    count_maintenance_by_location,
    create_maintenance,
    delete_all_maintenance,
    delete_maintenance_records,
    list_maintenance,
    list_maintenance_rows,
)
from dawndine.services.maintenance import (
    DETAIL_COLUMNS,
    DETAIL_SHEET,
    SUMMARY_COLUMNS,
    SUMMARY_SHEET,
    export_maintenance_workbook,
)


def test_create_and_list_sorted_by_location(tmp_db: None) -> None:
    create_maintenance("zebra 食堂", "灯管不亮", "张三", "2026-10-28")
    create_maintenance("Apple 档口", "插座松动", "李四", "2026-10-27")
    create_maintenance("canteen A", "水龙头漏水", "王五", "2026-10-26")

    locations = [item["location"] for item in list_maintenance()]
    assert locations == ["Apple 档口", "canteen A", "zebra 食堂"]


def test_create_defaults_pending_status_and_created_at(tmp_db: None) -> None:
    record = create_maintenance("一食堂", "蒸箱漏气", "赵六", "2026-10-28")

    assert record["status"] == "待处理"
    assert record["location"] == "一食堂"
    assert record["issue"] == "蒸箱漏气"
    assert record["reporter"] == "赵六"
    assert record["report_date"] == "2026-10-28"
    assert len(record["created_at"]) == 19
    assert record["id"] > 0


def test_create_requires_issue(tmp_db: None) -> None:
    with pytest.raises(ValueError):
        create_maintenance("一食堂", "   ", "赵六", "2026-10-28")


def test_count_by_location_sorted(tmp_db: None) -> None:
    create_maintenance("B 档口", "灯管不亮")
    create_maintenance("A 档口", "水龙头漏水")
    create_maintenance("A 档口", "蒸箱漏气")

    assert count_maintenance_by_location() == [["A 档口", 2], ["B 档口", 1]]


def test_maintenance_rows_shape(tmp_db: None) -> None:
    create_maintenance("一食堂", "蒸箱漏气", "赵六", "2026-10-28")

    rows = list_maintenance_rows()
    assert len(rows) == 1
    assert len(rows[0]) == 7
    assert rows[0][1] == "一食堂"
    assert rows[0][5] == "待处理"


def test_delete_maintenance_records_single_and_bulk(tmp_db: None) -> None:
    first = create_maintenance("一食堂", "蒸箱漏气")
    second = create_maintenance("二食堂", "灯管不亮")
    third = create_maintenance("教学楼A", "插座松动")

    assert delete_maintenance_records([int(first["id"])]) == 1
    assert [item["issue"] for item in list_maintenance()] == ["灯管不亮", "插座松动"]
    assert delete_maintenance_records([int(third["id"]), int(second["id"]), 99999]) == 2
    assert list_maintenance() == []
    assert delete_maintenance_records([]) == 0


def test_delete_all_maintenance(tmp_db: None) -> None:
    create_maintenance("一食堂", "蒸箱漏气")
    create_maintenance("二食堂", "灯管不亮")

    assert delete_all_maintenance() == 2
    assert list_maintenance() == []


def test_new_maintenance_reuses_smallest_freed_id(tmp_db: None) -> None:
    first = create_maintenance("一食堂", "蒸箱漏气")
    second = create_maintenance("二食堂", "灯管不亮")
    third = create_maintenance("教学楼A", "插座松动")
    assert [int(first["id"]), int(second["id"]), int(third["id"])] == [1, 2, 3]

    assert delete_maintenance_records([2]) == 1
    refilled = create_maintenance("三食堂", "空调漏水")
    assert int(refilled["id"]) == 2
    assert sorted(int(item["id"]) for item in list_maintenance()) == [1, 2, 3]

    assert delete_all_maintenance() == 3
    restarted = create_maintenance("一食堂", "门锁损坏")
    assert int(restarted["id"]) == 1


def test_new_maintenance_continues_after_contiguous_ids(tmp_db: None) -> None:
    create_maintenance("一食堂", "蒸箱漏气")
    create_maintenance("二食堂", "灯管不亮")

    assert int(create_maintenance("教学楼A", "插座松动")["id"]) == 3


def test_export_workbook_has_detail_and_summary_sheets(
    tmp_db: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("dawndine.services.maintenance.EXPORTS_DIR", tmp_path)
    create_maintenance("zebra 食堂", "灯管不亮", "张三", "2026-10-28")
    create_maintenance("Apple 档口", "插座松动", "李四", "2026-10-27")

    path = export_maintenance_workbook(list_maintenance())
    detail = pd.read_excel(path, sheet_name=DETAIL_SHEET, engine="openpyxl")
    summary = pd.read_excel(path, sheet_name=SUMMARY_SHEET, engine="openpyxl")

    assert path.is_file()
    assert path.name.startswith("maintenance-report-")
    assert list(detail.columns) == DETAIL_COLUMNS
    assert list(detail["地点"]) == ["Apple 档口", "zebra 食堂"]
    assert list(summary.columns) == SUMMARY_COLUMNS
    assert list(summary["地点"]) == ["Apple 档口", "zebra 食堂"]
    assert list(summary["维修数量"]) == [1, 1]


def test_export_empty_keeps_headers(
    tmp_db: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("dawndine.services.maintenance.EXPORTS_DIR", tmp_path)

    path = export_maintenance_workbook([])
    detail = pd.read_excel(path, sheet_name=DETAIL_SHEET, engine="openpyxl")
    summary = pd.read_excel(path, sheet_name=SUMMARY_SHEET, engine="openpyxl")

    assert list(detail.columns) == DETAIL_COLUMNS
    assert list(summary.columns) == SUMMARY_COLUMNS
    assert detail.empty
    assert summary.empty
