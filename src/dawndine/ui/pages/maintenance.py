"""页C：后勤维修界面与事件接线。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import gradio as gr

from dawndine.config import MAINTENANCE_STATS_HEADERS, MAINTENANCE_TABLE_HEADERS
from dawndine.llm import get_vision_model_name
from dawndine.ui.handlers.maintenance import (
    _maintenance_choices,
    _maintenance_overview_md,
    _maintenance_rows,
    _maintenance_selection_summary,
    _maintenance_stats_rows,
    add_manual_maintenance,
    clear_all_maintenance,
    clear_maintenance_selection,
    delete_selected_maintenance,
    export_maintenance_report,
    import_maintenance_from_image,
    on_maintenance_selection,
    refresh_maintenance_page,
    select_all_maintenance,
)
from dawndine.ui.theme import _MAINTENANCE_DATATYPE


def build_maintenance_page() -> dict[str, Any]:
    """构建后勤维修页布局，返回组件引用。"""

    with gr.Column(visible=False, elem_classes="dd-page") as page_maintenance:
        gr.Markdown("### 🔧 后勤维修", elem_classes="dd-card-title")
        gr.Markdown(
            "上传维修单照片用 Qwen-VL 自动识别，也可以手动补录；"
            "勾选任意记录即可删除，一键导出含明细与各地统计的总表。",
            elem_classes="dd-hint",
        )

        # 模块 1：维修明细
        with gr.Group(elem_classes="dd-maint-module"):
            with gr.Row(elem_classes="dd-table-toolbar"):
                gr.Markdown(
                    "#### 📋 维修明细（按地点 A-Z 排序）",
                    elem_classes="dd-card-title",
                )
                refresh_maintenance_button = gr.Button(
                    "刷新", size="sm", variant="secondary", scale=0
                )
            maintenance_overview = gr.Markdown(
                _maintenance_overview_md(),
                elem_classes="dd-hint",
            )
            maintenance_table = gr.Dataframe(
                headers=list(MAINTENANCE_TABLE_HEADERS),
                datatype=_MAINTENANCE_DATATYPE,
                value=_maintenance_rows(),
                type="array",
                interactive=False,
                wrap=True,
                max_height=320,
                label=None,
            )

        # 模块 2：图片解析录入
        with gr.Group(elem_classes="dd-maint-module"):
            gr.Markdown("#### 📷 图片解析录入", elem_classes="dd-maint-title")
            gr.Markdown(
                f"解析使用 {get_vision_model_name()}，需要当前会话或 .env 中有 Key；"
                "录入后状态默认“待处理”。",
                elem_classes="dd-hint",
            )
            with gr.Row():
                with gr.Column(scale=2):
                    maintenance_image = gr.Image(
                        label="上传维修单图片",
                        type="filepath",
                        sources=["upload"],
                        height=180,
                        show_download_button=False,
                    )
                with gr.Column(scale=3):
                    import_maintenance_button = gr.Button("解析并录入", variant="primary")
                    maintenance_status = gr.Markdown(
                        "上传维修单后点击“解析并录入”，识别结果会写入本机 SQLite。",
                        elem_classes="dd-status",
                    )

        # 模块 3：手动添加维修单
        with gr.Group(elem_classes="dd-maint-module"):
            gr.Markdown("#### ✍️ 手动添加维修单", elem_classes="dd-maint-title")
            gr.Markdown(
                "没有 Key 或图片不清楚时可直接手填；地点留空记为“待补”，日期留空默认今天。",
                elem_classes="dd-hint",
            )
            with gr.Row():
                maintenance_location = gr.Textbox(
                    label="地点",
                    placeholder="例如：一食堂 冷库",
                    scale=2,
                )
                maintenance_issue = gr.Textbox(
                    label="故障描述",
                    placeholder="例如：冷库温度异常，门封条破损",
                    lines=1,
                    scale=5,
                )
            with gr.Row():
                maintenance_reporter = gr.Textbox(
                    label="报修人",
                    placeholder="留空记为待补",
                    scale=2,
                )
                maintenance_report_date = gr.Textbox(
                    label="报修日期",
                    value=datetime.now().strftime("%Y-%m-%d"),
                    placeholder="YYYY-MM-DD",
                    scale=2,
                )
                add_maintenance_button = gr.Button(
                    "添加维修单",
                    variant="secondary",
                    scale=1,
                )
            maintenance_manual_status = gr.Markdown("", elem_classes="dd-status")

        # 模块 4：各地维修统计 / 导出总表
        with gr.Group(elem_classes="dd-maint-module"):
            gr.Markdown(
                "#### 📤 各地维修统计 / 导出总表",
                elem_classes="dd-maint-title",
            )
            with gr.Row():
                with gr.Column(scale=3):
                    maintenance_stats = gr.Dataframe(
                        headers=list(MAINTENANCE_STATS_HEADERS),
                        datatype=["str", "number"],
                        value=_maintenance_stats_rows(),
                        type="array",
                        interactive=False,
                        wrap=True,
                        max_height=260,
                        label=None,
                    )
                with gr.Column(scale=2):
                    gr.Markdown(
                        "导出为**一个 Excel 文件**：工作表“维修明细”含全部字段，"
                        "工作表“各地维修统计”按地点汇总维修数量。",
                        elem_classes="dd-hint",
                    )
                    export_maintenance_button = gr.Button(
                        "导出总表 (Excel)",
                        variant="secondary",
                    )
                    maintenance_export_status = gr.Markdown("", elem_classes="dd-status")
                    maintenance_report_file = gr.File(
                        label="维修总表 Excel（明细 + 各地统计）",
                        interactive=False,
                    )

        # 模块 5：删除维修记录
        with gr.Group(elem_classes="dd-maint-module"):
            gr.Markdown("#### 🗑️ 删除维修记录", elem_classes="dd-maint-title")
            gr.Markdown(
                "点击任意一条维修记录即可勾选（整行可点），也可以按住鼠标拖动框选多行；"
                "勾选结果会实时列在下方“待删除清单”。",
                elem_classes="dd-hint",
            )
            with gr.Row(elem_classes="dd-sched-tools"):
                select_all_maintenance_button = gr.Button(
                    "一键勾选",
                    size="sm",
                    variant="secondary",
                    scale=0,
                )
                clear_maintenance_selection_button = gr.Button(
                    "取消勾选",
                    size="sm",
                    variant="secondary",
                    scale=0,
                )
                delete_maintenance_button = gr.Button(
                    "一键删除所选",
                    variant="stop",
                    scale=0,
                )
            maintenance_pick = gr.CheckboxGroup(
                label="勾选要删除的维修记录（点击整行 / 按住拖动框选）",
                choices=_maintenance_choices(),
                value=[],
                interactive=True,
                elem_id="dd-maint-select",
            )
            maintenance_selection_box = gr.Markdown(
                _maintenance_selection_summary([]),
                elem_classes="dd-delete-box",
            )
            maintenance_delete_status = gr.Markdown("", elem_classes="dd-status")
            with gr.Accordion("危险操作：清空全部维修记录", open=False):
                gr.Markdown(
                    "清空后不可恢复，建议先导出总表或确认无需保留。",
                    elem_classes="dd-hint",
                )
                with gr.Row():
                    maintenance_clear_confirm = gr.Checkbox(
                        label="我确认清空全部维修记录",
                        scale=3,
                    )
                    clear_all_maintenance_button = gr.Button(
                        "清空全部",
                        variant="stop",
                        scale=1,
                    )
    return {
        "page": page_maintenance,
        "table": maintenance_table,
        "stats": maintenance_stats,
        "overview": maintenance_overview,
        "pick": maintenance_pick,
        "selection_box": maintenance_selection_box,
        "delete_status": maintenance_delete_status,
        "manual_status": maintenance_manual_status,
        "import_status": maintenance_status,
        "export_status": maintenance_export_status,
        "report_file": maintenance_report_file,
        "image": maintenance_image,
        "location": maintenance_location,
        "issue": maintenance_issue,
        "reporter": maintenance_reporter,
        "report_date": maintenance_report_date,
        "clear_confirm": maintenance_clear_confirm,
        "import_button": import_maintenance_button,
        "add_button": add_maintenance_button,
        "refresh_button": refresh_maintenance_button,
        "select_all_button": select_all_maintenance_button,
        "clear_selection_button": clear_maintenance_selection_button,
        "delete_button": delete_maintenance_button,
        "clear_all_button": clear_all_maintenance_button,
        "export_button": export_maintenance_button,
    }


def wire_maintenance_page(c: dict[str, Any], shared: dict[str, Any]) -> None:
    """接线维修录入、刷新、勾选与删除。"""

    refresh_outputs = [
        c["table"],
        c["stats"],
        c["overview"],
        c["pick"],
        c["selection_box"],
    ]
    c["import_button"].click(
        import_maintenance_from_image,
        inputs=[c["image"], shared["api_key_state"]],
        outputs=[c["import_status"], *refresh_outputs],
        api_name="import_maintenance_image",
    )
    c["add_button"].click(
        add_manual_maintenance,
        inputs=[
            c["location"],
            c["issue"],
            c["reporter"],
            c["report_date"],
        ],
        outputs=[c["manual_status"], *refresh_outputs],
        api_name="add_maintenance",
    )
    c["refresh_button"].click(
        refresh_maintenance_page,
        inputs=None,
        outputs=refresh_outputs,
        api_name="refresh_maintenance",
    )
    c["pick"].change(
        on_maintenance_selection,
        inputs=c["pick"],
        outputs=[c["selection_box"]],
        api_name=False,
    )
    c["select_all_button"].click(
        select_all_maintenance,
        inputs=None,
        outputs=[c["pick"], c["selection_box"]],
        api_name=False,
    )
    c["clear_selection_button"].click(
        clear_maintenance_selection,
        inputs=None,
        outputs=[c["pick"], c["selection_box"]],
        api_name=False,
    )
    c["delete_button"].click(
        delete_selected_maintenance,
        inputs=c["pick"],
        outputs=[*refresh_outputs, c["delete_status"]],
        api_name="delete_selected_maintenance",
    )
    c["clear_all_button"].click(
        clear_all_maintenance,
        inputs=c["clear_confirm"],
        outputs=[*refresh_outputs, c["delete_status"]],
        api_name="clear_all_maintenance",
    )
    c["export_button"].click(
        export_maintenance_report,
        inputs=None,
        outputs=[c["report_file"], c["export_status"]],
        api_name="export_maintenance_report",
    )
