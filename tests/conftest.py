"""DawnDine 测试公共配置。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def tmp_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """把模块级 DB_PATH 指向临时库，并初始化表结构。"""

    monkeypatch.setattr("dawndine.db.DB_PATH", tmp_path / "test.db")
    from dawndine.db import init_db

    init_db()
