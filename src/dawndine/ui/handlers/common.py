"""UI 回调共用的小工具：消息解析、Key 状态、上传落盘与编号归一化。"""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import uuid
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import gradio as gr
from langchain_core.messages import ToolMessage

from dawndine.config import UPLOADS_DIR
from dawndine.llm import allow_env_key, api_key_configured, key_source
from dawndine.services.watermark_store import list_templates

logger = logging.getLogger(__name__)

_CHAT_LOCK = threading.Lock()
# 单次对话最多占用锁 4 分钟：超时不再无限等待，避免一次卡死拖住整个页面。
_CHAT_LOCK_TIMEOUT = 240
_CHAT_BUSY_MESSAGE = "⏳ 上一条消息仍在处理，请稍候再试（或刷新页面重开当前会话）。"

def _message_text(message: Any) -> str:
    """从消息中提取文本。"""

    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(content or "")


def _short_error(exc: Exception) -> str:
    """异常压缩为一行，避免 Pydantic 长文本占屏。"""

    details = str(exc).strip().splitlines()
    return (details[0] if details else "未知错误")[:280]


def _normalize_history(history: Sequence[Any] | None) -> list[dict[str, str]]:
    """统一 Gradio 聊天历史结构。"""

    normalized: list[dict[str, str]] = []
    for item in history or []:
        if isinstance(item, dict):
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and content is not None:
                normalized.append({"role": role, "content": _message_text(content)})
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            user_text, assistant_text = item
            if user_text:
                normalized.append({"role": "user", "content": str(user_text)})
            if assistant_text:
                normalized.append({"role": "assistant", "content": str(assistant_text)})
    return normalized


def _parse_tool_payload(message: ToolMessage) -> dict[str, Any] | None:
    """解析工具返回 JSON。"""

    artifact = getattr(message, "artifact", None)
    if isinstance(artifact, dict) and "ok" in artifact:
        return artifact
    raw = message.content
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        raw = _message_text(raw)
    if not isinstance(raw, str):
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


def _key_status(ui_key: str = "") -> str:
    """生成 Key 状态文案，不展示 Key。"""

    source = key_source(ui_key)
    if source == "ui":
        return "✅ 本会话已设置 Key（仅保存在当前浏览器会话状态，不写入日志/数据库）。"
    if source == "env":
        return "✅ 未填写界面 Key，当前使用 `.env` 中的 DASHSCOPE_API_KEY。"
    if not allow_env_key():
        return (
            "🔒 公共会话模式：不会读取服务器 `.env` 中的共享 Key。"
            "请每位使用者填写自己的 DashScope Key；刷新页面即自动清空。"
        )
    return (
        "⚠️ 未配置 Key。请在下方填写本次会话 Key，或把 `.env.example` 复制为 "
        "`.env` 并填入 DASHSCOPE_API_KEY。"
    )


def _key_configured(ui_key: str = "") -> bool:
    """判断当前会话或 .env 是否有 Key。"""

    return api_key_configured(ui_key)


def _template_choices() -> list[str]:
    """安全读取模板列表。"""

    try:
        return list_templates()
    except Exception:  # noqa: BLE001 - 模板损坏不应阻塞 UI
        logger.exception("读取模板列表失败")
        return []


def _template_update(selected: str | None = None) -> Any:
    """构造模板下拉更新。"""

    choices = _template_choices()
    value = selected if selected in choices else (choices[0] if choices else None)
    return gr.update(choices=choices, value=value)


def _persist_upload(file_path: str | None, prefix: str) -> Path:
    """复制 Gradio 临时图片到 uploads/。"""

    if not file_path:
        raise ValueError("未提供图片。")
    source = Path(file_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"上传文件不存在：{source}")
    suffix = source.suffix.lower() or ".png"
    destination = UPLOADS_DIR / (
        f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}{suffix}"
    )
    shutil.copy2(source, destination)
    return destination.resolve()
