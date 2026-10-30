"""SQLite 日程数据层测试。"""

from __future__ import annotations

from datetime import datetime

import pytest

from dawndine.db import (
    create_schedule,
    delete_all_schedules,
    delete_schedule,
    delete_schedules,
    list_schedules,
    normalize_date,
    normalize_time,
    split_datetime,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-10-28", "2026-10-28"),
        ("2026/10/28", "2026-10-28"),
        ("2026.10.28", "2026-10-28"),
        ("2026年10月28日", "2026-10-28"),
    ],
)
def test_normalize_date_formats(raw: str, expected: str) -> None:
    assert normalize_date(raw) == expected


def test_normalize_date_empty_uses_today() -> None:
    assert normalize_date("") == datetime.now().strftime("%Y-%m-%d")
    assert normalize_date(None) == datetime.now().strftime("%Y-%m-%d")


def test_normalize_date_pending_and_invalid() -> None:
    assert normalize_date("待补") == "待补"
    with pytest.raises(ValueError):
        normalize_date("2026-13-40")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("08:30", "08:30"),
        ("08:30:15", "08:30"),
        ("08时30分", "08:30"),
    ],
)
def test_normalize_time_formats(raw: str, expected: str) -> None:
    assert normalize_time(raw) == expected


def test_normalize_time_empty_and_invalid() -> None:
    assert normalize_time("") == "待补"
    assert normalize_time(None) == "待补"
    with pytest.raises(ValueError):
        normalize_time("25:00")


def test_split_datetime_full_and_date_only() -> None:
    assert split_datetime("2026-10-28 09:15") == ("2026-10-28", "09:15")
    assert split_datetime("2026-10-28") == ("2026-10-28", "待补")


def test_split_datetime_garbage_does_not_raise() -> None:
    date_text, time_text = split_datetime("not-a-date")
    assert isinstance(date_text, str)
    assert isinstance(time_text, str)
    assert date_text
    assert time_text


def test_create_schedule_and_list_order(tmp_db: None) -> None:
    create_schedule("2026-10-28", "09:00", "今天的记录")
    create_schedule("2026-10-30", "10:00", "后天的记录")
    create_schedule("待补", "待补", "待补日期的记录")

    rows = list_schedules()
    assert [row["content"] for row in rows] == [
        "后天的记录",
        "今天的记录",
        "待补日期的记录",
    ]
    assert rows[-1]["date"] == "待补"


def test_delete_schedule_existing_and_repeat(tmp_db: None) -> None:
    record = create_schedule("2026-10-28", "09:00", "待删除")
    assert delete_schedule(int(record["id"])) is True
    assert delete_schedule(int(record["id"])) is False


def test_delete_schedules_bulk_ignores_missing(tmp_db: None) -> None:
    first = create_schedule("2026-10-28", "09:00", "第一条")
    second = create_schedule("2026-10-29", "10:00", "第二条")
    third = create_schedule("2026-10-30", "11:00", "保留")

    deleted = delete_schedules([int(first["id"]), int(second["id"]), 99999])
    assert deleted == 2
    assert [row["content"] for row in list_schedules()] == ["保留"]
    assert int(third["id"]) > 0
    assert delete_schedules([]) == 0


def test_delete_all_schedules(tmp_db: None) -> None:
    create_schedule("2026-10-28", "09:00", "第一条")
    create_schedule("2026-10-29", "10:00", "第二条")

    assert delete_all_schedules() == 2
    assert list_schedules() == []


def test_create_schedule_reuses_deleted_numbers(tmp_db: None) -> None:
    first = create_schedule("2026-10-28", "09:00", "第一条")
    second = create_schedule("2026-10-28", "10:00", "第二条")
    third = create_schedule("2026-10-28", "11:00", "第三条")
    assert [int(first["id"]), int(second["id"]), int(third["id"])] == [1, 2, 3]

    # 删除中间的编号：下一条新日程优先补回 2。
    assert delete_schedule(2) is True
    reused = create_schedule("2026-10-29", "09:00", "补回中间编号")
    assert int(reused["id"]) == 2

    # 再删除第一条：下一条优先补回 1，而不是继续往后加。
    assert delete_schedule(1) is True
    again = create_schedule("2026-10-29", "10:00", "补回最小编号")
    assert int(again["id"]) == 1

    # 编号 1~3 已连续，新日程接在最大编号之后。
    fourth = create_schedule("2026-10-30", "09:00", "顺延编号")
    assert int(fourth["id"]) == 4
    assert [row["content"] for row in list_schedules()] == [
        "顺延编号",
        "补回最小编号",
        "补回中间编号",
        "第三条",
    ]


def test_create_schedule_fills_gap_after_clear(tmp_db: None) -> None:
    create_schedule("2026-10-28", "09:00", "第一条")
    create_schedule("2026-10-28", "10:00", "第二条")
    assert delete_all_schedules() == 2

    rebuilt = create_schedule("2026-10-29", "09:00", "清空后的第一条")
    assert int(rebuilt["id"]) == 1
