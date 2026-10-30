"""页B：图片水印界面与事件接线。"""

from __future__ import annotations

from typing import Any

import gradio as gr

from dawndine.ui.handlers.common import _template_choices
from dawndine.ui.handlers.schedule import refresh_schedule_pick_and_box
from dawndine.ui.handlers.watermark import (
    _COLUMN_POSITION_OPTIONS,
    _FIELD_COLUMN_OPTIONS,
    _FIELD_POSITION_OPTIONS,
    _STYLE_COLOR_OPTIONS,
    _STYLE_DATE_OPTIONS,
    _STYLE_FORMAT_OPTIONS,
    _STYLE_GAP_OPTIONS,
    _STYLE_POSITION_OPTIONS,
    _STYLE_SIZE_OPTIONS,
    _STYLE_TIME_OPTIONS,
    _TEMPLATE_POSITION_PROMPTS,
    _TEMPLATE_SPACING_PROMPTS,
    apply_watermark_columns_from_ui,
    apply_watermark_style_from_ui,
    clear_watermark_columns_from_ui,
    create_template_from_upload,
    delete_template_from_ui,
    load_template_columns,
    render_watermark_from_upload,
    show_template_style,
    show_watermark_home,
    show_watermark_manage,
    show_watermark_new,
    show_watermark_render,
)


def build_watermark_page() -> dict[str, Any]:
    """构建图片水印页布局，返回组件引用。"""

    initial_templates = _template_choices()
    initial_template = initial_templates[0] if initial_templates else None
    (
        initial_left_text,
        initial_left_position,
        initial_right_text,
        initial_right_position,
    ) = load_template_columns(initial_template)

    with gr.Column(visible=False, elem_classes="dd-page") as page_watermark:
        gr.Markdown("### 🖼️ 图片水印", elem_classes="dd-card-title")
        gr.Markdown(
            "先上传样图建立模板，再用现场照片生成带日期、时间、地点和防伪码的"
            "陪餐/验收打卡图。地点和时间可勾选是否上图。",
            elem_classes="dd-hint",
        )
        watermark_status = gr.Markdown(
            "准备就绪。生成图片成功后会自动写入“我的日程”。",
            elem_classes="dd-status",
        )
        # 区域 A：主操作区（默认可见）
        with gr.Column(visible=True, elem_classes="dd-wm-home") as watermark_home:
            gr.Markdown("#### 选择要进行的操作", elem_classes="dd-card-title")
            with gr.Row(elem_classes="dd-wm-actions"):
                watermark_new_button = gr.Button(
                    "📝 新建水印模板",
                    elem_classes="dd-wm-card",
                    scale=1,
                )
                watermark_render_button = gr.Button(
                    "📸 生成图片",
                    elem_classes="dd-wm-card",
                    scale=1,
                )
                watermark_manage_button = gr.Button(
                    "📁 管理已有模板",
                    elem_classes="dd-wm-card",
                    scale=1,
                )
            gr.Markdown(
                "先新建模板，再到“管理已有模板”调整格式与内容栏，"
                "最后在“生成图片”上传现场照片出图。",
                elem_classes="dd-hint",
            )

        # 区域 B：新建水印模板（默认隐藏）
        with gr.Column(visible=False) as watermark_new_panel:
            with gr.Group(elem_classes="dd-wm-modal"):
                gr.Markdown("#### 📝 新建水印模板", elem_classes="dd-card-title")
                gr.Markdown(
                    "上传样图后，系统会分析色块与布局生成模板；"
                    "模板名称重复时会覆盖同名模板。",
                    elem_classes="dd-hint",
                )
                sample_image = gr.Image(
                    label="样图（分析色块与布局）",
                    type="filepath",
                    sources=["upload"],
                    height=210,
                    show_download_button=False,
                )
                new_template_name = gr.Textbox(
                    label="模板名称",
                    value="default",
                    placeholder="default",
                )
                template_requirement = gr.Textbox(
                    label="样式要求（可选）",
                    placeholder="例如：左下角打卡时间、深蓝底白字；右下角标题和地点",
                    lines=2,
                )
                with gr.Row():
                    template_position = gr.Dropdown(
                        label="水印位置",
                        choices=list(_TEMPLATE_POSITION_PROMPTS),
                        value="自动（按样图）",
                        scale=2,
                    )
                    template_spacing = gr.Dropdown(
                        label="元素间距",
                        choices=list(_TEMPLATE_SPACING_PROMPTS),
                        value="紧贴（推荐）",
                        scale=1,
                    )
                with gr.Row():
                    template_format = gr.Dropdown(
                        label="水印格式",
                        choices=list(_STYLE_FORMAT_OPTIONS)[1:],
                        value="标准（标题+地点+日期+时间）",
                        scale=2,
                    )
                    template_size = gr.Dropdown(
                        label="字号大小",
                        choices=list(_STYLE_SIZE_OPTIONS)[1:],
                        value="标准（1.0 倍）",
                        scale=1,
                    )
                with gr.Row():
                    template_color = gr.Dropdown(
                        label="配色",
                        choices=list(_STYLE_COLOR_OPTIONS)[1:],
                        value="白字深绿底（推荐）",
                        scale=2,
                    )
                    template_opacity = gr.Slider(
                        label="底框透明度（0=保持原样）",
                        minimum=0,
                        maximum=255,
                        value=0,
                        step=5,
                        scale=2,
                    )
                create_template_button = gr.Button("上传样图新建模板", variant="secondary")
                watermark_new_close_button = gr.Button(
                    "关闭并返回",
                    variant="secondary",
                    elem_classes="dd-wm-close",
                )

        # 区域 C：生成图片（默认隐藏）
        with gr.Column(visible=False) as watermark_render_panel:
            with gr.Group(elem_classes="dd-wm-modal"):
                gr.Markdown("#### 📸 生成图片", elem_classes="dd-card-title")
                gr.Markdown(
                    "当前模板在“📁 管理已有模板”中选择。地点与时间可自行勾选是否上图："
                    "勾选地点后留空则不写地点，勾选时间后留空则使用当前时间；"
                    "启用内容栏时，可指定地点/时间并入内容栏1或内容栏2的最上面或最下面。",
                    elem_classes="dd-hint",
                )
                scene_image = gr.Image(
                    label="现场照片",
                    type="filepath",
                    sources=["upload"],
                    height=210,
                    show_download_button=False,
                )
                with gr.Row():
                    use_location = gr.Checkbox(
                        label="使用陪餐地点",
                        value=True,
                        scale=1,
                    )
                    use_time = gr.Checkbox(
                        label="使用时间（日期与时间）",
                        value=True,
                        scale=1,
                    )
                location = gr.Textbox(
                    label="陪餐地点",
                    placeholder="例如：第一食堂二楼；勾选后留空则不输出地点",
                )
                manual_time = gr.Textbox(
                    label="手动时间",
                    placeholder="YYYY-MM-DD HH:MM；勾选后留空使用当前时间",
                )
                gr.Markdown("**地点/时间放在哪里**", elem_classes="dd-hint")
                with gr.Row():
                    field_column = gr.Dropdown(
                        label="所在内容栏",
                        choices=list(_FIELD_COLUMN_OPTIONS),
                        value="内容栏1（左）",
                        scale=1,
                    )
                    field_position = gr.Dropdown(
                        label="栏内位置",
                        choices=list(_FIELD_POSITION_OPTIONS),
                        value="最下面",
                        scale=1,
                    )
                gr.Markdown(
                    "未在模板中设置内容栏时，地点/时间按模板原有位置输出，这两项不生效。",
                    elem_classes="dd-hint",
                )
                render_button = gr.Button("生成图片", variant="primary")
                gr.Markdown("**生成结果**", elem_classes="dd-hint")
                result_image = gr.Image(
                    label="生成结果",
                    show_label=False,
                    type="filepath",
                    interactive=False,
                    height=330,
                    show_download_button=True,
                )
                output_path = gr.Textbox(
                    label="output_path（最近一次工具输出）",
                    value="",
                    lines=2,
                    max_lines=3,
                    interactive=False,
                    show_copy_button=True,
                    elem_id="dd-output-path",
                )
                watermark_render_close_button = gr.Button(
                    "关闭并返回",
                    variant="secondary",
                    elem_classes="dd-wm-close",
                )

        # 区域 D：管理已有模板（默认隐藏）
        with gr.Column(visible=False) as watermark_manage_panel:
            with gr.Group(elem_classes="dd-wm-modal"):
                gr.Markdown("#### 📁 管理已有模板", elem_classes="dd-card-title")
                gr.Markdown(
                    "选择模板后可删除、调整格式/位置/字号，或设置内容栏1、内容栏2。",
                    elem_classes="dd-hint",
                )
                template_dropdown = gr.Dropdown(
                    label="当前模板",
                    choices=initial_templates,
                    value=initial_template,
                    interactive=True,
                    allow_custom_value=False,
                )
                with gr.Row():
                    delete_template_confirm = gr.Checkbox(
                        label="我确认删除该模板",
                        scale=2,
                    )
                    delete_template_button = gr.Button(
                        "删除模板",
                        variant="stop",
                        size="sm",
                        scale=1,
                    )
                template_manage_status = gr.Markdown("", elem_classes="dd-hint")
                with gr.Accordion("③ 调整当前模板：格式 / 位置 / 大小", open=False):
                    template_style_summary = gr.Markdown(
                        show_template_style(initial_template),
                        elem_classes="dd-hint",
                    )
                    gr.Markdown(
                        "选择后点击“保存样式”，会写入当前模板，下次生成直接生效；"
                        "选“不调整”的项保持原样。字号可先用预设，再用下方倍率微调。",
                        elem_classes="dd-hint",
                    )
                    with gr.Row():
                        style_format = gr.Dropdown(
                            label="水印格式",
                            choices=list(_STYLE_FORMAT_OPTIONS),
                            value="不调整（保持模板）",
                            scale=2,
                        )
                        style_position = gr.Dropdown(
                            label="位置",
                            choices=list(_STYLE_POSITION_OPTIONS),
                            value="不调整（跟随模板）",
                            scale=2,
                        )
                    with gr.Row():
                        style_size = gr.Dropdown(
                            label="字号",
                            choices=list(_STYLE_SIZE_OPTIONS),
                            value="不调整（保持字号）",
                            scale=1,
                        )
                        style_color = gr.Dropdown(
                            label="配色",
                            choices=list(_STYLE_COLOR_OPTIONS),
                            value="不调整（保持配色）",
                            scale=2,
                        )
                    style_scale = gr.Slider(
                        label="字号倍率微调（1.0 = 原字号；选上面的预设时以预设为准）",
                        minimum=0.5,
                        maximum=2.5,
                        value=1.0,
                        step=0.05,
                    )
                    with gr.Row():
                        style_opacity = gr.Slider(
                            label="底框透明度（0=不调整）",
                            minimum=0,
                            maximum=255,
                            value=0,
                            step=5,
                            scale=2,
                        )
                        style_gap = gr.Dropdown(
                            label="元素间距",
                            choices=list(_STYLE_GAP_OPTIONS),
                            value="不调整（保持间距）",
                            scale=1,
                        )
                    with gr.Row():
                        style_date = gr.Dropdown(
                            label="日期格式",
                            choices=list(_STYLE_DATE_OPTIONS),
                            value="不调整（保持格式）",
                            scale=1,
                        )
                        style_time = gr.Dropdown(
                            label="时间格式",
                            choices=list(_STYLE_TIME_OPTIONS),
                            value="不调整（保持格式）",
                            scale=1,
                        )
                    apply_style_button = gr.Button(
                        "保存样式到当前模板",
                        variant="secondary",
                    )
                    style_apply_status = gr.Markdown("", elem_classes="dd-status")
                with gr.Accordion("④ 内容栏1 / 内容栏2：每栏独立位置", open=True):
                    gr.Markdown(
                        "内容栏1、内容栏2 每栏一行，按填写顺序从上到下排列；"
                        "两栏可分别放在不同位置。"
                        "可用占位符：{location} 地点、{date} 日期、{time} 时间、"
                        "{weekday} 星期、{anti_counterfeit} 防伪码。",
                        elem_classes="dd-hint",
                    )
                    with gr.Row():
                        left_column_text = gr.Textbox(
                            label="内容栏1（每行一条）",
                            lines=4,
                            value=initial_left_text,
                            placeholder="校园食堂陪餐\n地点：{location}\n{date} {time}",
                            scale=3,
                        )
                        left_column_position = gr.Dropdown(
                            label="内容栏1位置",
                            choices=list(_COLUMN_POSITION_OPTIONS),
                            value=initial_left_position,
                            scale=1,
                        )
                    with gr.Row():
                        right_column_text = gr.Textbox(
                            label="内容栏2（每行一条）",
                            lines=4,
                            value=initial_right_text,
                            placeholder="陪餐人：张三\n防伪码：{anti_counterfeit}",
                            scale=3,
                        )
                        right_column_position = gr.Dropdown(
                            label="内容栏2位置",
                            choices=list(_COLUMN_POSITION_OPTIONS),
                            value=initial_right_position,
                            scale=1,
                        )
                    with gr.Row():
                        apply_columns_button = gr.Button(
                            "保存内容栏到当前模板", variant="secondary", scale=3
                        )
                        clear_columns_button = gr.Button(
                            "清除内容栏（还原内容）", variant="stop", scale=2
                        )
                    column_apply_status = gr.Markdown("", elem_classes="dd-status")
                watermark_manage_close_button = gr.Button(
                    "关闭并返回",
                    variant="secondary",
                    elem_classes="dd-wm-close",
                )
        with gr.Accordion("最近工具返回（调试/留痕）", open=False):
            last_result = gr.JSON(label="工具返回 JSON", value=None)
    return {
        "page": page_watermark,
        "status": watermark_status,
        "home": watermark_home,
        "new_panel": watermark_new_panel,
        "render_panel": watermark_render_panel,
        "manage_panel": watermark_manage_panel,
        "new_button": watermark_new_button,
        "render_button_entry": watermark_render_button,
        "manage_button_entry": watermark_manage_button,
        "new_close_button": watermark_new_close_button,
        "render_close_button": watermark_render_close_button,
        "manage_close_button": watermark_manage_close_button,
        "sample_image": sample_image,
        "new_template_name": new_template_name,
        "template_requirement": template_requirement,
        "template_position": template_position,
        "template_spacing": template_spacing,
        "template_format": template_format,
        "template_size": template_size,
        "template_color": template_color,
        "template_opacity": template_opacity,
        "create_template_button": create_template_button,
        "template_dropdown": template_dropdown,
        "delete_template_confirm": delete_template_confirm,
        "delete_template_button": delete_template_button,
        "template_manage_status": template_manage_status,
        "template_style_summary": template_style_summary,
        "style_format": style_format,
        "style_position": style_position,
        "style_size": style_size,
        "style_scale": style_scale,
        "style_color": style_color,
        "style_opacity": style_opacity,
        "style_gap": style_gap,
        "style_date": style_date,
        "style_time": style_time,
        "apply_style_button": apply_style_button,
        "style_apply_status": style_apply_status,
        "left_column_text": left_column_text,
        "left_column_position": left_column_position,
        "right_column_text": right_column_text,
        "right_column_position": right_column_position,
        "apply_columns_button": apply_columns_button,
        "clear_columns_button": clear_columns_button,
        "column_apply_status": column_apply_status,
        "scene_image": scene_image,
        "use_location": use_location,
        "use_time": use_time,
        "location": location,
        "manual_time": manual_time,
        "field_column": field_column,
        "field_position": field_position,
        "render_button": render_button,
        "result_image": result_image,
        "output_path": output_path,
        "last_result": last_result,
    }


def wire_watermark_page(c: dict[str, Any], shared: dict[str, Any]) -> None:
    """接线水印模板创建、样式、内容栏、生成与区域显隐。"""

    c["create_template_button"].click(
        create_template_from_upload,
        inputs=[
            c["sample_image"],
            c["new_template_name"],
            c["template_requirement"],
            c["template_position"],
            c["template_spacing"],
            c["template_format"],
            c["template_size"],
            c["template_color"],
            c["template_opacity"],
        ],
        outputs=[c["status"], c["template_dropdown"], c["last_result"]],
        api_name="create_template",
    ).then(
        show_template_style,
        inputs=c["template_dropdown"],
        outputs=c["template_style_summary"],
        api_name=False,
    )
    c["delete_template_button"].click(
        delete_template_from_ui,
        inputs=[c["template_dropdown"], c["delete_template_confirm"]],
        outputs=[c["template_dropdown"], c["template_manage_status"], c["status"]],
        api_name="delete_template",
    ).then(
        show_template_style,
        inputs=c["template_dropdown"],
        outputs=c["template_style_summary"],
        api_name=False,
    )
    c["apply_style_button"].click(
        apply_watermark_style_from_ui,
        inputs=[
            c["template_dropdown"],
            c["style_format"],
            c["style_position"],
            c["style_size"],
            c["style_scale"],
            c["style_color"],
            c["style_opacity"],
            c["style_gap"],
            c["style_date"],
            c["style_time"],
        ],
        outputs=c["style_apply_status"],
        api_name="apply_watermark_style",
    ).then(
        show_template_style,
        inputs=c["template_dropdown"],
        outputs=c["template_style_summary"],
        api_name=False,
    )
    c["template_dropdown"].change(
        load_template_columns,
        inputs=c["template_dropdown"],
        outputs=[
            c["left_column_text"],
            c["left_column_position"],
            c["right_column_text"],
            c["right_column_position"],
        ],
        api_name=False,
    )
    c["apply_columns_button"].click(
        apply_watermark_columns_from_ui,
        inputs=[
            c["template_dropdown"],
            c["left_column_text"],
            c["left_column_position"],
            c["right_column_text"],
            c["right_column_position"],
        ],
        outputs=c["column_apply_status"],
        api_name="apply_watermark_columns",
    ).then(
        show_template_style,
        inputs=c["template_dropdown"],
        outputs=c["template_style_summary"],
        api_name=False,
    )
    c["clear_columns_button"].click(
        clear_watermark_columns_from_ui,
        inputs=c["template_dropdown"],
        outputs=[
            c["column_apply_status"],
            c["left_column_text"],
            c["left_column_position"],
            c["right_column_text"],
            c["right_column_position"],
        ],
        api_name="clear_watermark_columns",
    ).then(
        show_template_style,
        inputs=c["template_dropdown"],
        outputs=c["template_style_summary"],
        api_name=False,
    )
    c["render_button"].click(
        render_watermark_from_upload,
        inputs=[
            c["template_dropdown"],
            c["scene_image"],
            c["location"],
            c["manual_time"],
            c["left_column_text"],
            c["left_column_position"],
            c["right_column_text"],
            c["right_column_position"],
            c["use_location"],
            c["use_time"],
            c["field_column"],
            c["field_position"],
        ],
        outputs=[
            c["result_image"],
            c["output_path"],
            c["status"],
            c["last_result"],
            shared["schedule_table"],
        ],
        api_name="render_watermark",
    ).then(
        refresh_schedule_pick_and_box,
        inputs=shared["schedule_view"],
        outputs=[shared["schedule_pick"], shared["schedule_selection_box"]],
        api_name=False,
    )

    panels = [
        c["home"],
        c["new_panel"],
        c["render_panel"],
        c["manage_panel"],
    ]
    c["new_button"].click(show_watermark_new, inputs=None, outputs=panels, api_name=False)
    c["render_button_entry"].click(
        show_watermark_render, inputs=None, outputs=panels, api_name=False
    )
    c["manage_button_entry"].click(
        show_watermark_manage, inputs=None, outputs=panels, api_name=False
    )
    for close_button in (
        c["new_close_button"],
        c["render_close_button"],
        c["manage_close_button"],
    ):
        close_button.click(
            show_watermark_home, inputs=None, outputs=panels, api_name=False
        )
