"""每日四项食品安全工作清单工具。

本文件职责：
- 把用户提供的完成、未完成、异常事项归入四个日常板块；
- 输出 status 为 done/not_done/abnormal/unfilled 的清单；
- 生成缺口、待办、联动工具建议，设备不可用时转人工核查；
- 成功后把完整结果写入 records 表，供历史回查。

依赖：dawndine.config、dawndine.enums、dawndine.schemas、dawndine.db、
      dawndine.knowledge.rag、langchain-core。
被调用：dawndine.agent.graph（经 agent/tools/__init__.py）、测试脚本。
"""

from __future__ import annotations

import hashlib
import logging
from functools import lru_cache
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from dawndine.config import RAG_TOP_K
from dawndine.db import safe_save_record
from dawndine.enums import (
    CHECKLIST_ACCEPTANCE,
    CHECKLIST_CATEGORIES,
    CHECKLIST_MEAL,
    CHECKLIST_PLATFORM_DUAL,
    CHECKLIST_PREP_KNIFE,
    CHECKLIST_STATUS_VALUES,
    RECORD_KIND_CHECKLIST,
    TOOL_ABNORMAL,
    TOOL_CHECKLIST,
    TOOL_COMPLIANCE,
    TOOL_LEDGER,
    TOOL_WATERMARK,
    ChecklistStatus,
)
from dawndine.knowledge.rag import search
from dawndine.llm import api_key_from_config
from dawndine.schemas import ChecklistInput

logger = logging.getLogger(__name__)

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    CHECKLIST_ACCEPTANCE: (
        "验收",
        "验菜",
        "索证",
        "票证",
        "进货",
        "温度",
        "晨检",
        "留样",
        "监督",
        "加工",
    ),
    CHECKLIST_PLATFORM_DUAL: (
        "平台",
        "上传",
        "资料",
        "双人",
        "双检",
        "双锁",
        "台账",
        "系统",
    ),
    CHECKLIST_PREP_KNIFE: (
        "切配",
        "清洗",
        "刀具",
        "菜板",
        "砧板",
        "消毒",
        "生熟",
        "荤素",
    ),
    CHECKLIST_MEAL: ("陪餐", "拍照", "评价表", "餐食评价", "家长陪餐"),
}

_OWNER_HINTS: dict[str, str] = {
    CHECKLIST_ACCEPTANCE: "食安员 + 库管/验收员",
    CHECKLIST_PLATFORM_DUAL: "食安员 + 平台资料管理员",
    CHECKLIST_PREP_KNIFE: "厨师长 + 切配负责人",
    CHECKLIST_MEAL: "陪餐负责人/校领导 + 食安员",
}

_DEADLINES: dict[str, str] = {
    CHECKLIST_ACCEPTANCE: "当日 10:00 前",
    CHECKLIST_PLATFORM_DUAL: "当日 14:00 前",
    CHECKLIST_PREP_KNIFE: "开餐前",
    CHECKLIST_MEAL: "当餐结束后 1 小时内",
}

_NEGATIVE_WORDS = ("未", "没有", "无", "缺", "不全", "异常", "不可用", "故障", "离线", "停用")
_DEVICE_BAD_WORDS = ("不可用", "故障", "离线", "异常", "损坏", "坏", "停用")

# 指纹 -> 当前进程内的 Key；lru_cache 的 key 只放指纹，不放明文 Key。
_KEY_BY_FP: dict[str, str] = {}


def _match_category(text: str) -> str | None:
    """根据关键词把一条事项归入四个板块之一。"""

    clean = (text or "").strip()
    if not clean:
        return None
    scores: dict[str, int] = {}
    for category, keywords in _CATEGORY_KEYWORDS.items():
        scores[category] = sum(1 for keyword in keywords if keyword in clean)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None


def _key_fingerprint(api_key: str) -> str:
    """返回 Key 的短指纹，用于缓存 key。"""

    return hashlib.sha256((api_key or "").encode("utf-8")).hexdigest()[:12]


@lru_cache(maxsize=256)
def _kb_category_cached(text: str, key_fp: str) -> tuple[str, str] | None:
    """用知识库片段兜底分类，返回 (板块, 来源)；异常时返回 None。"""

    api_key = _KEY_BY_FP.get(key_fp, "")
    if not api_key:
        return None
    try:
        hits = search(query=text, k=RAG_TOP_K, api_key=api_key)
    except Exception as exc:  # noqa: BLE001 - 检索失败退回规则结果
        logger.warning(
            "清单知识检索失败：%s，query=%s，命中=%s",
            type(exc).__name__,
            text[:60],
            0,
        )
        return None
    for item in hits:
        content = str(item.get("content") or "")
        for category in CHECKLIST_CATEGORIES:
            if category in content:
                source = str(item.get("source") or "未知来源")
                return category, source
    return None


def _classify_items(
    items: list[str],
    api_key: str,
    kb_matched: list[dict[str, str]],
) -> dict[str, list[str]]:
    """把事项归入四个板块；规则未命中时用 KB 兜底并记录来源。"""

    grouped: dict[str, list[str]] = {category: [] for category in CHECKLIST_CATEGORIES}
    key_fp = _key_fingerprint(api_key)
    if api_key:
        _KEY_BY_FP[key_fp] = api_key

    for item in items:
        category = _match_category(item)
        if category is None and api_key:
            hit = _kb_category_cached(item, key_fp)
            if hit is not None:
                category, source = hit
                kb_matched.append({"item": item, "category": category, "source": source})
        if category in grouped:
            grouped[category].append(item)
    return grouped


def _has_negative(text: str) -> bool:
    """粗略判断文本是否表达未完成或异常。"""

    return any(word in (text or "") for word in _NEGATIVE_WORDS)


def _items_for_category(
    category: str,
    items: list[str],
) -> list[str]:
    """取属于指定板块的事项原文。"""

    return [item for item in items if _match_category(item) == category]


def _status_for_category(
    abnormal: list[str],
    undone: list[str],
    done: list[str],
) -> str:
    """按异常 > 未完成 > 已完成 > 未填报复确定状态。"""

    if abnormal:
        return ChecklistStatus.ABNORMAL.value
    if undone:
        return ChecklistStatus.NOT_DONE.value
    if done:
        return ChecklistStatus.DONE.value
    return ChecklistStatus.UNFILLED.value


@tool(TOOL_CHECKLIST, args_schema=ChecklistInput)
def daily_checklist_reminder(
    date: str,
    done_items: list[str] | str | None = None,
    undone_items: list[str] | str | None = None,
    abnormal_items: list[str] | str | None = None,
    board_knife_usage: str | None = None,
    device_status: dict[str, str] | None = None,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """生成每日四项食安工作清单、缺口、待办和联动建议。

    何时调用：
    - 用户问“今天该做什么/还缺什么/哪些还没做/今天清单”；
    - 用户提供已完成、未完成、异常事项，希望整理成清单。

    何时不调用：
    - 用户直接要求生成正式台账（应调用 generate_ledger_entry）；
    - 用户描述单一异常并要求处置（应建议 create_abnormal_closure）；
    - 没有任何日期或事项信息，无法形成当日清单时，先补问日期。

    规则：
    - 固定覆盖验收与全流程监督、平台资料与双人双检双人双锁、
      切配清洗与刀具菜板、陪餐拍照与评价表；
    - status 只能是 done/not_done/abnormal/unfilled；
    - 设备不可用标“转人工核查”，不默认跳过，也不自动认定违规；
    - 所有输出只是提醒和待办建议，不替代现场判断。

    Returns:
        成功：{"ok": True, "date", "checklist", "gaps", "todos",
              "link_suggestions", "note"}
        失败：{"ok": False, "error": "..."}
    """

    try:
        api_key = api_key_from_config(config)
        clean_date = (date or "").strip()
        if not clean_date:
            return {"ok": False, "error": "date 不能为空，请提供清单日期。"}

        def ensure_list(value: list[str] | str | None) -> list[str]:
            if value is None:
                return []
            if isinstance(value, str):
                text = value.replace("、", ",").replace("，", ",").replace("\n", ",")
                return [item.strip() for item in text.split(",") if item.strip()]
            return [str(item).strip() for item in value if str(item).strip()]

        done = ensure_list(done_items)
        undone = ensure_list(undone_items)
        abnormal = ensure_list(abnormal_items)

        if board_knife_usage:
            if _has_negative(board_knife_usage):
                abnormal.append(f"刀具菜板：{board_knife_usage.strip()}")
            else:
                done.append(f"刀具菜板：{board_knife_usage.strip()}")

        checklist: list[dict[str, str]] = []
        gaps: list[str] = []
        todos: list[dict[str, str]] = []
        kb_matched: list[dict[str, str]] = []
        grouped_abnormal = _classify_items(abnormal, api_key, kb_matched)
        grouped_undone = _classify_items(undone, api_key, kb_matched)
        grouped_done = _classify_items(done, api_key, kb_matched)

        for category in CHECKLIST_CATEGORIES:
            category_abnormal = grouped_abnormal.get(category, [])
            category_undone = grouped_undone.get(category, [])
            category_done = grouped_done.get(category, [])
            status = _status_for_category(category_abnormal, category_undone, category_done)

            evidence_parts = category_abnormal or category_undone or category_done
            evidence = "；".join(evidence_parts) if evidence_parts else "未提供信息"
            note = ""
            if status == ChecklistStatus.UNFILLED.value:
                note = "未填报，需现场确认后补记，不能默认视为完成。"
            elif status == ChecklistStatus.ABNORMAL.value:
                note = "存在异常线索，建议转异常处置并人工复核。"
            elif status == ChecklistStatus.NOT_DONE.value:
                note = "尚未完成，请按待办时限处理。"

            checklist.append(
                {
                    "category": category,
                    "status": status,
                    "evidence": evidence,
                    "note": note,
                }
            )

            if status != ChecklistStatus.DONE.value:
                label = {
                    ChecklistStatus.ABNORMAL.value: "异常",
                    ChecklistStatus.NOT_DONE.value: "未完成",
                    ChecklistStatus.UNFILLED.value: "未填报",
                }[status]
                gaps.append(f"{label}：{category}（{evidence}）")
                todos.append(
                    {
                        "item": f"处理{category}：{evidence}",
                        "owner_hint": _OWNER_HINTS[category],
                        "deadline": "立即"
                        if status == ChecklistStatus.ABNORMAL.value
                        else _DEADLINES[category],
                    }
                )

        device_gaps: list[str] = []
        if device_status:
            for device, state in device_status.items():
                state_text = str(state or "").strip()
                if any(word in state_text for word in _DEVICE_BAD_WORDS):
                    device_gaps.append(f"设备不可用：{device}（{state_text}），转人工核查")
                    todos.append(
                        {
                            "item": f"转人工核查设备：{device}（{state_text}）",
                            "owner_hint": "设备管理员 + 食安员",
                            "deadline": "立即",
                        }
                    )
        gaps.extend(device_gaps)

        link_suggestions: list[str] = []
        combined_undone = " ".join(undone + abnormal)
        if any(
            item["status"] in {ChecklistStatus.ABNORMAL.value, ChecklistStatus.NOT_DONE.value}
            for item in checklist
        ):
            if "留样" in combined_undone:
                link_suggestions.append(
                    f"留样未完成或异常 → 建议调用 {TOOL_LEDGER} 生成留样台账草稿。"
                )
            if any(word in combined_undone for word in ("温度", "票证", "验收")):
                link_suggestions.append(f"如需判断验菜合规性 → 建议调用 {TOOL_COMPLIANCE}。")
            if any(item["status"] == ChecklistStatus.ABNORMAL.value for item in checklist):
                link_suggestions.append(f"存在异常线索 → 建议调用 {TOOL_ABNORMAL} 做闭环草稿。")
            if any(
                item["category"] == CHECKLIST_PLATFORM_DUAL
                and item["status"] != ChecklistStatus.DONE.value
                for item in checklist
            ):
                link_suggestions.append(
                    f"平台资料或双人双锁待补 → 建议调用 {TOOL_LEDGER} 生成台账草稿。"
                )
            if any(
                item["category"] == CHECKLIST_MEAL and item["status"] != ChecklistStatus.DONE.value
                for item in checklist
            ):
                link_suggestions.append(
                    f"陪餐照片或评价表未完成 → 建议调用 {TOOL_WATERMARK} 生成打卡图。"
                )
        if not link_suggestions:
            if device_gaps:
                link_suggestions.append(
                    "设备不可用已转人工核查，请同步记录设备状态和替代核查方式。"
                )
            else:
                link_suggestions.append("四项均已记录或暂无缺口，本轮无需联动工具。")

        # 状态兜底：所有值必须来自 constants.py。
        for item in checklist:
            if item["status"] not in CHECKLIST_STATUS_VALUES:
                item["status"] = ChecklistStatus.UNFILLED.value

        note = (
            "本清单仅作流程提醒，不自动认定违规；未填报不等于未执行，设备不可用已列为转人工核查。"
        )
        result = {
            "ok": True,
            "date": clean_date,
            "checklist": checklist,
            "kb_matched": kb_matched,
            "gaps": gaps,
            "todos": todos,
            "link_suggestions": link_suggestions,
            "note": note,
        }
        record_id = safe_save_record(
            kind=RECORD_KIND_CHECKLIST,
            title=f"{clean_date} 每日清单",
            payload=result,
        )
        result["record_id"] = record_id or 0
        if not record_id:
            result["note"] = f"{result['note'].rstrip()} 草稿已生成，但历史留痕未写入。"
        return result
    except Exception as exc:  # noqa: BLE001 - 工具边界必须返回结构化错误
        logger.exception("每日清单工具执行失败")
        return {"ok": False, "error": f"每日清单工具执行失败：{exc}"}
