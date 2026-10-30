"""页A：后勤助手界面与事件接线。"""

from __future__ import annotations

from typing import Any

import gradio as gr

from dawndine.services.smalltalk import WELCOME_REPLY
from dawndine.ui.handlers.chat import _QUICK_PROMPTS, _make_quick_fill, chat, clear_chat
from dawndine.ui.handlers.schedule import refresh_schedule_pick_and_box


def build_assistant_page() -> dict[str, Any]:
    """构建聊天页布局，返回组件引用。"""

    with gr.Column(visible=True, elem_classes="dd-page") as page_chat:
        gr.Markdown("### 💬 后勤助手", elem_classes="dd-card-title")
        gr.Markdown(
            "覆盖食堂食安 + 后勤全域：维修报修、水电设施、宿舍、保洁环卫、绿化、"
            "资产、采购库存、安全消防、节能、车辆、消杀、反馈与场馆保障。"
            "可做合规判断、异常闭环、台账草稿、每日清单、检查应对、数据查询，也能记录日程。",
            elem_classes="dd-hint",
        )
        chat_status = gr.Markdown(
            "准备就绪。填写 Key 后可直接提问，或点击下方快捷工具填入模板。",
            elem_classes="dd-status",
        )
        chatbot = gr.Chatbot(
            value=[{"role": "assistant", "content": WELCOME_REPLY}],
            type="messages",
            height=330,
            layout="bubble",
            bubble_full_width=False,
            show_copy_button=True,
            show_copy_all_button=True,
            placeholder="描述现场情况、要求生成台账，或让助手记录日程。",
            elem_id="dd-chatbot",
            label="校园后勤助手对话",
        )
        with gr.Row():
            message_box = gr.Textbox(
                placeholder="例如：验收冷鲜猪肉，配送单写0—4℃，我实测6℃",
                show_label=False,
                container=False,
                scale=8,
                lines=3,
                max_lines=8,
                elem_id="dd-message",
            )
            send_button = gr.Button("发送", variant="primary", scale=1, elem_id="dd-send")
        with gr.Row(elem_classes="dd-quick-row"):
            quick_buttons = {
                label: gr.Button(f"＋ {label}", size="sm", variant="secondary")
                for label in _QUICK_PROMPTS
            }
        gr.Markdown(
            "快捷工具只把模板填入输入框，不会自动发送；补充地点、数值后点“发送”。",
            elem_classes="dd-hint",
        )
        clear_chat_button = gr.Button(
            "清空本会话对话 / 重置记忆",
            size="sm",
            variant="secondary",
        )
    return {
        "page": page_chat,
        "status": chat_status,
        "chatbot": chatbot,
        "message_box": message_box,
        "send_button": send_button,
        "quick_buttons": quick_buttons,
        "clear_chat_button": clear_chat_button,
    }


def wire_assistant_page(c: dict[str, Any], shared: dict[str, Any]) -> None:
    """接线聊天提交、快捷模板与清空对话。"""

    chat_inputs = [
        c["message_box"],
        c["chatbot"],
        shared["thread_id_state"],
        shared["api_key_state"],
        shared["api_key_box"],
    ]
    chat_outputs = [c["chatbot"], c["message_box"], c["status"], shared["schedule_table"]]
    c["message_box"].submit(
        chat,
        inputs=chat_inputs,
        outputs=chat_outputs,
        api_name="chat",
        show_progress="hidden",
    ).then(
        refresh_schedule_pick_and_box,
        inputs=shared["schedule_view"],
        outputs=[shared["schedule_pick"], shared["schedule_selection_box"]],
        api_name=False,
    )
    c["send_button"].click(
        chat,
        inputs=chat_inputs,
        outputs=chat_outputs,
        api_name=False,
        show_progress="hidden",
    ).then(
        refresh_schedule_pick_and_box,
        inputs=shared["schedule_view"],
        outputs=[shared["schedule_pick"], shared["schedule_selection_box"]],
        api_name=False,
    )
    c["clear_chat_button"].click(
        clear_chat,
        inputs=[shared["thread_id_state"]],
        outputs=[c["chatbot"], c["message_box"], c["status"], shared["schedule_table"]],
        api_name="clear_chat",
    ).then(
        refresh_schedule_pick_and_box,
        inputs=shared["schedule_view"],
        outputs=[shared["schedule_pick"], shared["schedule_selection_box"]],
        api_name=False,
    )
    for label, button in c["quick_buttons"].items():
        prompt = _QUICK_PROMPTS[label]
        button.click(
            _make_quick_fill(label, prompt),
            inputs=[c["message_box"]],
            outputs=[c["message_box"], c["status"]],
            api_name=False,
        )
