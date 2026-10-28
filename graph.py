"""LangGraph 工作流构建与编译。

本文件职责：
- 用 StateGraph 定义 agent 与 ToolNode 两个物理节点；
- agent 节点按请求动态创建 Qwen 客户端（动态 API Key）；
- 条件边使用 tools_condition，工具执行后回到 agent；
- 对强制触发关键词做一次 system 提示重试兜底；
- 创建全局唯一 MemorySaver，并导出编译后的 graph。

依赖：config/llm.py、config/prompts.py、tools/__init__.py、constants.py。
被调用：app.py、cli.py、测试脚本。

说明：
当前锁定的 LangGraph 0.3.x 尚未导出 MessagesAnnotation，因此优先尝试导入；
缺失时用 add_messages 构造等价的 messages 注解。状态语义保持一致。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Annotated, Any, TypedDict

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph, add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from config.llm import api_key_from_config, get_llm
from config.prompts import SYSTEM_PROMPT
from constants import (
    DEFAULT_THREAD_ID,
    FORCED_TRIGGER_KEYWORDS,
    GRAPH_RECURSION_LIMIT,
)
from tools import TOOLS

logger = logging.getLogger(__name__)

try:  # LangGraph 0.4+ / 1.x
    from langgraph.graph import MessagesAnnotation  # type: ignore[attr-defined]
except ImportError:  # LangGraph 0.2/0.3 兼容
    MessagesAnnotation = Annotated[list[AnyMessage], add_messages]  # type: ignore[misc]


class AgentState(TypedDict):
    """图状态：仅包含消息列表，由 add_messages 合并增量。"""

    messages: MessagesAnnotation


# 全局唯一检查点实例；纯内存，进程重启后丢失。
MEMORY_SAVER = MemorySaver()

_FORCED_RETRY_PROMPT = (
    "本轮属于强制触发场景：用户消息命中合规阈值、台账、水印等关键词。"
    "必须调用对应工具获取真实结果，不得凭记忆直接回答，也不得声称已经调用。"
)


def _content_to_text(content: Any) -> str:
    """从字符串或多模态内容块中提取文本。"""

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


def _last_human_text(messages: list[Any]) -> str:
    """取最后一条用户消息文本。"""

    for message in reversed(messages):
        if isinstance(message, HumanMessage) or getattr(message, "type", "") == "human":
            return _content_to_text(getattr(message, "content", ""))
    return ""


def _matches_forced_trigger(text: str) -> bool:
    """判断文本是否命中强制触发关键词。"""

    lowered = (text or "").lower()
    return any(keyword.lower() in lowered for keyword in FORCED_TRIGGER_KEYWORDS)


def _has_tool_result_since_last_human(messages: list[Any]) -> bool:
    """当前用户轮次内是否已经执行过工具。

    工具执行后模型通常只需生成五段式回答；此时即使原问题包含“台账”等
    关键词，也不应再次强制重试，否则会重复调用工具并形成循环。
    """

    for message in reversed(messages):
        if isinstance(message, HumanMessage) or getattr(message, "type", "") == "human":
            return False
        if isinstance(message, ToolMessage) or getattr(message, "type", "") == "tool":
            return True
    return False


def agent_node(
    state: Mapping[str, Any],
    config: Mapping[str, Any] | None = None,
    llm_with_tools: Any | None = None,
) -> dict[str, list[AIMessage]]:
    """执行 agent 判断与回答生成，必要时对强制场景重试一次。

    Args:
        state: 至少包含 messages 的图状态。
        config: LangGraph 运行配置，configurable.api_key 为当前会话 Key。
        llm_with_tools: 测试用可注入模型；生产环境按 Key 动态创建并绑定工具。

    Returns:
        {"messages": [AIMessage]}，由 add_messages 追加到状态。
    """

    messages = list(state.get("messages", []))
    if llm_with_tools is None:
        api_key = api_key_from_config(config)
        llm_with_tools = get_llm(api_key).bind_tools(TOOLS, tool_choice="auto")

    prompt_messages = [SystemMessage(content=SYSTEM_PROMPT), *messages]
    response = llm_with_tools.invoke(prompt_messages)

    tool_calls = getattr(response, "tool_calls", None) or []
    if not tool_calls:
        last_user_text = _last_human_text(messages)
        already_used_tool = _has_tool_result_since_last_human(messages)
        if _matches_forced_trigger(last_user_text) and not already_used_tool:
            logger.warning("强制触发场景未产生 tool_calls，追加 system 提示后重试一次。")
            retry_messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                *messages,
                SystemMessage(content=_FORCED_RETRY_PROMPT),
            ]
            response = llm_with_tools.invoke(retry_messages)
            if not (getattr(response, "tool_calls", None) or []):
                logger.warning("强制触发重试后仍未产生 tool_calls，交由应用层提示补充信息。")

    return {"messages": [response]}


def build_graph(
    llm_with_tools: Any | None = None,
    checkpointer: Any | None = None,
) -> Any:
    """构建并编译 DawnDine 工作流。

    Args:
        llm_with_tools: 可选，已 bind_tools 的模型，便于离线测试。
        checkpointer: 可选检查点实例；默认使用全局唯一 MEMORY_SAVER。

    Returns:
        编译后的 LangGraph 图对象。
    """

    saver = checkpointer or MEMORY_SAVER

    def node(
        state: Mapping[str, Any],
        config: Mapping[str, Any] | None = None,
    ) -> dict[str, list[AIMessage]]:
        return agent_node(state, config, llm_with_tools)

    builder = StateGraph(AgentState)
    builder.add_node("agent", node)
    builder.add_node("tools", ToolNode(TOOLS, handle_tool_errors=True))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=saver)


graph = build_graph()


def runtime_config(
    thread_id: str = DEFAULT_THREAD_ID,
    api_key: str = "",
) -> dict[str, Any]:
    """返回统一运行配置；每个网页会话使用独立 thread_id。

    `api_key` 只通过 RunnableConfig 在内存中传递，不写入 State、不写日志、
    不进入前端回显。Key 为空时由 llm/tool 回退读取 .env。
    """

    return {
        "configurable": {"thread_id": thread_id, "api_key": api_key},
        "recursion_limit": GRAPH_RECURSION_LIMIT,
    }


def reset_conversation(thread_id: str = DEFAULT_THREAD_ID) -> bool:
    """清除指定线程的内存对话；MemorySaver 支持时返回 True。"""

    try:
        MEMORY_SAVER.delete_thread(thread_id)
        logger.info("已清除对话线程：%s", thread_id)
        return True
    except Exception:  # noqa: BLE001 - 旧版检查点可能不支持删除
        logger.exception("清除对话线程失败")
        return False
