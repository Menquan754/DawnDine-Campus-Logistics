"""DawnDine 命令行对话界面。

本文件职责：
- 提供 input/print 多轮对话循环；
- 同样使用 graph.stream(stream_mode="updates")，与网页共享图与记忆；
- 支持 exit/quit/退出 退出，/clear 清空内存对话。

依赖：dawndine.agent.graph、dawndine.llm、dawndine.config、
      dawndine.services.smalltalk、langchain-core。
被调用：dawndine.__main__ --cli。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from dawndine.agent.graph import graph, reset_conversation, runtime_config
from dawndine.config import APP_DISCLAIMER, APP_TITLE, MISSING_API_KEY_MESSAGE
from dawndine.llm import get_env_api_key
from dawndine.services.smalltalk import WELCOME_REPLY, small_talk_reply

logger = logging.getLogger(__name__)

_EXIT_WORDS = {"exit", "quit", "q", "退出", "再见"}
_CLEAR_WORDS = {"/clear", "clear", "清空", "重置"}


def _message_text(message: Any) -> str:
    """从 AIMessage 提取文本。"""

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


def _tool_summary(message: ToolMessage) -> str:
    """提取工具返回中的 ok 和 output_path，供控制台显示。"""

    raw = message.content
    if isinstance(raw, list):
        raw = _message_text(raw)
    if not isinstance(raw, str):
        return "已返回"
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return "已返回"
    if not isinstance(data, dict):
        return "已返回"
    if not data.get("ok"):
        return f"失败：{data.get('error', '未知错误')}"
    if data.get("output_path"):
        return f"完成，图片：{data['output_path']}"
    return "完成"


def _print_turn(user_text: str) -> str:
    """执行一轮图调用并打印过程，返回最终文本。"""

    quick_reply = small_talk_reply(user_text)
    if quick_reply:
        return quick_reply

    if not get_env_api_key():
        return f"⚠️ {MISSING_API_KEY_MESSAGE}"

    final_text = ""
    try:
        for chunk in graph.stream(
            {"messages": [HumanMessage(content=user_text)]},
            config=runtime_config(api_key=get_env_api_key()),
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
                            print(f"  [工具] 正在调用：{names}")
                            continue
                        text = _message_text(item).strip()
                        if text:
                            final_text = text
                elif node_name == "tools" and isinstance(payload, dict):
                    for item in payload.get("messages", []):
                        if isinstance(item, ToolMessage):
                            print(f"  [工具] {item.name or '工具'} {_tool_summary(item)}")
    except Exception as exc:  # noqa: BLE001 - CLI 统一兜底
        logger.exception("CLI 对话失败")
        if "401" in str(exc) or "api key" in str(exc).lower():
            return f"⚠️ {MISSING_API_KEY_MESSAGE}"
        return f"⚠️ 本轮执行失败：{exc}"
    return final_text


def run_cli() -> None:
    """启动交互式控制台。"""

    print("=" * 68)
    print(APP_TITLE)
    print("=" * 68)
    print("输入问题开始对话；exit / quit / 退出 结束；/clear 清空多轮记忆。")
    if not get_env_api_key():
        print(f"⚠️ {MISSING_API_KEY_MESSAGE}")
    print()
    print(f"后勤助手 >\n{WELCOME_REPLY}\n")

    while True:
        try:
            user_text = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            break

        if not user_text:
            continue
        if user_text.lower() in _EXIT_WORDS or user_text in _EXIT_WORDS:
            print("已退出。")
            break
        if user_text.lower() in _CLEAR_WORDS or user_text in _CLEAR_WORDS:
            reset_conversation()
            print("已清空当前线程的对话记忆。\n")
            continue

        print("后勤助手 > 正在处理…")
        answer = _print_turn(user_text)
        if answer:
            print(f"\n后勤助手 >\n{answer}\n")
        else:
            print("\n后勤助手 > 本轮没有生成文字结论，请补充信息后重试。\n")

    print(f"\n{APP_DISCLAIMER}")


if __name__ == "__main__":
    raise SystemExit("请使用 uv run main.py --cli 启动。")
