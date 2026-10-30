"""后勤全域台账查询工具（只读）。

本文件职责：
- 让助手能回答“库存还剩多少 / 三号楼有哪些设备 / 本周巡检发现了什么 /
  维修单还有几张没处理”等基于本地 SQLite 的问题；
- 统一输出结构化记录与可直接引用的摘要文本，避免模型凭空编造台账数据；
- 覆盖维修、资产、库存（含库存预警）、巡检、供应商、人员、反馈与总览。

依赖：dawndine.enums、dawndine.schemas、dawndine.db、langchain-core。
被调用：dawndine.agent.graph（经 agent/tools/__init__.py）。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from dawndine.db import (
    list_assets,
    list_feedback,
    list_inspections,
    list_inventory,
    list_low_stock,
    list_maintenance,
    list_staff,
    list_suppliers,
    logistics_overview,
)
from dawndine.enums import LOGISTICS_DATA_KINDS, TOOL_LOGISTICS_QUERY
from dawndine.schemas import LogisticsQueryInput

logger = logging.getLogger(__name__)

_KIND_ALIASES: tuple[tuple[str, str], ...] = (
    ("库存预警", "low_stock"),
    ("低库存", "low_stock"),
    ("补货", "low_stock"),
    ("概览", "overview"),
    ("总览", "overview"),
    ("全部", "overview"),
    ("统计", "overview"),
    ("报修", "maintenance"),
    ("维修", "maintenance"),
    ("工单", "maintenance"),
    ("设备", "asset"),
    ("资产", "asset"),
    ("库存", "inventory"),
    ("物资", "inventory"),
    ("巡检", "inspection"),
    ("检查记录", "inspection"),
    ("供应商", "supplier"),
    ("供货商", "supplier"),
    ("人员", "staff"),
    ("员工", "staff"),
    ("健康证", "staff"),
    ("反馈", "feedback"),
    ("投诉", "feedback"),
    ("评价", "feedback"),
)

_KIND_LABELS: dict[str, str] = {
    "overview": "后勤总览",
    "maintenance": "维修记录",
    "asset": "资产设备",
    "inventory": "物资库存",
    "low_stock": "库存预警",
    "inspection": "巡检记录",
    "supplier": "供应商档案",
    "staff": "后勤人员",
    "feedback": "服务反馈",
}


def _resolve_kind(raw: str) -> str:
    """把自然语言类型归一为内部键；无法识别时返回 overview。"""

    text = (raw or "").strip()
    for alias, key in _KIND_ALIASES:
        if alias in text:
            return key
    return "overview"


def _maintenance_lines(rows: list[dict[str, Any]], limit: int) -> list[str]:
    """生成维修记录的可读摘要行。"""

    lines: list[str] = []
    for row in rows[:limit]:
        lines.append(
            f"- #{row['id']} {row['location']}｜{row['issue']}｜"
            f"{row['status']}｜报修 {row['report_date']}｜{row['reporter']}"
        )
    return lines


def _asset_lines(rows: list[dict[str, Any]], limit: int) -> list[str]:
    """生成资产设备的可读摘要行。"""

    lines: list[str] = []
    for row in rows[:limit]:
        serial = row["asset_no"] or "无编号"
        place = row["location"] or "地点待补"
        lines.append(
            f"- {row['name']}（{serial}）｜{row['category'] or '未分类'}｜"
            f"{place}｜{row['status']}｜责任人 {row['owner'] or '待补'}"
        )
    return lines


def _inventory_lines(rows: list[dict[str, Any]], limit: int) -> list[str]:
    """生成库存摘要行，并对低于补货线的物资加“需补货”标记。"""

    lines: list[str] = []
    for row in rows[:limit]:
        unit = row["unit"] or "件"
        warning = ""
        if row["reorder_level"] > 0 and row["quantity"] <= row["reorder_level"]:
            warning = f"｜需补货（补货线 {row['reorder_level']:g}）"
        lines.append(
            f"- {row['item']}：{row['quantity']:g}{unit}｜"
            f"{row['location'] or '库房待补'}｜{row['supplier'] or '供应商待补'}{warning}"
        )
    return lines


def _inspection_lines(rows: list[dict[str, Any]], limit: int) -> list[str]:
    """生成巡检记录的可读摘要行。"""

    lines: list[str] = []
    for row in rows[:limit]:
        issue = f"｜问题：{row['issue']}" if row["issue"] else ""
        lines.append(
            f"- {row['inspect_date']} {row['area']}·{row['item']}｜"
            f"{row['result']}｜{row['status']}｜巡检人 {row['inspector']}{issue}"
        )
    return lines


def _supplier_lines(rows: list[dict[str, Any]], limit: int) -> list[str]:
    """生成供应商档案摘要行。"""

    lines: list[str] = []
    for row in rows[:limit]:
        lines.append(
            f"- {row['name']}｜{row['category'] or '未分类'}｜"
            f"联系人 {row['contact'] or '待补'}｜证照有效期 {row['license_until'] or '待补'}"
        )
    return lines


def _staff_lines(rows: list[dict[str, Any]], limit: int) -> list[str]:
    """生成后勤人员摘要行。"""

    lines: list[str] = []
    for row in rows[:limit]:
        lines.append(
            f"- {row['name']}｜{row['department'] or '部门待补'}·"
            f"{row['role'] or '岗位待补'}｜健康证到期 {row['health_cert_until'] or '待补'}"
        )
    return lines


def _feedback_lines(rows: list[dict[str, Any]], limit: int) -> list[str]:
    """生成服务反馈摘要行。"""

    lines: list[str] = []
    for row in rows[:limit]:
        rating = f"｜评分 {row['rating']}/5" if row["rating"] else ""
        lines.append(
            f"- #{row['id']} {row['category'] or '未分类'}｜{row['status']}{rating}｜"
            f"{row['content']}"
        )
    return lines


@tool(TOOL_LOGISTICS_QUERY, args_schema=LogisticsQueryInput)
def query_logistics_records(
    kind: str,
    keyword: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """只读查询本地后勤数据库：维修、资产、库存、巡检、供应商、人员、反馈与总览。

    何时调用：
    - 用户问“还有多少维修单没处理/某地点的报修记录”；
    - 用户问“某设备在不在台账/资产状态/保修到期”；
    - 用户问“某物资还剩多少/哪些需要补货”；
    - 用户问“最近巡检发现了什么/整改是否闭环”；
    - 用户问“供应商档案/人员健康证/师生反馈”；
    - 用户要求对后勤数据做汇总、盘点或复盘。

    何时不调用：
    - 用户只是问制度、标准、流程（应检索知识库）；
    - 用户要求新增/修改/删除数据（本工具只读，应到对应页面或后续写接口）；
    - 用户没有给出数据类型且问题与本地台账无关。

    说明：
    - 数据来自本机 SQLite（data/dawndine.db），空库时如实说“暂无记录”；
    - 不得把摘要中的示例当成真实数据，也不得编造记录 ID、数量与日期；
    - 涉及安全应急（漏电、燃气、火情）时先给处置建议，再查台账。

    Returns:
        成功：{"ok": True, "kind": ..., "label": ..., "total": ..., "summary": ...,
              "records": [...], "note": ...}
        失败：{"ok": False, "error": "..."}
    """

    resolved = _resolve_kind(kind)
    clean_keyword = (keyword or "").strip()
    safe_limit = max(1, min(int(limit), 200))

    try:
        if resolved == "overview":
            counts = logistics_overview()
            summary_lines = [
                f"- 维修 {counts['maintenance']} 条｜资产 {counts['assets']} 条｜"
                f"库存 {counts['inventory']} 种｜巡检 {counts['inspections']} 条",
                f"- 供应商 {counts['suppliers']} 家｜人员 {counts['staff']} 人｜"
                f"反馈 {counts['feedback']} 条｜日程 {counts['schedules']} 条",
            ]
            low_stock_count = len(list_low_stock())
            if low_stock_count:
                summary_lines.append(f"- 库存预警：{low_stock_count} 种物资低于补货线")
            return {
                "ok": True,
                "kind": resolved,
                "label": _KIND_LABELS[resolved],
                "total": sum(counts.values()),
                "counts": counts,
                "summary": "\n".join(summary_lines),
                "records": [],
                "note": "以上为本地数据库实时计数；没有记录的表按 0 处理。",
            }

        if resolved == "maintenance":
            rows = list_maintenance()
            if clean_keyword:
                rows = [
                    row
                    for row in rows
                    if clean_keyword.casefold()
                    in f"{row['location']}{row['issue']}{row['reporter']}{row['status']}".casefold()
                ]
            pending = sum(1 for row in rows if row["status"] == "待处理")
            summary_lines = [f"- 维修记录共 {len(rows)} 条，其中待处理 {pending} 条"]
            summary_lines.extend(_maintenance_lines(rows, safe_limit))
        elif resolved == "asset":
            rows = list_assets(keyword=clean_keyword, limit=safe_limit)
            summary_lines = [f"- 资产设备共 {len(rows)} 条（最多显示 {safe_limit} 条）"]
            summary_lines.extend(_asset_lines(rows, safe_limit))
        elif resolved == "inventory":
            rows = list_inventory(keyword=clean_keyword, limit=safe_limit)
            summary_lines = [f"- 物资库存共 {len(rows)} 种（最多显示 {safe_limit} 种）"]
            summary_lines.extend(_inventory_lines(rows, safe_limit))
        elif resolved == "low_stock":
            rows = list_low_stock()
            if clean_keyword:
                rows = [
                    row
                    for row in rows
                    if clean_keyword.casefold()
                    in f"{row['item']}{row['category']}{row['supplier']}".casefold()
                ]
            summary_lines = [f"- 低于补货线的物资共 {len(rows)} 种"]
            summary_lines.extend(_inventory_lines(rows, safe_limit))
        elif resolved == "inspection":
            rows = list_inspections(keyword=clean_keyword, limit=safe_limit)
            abnormal = sum(1 for row in rows if row["result"] == "异常")
            summary_lines = [f"- 巡检记录共 {len(rows)} 条，其中异常 {abnormal} 条"]
            summary_lines.extend(_inspection_lines(rows, safe_limit))
        elif resolved == "supplier":
            rows = list_suppliers(keyword=clean_keyword, limit=safe_limit)
            summary_lines = [f"- 供应商档案共 {len(rows)} 家"]
            summary_lines.extend(_supplier_lines(rows, safe_limit))
        elif resolved == "staff":
            rows = list_staff(keyword=clean_keyword, limit=safe_limit)
            summary_lines = [f"- 后勤人员档案共 {len(rows)} 人"]
            summary_lines.extend(_staff_lines(rows, safe_limit))
        else:  # feedback
            rows = list_feedback(keyword=clean_keyword, limit=safe_limit)
            pending = sum(1 for row in rows if row["status"] == "待处理")
            summary_lines = [f"- 服务反馈共 {len(rows)} 条，其中待处理 {pending} 条"]
            summary_lines.extend(_feedback_lines(rows, safe_limit))

        return {
            "ok": True,
            "kind": resolved,
            "label": _KIND_LABELS[resolved],
            "total": len(rows),
            "summary": "\n".join(summary_lines),
            "records": rows[:safe_limit],
            "note": (
                "数据来自本地 SQLite，只读查询；"
                f"当前支持：{'、'.join(LOGISTICS_DATA_KINDS)}与库存预警、总览。"
            ),
        }
    except Exception as exc:  # noqa: BLE001 - 工具边界必须返回结构化错误
        logger.exception("后勤台账查询失败：kind=%s", kind)
        return {"ok": False, "error": f"后勤台账查询失败：{exc}"}
