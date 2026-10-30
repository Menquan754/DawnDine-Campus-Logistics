"""DawnDine 多页面 Gradio 工作台装配入口。

本文件只负责：
- 创建 Blocks 容器、侧栏与五个工作区页面；
- 注入各页面的组件引用并完成跨页事件接线；
- 提供 launch() 启动 Web 界面。

页面布局见 ui/pages/，回调逻辑见 ui/handlers/，主题与脚本见 ui/theme.py。
"""

from __future__ import annotations

import os
from typing import Any

import gradio as gr

from dawndine.config import (
    APP_DISCLAIMER,
    APP_SUBTITLE,
    APP_TITLE,
    APP_VERSION,
    EXPORTS_DIR,
    UPLOADS_DIR,
    WATERMARKED_DIR,
    get_server_host,
    get_server_port,
    get_server_share,
)
from dawndine.ui.handlers.knowledge import switch_page
from dawndine.ui.handlers.maintenance import refresh_maintenance_page
from dawndine.ui.handlers.schedule import refresh_schedule_pick_and_box, refresh_schedules
from dawndine.ui.handlers.session import init_session
from dawndine.ui.pages.assistant import build_assistant_page, wire_assistant_page
from dawndine.ui.pages.knowledge import build_knowledge_page, wire_knowledge_page
from dawndine.ui.pages.maintenance import build_maintenance_page, wire_maintenance_page
from dawndine.ui.pages.schedule import build_schedule_page, wire_schedule_page
from dawndine.ui.pages.settings import build_settings_page, wire_settings_page
from dawndine.ui.pages.watermark import build_watermark_page, wire_watermark_page
from dawndine.ui.theme import _BOOT_JS, _CSS, _THEME, _THEME_SYNC_JS

_NAV_CHOICES = [
    ("💬  后勤助手", "chat"),
    ("🖼️  图片水印", "watermark"),
    ("🔧  后勤维修", "maintenance"),
    ("📅  我的日程", "schedule"),
    ("📚  知识库", "kg"),
]


def _build_sidebar() -> tuple[Any, Any, Any]:
    """构建左侧导航栏，返回（导航单选、会话标识、thread_id 显示框）。"""

    gr.HTML(
        f"""
        <div class="dd-brand">
          <div class="dd-logo">DD</div>
          <div>
            <div class="dd-brand-name">{APP_TITLE}</div>
            <div class="dd-brand-sub">本地工作台 · {APP_VERSION}</div>
          </div>
        </div>
        """
    )
    nav = gr.Radio(
        choices=_NAV_CHOICES,
        value="chat",
        show_label=False,
        elem_id="dd-nav",
    )
    thread_display = gr.Textbox(
        label="当前会话 thread_id",
        value="等待初始化…",
        interactive=False,
        max_lines=1,
        show_copy_button=True,
        elem_classes="dd-thread",
    )
    gr.HTML(
        """
        <div class="dd-side-note">
          本地/网页运行 · LangGraph · SQLite<br/>
          <strong>不会上传现场照片到训练集</strong>，仅当前服务器处理。<br/>
          刷新页面 = 全新会话，Key 与对话自动清空。
        </div>
        <div class="dd-side-footer">
          输出为建议与草稿<br/>不替代现场判断与责任认定
        </div>
        """
    )
    return nav, thread_display


def build_demo() -> gr.Blocks:
    """构建多页面 Gradio 工作台。"""

    with gr.Blocks(
        theme=_THEME,
        css=_CSS,
        js=_BOOT_JS,
        title=APP_TITLE,
        analytics_enabled=False,
    ) as demo:
        thread_id_state = gr.State("")
        api_key_state = gr.State("")

        with gr.Sidebar(open=True, width=286, position="left", elem_id="dd-sidebar"):
            nav, thread_display = _build_sidebar()

        with gr.Column(elem_id="dd-workspace"):
            with gr.Row(elem_classes="dd-topbar"):
                gr.HTML(
                    f"""
                    <div>
                      <h1 class="dd-title">{APP_TITLE}</h1>
                      <p class="dd-subtitle">{APP_SUBTITLE}</p>
                    </div>
                    """
                )
                gr.HTML('<div class="dd-live">● 本地工作台运行中</div>')

            with gr.Column(elem_classes="dd-mobile-nav"):
                mobile_nav = gr.Radio(
                    choices=_NAV_CHOICES,
                    value="chat",
                    show_label=False,
                )

            assistant = build_assistant_page()
            watermark = build_watermark_page()
            maintenance = build_maintenance_page()
            schedule = build_schedule_page()
            knowledge = build_knowledge_page()

            gr.HTML(
                f'<div class="dd-footer"><strong>{APP_DISCLAIMER}</strong><br/>'
                f"{APP_TITLE} · {APP_VERSION} · 本地运行，数据保存在本机 · "
                "输出为建议与草稿，正式记录须由责任人核对签字。</div>"
            )

        settings = build_settings_page()

        shared: dict[str, Any] = {
            "thread_id_state": thread_id_state,
            "api_key_state": api_key_state,
            "api_key_box": settings["api_key_box"],
            "thread_display": thread_display,
            "chatbot": assistant["chatbot"],
            "schedule_table": schedule["table"],
            "schedule_view": schedule["view"],
            "schedule_pick": schedule["pick"],
            "schedule_selection_box": schedule["selection_box"],
            "maintenance_table": maintenance["table"],
            "maintenance_stats": maintenance["stats"],
            "template_dropdown": watermark["template_dropdown"],
        }

        wire_assistant_page(assistant, shared)
        wire_watermark_page(watermark, shared)
        wire_maintenance_page(maintenance, shared)
        wire_schedule_page(schedule, shared)
        wire_knowledge_page(knowledge)
        wire_settings_page(settings, shared)

        # 会话初始化：新 thread_id、清空 Key 与对话，并刷新日程/维修列表。
        demo.load(
            init_session,
            inputs=None,
            outputs=[
                thread_id_state,
                thread_display,
                settings["key_status"],
                schedule["table"],
                watermark["template_dropdown"],
                api_key_state,
                settings["api_key_box"],
                assistant["chatbot"],
            ],
            api_name="init_session",
        ).then(
            refresh_schedule_pick_and_box,
            inputs=schedule["view"],
            outputs=[schedule["pick"], schedule["selection_box"]],
            api_name=False,
        ).then(
            refresh_maintenance_page,
            inputs=None,
            outputs=[
                maintenance["table"],
                maintenance["stats"],
                maintenance["overview"],
                maintenance["pick"],
                maintenance["selection_box"],
            ],
            api_name=False,
        )

        page_outputs = [
            assistant["page"],
            watermark["page"],
            maintenance["page"],
            schedule["page"],
            knowledge["page"],
        ]
        nav.change(switch_page, inputs=nav, outputs=page_outputs, api_name="switch_page")
        nav.change(
            refresh_schedules,
            inputs=schedule["view"],
            outputs=schedule["table"],
            api_name=False,
        )
        nav.change(
            refresh_schedule_pick_and_box,
            inputs=schedule["view"],
            outputs=[schedule["pick"], schedule["selection_box"]],
            api_name=False,
        )
        nav.change(
            refresh_maintenance_page,
            inputs=None,
            outputs=[
                maintenance["table"],
                maintenance["stats"],
                maintenance["overview"],
                maintenance["pick"],
                maintenance["selection_box"],
            ],
            api_name=False,
        )
        mobile_nav.change(switch_page, inputs=mobile_nav, outputs=page_outputs, api_name=False)
        mobile_nav.change(
            refresh_schedules,
            inputs=schedule["view"],
            outputs=schedule["table"],
            api_name=False,
        )
        mobile_nav.change(
            refresh_schedule_pick_and_box,
            inputs=schedule["view"],
            outputs=[schedule["pick"], schedule["selection_box"]],
            api_name=False,
        )
        mobile_nav.change(
            refresh_maintenance_page,
            inputs=None,
            outputs=[
                maintenance["table"],
                maintenance["stats"],
                maintenance["overview"],
                maintenance["pick"],
                maintenance["selection_box"],
            ],
            api_name=False,
        )

        # 纯前端事件：按当前浏览器记住的主题回显单选按钮。
        demo.load(
            None,
            inputs=None,
            outputs=settings["theme_radio"],
            js=_THEME_SYNC_JS,
            api_name=False,
        )

    return demo


def launch(
    inbrowser: bool | None = None,
    share: bool | None = None,
    server_name: str | None = None,
    server_port: int | None = None,
) -> None:
    """启动 Web 界面。

    默认仅本机 127.0.0.1:7860；可用 `--host 0.0.0.0` 开放局域网，
    或用 `--share` 生成临时公网链接。每个浏览器会话仍是全新状态。
    """

    should_open = (
        inbrowser if inbrowser is not None else os.getenv("DAWNDINE_NO_BROWSER", "0") != "1"
    )
    should_share = share if share is not None else get_server_share()
    host = (server_name or get_server_host()).strip() or "127.0.0.1"
    port = server_port or get_server_port()
    build_demo().queue(default_concurrency_limit=4, max_size=32).launch(
        server_name=host,
        server_port=port,
        share=should_share,
        inbrowser=should_open,
        allowed_paths=[str(UPLOADS_DIR), str(WATERMARKED_DIR), str(EXPORTS_DIR)],
        show_api=False,
        show_error=False,
        max_file_size="20mb",
    )
