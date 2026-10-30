"""单会话初始化与 Agent 初始化测试。"""

from __future__ import annotations

import pytest

import dawndine.ui.handlers.session as appmod
from dawndine import db
from dawndine.agent.tools import watermark as watermark_tool


def test_init_session_returns_single_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(appmod, "init_db", lambda: None)
    monkeypatch.setattr(appmod, "_schedule_rows", lambda view="全部": [])
    monkeypatch.setattr(appmod, "_template_update", lambda selected=None: None)
    monkeypatch.setattr(appmod, "_key_status", lambda ui_key="": "无 Key")

    thread_id, display, _, _, _, _, _, history = appmod.init_session()

    assert len(thread_id) == 32
    assert display.startswith(thread_id[:8])
    assert history == appmod._CHAT_WELCOME


def test_initialize_agent_requires_confirmation() -> None:
    status, *rest = appmod.initialize_agent(False)

    assert "请先勾选" in status
    assert len(rest) == 8


def test_initialize_agent_rebuilds_fresh_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counts = {
        "records": 2,
        "schedules": 3,
        "maintenance": 1,
        "assets": 0,
        "inventory": 0,
        "inspections": 0,
        "suppliers": 0,
        "staff": 0,
        "feedback": 0,
    }
    monkeypatch.setattr(appmod, "reset_all_data", lambda: counts)
    monkeypatch.setattr(appmod, "reset_templates", lambda: 4)
    monkeypatch.setattr(appmod, "clear_all_conversations", lambda: 5)
    monkeypatch.setattr(appmod, "_clear_generated_files", lambda: 6)

    result = appmod.initialize_agent(True)

    assert len(result) == 9
    status, thread_id = result[0], result[1]
    assert "已完成" in status
    assert "**6**" in status
    assert "水印模板 **4**" in status
    assert thread_id
    assert result[2] == appmod._CHAT_WELCOME
    assert result[3].startswith(thread_id[:8])


def test_initialize_agent_reports_failure_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> dict[str, int]:
        raise OSError("database is locked")

    monkeypatch.setattr(appmod, "reset_all_data", boom)
    monkeypatch.setattr(appmod, "reset_templates", lambda: 2)
    monkeypatch.setattr(appmod, "clear_all_conversations", lambda: 3)
    monkeypatch.setattr(appmod, "_clear_generated_files", lambda: 4)

    result = appmod.initialize_agent(True)

    assert len(result) == 9
    assert "部分完成" in result[0]
    assert "database is locked" in result[0]
    assert "水印模板 **2**" in result[0]
    assert result[1]


def test_reset_all_data_clears_business_tables(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "reset.db")
    db.init_db()
    db.create_schedule("2026-10-30", "10:00", "检查冷库", source="manual")

    counts = db.reset_all_data()

    assert counts["schedules"] == 1
    assert db.logistics_overview()["schedules"] == 0


def test_reset_templates_clears_all_templates(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    template_file = tmp_path / "templates.json"
    template_file.write_text('{"a": {}, "b": {}}', encoding="utf-8")
    monkeypatch.setattr("dawndine.services.watermark_store.TEMPLATE_FILE", template_file)

    assert watermark_tool.reset_templates() == 2
    assert watermark_tool.reset_templates() == 0
    assert template_file.read_text(encoding="utf-8") == "{}"
