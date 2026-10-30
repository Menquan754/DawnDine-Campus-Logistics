"""导航与知识库回调。"""

from __future__ import annotations

import html
import logging
from typing import Any

import gradio as gr

from dawndine.config import KG_HTML_FILE
from dawndine.knowledge.graph_builder import build_knowledge_graph
from dawndine.knowledge.wiki import (
    ALL_CATEGORIES,
    filter_wiki,
    load_wiki,
    wiki_overview,
    wiki_rows,
)
from dawndine.ui.handlers.common import _short_error

logger = logging.getLogger(__name__)

def switch_page(choice: str) -> tuple[Any, ...]:
    """切换五个工作区，返回可见性更新。"""

    return (
        gr.update(visible=choice == "chat"),
        gr.update(visible=choice == "watermark"),
        gr.update(visible=choice == "maintenance"),
        gr.update(visible=choice == "schedule"),
        gr.update(visible=choice == "kg"),
    )


def _kg_empty_html(message: str) -> str:
    """知识图谱未生成时的占位提示。"""

    return f'<div class="dd-kg-empty">{html.escape(message)}</div>'


def kg_iframe_html() -> str:
    """读取 data/kg.html，用 srcdoc 嵌入 iframe，隔离 pyvis 的脚本与样式。"""

    if not KG_HTML_FILE.is_file():
        return _kg_empty_html(
            "尚未生成知识图谱：请点击上方“刷新图谱”，或执行 uv add networkx pyvis 后重试。"
        )
    try:
        raw = KG_HTML_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        logger.exception("读取知识图谱 HTML 失败")
        return _kg_empty_html(f"读取知识图谱失败：{_short_error(exc)}")
    return (
        '<iframe class="dd-kg-frame" title="后勤知识图谱" '
        f'srcdoc="{html.escape(raw, quote=True)}"></iframe>'
    )


def initial_kg_html() -> str:
    """首次进入页面时尽量生成图谱；缺少依赖时显示安装提示。"""

    if not KG_HTML_FILE.is_file():
        try:
            build_knowledge_graph()
        except Exception as exc:  # noqa: BLE001
            logger.info("知识图谱尚未生成：%s", exc)
            return _kg_empty_html(f"知识图谱尚未生成：{_short_error(exc)}")
    return kg_iframe_html()


def refresh_kg_view() -> tuple[str, str]:
    """重新构建 Wiki 图谱并返回新的 iframe HTML 与结果提示。"""

    try:
        stats = build_knowledge_graph()
    except Exception as exc:  # noqa: BLE001
        logger.exception("刷新知识图谱失败")
        return kg_iframe_html(), f"⚠️ 知识图谱生成失败：{_short_error(exc)}"
    return kg_iframe_html(), (
        f"✅ 已生成知识图谱：**{stats['entries']}** 条 Wiki、"
        f"**{stats['categories']}** 个分类、**{stats['entities']}** 个实体、"
        f"**{stats['relations']}** 条关联（{stats['nodes']} 个节点 / {stats['edges']} 条边）。"
    )


def query_wiki_view(keyword: str, category: str) -> tuple[list[list[str]], str]:
    """按关键词与分类筛选 Wiki，并返回表格行与统计提示。"""

    entries = load_wiki()
    matched = filter_wiki(entries, keyword=keyword or "", category=category or ALL_CATEGORIES)
    status = f"筛选出 **{len(matched)}** 条 / 共 **{len(entries)}** 条；{wiki_overview(entries)}"
    return wiki_rows(matched), status
