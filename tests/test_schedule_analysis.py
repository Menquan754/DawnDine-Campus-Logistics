"""日程分析（只读统计）测试。"""

from __future__ import annotations

from datetime import datetime, timedelta

from dawndine.db import create_schedule
from dawndine.services.schedule import analyze_schedules, format_analysis_markdown


def _today(offset: int = 0) -> str:
    return (datetime.now() + timedelta(days=offset)).strftime("%Y-%m-%d")


def test_analyze_empty_database(tmp_db: None) -> None:
    report = analyze_schedules()

    assert report["ok"] is True
    assert report["total"] == 0
    assert report["today_count"] == 0
    assert report["conflicts"] == []
    assert report["suggestions"]


def test_analyze_counts_today_week_pending_overdue(tmp_db: None) -> None:
    create_schedule(_today(), "08:30", "晨检记录")
    create_schedule(_today(3), "14:00", "留样检查")
    create_schedule(_today(-2), "09:00", "过期安排")
    create_schedule(_today(), "待补", "待补时间安排")

    report = analyze_schedules()

    assert report["ok"] is True
    assert report["total"] == 4
    assert report["today_count"] == 2
    assert report["pending_count"] == 1
    assert report["overdue_count"] == 1
    assert report["week_count"] == 3
    assert any("待补" in item for item in report["suggestions"])


def test_analyze_detects_time_conflicts(tmp_db: None) -> None:
    create_schedule(_today(), "12:00", "陪餐记录")
    create_schedule(_today(), "12:00", "冷库温度检查")
    create_schedule(_today(), "13:00", "不冲突安排")

    report = analyze_schedules()

    assert len(report["conflicts"]) == 1
    group = report["conflicts"][0]
    assert group["time"] == "12:00"
    assert group["count"] == 2
    assert len(group["items"]) == 2


def test_analyze_source_distribution(tmp_db: None) -> None:
    create_schedule(_today(), "08:00", "手动安排", source="手动")
    create_schedule(_today(), "09:00", "对话安排")

    report = analyze_schedules()
    sources = {item["source"]: item["count"] for item in report["by_source"]}

    assert sources["手动"] == 1
    assert sources["对话"] == 1


def test_format_analysis_markdown_contains_sections(tmp_db: None) -> None:
    create_schedule(_today(), "08:30", "晨检记录")
    create_schedule(_today(), "待补", "待补时间安排")

    markdown = format_analysis_markdown(analyze_schedules())

    assert "### 日程分析 · 共 2 条" in markdown
    assert "今天" in markdown
    assert "待补" in markdown
    assert "**建议**" in markdown


def test_format_analysis_markdown_handles_error() -> None:
    markdown = format_analysis_markdown({"ok": False, "error": "读取失败"})

    assert markdown.startswith("⚠️")
    assert "读取失败" in markdown
