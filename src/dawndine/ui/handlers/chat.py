"""页A：后勤助手聊天回调。"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime
from typing import Any

import gradio as gr
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from dawndine.agent.graph import graph, reset_conversation, runtime_config
from dawndine.config import MISSING_API_KEY_MESSAGE
from dawndine.llm import resolve_api_key
from dawndine.services.smalltalk import small_talk_reply
from dawndine.ui.handlers.common import (
    _CHAT_BUSY_MESSAGE,
    _CHAT_LOCK,
    _CHAT_LOCK_TIMEOUT,
    _message_text,
    _normalize_history,
    _parse_tool_payload,
    _short_error,
)
from dawndine.ui.handlers.schedule import _schedule_rows

logger = logging.getLogger(__name__)

_WATERMARK_INTENT_WORDS = ("水印", "打卡图", "打卡照", "陪餐图")
_QUICK_PROMPTS: dict[str, str] = {
    "合规判断": (
        "请做合规判断（涉及温度、重量、时间等数值时必须调用合规知识库工具）。\n"
        "监管环节（验收/晨检/留样/切配/陪餐等）：\n"
        "检查对象：\n"
        "现场现象：\n"
        "关键数值（温度/重量/时长等）：\n"
        "地区或学校：\n"
        "需要判断的问题："
    ),
    "异常上报": (
        "请按异常闭环处理（请调用异常闭环工具）。\n"
        "异常类型（温度超标/票证不全/留样不足/设备不可用等）：\n"
        "发现时间：\n"
        "发现人/岗位：\n"
        "异常对象：\n"
        "异常现象与现场事实：\n"
        "已做的临时处置："
    ),
    "生成台账": (
        "请生成台账（请调用台账工具）。\n"
        "台账类型（日管控/周排查/月调度/晨检/留样/验菜/陪餐/双人双锁/采购/消毒）：\n"
        "日期时间（YYYY-MM-DD HH:MM）：\n"
        "相关人员（多人用逗号分隔）：\n"
        "过程与结果（动作、数量、结论）：\n"
        "异常及处置：\n"
        "双人执行/双人双锁情况：\n"
        "记录方式（realtime 实时 / backfill 补录）："
    ),
    "知识查询": (
        "请检索食品安全知识库并回答（请调用知识检索工具）。\n"
        "具体问题（如餐具消毒时长、后厨卫生标准、采购库存怎么管）：\n"
        "领域（食材与食品安全/台账与系统操作/后厨与环境卫生/采购库存与成本/"
        "陪餐与师生反馈/制度整改与应急/日常咨询）：\n"
        "现场补充信息（可选）："
    ),
    "每日清单": (
        "请生成今天的每日清单（{today}，请调用每日清单工具）。\n"
        "日期：\n"
        "已完成事项：\n"
        "未完成事项：\n"
        "已发现异常：\n"
        "刀具菜板使用情况：\n"
        "设备状态（如留样柜不可用）："
    ),
    "检查应对": (
        "请给检查应对指引（请调用检查应对工具）。\n"
        "检查场景（市场监管局/学校自查/家长开放日等）：\n"
        "检查人员提出的问题：\n"
        "涉及领域（双人双锁/留样/晨检/验菜/陪餐等）：\n"
        "是否涉及补录（是/否，涉及请说明原因）："
    ),
    "日程复盘": (
        "请分析我的日程（请调用日程分析工具）。\n"
        "关注范围（全部/本周/指定日期）：\n"
        "重点回答（时间冲突/待补时间/日期已过/优先级建议）：\n"
        "补充说明（可选）："
    ),
}

def _wants_watermark(message: str) -> bool:
    """聊天页不接收图片；识别水印意图后引导到图片水印页。"""

    return any(word in (message or "") for word in _WATERMARK_INTENT_WORDS)


def _chat_error(history: list[dict[str, str]], text: str) -> tuple[Any, ...]:
    """构造聊天错误返回。"""

    history.append({"role": "assistant", "content": text})
    return history, "", "⚠️ 执行失败", gr.skip()


def _make_quick_fill(label: str, prompt: str) -> Callable[[str], tuple[str, str]]:
    """生成“填入快捷模板”事件处理器。

    只填充输入框，不自动发送：用户可先补全地点、数值等信息，
    再按发送键调用 Agent，避免模板不完整时误触发或把输入框清空。
    """

    def handler(current: str) -> tuple[str, str]:
        resolved_prompt = prompt.replace("{today}", f"{datetime.now():%Y-%m-%d}")
        text = (current or "").strip()
        if not text:
            filled = resolved_prompt
        elif resolved_prompt.strip() in text:
            filled = text
        else:
            filled = f"{text}\n\n{resolved_prompt}"
        return filled, f"📝 已填入「{label}」模板，请补充信息后点击发送。"

    return handler


def chat(
    message: str,
    history: Sequence[Any] | None,
    thread_id: str,
    ui_api_key: str,
    typed_api_key: str = "",
) -> Iterator[tuple[Any, ...]]:
    """聊天事件：按会话 thread_id 与 Key 调用 LangGraph。

    `typed_api_key` 来自设置页密码框：用户填了 Key 但还没点“保存 Key”时，
    直接点发送也能正常调用，不会误报缺少 Key。
    """

    chat_history = _normalize_history(history)
    user_text = (message or "").strip()
    if not user_text:
        yield chat_history, "", "请输入问题后再发送。", gr.skip()
        return

    chat_history.append({"role": "user", "content": user_text})
    yield chat_history, "", "⏳ 正在分析现场信息…", gr.skip()

    # 纯寒暄/自我介绍不进入大模型：即使没有 Key 也能自然回应。
    quick_reply = small_talk_reply(user_text)
    if quick_reply:
        chat_history.append({"role": "assistant", "content": quick_reply})
        yield chat_history, "", "✅ 已回复", gr.skip()
        return

    if _wants_watermark(user_text):
        chat_history.append(
            {
                "role": "assistant",
                "content": (
                    "请点击左侧 **🖼️ 图片水印** 页面，上传样图和现场照片后生成图片。"
                    "聊天页不接收图片，避免把临时路径误写入台账。"
                ),
            }
        )
        yield chat_history, "", "🖼️ 已提示前往图片水印页", gr.skip()
        return

    candidate_key = (ui_api_key or "").strip() or (typed_api_key or "").strip()
    active_key = resolve_api_key(candidate_key)
    if not active_key:
        chat_history.append(
            {
                "role": "assistant",
                "content": (
                    "⚠️ 当前没有可用的 DashScope API Key，无法进行真实对话。\n\n"
                    "请在页脚 **设置** 中填写本次会话 Key，"
                    "或在 `.env` 中配置 `DASHSCOPE_API_KEY` 后重启。"
                ),
            }
        )
        yield chat_history, "", "⚠️ 未配置 API Key", gr.skip()
        return

    if not thread_id:
        thread_id = uuid.uuid4().hex

    current_status = "⏳ 正在调用 Qwen…"
    assistant_text = ""
    last_tool: dict[str, Any] | None = None
    # 限时抢占：上一轮卡住时不再无限等待，直接提示稍后重试，避免整页失去响应。
    if not _CHAT_LOCK.acquire(timeout=_CHAT_LOCK_TIMEOUT):
        chat_history.append({"role": "assistant", "content": f"⚠️ {_CHAT_BUSY_MESSAGE}"})
        yield chat_history, "", "⏳ 上一条消息仍在处理", gr.skip()
        return
    try:
        for chunk in graph.stream(
            {"messages": [HumanMessage(content=user_text)]},
            config=runtime_config(thread_id=thread_id, api_key=active_key),
            stream_mode="updates",
        ):
            if not isinstance(chunk, dict):
                continue
            for node_name, payload in chunk.items():
                if node_name == "agent" and isinstance(payload, dict):
                    for item in payload.get("messages", []):
                        if not isinstance(item, AIMessage):
                            continue
                        tool_calls = getattr(item, "tool_calls", None) or []
                        if tool_calls:
                            names = "、".join(str(call.get("name")) for call in tool_calls)
                            current_status = f"🛠️ 正在调用工具：{names}"
                            yield chat_history, "", current_status, gr.skip()
                            continue
                        text = _message_text(item).strip()
                        if text:
                            assistant_text = text
                            chat_history.append({"role": "assistant", "content": text})
                            current_status = "✅ 回答已生成"
                            yield chat_history, "", current_status, _schedule_rows()
                elif node_name == "tools" and isinstance(payload, dict):
                    for item in payload.get("messages", []):
                        if not isinstance(item, ToolMessage):
                            continue
                        last_tool = _parse_tool_payload(item)
                        tool_name = item.name or "工具"
                        if last_tool is not None:
                            ok = bool(last_tool.get("ok"))
                            err = str(last_tool.get("error", "未知错误"))
                            current_status = (
                                f"✅ 工具 {tool_name} 执行完成"
                                if ok
                                else f"⚠️ 工具 {tool_name} 执行失败：{err}"
                            )
                        else:
                            current_status = f"✅ 工具 {tool_name} 已返回"
                        yield chat_history, "", current_status, _schedule_rows()

        if not assistant_text:
            assistant_text = (
                "工具已执行，但模型未返回文字结论。请到“我的日程”查看是否已产生记录，"
                "或补充信息后重试。"
            )
            chat_history.append({"role": "assistant", "content": assistant_text})
        if last_tool and last_tool.get("schedule_id"):
            current_status = "✅ 本轮完成，已写入我的日程"
        else:
            current_status = "✅ 本轮完成"
        yield chat_history, "", current_status, _schedule_rows()
    except Exception as exc:  # noqa: BLE001 - UI 层统一兜底
        logger.exception("LangGraph 对话执行失败")
        detail = str(exc)
        if "401" in detail or "api key" in detail.lower() or "authentication" in detail.lower():
            friendly = MISSING_API_KEY_MESSAGE
        else:
            friendly = f"本轮执行失败：{_short_error(exc)}。请检查网络、Key 或稍后重试。"
        yield _chat_error(chat_history, f"⚠️ {friendly}")
    finally:
        _CHAT_LOCK.release()


def clear_chat(thread_id: str) -> tuple[Any, ...]:
    """清空当前会话聊天记录与 LangGraph 内存。"""

    if thread_id:
        try:
            reset_conversation(thread_id)
        except Exception:  # noqa: BLE001 - 内存清理失败也不阻塞 UI 清空
            logger.exception("清空会话内存失败：%s", thread_id)
    return [], "", "🧹 当前会话对话已清空，可开始新的检查。", gr.skip()
