"""后勤 Wiki 知识加载、校验与筛选。

本文件职责：
- 读取 data/knowledge/wiki.json（结构化 Wiki 数组）；
- 校验字段并做轻量清洗，坏条目跳过而不阻塞页面；
- 为知识库入库、知识图谱和 Wiki 查询页提供统一的条目列表；
- 提供关键词/分类筛选与 Dataframe 行转换。

依赖：dawndine.config、Python 标准库。
被调用：dawndine.knowledge.rag、dawndine.knowledge.graph_builder、app.py、tests。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from dawndine.config import WIKI_FILE

logger = logging.getLogger(__name__)

__all__ = [
    "ALL_CATEGORIES",
    "WIKI_TABLE_HEADERS",
    "filter_wiki",
    "load_wiki",
    "wiki_categories",
    "wiki_overview",
    "wiki_path",
    "wiki_rows",
]

WIKI_FILE_NAME = "wiki.json"
REQUIRED_FIELDS: tuple[str, ...] = ("id", "category", "entity", "title", "content")
ALL_CATEGORIES = "全部"
WIKI_TABLE_HEADERS: tuple[str, ...] = ("编号", "标题", "分类", "实体", "内容")


def wiki_path() -> Path:
    """返回 Wiki JSON 的默认路径。"""

    return WIKI_FILE


def _normalize_relations(value: Any) -> list[str]:
    """把 relations 统一成去重后的非空字符串列表。"""

    if isinstance(value, str):
        candidates = value.replace("，", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        candidates = list(value)
    else:
        return []
    relations: list[str] = []
    for item in candidates:
        text = str(item).strip()
        if text and text not in relations:
            relations.append(text)
    return relations


def _clean_entry(item: Any, index: int) -> dict[str, Any] | None:
    """校验单条 Wiki；字段缺失或类型不对时返回 None。"""

    if not isinstance(item, dict):
        logger.warning("Wiki 第 %s 条不是对象，已跳过。", index)
        return None
    clean: dict[str, Any] = {}
    for field in REQUIRED_FIELDS:
        value = str(item.get(field, "") or "").strip()
        if not value:
            logger.warning("Wiki 第 %s 条缺少字段 %s，已跳过。", index, field)
            return None
        clean[field] = value
    clean["relations"] = _normalize_relations(item.get("relations"))
    return clean


def load_wiki(path: Path | str | None = None) -> list[dict[str, Any]]:
    """读取并校验 Wiki JSON，返回有效条目；文件缺失或损坏时返回空列表。"""

    target = Path(path) if path is not None else wiki_path()
    if not target.is_file():
        return []
    try:
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        logger.warning("读取 Wiki 知识失败：%s（%s）", target, exc)
        return []

    # 兼容 {"items": [...]} 这类包裹结构，主格式仍是纯数组。
    if isinstance(raw, dict):
        for key in ("items", "data", "wiki"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
    if not isinstance(raw, list):
        logger.warning("Wiki 文件不是 JSON 数组：%s", target)
        return []

    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw, start=1):
        entry = _clean_entry(item, index)
        if entry is None:
            continue
        if entry["id"] in seen_ids:
            logger.warning("Wiki id 重复：%s，已跳过。", entry["id"])
            continue
        seen_ids.add(entry["id"])
        entries.append(entry)
    if len(entries) != len(raw):
        logger.info("Wiki 载入 %s/%s 条，其余条目格式不完整已跳过。", len(entries), len(raw))
    return entries


def wiki_categories(entries: list[dict[str, Any]]) -> list[str]:
    """按出现顺序返回去重分类列表，供下拉框使用。"""

    categories: list[str] = []
    for entry in entries:
        category = entry.get("category", "")
        if category and category not in categories:
            categories.append(category)
    return categories


def filter_wiki(
    entries: list[dict[str, Any]],
    keyword: str = "",
    category: str = ALL_CATEGORIES,
) -> list[dict[str, Any]]:
    """按关键词（标题/实体/正文/编号）与分类筛选 Wiki 条目。"""

    needle = (keyword or "").strip().casefold()
    target_category = (category or ALL_CATEGORIES).strip()
    results: list[dict[str, Any]] = []
    for entry in entries:
        if target_category not in ("", ALL_CATEGORIES) and entry["category"] != target_category:
            continue
        if needle:
            haystack = " ".join(
                (entry["id"], entry["category"], entry["entity"], entry["title"], entry["content"])
            ).casefold()
            if needle not in haystack:
                continue
        results.append(entry)
    # 按编号升序（E001、E002…），切换分类后表格第一行就是该分类的第一条。
    results.sort(key=lambda item: item["id"])
    return results


def wiki_rows(entries: list[dict[str, Any]]) -> list[list[str]]:
    """把 Wiki 条目转换为 Dataframe 行：编号、标题、分类、实体、内容。"""

    return [
        [entry["id"], entry["title"], entry["category"], entry["entity"], entry["content"]]
        for entry in entries
    ]


def wiki_overview(entries: list[dict[str, Any]] | None = None) -> str:
    """返回“共 N 条、M 个分类、K 个实体”的一行概览。"""

    items = load_wiki() if entries is None else entries
    entities = {entry["entity"] for entry in items}
    return (
        f"知识库共 **{len(items)}** 条，"
        f"**{len(wiki_categories(items))}** 个分类，"
        f"**{len(entities)}** 个实体"
    )
