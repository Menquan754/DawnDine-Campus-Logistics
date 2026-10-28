"""DawnDine 多页面 Gradio 工作台。

本文件职责：
- 左导航 + 右工作区三页面：食堂助手、图片水印、我的日程；
- 每个浏览器会话独立 thread_id，避免多用户对话串线；
- 系统设置中管理仅当前会话有效的 DashScope Key；
- 聊天走 LangGraph，水印走 Pillow，日程走 SQLite + Qwen-VL；
- 统一展示工具状态、水印 output_path 和最近工具返回。

依赖：graph.py、config/llm.py、modules/db.py、modules/vision.py、
      tools/watermark.py、constants.py、gradio、langchain-core。
被调用：main.py、PyCharm Web 运行配置、直接 uv run app.py。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import uuid
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import gradio as gr
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from config.llm import (
    api_key_configured,
    get_vision_model_name,
    key_source,
    resolve_api_key,
)
from constants import (
    APP_DISCLAIMER,
    APP_SUBTITLE,
    APP_TITLE,
    MISSING_API_KEY_MESSAGE,
    SCHEDULE_SOURCE_MANUAL,
    SCHEDULE_TABLE_HEADERS,
    SERVER_HOST,
    SERVER_PORT,
    UPLOADS_DIR,
    WATERMARKED_DIR,
    ensure_runtime_dirs,
)
from graph import graph, reset_conversation, runtime_config
from modules.db import (
    bulk_create_schedules,
    create_schedule,
    init_db,
    list_schedule_rows,
    normalize_date,
    normalize_time,
)
from modules.vision import parse_schedule_image, probe_vision_model
from tools.watermark import generate_meal_accompaniment_record, list_templates

logger = logging.getLogger(__name__)

ensure_runtime_dirs()
init_db()

_CHAT_LOCK = threading.Lock()
_WATERMARK_INTENT_WORDS = ("水印", "打卡图", "打卡照", "陪餐图")
_QUICK_PROMPTS: dict[str, str] = {
    "合规判断": "请做合规判断，现场情况如下：",
    "异常上报": "请按异常闭环处理，情况如下：",
    "生成台账": "请生成台账，信息如下：",
    "每日清单": f"帮我生成今天的每日清单（{datetime.now():%Y-%m-%d}），情况如下：",
    "检查应对": "检查应对问题：",
}

_CSS = """
:root {
  --dd-bg: #f2f7f6;
  --dd-bg-2: #e8f2ef;
  --dd-surface: #ffffff;
  --dd-soft: #f5faf8;
  --dd-ink: #18332c;
  --dd-muted: #657b75;
  --dd-line: #dce9e5;
  --dd-teal: #0f766e;
  --dd-teal-dark: #0b5c56;
  --dd-cyan: #0891b2;
  --dd-mint: #dff3ec;
  --dd-amber: #b7791f;
  --dd-shadow: 0 12px 32px rgba(24, 51, 44, 0.07);
}
html, body, .gradio-container { color-scheme: light; }
.gradio-container {
  width: 100% !important;
  max-width: 1500px !important;
  margin: 0 auto !important;
  padding: 18px 22px 30px var(--dd-pad-left, 310px) !important;
  background:
    radial-gradient(circle at 8% 0%, rgba(8, 145, 178, 0.09), transparent 30%),
    radial-gradient(circle at 96% 2%, rgba(15, 118, 110, 0.08), transparent 28%),
    var(--dd-bg);
}
#dd-sidebar {
  left: max(12px, calc((100vw - 1500px) / 2 + 2px)) !important;
  top: 12px !important;
  width: 286px !important;
  max-height: calc(100vh - 24px);
  overflow-y: auto;
  transform: translateX(0) !important;
  background: rgba(255, 255, 255, 0.94) !important;
  border: 1px solid var(--dd-line) !important;
  border-radius: 22px !important;
  padding: 16px 14px !important;
  box-shadow: var(--dd-shadow) !important;
  min-width: 286px !important;
  align-self: flex-start;
}
#dd-sidebar .toggle-button { display: none !important; }
.toggle-button { display: none !important; }
.dd-brand {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 6px 6px 14px;
  border-bottom: 1px solid var(--dd-line);
  margin-bottom: 12px;
}
.dd-logo {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  color: #fff;
  font-weight: 900;
  font-size: 14px;
  letter-spacing: -0.06em;
  background: linear-gradient(135deg, var(--dd-teal), var(--dd-cyan));
  box-shadow: 0 8px 18px rgba(15, 118, 110, 0.24);
}
.dd-brand-name {
  font-size: 14px;
  font-weight: 850;
  color: var(--dd-ink);
  line-height: 1.25;
  white-space: nowrap;
}
.dd-brand-sub {
  margin-top: 2px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--dd-muted);
}
#dd-nav { margin-top: 4px; }
#dd-nav .wrap {
  display: flex !important;
  flex-direction: column !important;
  gap: 7px !important;
}
#dd-nav label {
  border: 1px solid transparent !important;
  border-radius: 12px !important;
  padding: 9px 11px !important;
  background: transparent !important;
  color: var(--dd-ink) !important;
  font-weight: 650 !important;
  cursor: pointer;
}
#dd-nav label:hover { background: var(--dd-soft) !important; }
#dd-nav label:has(input:checked) {
  background: var(--dd-mint) !important;
  border-color: rgba(15, 118, 110, 0.18) !important;
  color: var(--dd-teal-dark) !important;
}
#dd-nav input { accent-color: var(--dd-teal); }
.dd-side-note {
  margin-top: 18px;
  padding: 12px;
  border-radius: 14px;
  background: var(--dd-soft);
  border: 1px solid var(--dd-line);
  color: var(--dd-muted);
  font-size: 11px;
  line-height: 1.6;
}
.dd-side-footer {
  margin-top: 12px;
  color: #80928c;
  font-size: 10px;
  line-height: 1.5;
}
#dd-sidebar .dd-thread {
  margin-top: 12px;
}
#dd-sidebar .dd-thread textarea {
  font-family: "Cascadia Code", Consolas, monospace;
  font-size: 10px;
  color: #5f756e;
  white-space: nowrap !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
}
.dd-topbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  padding: 6px 4px 16px;
}
.dd-eyebrow {
  color: var(--dd-teal);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.16em;
}
.dd-title {
  margin: 5px 0 3px !important;
  color: var(--dd-ink) !important;
  font-size: clamp(25px, 3vw, 34px) !important;
  line-height: 1.1 !important;
  font-weight: 850 !important;
  letter-spacing: -0.02em;
}
.dd-subtitle {
  margin: 0 !important;
  color: var(--dd-muted) !important;
  font-size: 13px !important;
}
.dd-live {
  flex: none;
  margin-top: 8px;
  border-radius: 999px;
  padding: 7px 11px;
  background: #eaf8f3;
  border: 1px solid #c9e9dd;
  color: #1f6f58;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}
.dd-page {
  border: 1px solid var(--dd-line) !important;
  border-radius: 22px !important;
  background: rgba(255, 255, 255, 0.92) !important;
  box-shadow: var(--dd-shadow) !important;
  padding: 18px !important;
}
.dd-panel {
  border: 1px solid var(--dd-line) !important;
  border-radius: 18px !important;
  background: var(--dd-surface) !important;
  padding: 14px !important;
  box-shadow: 0 5px 16px rgba(24, 51, 44, 0.04) !important;
}
.dd-card-title {
  margin: 0 0 10px !important;
  color: var(--dd-ink) !important;
  font-size: 14px !important;
  font-weight: 800 !important;
}
.dd-card-title + p { color: var(--dd-muted) !important; }
.dd-status {
  min-height: 38px;
  border-radius: 12px;
  padding: 8px 12px;
  background: #eef8f4;
  border: 1px solid #d7ede5;
  color: #245847;
  font-size: 13px;
}
.dd-status p { margin: 0 !important; }
#dd-chatbot {
  border: 1px solid var(--dd-line) !important;
  border-radius: 16px !important;
  background: #fbfdfc !important;
  overflow: hidden;
}
#dd-chatbot .message { font-size: 14px; line-height: 1.65; }
#dd-chatbot .message, #dd-chatbot .prose, #dd-chatbot .prose p {
  overflow-wrap: anywhere;
  word-break: break-word;
}
#dd-message textarea { border-radius: 12px !important; font-size: 14px !important; }
#dd-send { min-width: 84px; border-radius: 12px !important; font-weight: 750 !important; }
.dd-quick-row { gap: 6px !important; flex-wrap: wrap !important; }
.dd-quick-row button {
  border-radius: 999px !important;
  min-height: 30px !important;
  font-size: 11px !important;
  padding: 2px 11px !important;
  background: #f3faf7 !important;
  border: 1px solid #d5ebe3 !important;
  color: #286b57 !important;
}
.dd-settings {
  border: 1px solid var(--dd-line) !important;
  border-radius: 16px !important;
  background: rgba(255, 255, 255, 0.72) !important;
  margin-bottom: 14px !important;
}
.dd-settings .gr-accordion > button {
  color: var(--dd-ink) !important;
  font-weight: 750 !important;
}
.dd-key-status {
  min-height: 34px;
  color: var(--dd-muted);
  font-size: 12px;
  line-height: 1.55;
}
.dd-hint {
  color: var(--dd-muted);
  font-size: 11px;
  line-height: 1.55;
}
#dd-output-path textarea {
  font-family: "Cascadia Code", Consolas, monospace;
  font-size: 11px;
  white-space: pre-wrap !important;
  overflow-wrap: anywhere !important;
  word-break: break-all !important;
}
.dd-footer {
  margin-top: 18px;
  padding-top: 12px;
  border-top: 1px solid var(--dd-line);
  color: #6c807a;
  font-size: 11px;
  line-height: 1.6;
  text-align: center;
}
.dd-footer strong { color: #2d5c4d; }
@media (max-width: 900px) {
  html, body { max-width: 100%; overflow-x: hidden; }
  .gradio-container {
    width: 100vw !important;
    max-width: 100vw !important;
    overflow-x: hidden;
  }
  #dd-sidebar { display: none !important; }
  .dd-mobile-nav { display: block !important; margin-bottom: 10px; }
  .dd-key-row { flex-direction: column !important; align-items: stretch !important; }
  .dd-key-row > * { width: 100% !important; }
  .dd-topbar { flex-direction: column; gap: 4px; }
  .dd-page, .dd-panel, .dd-settings { min-width: 0 !important; max-width: 100% !important; }
  .dd-page { padding: 12px !important; }
  .dd-main, .dd-main * { min-width: 0 !important; }
}
.dd-mobile-nav { display: none; }
"""

_THEME = gr.themes.Soft(
    primary_hue="teal",
    secondary_hue="cyan",
    neutral_hue="slate",
    font=["Inter", "Microsoft YaHei", "sans-serif"],
)

_FORCE_LIGHT_JS = """
() => {
  const applyResponsive = () => {
    const mobile = window.innerWidth <= 900;
    document.documentElement.style.setProperty('--dd-pad-left', mobile ? '10px' : '310px');
  };
  applyResponsive();
  window.addEventListener('resize', applyResponsive);

  const forceLight = () => {
    document.documentElement.classList.remove('dark');
    document.documentElement.style.colorScheme = 'light';
    if (document.body) {
      document.body.classList.remove('dark');
      document.body.style.colorScheme = 'light';
    }
  };
  forceLight();
  const observer = new MutationObserver(forceLight);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['class']
  });
  if (document.body) {
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ['class']
    });
  }
  setTimeout(() => observer.disconnect(), 2500);
}
"""

_TABLE_DATATYPE = ["number", "str", "str", "str", "str", "str"]


# ---------------------------------------------------------------------------
# 基础
# ---------------------------------------------------------------------------
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


def _schedule_rows() -> list[list[Any]]:
    """读取最新日程行，异常时返回空表并记录日志。"""

    try:
        return list_schedule_rows()
    except Exception:  # noqa: BLE001 - UI 不应因数据库异常整体崩溃
        logger.exception("读取日程失败")
        return []


def _friendly_time_error(value: str | None) -> str | None:
    """校验水印手动时间格式。"""

    clean = (value or "").strip()
    if not clean:
        return None
    try:
        datetime.strptime(clean, "%Y-%m-%d %H:%M")
    except ValueError:
        return "手动时间格式应为 YYYY-MM-DD HH:MM，例如 2026-10-28 12:00。"
    return None


# ---------------------------------------------------------------------------
# 会话 / 设置
# ---------------------------------------------------------------------------
def init_session() -> tuple[str, str, str, list[list[Any]], Any]:
    """为每个浏览器会话初始化独立 thread_id、Key 状态和日程表。"""

    init_db()
    session_id = uuid.uuid4().hex
    short_id = f"{session_id[:8]}…{session_id[-4:]}"
    return session_id, short_id, _key_status(""), _schedule_rows(), _template_update()


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


# ---------------------------------------------------------------------------
# 页A：聊天
# ---------------------------------------------------------------------------
def _wants_watermark(message: str) -> bool:
    """聊天页不接收图片；识别水印意图后引导到图片水印页。"""

    return any(word in (message or "") for word in _WATERMARK_INTENT_WORDS)


def _chat_error(history: list[dict[str, str]], text: str) -> tuple[Any, ...]:
    """构造聊天错误返回。"""

    history.append({"role": "assistant", "content": text})
    return history, "", "⚠️ 执行失败", gr.skip()


def chat(
    message: str,
    history: Sequence[Any] | None,
    thread_id: str,
    ui_api_key: str,
) -> Iterator[tuple[Any, ...]]:
    """聊天事件：按会话 thread_id 与 Key 调用 LangGraph。"""

    chat_history = _normalize_history(history)
    user_text = (message or "").strip()
    if not user_text:
        yield chat_history, "", "请输入问题后再发送。", gr.skip()
        return

    chat_history.append({"role": "user", "content": user_text})
    yield chat_history, "", "⏳ 正在分析现场信息…", gr.skip()

    if _wants_watermark(user_text):
        chat_history.append(
            {
                "role": "assistant",
                "content": (
                    "请点击左侧 **🖼️ 图片水印** 页面，上传样图和现场照片后生成打卡图。"
                    "聊天页不接收图片，避免把临时路径误写入台账。"
                ),
            }
        )
        yield chat_history, "", "🖼️ 已提示前往图片水印页", gr.skip()
        return

    active_key = resolve_api_key(ui_api_key)
    if not active_key:
        chat_history.append(
            {
                "role": "assistant",
                "content": (
                    "⚠️ 当前没有可用的 DashScope API Key，无法进行真实对话。\n\n"
                    "请在页面顶部 **系统设置** 中填写本次会话 Key，"
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
    try:
        with _CHAT_LOCK:
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


def clear_chat(thread_id: str) -> tuple[Any, ...]:
    """清空当前会话聊天记录与 LangGraph 内存。"""

    if thread_id:
        reset_conversation(thread_id)
    return [], "", "🧹 当前会话对话已清空，可开始新的检查。", gr.skip()


# ---------------------------------------------------------------------------
# 页B：图片水印
# ---------------------------------------------------------------------------
def create_template_from_upload(
    sample_image: str | None,
    template_name: str | None,
    user_requirement: str | None,
) -> tuple[Any, ...]:
    """保存样图并创建水印模板。"""

    if not sample_image:
        return "⚠️ 请先上传一张样图。", gr.skip(), None
    try:
        sample = _persist_upload(sample_image, "sample")
        result = generate_meal_accompaniment_record.invoke(
            {
                "mode": "new_template",
                "template_name": (template_name or "default").strip() or "default",
                "sample_image_path": str(sample),
                "user_requirement": (user_requirement or "").strip() or None,
            }
        )
        if not result.get("ok"):
            return f"⚠️ 模板创建失败：{result.get('error', '未知错误')}", gr.skip(), result
        name = str(result.get("template_name") or "default")
        return (
            f"✅ 已创建模板“{name}”。请核对文字、位置和字号，确认后再生成打卡图。",
            _template_update(name),
            result,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("创建水印模板失败")
        return f"⚠️ 模板创建失败：{_short_error(exc)}", gr.skip(), {"ok": False, "error": str(exc)}


def render_watermark_from_upload(
    template_name: str | None,
    scene_image: str | None,
    location: str | None,
    manual_time: str | None,
) -> tuple[Any, ...]:
    """生成水印图，并刷新水印与日程表。"""

    if not scene_image:
        return None, "", "⚠️ 请先上传现场照片。", None, gr.skip()
    if not template_name:
        return None, "", "⚠️ 请先创建或选择水印模板。", None, gr.skip()
    time_error = _friendly_time_error(manual_time)
    if time_error:
        return None, "", f"⚠️ {time_error}", {"ok": False, "error": time_error}, gr.skip()
    try:
        scene = _persist_upload(scene_image, "scene")
        result = generate_meal_accompaniment_record.invoke(
            {
                "mode": "use_template",
                "template_name": template_name,
                "scene_image_path": str(scene),
                "location": (location or "").strip() or None,
                "manual_time": (manual_time or "").strip() or None,
            }
        )
        if not result.get("ok"):
            return (
                None,
                "",
                f"⚠️ 打卡图生成失败：{result.get('error', '未知错误')}",
                result,
                gr.skip(),
            )
        path = str(result.get("output_path") or "")
        note = str(result.get("note", ""))
        return path or None, path, f"✅ 打卡图已生成。{note}".strip(), result, _schedule_rows()
    except Exception as exc:  # noqa: BLE001
        logger.exception("生成水印图失败")
        return None, "", f"⚠️ 打卡图生成失败：{_short_error(exc)}", {"ok": False}, gr.skip()


# ---------------------------------------------------------------------------
# 页C：我的日程
# ---------------------------------------------------------------------------
def refresh_schedules() -> list[list[Any]]:
    """刷新日程表。"""

    return _schedule_rows()


def add_manual_schedule(
    date_value: str,
    time_value: str,
    content: str,
) -> tuple[Any, ...]:
    """手动新增一条日程。"""

    if not (content or "").strip():
        return gr.skip(), "⚠️ 请填写日程事项。", gr.skip()
    try:
        date_text = normalize_date(date_value)
        time_text = normalize_time(time_value)
        record = create_schedule(
            date=date_text,
            time=time_text,
            content=content,
            source=SCHEDULE_SOURCE_MANUAL,
        )
        return (
            _schedule_rows(),
            f"✅ 已添加日程：{record['date']} {record['time']} {record['content']}",
            "",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("手动添加日程失败")
        return gr.skip(), f"⚠️ 添加失败：{_short_error(exc)}", gr.skip()


def import_schedule_from_image(
    image_path: str | None,
    ui_api_key: str,
) -> tuple[Any, ...]:
    """调用 Qwen-VL 解析图片并批量写入日程。"""

    if not image_path:
        return "⚠️ 请先上传日程图片。", gr.skip()
    if not _key_configured(ui_api_key):
        return "⚠️ 图片解析需要 DashScope Key，请先在系统设置中填写。", gr.skip()
    try:
        saved = _persist_upload(image_path, "schedule")
        parsed = parse_schedule_image(str(saved), api_key=resolve_api_key(ui_api_key))
        records = parsed["records"]
        if not records:
            return f"⚠️ {parsed['note']}", _schedule_rows()
        inserted = bulk_create_schedules(records)
        if not inserted:
            return "⚠️ 图片解析到日程，但写入失败，请检查日期/时间格式。", _schedule_rows()
        return (
            f"✅ 已导入 {len(inserted)} 条日程。{parsed['note']}",
            _schedule_rows(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("图片导入日程失败")
        return f"⚠️ 导入失败：{_short_error(exc)}", gr.skip()


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------
def switch_page(choice: str) -> tuple[Any, ...]:
    """切换三个工作区，返回可见性更新。"""

    return (
        gr.update(visible=choice == "chat"),
        gr.update(visible=choice == "watermark"),
        gr.update(visible=choice == "schedule"),
    )


def build_demo() -> gr.Blocks:
    """构建多页面 Gradio 工作台。"""

    initial_templates = _template_choices()
    initial_template = initial_templates[0] if initial_templates else None
    initial_key_status = _key_status("")

    with gr.Blocks(
        theme=_THEME,
        css=_CSS,
        js=_FORCE_LIGHT_JS,
        title=APP_TITLE,
        analytics_enabled=False,
    ) as demo:
        thread_id_state = gr.State("")
        api_key_state = gr.State("")

        with gr.Sidebar(open=True, width=286, position="left", elem_id="dd-sidebar"):
            gr.HTML(
                """
                <div class="dd-brand">
                  <div class="dd-logo">DD</div>
                  <div>
                    <div class="dd-brand-name">校园食堂后勤助手</div>
                    <div class="dd-brand-sub">FOOD SAFETY WORKSPACE</div>
                  </div>
                </div>
                """
            )
            nav = gr.Radio(
                choices=[
                    ("💬  食堂助手", "chat"),
                    ("🖼️  图片水印", "watermark"),
                    ("📅  我的日程", "schedule"),
                ],
                value="chat",
                label="工作区",
                elem_id="dd-nav",
            )
            gr.HTML(
                """
                <div class="dd-side-note">
                  本地运行 · LangGraph · SQLite<br/>
                  <strong>不会上传现场照片到训练集</strong>，仅当前服务器处理。
                </div>
                <div class="dd-side-footer">
                  输出为建议与草稿<br/>不替代现场判断与责任认定
                </div>
                """
            )
            thread_display = gr.Textbox(
                label="当前会话 thread_id",
                value="等待初始化…",
                interactive=False,
                max_lines=1,
                show_copy_button=True,
                elem_classes="dd-thread",
            )

        with gr.Column(elem_id="dd-workspace"):
            with gr.Row(elem_classes="dd-topbar"):
                gr.HTML(
                    f"""
                    <div>
                      <div class="dd-eyebrow">DAWNDINE · CAMPUS FOOD SAFETY</div>
                      <h1 class="dd-title">{APP_TITLE}</h1>
                      <p class="dd-subtitle">{APP_SUBTITLE}</p>
                    </div>
                    """
                )
                gr.HTML('<div class="dd-live">● 本地工作台运行中</div>')

            with gr.Column(elem_classes="dd-mobile-nav"):
                mobile_nav = gr.Radio(
                    choices=[
                        ("💬  食堂助手", "chat"),
                        ("🖼️  图片水印", "watermark"),
                        ("📅  我的日程", "schedule"),
                    ],
                    value="chat",
                    label="工作区",
                )

            with gr.Accordion(
                "⚙ 系统设置 · API Key 与会话",
                open=not _key_configured(""),
                elem_classes="dd-settings",
            ):
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
                    "Key 不写入 SQLite、不写入前端日志。</div>"
                )
                with gr.Row():
                    probe_vision_button = gr.Button(
                        "检测视觉模型",
                        size="sm",
                        variant="secondary",
                    )
                    vision_probe_status = gr.Markdown(
                        f"视觉模型：`{get_vision_model_name()}`"
                        "（可通过 .env 的 `DASHSCOPE_VL_MODEL` 覆盖）",
                        elem_classes="dd-key-status",
                    )

            # 页 A
            with gr.Column(visible=True, elem_classes="dd-page") as page_chat:
                gr.Markdown("### 💬 食堂助手", elem_classes="dd-card-title")
                gr.Markdown(
                    "合规判断、异常处置、台账草稿、每日清单、检查应对，也可以直接让助手记录日程。",
                    elem_classes="dd-hint",
                )
                chat_status = gr.Markdown(
                    "准备就绪。填写 Key 后可直接提问，或使用下方快捷工具。",
                    elem_classes="dd-status",
                )
                chatbot = gr.Chatbot(
                    value=[],
                    type="messages",
                    height=330,
                    layout="bubble",
                    bubble_full_width=False,
                    show_copy_button=True,
                    show_copy_all_button=True,
                    placeholder="描述现场情况、要求生成台账，或让助手记录日程。",
                    elem_id="dd-chatbot",
                    label="校园食堂后勤助手对话",
                )
                with gr.Row():
                    message_box = gr.Textbox(
                        placeholder="例如：验收冷鲜猪肉，配送单写0—4℃，我实测6℃",
                        show_label=False,
                        container=False,
                        scale=8,
                        lines=1,
                        elem_id="dd-message",
                    )
                    send_button = gr.Button("发送", variant="primary", scale=1, elem_id="dd-send")
                with gr.Row(elem_classes="dd-quick-row"):
                    quick_buttons = {
                        label: gr.Button(f"＋ {label}", size="sm", variant="secondary")
                        for label in _QUICK_PROMPTS
                    }
                clear_chat_button = gr.Button(
                    "清空本会话对话 / 重置记忆",
                    size="sm",
                    variant="secondary",
                )

            # 页 B
            with gr.Column(visible=False, elem_classes="dd-page") as page_watermark:
                gr.Markdown("### 🖼️ 图片水印", elem_classes="dd-card-title")
                gr.Markdown(
                    "先上传样图建立模板，再用现场照片生成带日期、时间、地点和防伪码的"
                    "陪餐/验收打卡图。地点留空会写“待补”。",
                    elem_classes="dd-hint",
                )
                watermark_status = gr.Markdown(
                    "准备就绪。生成打卡成功后会自动写入“我的日程”。",
                    elem_classes="dd-status",
                )
                with gr.Row():
                    with gr.Column(elem_classes="dd-panel"):
                        gr.Markdown("#### ① 模板准备", elem_classes="dd-card-title")
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
                            placeholder="例如：左上角简洁、深绿色底、白字",
                            lines=2,
                        )
                        create_template_button = gr.Button("上传样图新建模板", variant="secondary")
                        template_dropdown = gr.Dropdown(
                            label="当前模板",
                            choices=initial_templates,
                            value=initial_template,
                            interactive=True,
                            allow_custom_value=False,
                        )
                    with gr.Column(elem_classes="dd-panel"):
                        gr.Markdown("#### ② 生成打卡图", elem_classes="dd-card-title")
                        scene_image = gr.Image(
                            label="现场照片",
                            type="filepath",
                            sources=["upload"],
                            height=210,
                            show_download_button=False,
                        )
                        location = gr.Textbox(
                            label="陪餐地点（可选）",
                            placeholder="例如：第一食堂二楼；留空则写“待补”",
                        )
                        manual_time = gr.Textbox(
                            label="手动时间（可选）",
                            placeholder="YYYY-MM-DD HH:MM；留空使用当前时间",
                        )
                        render_button = gr.Button("生成水印打卡图", variant="primary")
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
                with gr.Accordion("最近工具返回（调试/留痕）", open=False):
                    last_result = gr.JSON(label="工具返回 JSON", value=None)

            # 页 C
            with gr.Column(visible=False, elem_classes="dd-page") as page_schedule:
                gr.Markdown("### 📅 我的日程", elem_classes="dd-card-title")
                gr.Markdown(
                    "台账、异常、水印成功后自动沉淀；也可以上传通知截图用 Qwen-VL 解析，"
                    "或手动添加。",
                    elem_classes="dd-hint",
                )
                with gr.Row(elem_classes="dd-panel"):
                    with gr.Column(scale=2):
                        schedule_image = gr.Image(
                            label="上传日程/通知截图",
                            type="filepath",
                            sources=["upload"],
                            height=170,
                            show_download_button=False,
                        )
                    with gr.Column(scale=3):
                        gr.Markdown("#### 图片导入日程", elem_classes="dd-card-title")
                        gr.Markdown(
                            "Qwen-VL 会从通知、排班或日程截图中抽取日期、时间、事项和地点，"
                            "确认后写入本地 SQLite。",
                            elem_classes="dd-hint",
                        )
                        import_schedule_button = gr.Button("解析图片并导入日程", variant="primary")
                        schedule_status = gr.Markdown(
                            f"图片解析使用 {get_vision_model_name()}，"
                            "需要当前会话或 .env 中有 Key。",
                            elem_classes="dd-status",
                        )

                with gr.Row():
                    gr.Markdown(
                        "#### 全部日程（按日期/时间倒序）",
                        elem_classes="dd-card-title",
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

                gr.Markdown("#### 底部 · 手动添加日程", elem_classes="dd-card-title")
                with gr.Row(elem_classes="dd-panel"):
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
                    add_schedule_button = gr.Button("添加日程", variant="primary", scale=1)

            gr.HTML(
                f'<div class="dd-footer"><strong>{APP_DISCLAIMER}</strong><br/>'
                f"{APP_TITLE} · LangGraph + Qwen + Chroma + Pillow + SQLite + Gradio · "
                "输出为建议与草稿，正式记录须由责任人核对签字。</div>"
            )

        # 会话初始化
        demo.load(
            init_session,
            inputs=None,
            outputs=[
                thread_id_state,
                thread_display,
                key_status_md,
                schedule_table,
                template_dropdown,
            ],
            api_name="init_session",
        )

        # 切换页面
        nav.change(
            switch_page,
            inputs=nav,
            outputs=[page_chat, page_watermark, page_schedule],
            api_name="switch_page",
        )
        nav.change(refresh_schedules, inputs=None, outputs=schedule_table, api_name=False)
        mobile_nav.change(
            switch_page,
            inputs=mobile_nav,
            outputs=[page_chat, page_watermark, page_schedule],
            api_name=False,
        )
        mobile_nav.change(
            refresh_schedules,
            inputs=None,
            outputs=schedule_table,
            api_name=False,
        )

        # 设置
        save_key_button.click(
            save_api_key,
            inputs=api_key_box,
            outputs=[api_key_state, key_status_md, api_key_box],
            api_name="save_api_key",
        )
        clear_key_button.click(
            clear_api_key,
            inputs=None,
            outputs=[api_key_state, key_status_md, api_key_box],
            api_name="clear_api_key",
        )
        probe_vision_button.click(
            probe_vision,
            inputs=api_key_state,
            outputs=vision_probe_status,
            api_name="probe_vision_model",
        )

        # 聊天
        chat_inputs = [message_box, chatbot, thread_id_state, api_key_state]
        chat_outputs = [chatbot, message_box, chat_status, schedule_table]
        message_box.submit(
            chat,
            inputs=chat_inputs,
            outputs=chat_outputs,
            api_name="chat",
            show_progress="hidden",
        )
        send_button.click(
            chat,
            inputs=chat_inputs,
            outputs=chat_outputs,
            api_name=False,
            show_progress="hidden",
        )
        clear_chat_button.click(
            clear_chat,
            inputs=[thread_id_state],
            outputs=[chatbot, message_box, chat_status, schedule_table],
            api_name="clear_chat",
        )

        for label, button in quick_buttons.items():
            prompt = _QUICK_PROMPTS[label]
            button.click(
                lambda text=prompt: text,
                inputs=None,
                outputs=message_box,
                api_name=False,
            ).then(
                chat,
                inputs=chat_inputs,
                outputs=chat_outputs,
                api_name=False,
                show_progress="hidden",
            )

        # 水印
        create_template_button.click(
            create_template_from_upload,
            inputs=[sample_image, new_template_name, template_requirement],
            outputs=[watermark_status, template_dropdown, last_result],
            api_name="create_template",
        )
        render_button.click(
            render_watermark_from_upload,
            inputs=[template_dropdown, scene_image, location, manual_time],
            outputs=[result_image, output_path, watermark_status, last_result, schedule_table],
            api_name="render_watermark",
        )

        # 日程
        refresh_schedule_button.click(
            refresh_schedules,
            inputs=None,
            outputs=schedule_table,
            api_name="refresh_schedules",
        )
        add_schedule_button.click(
            add_manual_schedule,
            inputs=[schedule_date, schedule_time, schedule_content],
            outputs=[schedule_table, schedule_status, schedule_content],
            api_name="add_schedule",
        )
        import_schedule_button.click(
            import_schedule_from_image,
            inputs=[schedule_image, api_key_state],
            outputs=[schedule_status, schedule_table],
            api_name="import_schedule_image",
        )

    return demo


demo = build_demo()


def launch(inbrowser: bool | None = None) -> None:
    """启动 Web 界面，默认在 127.0.0.1:7860 打开浏览器。"""

    should_open = (
        inbrowser if inbrowser is not None else os.getenv("DAWNDINE_NO_BROWSER", "0") != "1"
    )
    demo.queue(default_concurrency_limit=4, max_size=32).launch(
        server_name=SERVER_HOST,
        server_port=SERVER_PORT,
        inbrowser=should_open,
        allowed_paths=[str(UPLOADS_DIR), str(WATERMARKED_DIR)],
        show_api=False,
        show_error=False,
        max_file_size="20mb",
    )


if __name__ == "__main__":
    launch()
