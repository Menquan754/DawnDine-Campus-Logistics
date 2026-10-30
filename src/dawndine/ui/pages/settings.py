"""系统设置弹窗与事件接线。"""

from __future__ import annotations

from typing import Any

import gradio as gr

from dawndine.config import APP_BUILD_NOTE, APP_DISCLAIMER, APP_VERSION
from dawndine.llm import get_vision_model_name
from dawndine.ui.handlers.common import _key_status
from dawndine.ui.handlers.maintenance import logistics_overview_md
from dawndine.ui.handlers.schedule import refresh_schedule_pick_and_box
from dawndine.ui.handlers.session import (
    clear_api_key,
    initialize_agent,
    probe_vision,
    rebuild_knowledge_index,
    save_api_key,
)
from dawndine.ui.theme import _CLOSE_SETTINGS_JS, _THEME_CHANGE_JS


def build_settings_page() -> dict[str, Any]:
    """构建设置弹窗布局，返回组件引用。"""

    initial_key_status = _key_status("")

    with gr.Column(elem_id="dd-settings-modal", elem_classes="dd-modal"):
        with gr.Column(elem_classes="dd-modal-panel"):
            with gr.Row(elem_classes="dd-modal-head"):
                gr.Markdown("### ⚙ 系统设置")
                close_settings_button = gr.Button(
                    "✕",
                    size="sm",
                    variant="secondary",
                    scale=0,
                    elem_classes="dd-modal-close",
                )
            with gr.Group(elem_classes="dd-settings-block"):
                gr.Markdown(
                    "#### 🔑 DashScope API Key（仅当前会话）", elem_classes="dd-settings-title"
                )
                with gr.Row(elem_classes="dd-key-row"):
                    api_key_box = gr.Textbox(
                        label="DashScope API Key（仅当前会话）",
                        type="password",
                        placeholder="留空则使用 .env 中的 DASHSCOPE_API_KEY",
                        scale=4,
                    )
                    save_key_button = gr.Button("保存 Key", variant="primary", scale=1)
                    clear_key_button = gr.Button("清除", variant="secondary", scale=1)
                key_status_md = gr.Markdown(initial_key_status, elem_classes="dd-key-status")
                gr.HTML(
                    '<div class="dd-hint">每个网页会话有独立 thread_id；'
                    "Key 不写入 SQLite、不写入前端日志。刷新或重新打开页面即全新会话，"
                    "会话 Key、聊天记录自动清空。</div>"
                )

            with gr.Group(elem_classes="dd-settings-block"):
                gr.Markdown("#### 🧠 模型与知识库", elem_classes="dd-settings-title")
                with gr.Row(elem_classes="dd-settings-actions"):
                    probe_vision_button = gr.Button(
                        "检测视觉模型",
                        size="sm",
                        variant="secondary",
                        scale=0,
                    )
                    rebuild_kb_button = gr.Button(
                        "重建知识库索引",
                        size="sm",
                        variant="secondary",
                        scale=0,
                    )
                vision_probe_status = gr.Markdown(
                    f"视觉模型：`{get_vision_model_name()}`"
                    "（可通过 .env 的 `DASHSCOPE_VL_MODEL` 覆盖）",
                    elem_classes="dd-key-status",
                )
                kb_rebuild_status = gr.Markdown(
                    "知识文件变更后会自动重建索引，也可手动重建。",
                    elem_classes="dd-key-status",
                )

            with gr.Group(elem_classes="dd-settings-block"):
                gr.Markdown("#### 🗄️ 数据库", elem_classes="dd-settings-title")
                with gr.Row(elem_classes="dd-settings-actions"):
                    refresh_db_button = gr.Button(
                        "刷新数据概览",
                        size="sm",
                        variant="secondary",
                        scale=0,
                    )
                db_overview_md = gr.Markdown(
                    logistics_overview_md(),
                    elem_classes="dd-key-status",
                )

            with gr.Group(elem_classes="dd-settings-block"):
                gr.Markdown("#### 🧹 Agent 初始化", elem_classes="dd-settings-title")
                gr.Markdown(
                    "一键恢复到首次安装状态：清空日程、维修、资产、库存、巡检、供应商、人员、"
                    "反馈、工具留痕、水印模板与全部对话会话，并删除 uploads / exports / "
                    "watermarked 下的生成文件。知识库文件（data/knowledge）不受影响。",
                    elem_classes="dd-key-status",
                )
                with gr.Row(elem_classes="dd-settings-actions"):
                    reset_confirm = gr.Checkbox(
                        label="我确认清空以上全部数据（不可恢复）",
                        scale=3,
                    )
                    initialize_button = gr.Button(
                        "初始化 Agent",
                        size="sm",
                        variant="stop",
                        scale=0,
                    )
                initialize_status = gr.Markdown("", elem_classes="dd-key-status")

            with gr.Group(elem_classes="dd-settings-block"):
                gr.Markdown("#### 🎨 外观主题", elem_classes="dd-settings-title")
                with gr.Row(elem_classes="dd-theme-row"):
                    theme_radio = gr.Radio(
                        choices=["浅色", "深色", "跟随系统"],
                        value="浅色",
                        label="显示主题",
                        scale=1,
                    )
                gr.Markdown(
                    "切换后立即生效，并记住在当前浏览器；不会再被强制锁定为浅色。",
                    elem_classes="dd-key-status",
                )

            with gr.Group(elem_classes="dd-settings-block"):
                gr.Markdown("#### ℹ️ 关于本版本", elem_classes="dd-settings-title")
                gr.HTML(
                    f'<div class="dd-build-note">版本 {APP_VERSION} · '
                    f"本次更新：{APP_BUILD_NOTE}。"
                    "若页面没有这些功能，说明仍是旧进程，请关闭窗口后重新双击启动脚本。</div>"
                    f'<div class="dd-hint">{APP_DISCLAIMER}</div>'
                )
    return {
        "modal": None,
        "api_key_box": api_key_box,
        "save_key_button": save_key_button,
        "clear_key_button": clear_key_button,
        "key_status": key_status_md,
        "probe_vision_button": probe_vision_button,
        "rebuild_kb_button": rebuild_kb_button,
        "vision_probe_status": vision_probe_status,
        "kb_rebuild_status": kb_rebuild_status,
        "refresh_db_button": refresh_db_button,
        "db_overview_md": db_overview_md,
        "reset_confirm": reset_confirm,
        "initialize_button": initialize_button,
        "initialize_status": initialize_status,
        "theme_radio": theme_radio,
        "close_settings_button": close_settings_button,
    }


def wire_settings_page(c: dict[str, Any], shared: dict[str, Any]) -> None:
    """接线 Key 管理、模型检测、数据库概览、初始化与主题。"""

    c["save_key_button"].click(
        save_api_key,
        inputs=c["api_key_box"],
        outputs=[shared["api_key_state"], c["key_status"], c["api_key_box"]],
        api_name="save_api_key",
    )
    c["clear_key_button"].click(
        clear_api_key,
        inputs=None,
        outputs=[shared["api_key_state"], c["key_status"], c["api_key_box"]],
        api_name="clear_api_key",
    )
    c["probe_vision_button"].click(
        probe_vision,
        inputs=shared["api_key_state"],
        outputs=c["vision_probe_status"],
        api_name="probe_vision_model",
    )
    c["rebuild_kb_button"].click(
        rebuild_knowledge_index,
        inputs=shared["api_key_state"],
        outputs=c["kb_rebuild_status"],
        api_name=False,
    )
    c["theme_radio"].change(
        None,
        inputs=c["theme_radio"],
        js=_THEME_CHANGE_JS,
        api_name=False,
    )
    c["close_settings_button"].click(
        None,
        inputs=None,
        outputs=None,
        js=_CLOSE_SETTINGS_JS,
        api_name=False,
    )
    c["refresh_db_button"].click(
        logistics_overview_md,
        inputs=None,
        outputs=c["db_overview_md"],
        api_name=False,
    )
    c["initialize_button"].click(
        initialize_agent,
        inputs=c["reset_confirm"],
        outputs=[
            c["initialize_status"],
            shared["thread_id_state"],
            shared["chatbot"],
            shared["thread_display"],
            shared["schedule_table"],
            shared["maintenance_table"],
            shared["maintenance_stats"],
            shared["template_dropdown"],
            c["reset_confirm"],
        ],
        api_name=False,
    ).then(
        refresh_schedule_pick_and_box,
        inputs=shared["schedule_view"],
        outputs=[shared["schedule_pick"], shared["schedule_selection_box"]],
        api_name=False,
    )
