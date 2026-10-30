"""知识库检索、领域识别与 manifest 自动重建测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dawndine.agent.tools.knowledge import (
    DOMAIN_DAILY,
    DOMAIN_FEEDBACK,
    DOMAIN_FOOD_SAFETY,
    DOMAIN_GENERAL,
    DOMAIN_KITCHEN,
    DOMAIN_LEDGER,
    DOMAIN_PURCHASE,
    DOMAIN_RULES,
    detect_domain,
    extract_key_points,
    search_food_safety_knowledge,
)
from dawndine.knowledge import rag as rag_store


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("餐具消毒要多久，留样够不够", DOMAIN_FOOD_SAFETY),
        ("采购台账怎么填，平台怎么上传", DOMAIN_LEDGER),
        ("后厨地面有积水，健康证过期怎么办", DOMAIN_KITCHEN),
        ("库存先进先出怎么做，临期怎么处理", DOMAIN_PURCHASE),
        ("师生投诉饭菜有异物，陪餐记录怎么写", DOMAIN_FEEDBACK),
        ("市场监管局检查发现问题怎么整改", DOMAIN_RULES),
        ("食堂几点开放，保洁用品怎么申领", DOMAIN_DAILY),
        ("你好", DOMAIN_GENERAL),
    ],
)
def test_detect_domain(question: str, expected: str) -> None:
    assert detect_domain(question) == expected


def test_extract_key_points_keeps_numbered_items() -> None:
    hits = [
        {
            "content": "一、清洗流程\n1. 刮除残渣\n2. 流动水冲洗\n3. 消毒后入保洁柜",
            "source": "餐具清洗消毒与保洁.txt",
        }
    ]
    points = extract_key_points(hits)
    assert "刮除残渣" in points
    assert "流动水冲洗" in points
    assert all(len(point) <= 90 for point in points)


def test_knowledge_tool_returns_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(query: str, k: int, api_key: str) -> list[dict]:
        assert "餐具" in query
        return [
            {
                "content": "1. 煮沸消毒：水沸腾后持续 10 分钟以上。",
                "source": "餐具清洗消毒与保洁.txt",
                "score": 0.2,
            }
        ]

    monkeypatch.setattr("dawndine.agent.tools.knowledge.search", fake_search)
    result = search_food_safety_knowledge.invoke(
        {"question": "餐具煮沸消毒要多久", "top_k": 3},
        config={"configurable": {"api_key": "sk-test"}},
    )

    assert result["ok"] is True
    assert result["domain"] == DOMAIN_FOOD_SAFETY
    assert result["sources"] == ["餐具清洗消毒与保洁.txt"]
    assert any("煮沸" in point for point in result["key_points"])


def test_knowledge_tool_reports_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dawndine.agent.tools.knowledge.search", lambda **kwargs: [])
    result = search_food_safety_knowledge.invoke(
        {"question": "食堂屋顶漏水怎么办"},
        config={"configurable": {"api_key": "sk-test"}},
    )

    assert result["ok"] is True
    assert result["hits"] == []
    assert "未检索到" in result["note"]


def test_manifest_detects_knowledge_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    manifest = tmp_path / "chroma" / "knowledge_manifest.json"
    monkeypatch.setattr(rag_store, "KNOWLEDGE_DIR", knowledge_dir)
    monkeypatch.setattr(rag_store, "KNOWLEDGE_MANIFEST_FILE", manifest)

    first = knowledge_dir / "标准.txt"
    first.write_text("冷藏温度 0—4℃。", encoding="utf-8")
    files = rag_store._knowledge_files()
    fingerprint = rag_store.knowledge_fingerprint(files)

    assert rag_store._index_needs_rebuild(0, fingerprint) is True
    rag_store._write_manifest(fingerprint, 1, files)
    assert rag_store._index_needs_rebuild(1, fingerprint) is False

    status = rag_store.knowledge_status()
    assert status["up_to_date"] is True
    assert status["file_count"] == 1

    first.write_text("冷藏温度 0—4℃，冷冻不高于 -18℃。", encoding="utf-8")
    changed = rag_store.knowledge_fingerprint(rag_store._knowledge_files())
    assert changed != fingerprint
    assert rag_store._index_needs_rebuild(1, changed) is True


def test_manifest_rebuilds_when_count_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    manifest = tmp_path / "chroma" / "knowledge_manifest.json"
    monkeypatch.setattr(rag_store, "KNOWLEDGE_DIR", knowledge_dir)
    monkeypatch.setattr(rag_store, "KNOWLEDGE_MANIFEST_FILE", manifest)

    (knowledge_dir / "制度.txt").write_text("留样 125g，48 小时。", encoding="utf-8")
    files = rag_store._knowledge_files()
    fingerprint = rag_store.knowledge_fingerprint(files)
    rag_store._write_manifest(fingerprint, 3, files)

    assert rag_store._index_needs_rebuild(2, fingerprint) is True
