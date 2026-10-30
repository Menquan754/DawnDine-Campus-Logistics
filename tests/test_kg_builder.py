"""知识图谱构建测试（依赖缺失时自动跳过）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dawndine.knowledge.graph_builder import KnowledgeGraphError, build_knowledge_graph

pytest.importorskip("networkx")
pytest.importorskip("pyvis")

SAMPLE = [
    {
        "id": "E001",
        "category": "食安法规与标准",
        "entity": "留样柜",
        "title": "食品留样基本要求",
        "content": "每餐次每个品种留样不少于125克，冷藏保存48小时。",
        "relations": ["食品留样", "冷藏"],
    },
    {
        "id": "E002",
        "category": "维修响应与规范",
        "entity": "下水道",
        "title": "后厨堵塞处理",
        "content": "先停止排水并清理隔油池浮油，再用疏通机处理。",
        "relations": ["隔油池", "疏通机"],
    },
]


def test_build_knowledge_graph(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki.json"
    wiki.write_text(json.dumps(SAMPLE, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "kg.html"

    stats = build_knowledge_graph(wiki, output)

    assert stats["entries"] == 2
    assert stats["categories"] == 2
    assert stats["entities"] == 2
    assert stats["relations"] == 4
    assert stats["nodes"] >= 7
    assert output.is_file()
    html = output.read_text(encoding="utf-8")
    assert "vis" in html.lower()
    # 悬停小框：容器、样式与脚本都注入到图谱页面内，离开节点即隐藏。
    assert 'id="dd-kg-tooltip"' in html
    assert "hoverNode" in html
    assert "blurNode" in html
    assert "E001" in html
    # 布局稳定后逐级加大阻尼：保留碰撞，但弹动一次比一次轻，避免持续抽搐。
    assert "stabilizationIterationsDone" in html
    assert "dragStart" in html
    assert "applyPhysics" in html
    assert "stopSimulation" in html
    assert '"damping": 0.12' in html
    assert '"minVelocity": 0.8' in html
    # 不再用“一拖就彻底关闭物理”的硬冻结方案。
    assert "setOptions({ physics: false })" not in html


def test_build_knowledge_graph_rejects_empty_wiki(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki.json"
    wiki.write_text("[]", encoding="utf-8")

    with pytest.raises(KnowledgeGraphError):
        build_knowledge_graph(wiki, tmp_path / "kg.html")


def test_relation_entity_is_promoted_when_it_has_own_entry(tmp_path: Path) -> None:
    """先出现在 relations 里的实体，轮到自己的条目时应升级为正式实体。"""

    staggered = tmp_path / "staggered.json"
    staggered.write_text(
        json.dumps(
            [
                {
                    "id": "E001",
                    "category": "食堂日常操作",
                    "entity": "留样柜",
                    "title": "留样柜使用",
                    "content": "留样柜专柜专用，每日核对温度。",
                    "relations": ["冷藏柜"],
                },
                {
                    "id": "E002",
                    "category": "设备与空间信息",
                    "entity": "冷藏柜",
                    "title": "冷藏柜温度",
                    "content": "冷藏柜温度保持 0—5 摄氏度。",
                    "relations": ["留样柜"],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    stats = build_knowledge_graph(staggered, tmp_path / "kg.html")

    assert stats["entries"] == 2
    assert stats["entities"] == 2
    # 两条 relations 指向同一对节点，无向图里合并为一条关联边。
    assert stats["relations"] == 1
    assert stats["nodes"] == 4
