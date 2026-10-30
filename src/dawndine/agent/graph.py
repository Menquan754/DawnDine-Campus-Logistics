"""LangGraph 工作流构建与编译。

本文件职责：
- 用 StateGraph 定义 agent 与 ToolNode 两个物理节点；
- agent 节点按请求动态创建 Qwen 客户端（动态 API Key）；
- 条件边使用 tools_condition，工具执行后回到 agent；
- 对强制触发关键词做一次 system 提示重试兜底；
- 创建全局唯一 MemorySaver，并导出编译后的 graph。

依赖：dawndine.llm、dawndine.prompts、dawndine.config、dawndine.knowledge.rag、
      dawndine.agent.tools。
被调用：app.py、cli.py、测试脚本。

说明：
当前锁定的 LangGraph 0.3.x 尚未导出 MessagesAnnotation，因此优先尝试导入；
缺失时用 add_messages 构造等价的 messages 注解。状态语义保持一致。
"""

from __future__ import annotations

import logging
import re
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

from dawndine.agent.tools import TOOLS
from dawndine.agent.tools.knowledge import DOMAIN_GENERAL, detect_domain
from dawndine.config import (
    CONFIRM_ONLY_PATTERN,
    DEFAULT_THREAD_ID,
    FORCED_TRIGGER_ACTION_WORDS,
    FORCED_TRIGGER_KEYWORDS,
    FORCED_TRIGGER_SHORT_TERMS,
    GRAPH_RECURSION_LIMIT,
    RAG_AUTO_CONTEXT_MAX_CHARS,
    RAG_AUTO_CONTEXT_MAX_ITEMS,
)
from dawndine.knowledge.rag import search
from dawndine.llm import api_key_from_config, get_llm
from dawndine.prompts import build_system_prompt

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
    "本轮属于强制触发场景：用户消息命中合规阈值、台账、水印、日程或本地后勤数据关键词。"
    "必须调用对应工具获取真实结果，不得凭记忆直接回答，也不得声称已经调用。"
)

# 命中这些词时，明确提示模型优先查本地后勤台账，避免凭印象报数。
_DATA_QUERY_KEYWORDS: tuple[str, ...] = (
    "维修单",
    "维修记录",
    "报修记录",
    "资产台账",
    "设备台账",
    "资产状态",
    "库存",
    "余量",
    "补货",
    "低库存",
    "巡检记录",
    "巡检结果",
    "供应商档案",
    "健康证",
    "服务反馈",
    "工单",
    "待处理",
    "统计一下",
    "汇总一下",
)


def _logistics_hint(text: str) -> str:
    """用户问本地台账数据时，追加只读查询工具提示。"""

    clean = (text or "").strip()
    if not clean:
        return ""
    if not any(keyword in clean for keyword in _DATA_QUERY_KEYWORDS):
        return ""
    return (
        "【本地数据查询提示】用户本轮在问本地后勤台账数据。"
        "如涉及维修、资产、库存、巡检、供应商、人员、反馈或总览，"
        "必须调用 query_logistics_records 获取真实记录后再回答；"
        "工具返回为空时写“暂无记录”，不得编造数量、编号或日期。"
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
    """判断文本是否命中强制触发关键词。

    短词（温度/留样/水印/验收）单独出现不足以强制，必须与动作词共现；
    纯确认/应答消息不触发。
    """

    stripped = (text or "").strip()
    if not stripped:
        return False
    if re.fullmatch(CONFIRM_ONLY_PATTERN, stripped):
        return False

    lowered = stripped.lower()
    matched = [keyword for keyword in FORCED_TRIGGER_KEYWORDS if keyword.lower() in lowered]
    if not matched:
        return False
    if any(keyword not in FORCED_TRIGGER_SHORT_TERMS for keyword in matched):
        return True
    return any(action.lower() in lowered for action in FORCED_TRIGGER_ACTION_WORDS)


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


def _knowledge_context(text: str, api_key: str) -> str:
    """检索本地知识库并拼成 system 提示摘录。

    检索失败时静默降级，不影响正常对话；工具执行后的二次调用不再注入，
    避免重复 embedding 与上下文膨胀。
    """

    clean = (text or "").strip()
    if len(clean) < 4 or re.fullmatch(CONFIRM_ONLY_PATTERN, clean):
        return ""
    domain = detect_domain(clean)
    query = f"{domain} {clean}" if domain != DOMAIN_GENERAL else clean
    try:
        hits = search(
            query=query,
            k=max(1, int(RAG_AUTO_CONTEXT_MAX_ITEMS)),
            api_key=api_key,
        )
    except Exception as exc:  # noqa: BLE001 - 检索失败必须静默降级
        logger.info("自动知识检索跳过：%s", type(exc).__name__)
        return ""

    lines: list[str] = []
    used = 0
    for item in hits:
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        source = str(item.get("source") or "本地知识库").strip()
        snippet = content[:260].rstrip()
        if len(content) > 260:
            snippet += "…"
        block = f"- 来源《{source}》：{snippet}"
        if used + len(block) > RAG_AUTO_CONTEXT_MAX_CHARS:
            break
        lines.append(block)
        used += len(block)
    if not lines:
        return ""
    return (
        "【本地知识库摘录（自动检索，仅供参考，不得整段照抄，也不得据此编造条款号）】\n"
        + "\n".join(lines)
        + "\n回答时优先使用上述摘录；摘录未覆盖的内容明确写“需按本校最新制度确认”。"
    )


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
    api_key = api_key_from_config(config)
    if llm_with_tools is None:
        llm_with_tools = get_llm(api_key).bind_tools(TOOLS, tool_choice="auto")

    system_prompt = build_system_prompt()
    if not _has_tool_result_since_last_human(messages):
        last_text = _last_human_text(messages)
        knowledge = _knowledge_context(last_text, api_key)
        if knowledge:
            system_prompt = f"{system_prompt}\n\n{knowledge}"
        logistics_hint = _logistics_hint(last_text)
        if logistics_hint:
            system_prompt = f"{system_prompt}\n\n{logistics_hint}"
    prompt_messages = [SystemMessage(content=system_prompt), *messages]
    response = llm_with_tools.invoke(prompt_messages)

    tool_calls = getattr(response, "tool_calls", None) or []
    if not tool_calls:
        last_user_text = _last_human_text(messages)
        already_used_tool = _has_tool_result_since_last_human(messages)
        if _matches_forced_trigger(last_user_text) and not already_used_tool:
            logger.warning("强制触发场景未产生 tool_calls，追加 system 提示后重试一次。")
            retry_messages = [
                SystemMessage(content=system_prompt),
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


def clear_all_conversations() -> int:
    """清空全部内存对话线程，返回成功删除的数量（用于 Agent 初始化）。"""

    storage = getattr(MEMORY_SAVER, "storage", None)
    thread_ids = list(storage.keys()) if isinstance(storage, Mapping) else []
    removed = 0
    for thread_id in thread_ids:
        try:
            MEMORY_SAVER.delete_thread(thread_id)
            removed += 1
        except Exception:  # noqa: BLE001 - 单个线程失败不影响其余清理
            logger.exception("清空对话线程失败：%s", thread_id)
    if thread_ids:
        logger.info("已清空 %s/%s 个对话线程", removed, len(thread_ids))
    return removed
