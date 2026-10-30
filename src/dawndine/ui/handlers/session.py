"""会话初始化、系统设置与 Agent 重置回调。"""

from __future__ import annotations

import logging
import shutil
import uuid
from collections.abc import Callable
from typing import Any

import gradio as gr

from dawndine.agent.graph import clear_all_conversations
from dawndine.agent.tools.watermark import reset_templates
from dawndine.config import (
    EXPORTS_DIR,
    MISSING_API_KEY_MESSAGE,
    UPLOADS_DIR,
    WATERMARKED_DIR,
)
from dawndine.db import init_db, reset_all_data
from dawndine.knowledge.rag import rebuild_index
from dawndine.llm import resolve_api_key
from dawndine.services.smalltalk import WELCOME_REPLY
from dawndine.services.vision import probe_vision_model
from dawndine.ui.handlers.common import _key_status, _short_error, _template_update
from dawndine.ui.handlers.maintenance import _maintenance_rows, _maintenance_stats_rows
from dawndine.ui.handlers.schedule import _schedule_rows

logger = logging.getLogger(__name__)

_CHAT_WELCOME: list[dict[str, str]] = [{"role": "assistant", "content": WELCOME_REPLY}]

def _thread_display(thread_id: str) -> str:
    """thread_id 只展示首尾，避免侧栏被长字符串撑破。"""

    if not thread_id:
        return "等待初始化…"
    return f"{thread_id[:8]}…{thread_id[-4:]}"


def init_session() -> tuple[str, str, str, list[list[Any]], Any, str, str, list[dict[str, str]]]:
    """为每个浏览器会话初始化全新状态。

    每次页面加载都会生成新的 thread_id，并显式清空会话 Key、输入框和对话，
    确保不会看到上一位使用者留下的 Key 或聊天内容。
    """

    try:
        init_db()
    except Exception:  # noqa: BLE001 - 数据库初始化失败时仍允许打开页面
        logger.exception("初始化数据库失败")
    session_id = uuid.uuid4().hex
    return (
        session_id,
        _thread_display(session_id),
        _key_status(""),
        _schedule_rows(),
        _template_update(),
        "",
        "",
        list(_CHAT_WELCOME),
    )


def _clear_generated_files() -> int:
    """删除 uploads / exports / watermarked 下由本应用生成的图片与报表。"""

    removed = 0
    for directory in (UPLOADS_DIR, EXPORTS_DIR, WATERMARKED_DIR):
        if not directory.exists():
            continue
        for item in directory.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
                removed += 1
            except OSError:
                logger.warning("初始化时删除文件失败：%s", item)
    return removed


def initialize_agent(confirm: bool) -> tuple[Any, ...]:
    """一键初始化：清空业务数据、水印模板、生成文件与全部对话线程。"""

    if not confirm:
        return (
            "⚠️ 请先勾选“我确认清空全部数据”，再点击“初始化 Agent”。",
            *[gr.skip() for _ in range(8)],
        )

    # 四步清理互不阻塞：某一步失败时其余步骤继续，最后统一汇报。
    failures: list[str] = []
    counts: dict[str, int] = {}
    templates = conversations = files = 0
    steps: list[tuple[str, Callable[[], Any]]] = [
        ("业务数据", reset_all_data),
        ("水印模板", reset_templates),
        ("对话线程", clear_all_conversations),
        ("生成文件", _clear_generated_files),
    ]
    for step_name, step in steps:
        try:
            result = step()
        except Exception as exc:  # noqa: BLE001 - 单步失败不影响其余清理
            logger.exception("Agent 初始化失败：%s", step_name)
            failures.append(f"{step_name}（{_short_error(exc)}）")
            continue
        if step_name == "业务数据":
            counts = result if isinstance(result, dict) else {}
        elif step_name == "水印模板":
            templates = int(result or 0)
        elif step_name == "对话线程":
            conversations = int(result or 0)
        else:
            files = int(result or 0)

    thread_id = uuid.uuid4().hex
    total = sum(counts.values())
    summary = (
        f"清空业务数据 **{total}** 条"
        f"（维修 {counts.get('maintenance', 0)}、资产 {counts.get('assets', 0)}、"
        f"库存 {counts.get('inventory', 0)}、巡检 {counts.get('inspections', 0)}、"
        f"供应商 {counts.get('suppliers', 0)}、人员 {counts.get('staff', 0)}、"
        f"反馈 {counts.get('feedback', 0)}、日程 {counts.get('schedules', 0)}、"
        f"工具留痕 {counts.get('records', 0)}），"
        f"水印模板 **{templates}** 个、对话 **{conversations}** 个、生成文件 **{files}** 个；"
        "知识库文件未删除。"
    )
    if failures:
        status = f"⚠️ 初始化部分完成：{summary} 失败步骤：{'、'.join(failures)}。请重试。"
    else:
        status = f"✅ 已完成 Agent 初始化：{summary} 已重置当前会话。"
    return (
        status,
        thread_id,
        list(_CHAT_WELCOME),
        _thread_display(thread_id),
        _schedule_rows(),
        _maintenance_rows(),
        _maintenance_stats_rows(),
        _template_update(),
        gr.update(value=False),
    )


def save_api_key(value: str) -> tuple[str, str, str]:
    """保存本次会话 Key 到 gr.State，并清空密码输入框。"""

    clean = (value or "").strip()
    if clean and len(clean) < 10:
        return "", "⚠️ Key 长度异常，请检查后重试。", ""
    return clean, _key_status(clean), ""


def clear_api_key() -> tuple[str, str, str]:
    """清除本次会话 Key，回退到 .env。"""

    return "", _key_status(""), ""


def probe_vision(ui_api_key: str) -> str:
    """用一张 96×96 测试图检查当前视觉模型是否可用。"""

    result = probe_vision_model(resolve_api_key(ui_api_key))
    if result.get("ok"):
        return (
            f"✅ 视觉模型 `{result.get('model')}` 可用。\n\n"
            f"模型回复：{result.get('reply') or '（空）'}"
        )
    return f"⚠️ {result.get('error', '视觉模型检测失败')}"


def rebuild_knowledge_index(ui_api_key: str) -> str:
    """用当前会话 Key 重建本地 Chroma 知识库索引。"""

    api_key = resolve_api_key(ui_api_key)
    if not api_key:
        return MISSING_API_KEY_MESSAGE
    try:
        count = rebuild_index(api_key=api_key)
        return f"✅ 索引重建完成：{count} 个片段"
    except Exception as exc:  # noqa: BLE001 - 设置区不能因重建失败整体崩溃
        logger.exception("重建知识库索引失败")
        return "⚠️ 重建失败：" + _short_error(exc)
