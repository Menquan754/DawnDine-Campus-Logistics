"""Wiki 知识加载、筛选与索引接入测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dawndine.knowledge import rag as rag_store
from dawndine.knowledge.wiki import (
    ALL_CATEGORIES,
    filter_wiki,
    load_wiki,
    wiki_categories,
    wiki_rows,
)

SAMPLE = [
    {
        "id": "E001",
        "category": "食安法规与标准",
        "entity": "留样柜",
        "title": "食品留样基本要求",
        "content": "每餐次每个品种留样不少于125克，0至5℃冷藏保存48小时。",
        "relations": ["食品留样", "冷藏"],
    },
    {
        "id": "E002",
        "category": "维修响应与规范",
        "entity": "下水道",
        "title": "后厨堵塞处理",
        "content": "先停止排水并清理隔油池浮油，再用疏通机处理，完工冲洗消毒。",
        "relations": ["隔油池", "疏通机"],
    },
]


def _write_wiki(path: Path, items: list[dict]) -> None:
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def test_load_wiki_skips_invalid_entries(tmp_path: Path) -> None:
    path = tmp_path / "wiki.json"
    _write_wiki(path, [SAMPLE[0], {"id": "E999"}, "bad", SAMPLE[1], SAMPLE[0]])

    entries = load_wiki(path)

    assert [item["id"] for item in entries] == ["E001", "E002"]
    assert entries[0]["relations"] == ["食品留样", "冷藏"]


def test_load_wiki_handles_missing_and_broken_file(tmp_path: Path) -> None:
    assert load_wiki(tmp_path / "missing.json") == []

    broken = tmp_path / "broken.json"
    broken.write_text("{not-json", encoding="utf-8")
    assert load_wiki(broken) == []


def test_filter_wiki_by_keyword_and_category(tmp_path: Path) -> None:
    path = tmp_path / "wiki.json"
    _write_wiki(path, SAMPLE)
    entries = load_wiki(path)

    assert wiki_categories(entries) == ["食安法规与标准", "维修响应与规范"]
    assert [item["id"] for item in filter_wiki(entries, keyword="留样")] == ["E001"]
    assert [item["id"] for item in filter_wiki(entries, keyword="隔油池")] == ["E002"]
    assert filter_wiki(entries, category="维修响应与规范")[0]["id"] == "E002"
    assert len(filter_wiki(entries, category=ALL_CATEGORIES)) == 2

    rows = wiki_rows(entries)
    assert rows[0][0] == "E001"
    assert rows[0][1] == "食品留样基本要求"
    assert rows[1][3] == "下水道"
    assert len(rows[0]) == 5


def test_rag_indexes_wiki_with_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    _write_wiki(knowledge_dir / "wiki.json", SAMPLE)
    monkeypatch.setattr(rag_store, "KNOWLEDGE_DIR", knowledge_dir)

    chunks = rag_store._load_documents()

    assert len(chunks) == 2
    for chunk in chunks:
        assert chunk.metadata["source"] == "wiki.json"
        assert chunk.metadata["entity"]
        assert chunk.metadata["category"]
        assert chunk.metadata["wiki_id"]

    first = next(chunk for chunk in chunks if chunk.metadata["wiki_id"] == "E001")
    assert "留样" in first.page_content
    assert first.page_content.startswith("[E001]")
    assert first.metadata["entity"] == "留样柜"


def test_fingerprint_changes_when_wiki_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    wiki = knowledge_dir / "wiki.json"
    _write_wiki(wiki, SAMPLE)
    monkeypatch.setattr(rag_store, "KNOWLEDGE_DIR", knowledge_dir)

    before = rag_store.knowledge_fingerprint()
    extended = SAMPLE + [dict(SAMPLE[0], id="E003")]
    wiki.write_text(json.dumps(extended, ensure_ascii=False), encoding="utf-8")
    after = rag_store.knowledge_fingerprint()

    assert before != after
    status = rag_store.knowledge_status()
    assert status["wiki_entries"] == 3
