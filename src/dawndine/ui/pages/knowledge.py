"""页E：知识库（知识图谱 + Wiki 查询）界面与事件接线。"""

from __future__ import annotations

from typing import Any

import gradio as gr

from dawndine.knowledge.wiki import (
    ALL_CATEGORIES,
    WIKI_TABLE_HEADERS,
    load_wiki,
    wiki_categories,
    wiki_overview,
    wiki_rows,
)
from dawndine.ui.handlers.knowledge import (
    initial_kg_html,
    query_wiki_view,
    refresh_kg_view,
)
from dawndine.ui.theme import _WIKI_SCROLL_JS


def build_knowledge_page() -> dict[str, Any]:
    """构建知识库页布局，返回组件引用。"""

    initial_wiki_entries = load_wiki()
    wiki_category_choices = [ALL_CATEGORIES, *wiki_categories(initial_wiki_entries)]
    initial_wiki_rows = wiki_rows(initial_wiki_entries)
    initial_kg = initial_kg_html()

    with gr.Column(visible=False, elem_classes="dd-page") as page_kg:
        gr.Markdown("### 📚 知识库", elem_classes="dd-card-title")
        gr.Markdown(
            "系统化 Wiki 知识（食安法规、食堂操作、维修响应、设备空间）与实体关联图谱；"
            "支持关键词检索与分类筛选，Agent 回答食安/维修问题前会优先检索这里。",
            elem_classes="dd-hint",
        )
        with gr.Tabs():
            with gr.Tab("🕸️ 知识图谱"):
                with gr.Row(elem_classes="dd-table-toolbar"):
                    gr.Markdown("#### 分类—实体—关联图谱", elem_classes="dd-card-title")
                    refresh_kg_button = gr.Button(
                        "刷新图谱", variant="primary", size="sm", scale=0
                    )
                kg_status = gr.Markdown(
                    f"{wiki_overview(initial_wiki_entries)}；点击“刷新图谱”可重新生成。",
                    elem_classes="dd-status",
                )
                kg_view = gr.HTML(value=initial_kg, elem_id="dd-kg")
                gr.Markdown(
                    "鼠标停在节点上会弹出小框，显示该条知识的编号与内容，移开即消失；"
                    "拖拽节点可调整布局，滚轮缩放，右上角按钮可展开导航；"
                    "绿色为食安与食堂，蓝色为维修，紫色为设备空间，灰色为关联概念。",
                    elem_classes="dd-hint",
                )
            with gr.Tab("🔎 Wiki 知识查询"):
                with gr.Row(elem_classes="dd-panel"):
                    wiki_search = gr.Textbox(
                        label="关键词",
                        placeholder="输入编号、实体、标题或正文关键词，如：E001、留样柜、爆管",
                        scale=3,
                    )
                    wiki_category = gr.Dropdown(
                        label="分类",
                        choices=wiki_category_choices,
                        value=ALL_CATEGORIES,
                        scale=2,
                    )
                    wiki_search_button = gr.Button(
                        "搜索", variant="primary", size="sm", scale=0
                    )
                    wiki_reload_button = gr.Button(
                        "刷新列表", variant="secondary", size="sm", scale=0
                    )
                wiki_status = gr.Markdown(
                    f"共 **{len(initial_wiki_entries)}** 条；"
                    f"{wiki_overview(initial_wiki_entries)}",
                    elem_classes="dd-status",
                )
                wiki_table = gr.Dataframe(
                    headers=list(WIKI_TABLE_HEADERS),
                    value=initial_wiki_rows,
                    datatype=["str", "str", "str", "str", "str"],
                    type="array",
                    interactive=False,
                    wrap=True,
                    max_height=430,
                    column_widths=["9%", "22%", "15%", "15%", "39%"],
                    elem_id="dd-wiki-table",
                    label=None,
                )
    return {
        "page": page_kg,
        "kg_view": kg_view,
        "kg_status": kg_status,
        "refresh_kg_button": refresh_kg_button,
        "wiki_search": wiki_search,
        "wiki_category": wiki_category,
        "wiki_status": wiki_status,
        "wiki_table": wiki_table,
        "wiki_search_button": wiki_search_button,
        "wiki_reload_button": wiki_reload_button,
    }


def wire_knowledge_page(c: dict[str, Any]) -> None:
    """接线图谱刷新与 Wiki 检索。"""

    c["refresh_kg_button"].click(
        refresh_kg_view,
        inputs=None,
        outputs=[c["kg_view"], c["kg_status"]],
        api_name=False,
    )
    c["wiki_search_button"].click(
        query_wiki_view,
        inputs=[c["wiki_search"], c["wiki_category"]],
        outputs=[c["wiki_table"], c["wiki_status"]],
        api_name=False,
    )
    c["wiki_search"].submit(
        query_wiki_view,
        inputs=[c["wiki_search"], c["wiki_category"]],
        outputs=[c["wiki_table"], c["wiki_status"]],
        api_name=False,
    )
    c["wiki_category"].change(
        query_wiki_view,
        inputs=[c["wiki_search"], c["wiki_category"]],
        outputs=[c["wiki_table"], c["wiki_status"]],
        js=_WIKI_SCROLL_JS,
        api_name=False,
    )
    c["wiki_reload_button"].click(
        query_wiki_view,
        inputs=[c["wiki_search"], c["wiki_category"]],
        outputs=[c["wiki_table"], c["wiki_status"]],
        api_name=False,
    )
