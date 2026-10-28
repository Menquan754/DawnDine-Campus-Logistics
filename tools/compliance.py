"""合规知识检索与结构化判断工具。

本文件职责：
- 调用 modules.rag_store.search 从本地 Chroma 检索制度片段；
- 把检索片段和现场事实拼入提示词，交由当前会话 Key 的 Qwen 输出 JSON；
- 无命中时强制降级为“存疑/需现场确认”，不凭记忆编造条款。

依赖：config/llm.py、constants.py、modules/rag_store.py、schemas.py。
被调用：graph.py（经 tools/__init__.py）、测试脚本。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from config.llm import api_key_from_config, get_llm
from constants import (
    CONCLUSION_VALUES,
    CONFIDENCE_VALUES,
    MISSING_API_KEY_MESSAGE,
    RAG_TOP_K,
    SENSORY_KEYWORDS,
    TOOL_COMPLIANCE,
)
from modules.rag_store import search
from schemas import ComplianceInput

logger = logging.getLogger(__name__)

_ALLOWED_CONCLUSIONS = set(CONCLUSION_VALUES)
_ALLOWED_CONFIDENCE = set(CONFIDENCE_VALUES)
_JSON_BLOCK_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")

_COMPLIANCE_SYSTEM_PROMPT = """你是学校食堂食品安全合规判断助手。
只根据用户事实和给出的检索片段判断，不得编造法规编号、条款号、检查人员或地方规定。
只输出一个 JSON 对象，不要 Markdown 代码围栏，不要额外解释。字段必须完整：
{
  "conclusion": "合规|不合规|存疑|需现场确认",
  "basis": "条款或制度名称；无明确依据时写“未检索到明确依据，按通用原则”",
  "action_hint": "一句话现场动作",
  "retention_hint": "留痕要求",
  "confidence": "high|medium|low"
}
判断边界：
- 涉及食材新鲜度、异味、口感等感官问题，不得判断，conclusion 用“需现场确认”。
- 检索片段不支持明确结论时，conclusion 只能为“存疑”或“需现场确认”。
- 不得进行责任认定，不得声称已经上报或生成正式记录。
- 数值接近阈值但信息不足时，优先“需现场确认”。
"""


def _message_text(message: Any) -> str:
    """兼容字符串和内容块列表两种模型输出。"""

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


def _parse_json_object(raw: str) -> dict[str, Any]:
    """从模型输出中提取并解析 JSON 对象。"""

    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK_PATTERN.search(text)
        if not match:
            raise ValueError("模型未返回 JSON 对象") from None
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("模型返回的 JSON 根节点不是对象")
    return data


def _normalize_conclusion(value: str) -> str:
    """把常见同义结论归一为固定枚举值。"""

    aliases = {
        "符合": "合规",
        "不符合": "不合规",
        "无法判断": "需现场确认",
        "需现场核实": "需现场确认",
        "现场确认": "需现场确认",
    }
    conclusion = aliases.get(value.strip(), value.strip())
    if conclusion not in _ALLOWED_CONCLUSIONS:
        raise ValueError(f"结论值非法：{value}")
    return conclusion


def _require_text(data: dict[str, Any], key: str) -> str:
    """读取必填文本字段，缺失或空白时抛错。"""

    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"模型输出缺少字段：{key}")
    return value.strip()


def _sensory_only(phenomenon: str, key_values: str | None) -> bool:
    """判断是否只是感官问题；含明确数值时不短路。"""

    if key_values and _NUMBER_PATTERN.search(key_values):
        return False
    if _NUMBER_PATTERN.search(phenomenon):
        return False
    return any(keyword in phenomenon for keyword in SENSORY_KEYWORDS)


@tool(TOOL_COMPLIANCE, args_schema=ComplianceInput)
def check_compliance_knowledge(
    stage: str,
    object_name: str,
    phenomenon: str,
    key_values: str | None = None,
    region_or_school: str | None = None,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """检索本地食品安全制度并给出合规判断，禁止凭记忆回答阈值问题。

    何时调用：
    - 出现具体温度、重量、时间、数量差异等合规阈值；
    - 需要判断某个环节、对象或现象是否符合制度；
    - 验收异常、留样不足、晨检异常等需要依据的判断。

    何时不调用：
    - 纯粹询问食材新鲜度、异味、口感等感官问题；
    - 用户要求生成台账、水印图或记录日程（应调用对应专用工具）；
    - 没有现场事实，只是泛泛聊天。

    本工具只依据本地检索片段和用户事实，不判断感官质量，不替代责任认定。
    检索无命中时，conclusion 只能降级为“存疑”或“需现场确认”，不得编造依据。

    Returns:
        成功：{"ok": True, "conclusion", "basis", "action_hint",
              "retention_hint", "confidence", "sources"}
        失败：{"ok": False, "error": "..."}
    """

    try:
        stage = (stage or "").strip()
        object_name = (object_name or "").strip()
        phenomenon = (phenomenon or "").strip()
        if not stage or not object_name or not phenomenon:
            return {"ok": False, "error": "环节、对象和现象描述不能为空。"}

        api_key = api_key_from_config(config)
        if _sensory_only(phenomenon, key_values):
            return {
                "ok": True,
                "conclusion": "需现场确认",
                "basis": "感官判断超出系统能力范围，未引用具体条款。",
                "action_hint": "超出判断范围，请现场确认食材状态并联系现场负责人。",
                "retention_hint": "保存现场照片、检查记录和确认人签字，必要时转交责任人。",
                "confidence": "low",
                "sources": [],
            }

        query_parts = [
            f"环节：{stage}",
            f"对象：{object_name}",
            f"现象：{phenomenon}",
        ]
        if key_values:
            query_parts.append(f"关键数值：{key_values}")
        if region_or_school:
            query_parts.append(f"地区/学校：{region_or_school}")
        query = "\n".join(query_parts)

        hits = search(query=query, k=RAG_TOP_K, api_key=api_key)
        unique_sources = sorted(
            {str(item.get("source", "")) for item in hits if item.get("source")}
        )

        if hits:
            snippets = []
            for index, item in enumerate(hits, start=1):
                snippets.append(
                    f"[片段{index}｜来源：{item.get('source', '未知')}]\n"
                    f"{item.get('content', '').strip()}"
                )
            context = "\n\n".join(snippets)
        else:
            context = "（本地知识库未检索到明确片段）"

        human_prompt = (
            f"现场事实：\n{query}\n\n"
            f"本地制度检索片段：\n{context}\n\n"
            "请严格按系统要求输出 JSON。无明确依据时不得判定合规。"
        )
        response = get_llm(api_key).invoke(
            [
                SystemMessage(content=_COMPLIANCE_SYSTEM_PROMPT),
                HumanMessage(content=human_prompt),
            ]
        )
        raw_text = _message_text(response)
        data = _parse_json_object(raw_text)

        conclusion = _normalize_conclusion(_require_text(data, "conclusion"))
        basis = _require_text(data, "basis")
        action_hint = _require_text(data, "action_hint")
        retention_hint = _require_text(data, "retention_hint")
        confidence = _require_text(data, "confidence").lower()
        if confidence not in _ALLOWED_CONFIDENCE:
            raise ValueError(f"置信度非法：{confidence}")

        if not hits:
            # 没有检索依据时绝不接受“合规/不合规”的强结论。
            if conclusion not in {"存疑", "需现场确认"}:
                conclusion = "存疑"
            basis = "未检索到明确依据，按通用原则；具体需按本地最新规定确认。"
            confidence = "low"

        return {
            "ok": True,
            "conclusion": conclusion,
            "basis": basis,
            "action_hint": action_hint,
            "retention_hint": retention_hint,
            "confidence": confidence,
            "sources": unique_sources,
        }
    except Exception as exc:  # noqa: BLE001 - 工具边界必须返回结构化错误
        logger.exception("合规判断工具执行失败")
        detail = str(exc)
        if not detail:
            detail = "未知错误"
        if "DASHSCOPE_API_KEY" in detail or "api key" in detail.lower():
            detail = MISSING_API_KEY_MESSAGE
        return {"ok": False, "error": f"合规判断工具执行失败：{detail}"}
