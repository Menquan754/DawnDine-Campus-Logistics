"""页D：我的日程界面与事件接线。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import gradio as gr

from dawndine.config import SCHEDULE_TABLE_HEADERS
from dawndine.llm import get_vision_model_name
from dawndine.ui.handlers.schedule import (
    _schedule_choices,
    _schedule_rows,
    _schedule_selection_summary,
    add_manual_schedule,
    analyze_schedule_view,
    clear_all_schedules,
    clear_schedule_selection,
    delete_selected_schedules,
    export_schedule_image,
    import_schedule_from_image,
    on_schedule_selection,
    refresh_schedule_pick_and_box,
    refresh_schedules,
    select_all_schedules,
    update_schedule_from_ui,
)
from dawndine.ui.theme import _TABLE_DATATYPE


def build_schedule_page() -> dict[str, Any]:
    """构建我的日程页布局，返回组件引用。"""

    with gr.Column(visible=False, elem_classes="dd-page") as page_schedule:
        gr.Markdown("### 📅 我的日程", elem_classes="dd-card-title")
        gr.Markdown(
            "台账、异常、水印成功后自动沉淀；也可以上传通知截图用 Qwen-VL 解析，"
            "或手动添加。",
            elem_classes="dd-hint",
        )
        # 模块 1：日程列表（置顶，先看数据再操作）
        with gr.Group(elem_classes="dd-sch-module"):
            with gr.Row(elem_classes="dd-table-toolbar"):
                gr.Markdown(
                    "#### 📋 日程列表（按日期/时间倒序）",
                    elem_classes="dd-card-title",
                )
                schedule_view = gr.Radio(
                    ["全部", "今天", "未来 7 天", "待补时间"],
                    value="全部",
                    show_label=False,
                    scale=3,
                    elem_classes="dd-view-radio",
                )
                refresh_schedule_button = gr.Button(
                    "刷新", size="sm", variant="secondary", scale=0
                )
            schedule_table = gr.Dataframe(
                headers=list(SCHEDULE_TABLE_HEADERS),
                datatype=_TABLE_DATATYPE,
                value=_schedule_rows(),
                type="array",
                interactive=False,
                wrap=True,
                max_height=360,
                label=None,
            )
            gr.Markdown(
                "视图可切换为今天、未来 7 天或待补时间；“刷新”会重新读取本地 SQLite。",
                elem_classes="dd-hint",
            )

        # 模块 2：图片导入日程
        with gr.Group(elem_classes="dd-sch-module"):
            gr.Markdown("#### 📷 图片导入日程", elem_classes="dd-sch-title")
            gr.Markdown(
                "Qwen-VL 会从通知、排班或日程截图中抽取日期、时间、事项和地点，"
                "确认后写入本地 SQLite。",
                elem_classes="dd-hint",
            )
            with gr.Row():
                with gr.Column(scale=2):
                    schedule_image = gr.Image(
                        label="上传日程/通知截图",
                        type="filepath",
                        sources=["upload"],
                        height=170,
                        show_download_button=False,
                    )
                with gr.Column(scale=3):
                    import_schedule_button = gr.Button(
                        "解析图片并导入日程",
                        variant="primary",
                    )
                    schedule_status = gr.Markdown(
                        f"图片解析使用 {get_vision_model_name()}，"
                        "需要当前会话或 .env 中有 Key。",
                        elem_classes="dd-status",
                    )

        # 模块 3：手动添加日程
        with gr.Group(elem_classes="dd-sch-module"):
            gr.Markdown("#### ✍️ 手动添加日程", elem_classes="dd-sch-title")
            gr.Markdown(
                "适合临时会议、检查安排；日期用 YYYY-MM-DD，时间用 HH:MM，"
                "留空时间会进入“待补时间”视图。",
                elem_classes="dd-hint",
            )
            with gr.Row():
                schedule_date = gr.Textbox(
                    label="日期",
                    value=datetime.now().strftime("%Y-%m-%d"),
                    placeholder="YYYY-MM-DD",
                    scale=2,
                )
                schedule_time = gr.Textbox(
                    label="时间",
                    value=datetime.now().strftime("%H:%M"),
                    placeholder="HH:MM",
                    scale=2,
                )
                schedule_content = gr.Textbox(
                    label="事项",
                    placeholder="例如：检查冷库温度并拍照",
                    lines=1,
                    scale=5,
                )
            add_schedule_button = gr.Button("添加日程", variant="primary")

        # 模块 4：导出图片 / 日程分析
        with gr.Group(elem_classes="dd-sch-module"):
            gr.Markdown("#### 🖼️ 导出图片 / 日程分析", elem_classes="dd-sch-title")
            gr.Markdown(
                "导出会把当前视图画成 PNG 表格图，方便打印或转发；"
                "分析会统计今天、未来 7 天、待补时间、日期已过与时间冲突。",
                elem_classes="dd-hint",
            )
            with gr.Row():
                with gr.Column(scale=3):
                    with gr.Row():
                        export_schedule_button = gr.Button(
                            "导出当前视图图片",
                            variant="secondary",
                            scale=1,
                        )
                        analyze_schedule_button = gr.Button(
                            "分析当前日程",
                            variant="secondary",
                            scale=1,
                        )
                    schedule_export_status = gr.Markdown("", elem_classes="dd-status")
                    schedule_analysis_md = gr.Markdown("", elem_classes="dd-key-status")
                    schedule_export_path = gr.Textbox(
                        label="导出文件路径",
                        value="",
                        interactive=False,
                        show_copy_button=True,
                        elem_id="dd-export-path",
                    )
                with gr.Column(scale=2):
                    schedule_export_image = gr.Image(
                        label="导出的日程图片",
                        type="filepath",
                        interactive=False,
                        height=260,
                        show_download_button=True,
                    )

        # 模块 5：修改 / 删除日程
        with gr.Group(elem_classes="dd-sch-module"):
            gr.Markdown("#### ✏️ 修改 / 删除日程", elem_classes="dd-sch-title")
            gr.Markdown(
                "点击任意一条日程即可勾选（整行可点），也可以按住鼠标拖动框选多行；"
                "勾选结果会实时列在下方“待删除清单”。",
                elem_classes="dd-hint",
            )
            with gr.Row(elem_classes="dd-sched-tools"):
                select_all_schedules_button = gr.Button(
                    "一键勾选",
                    size="sm",
                    variant="secondary",
                    scale=0,
                )
                clear_schedule_selection_button = gr.Button(
                    "取消勾选",
                    size="sm",
                    variant="secondary",
                    scale=0,
                )
                delete_schedule_button = gr.Button(
                    "一键删除所选",
                    variant="stop",
                    scale=0,
                )
            schedule_pick = gr.CheckboxGroup(
                label="勾选要删除的日程（点击整行 / 按住拖动框选）",
                choices=_schedule_choices(),
                value=[],
                interactive=True,
                elem_id="dd-sched-select",
            )
            schedule_selection_box = gr.Markdown(
                _schedule_selection_summary([]),
                elem_classes="dd-delete-box",
            )
            with gr.Row():
                schedule_id = gr.Number(
                    label="日程编号（勾选单条时自动填入）",
                    precision=0,
                    minimum=1,
                    scale=1,
                )
                update_schedule_button = gr.Button("修改", variant="secondary", scale=1)
            with gr.Row():
                edit_date = gr.Textbox(
                    label="日期",
                    placeholder="留空表示不修改",
                    scale=2,
                )
                edit_time = gr.Textbox(
                    label="时间",
                    placeholder="留空表示不修改",
                    scale=2,
                )
                edit_content = gr.Textbox(
                    label="事项",
                    placeholder="留空表示不修改",
                    lines=1,
                    scale=5,
                )
            schedule_edit_status = gr.Markdown("", elem_classes="dd-status")
            with gr.Accordion("危险操作：清空全部日程", open=False):
                gr.Markdown(
                    "清空后不可恢复，建议先导出或确认无需保留。",
                    elem_classes="dd-hint",
                )
                with gr.Row():
                    clear_all_confirm = gr.Checkbox(
                        label="我确认清空全部日程",
                        scale=3,
                    )
                    clear_all_button = gr.Button(
                        "清空全部",
                        variant="stop",
                        scale=1,
                    )
    return {
        "page": page_schedule,
        "table": schedule_table,
        "view": schedule_view,
        "pick": schedule_pick,
        "selection_box": schedule_selection_box,
        "status": schedule_status,
        "edit_status": schedule_edit_status,
        "analysis": schedule_analysis_md,
        "export_status": schedule_export_status,
        "export_path": schedule_export_path,
        "export_image": schedule_export_image,
        "image": schedule_image,
        "date": schedule_date,
        "time": schedule_time,
        "content": schedule_content,
        "schedule_id": schedule_id,
        "edit_date": edit_date,
        "edit_time": edit_time,
        "edit_content": edit_content,
        "clear_confirm": clear_all_confirm,
        "refresh_button": refresh_schedule_button,
        "export_button": export_schedule_button,
        "analyze_button": analyze_schedule_button,
        "update_button": update_schedule_button,
        "add_button": add_schedule_button,
        "import_button": import_schedule_button,
        "select_all_button": select_all_schedules_button,
        "clear_selection_button": clear_schedule_selection_button,
        "delete_button": delete_schedule_button,
        "clear_all_button": clear_all_button,
    }


def wire_schedule_page(c: dict[str, Any], shared: dict[str, Any]) -> None:
    """接线日程刷新、勾选、修改、删除、导出与导入。"""

    c["refresh_button"].click(
        refresh_schedules,
        inputs=c["view"],
        outputs=c["table"],
        api_name="refresh_schedules",
    ).then(
        refresh_schedule_pick_and_box,
        inputs=c["view"],
        outputs=[c["pick"], c["selection_box"]],
        api_name=False,
    )
    c["view"].change(
        refresh_schedules,
        inputs=c["view"],
        outputs=c["table"],
        api_name=False,
    )
    c["view"].change(
        refresh_schedule_pick_and_box,
        inputs=c["view"],
        outputs=[c["pick"], c["selection_box"]],
        api_name=False,
    )
    c["pick"].change(
        on_schedule_selection,
        inputs=[c["pick"], c["view"]],
        outputs=[c["schedule_id"], c["selection_box"]],
        api_name=False,
    )
    c["select_all_button"].click(
        select_all_schedules,
        inputs=c["view"],
        outputs=[c["pick"], c["selection_box"]],
        api_name=False,
    )
    c["clear_selection_button"].click(
        clear_schedule_selection,
        inputs=c["view"],
        outputs=[c["pick"], c["selection_box"]],
        api_name=False,
    )
    c["delete_button"].click(
        delete_selected_schedules,
        inputs=[c["pick"], c["view"]],
        outputs=[c["table"], c["pick"], c["selection_box"], c["edit_status"]],
        api_name="delete_schedules",
    )
    c["export_button"].click(
        export_schedule_image,
        inputs=c["view"],
        outputs=[c["export_image"], c["export_status"], c["export_path"]],
        api_name="export_schedule_image",
    )
    c["analyze_button"].click(
        analyze_schedule_view,
        inputs=None,
        outputs=c["analysis"],
        api_name="analyze_schedules",
    )
    c["clear_all_button"].click(
        clear_all_schedules,
        inputs=[c["clear_confirm"], c["view"]],
        outputs=[c["table"], c["pick"], c["selection_box"], c["edit_status"]],
        api_name="clear_all_schedules",
    )
    c["update_button"].click(
        update_schedule_from_ui,
        inputs=[c["schedule_id"], c["edit_date"], c["edit_time"], c["edit_content"], c["view"]],
        outputs=[c["table"], c["edit_status"]],
        api_name=False,
    ).then(
        refresh_schedule_pick_and_box,
        inputs=c["view"],
        outputs=[c["pick"], c["selection_box"]],
        api_name=False,
    )
    c["add_button"].click(
        add_manual_schedule,
        inputs=[c["date"], c["time"], c["content"]],
        outputs=[c["table"], c["status"], c["content"]],
        api_name="add_schedule",
    ).then(
        refresh_schedule_pick_and_box,
        inputs=c["view"],
        outputs=[c["pick"], c["selection_box"]],
        api_name=False,
    )
    c["import_button"].click(
        import_schedule_from_image,
        inputs=[c["image"], shared["api_key_state"]],
        outputs=[c["status"], c["table"]],
        api_name="import_schedule_image",
    ).then(
        refresh_schedule_pick_and_box,
        inputs=c["view"],
        outputs=[c["pick"], c["selection_box"]],
        api_name=False,
    )
