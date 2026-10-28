"""台账生成工具。

本文件职责：
- 根据台账类型、日期、人员、过程信息生成结构化 ledger_items；
- 校验实时/补录模式，补录必须填写原因，并尽量校验事件时间；
- 输出可复制文本与留痕提示；
- 成功后向 SQLite 日程表写入“生成XX台账”摘要。

依赖：constants.py、schemas.py、modules/db.py、langchain-core。
被调用：graph.py（经 tools/__init__.py）、测试脚本。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from langchain_core.tools import tool

from constants import (
    DATETIME_FORMAT,
    LEDGER_STATUS_VALUES,
    SCHEDULE_SOURCE_LEDGER,
    TOOL_LEDGER,
    LedgerStatus,
    LedgerType,
    RecordMode,
)
from modules.db import safe_create_schedule, split_datetime
from schemas import LedgerInput

logger = logging.getLogger(__name__)

PENDING_VALUE = "待补"

_TYPE_KEYWORDS: dict[LedgerType, list[tuple[str, tuple[str, ...]]]] = {
    LedgerType.DAILY_CONTROL: [
        ("晨检情况", ("晨检", "健康")),
        ("原料验收", ("验收", "票证", "进货", "温度")),
        ("加工过程", ("加工", "切配", "烹饪", "消毒")),
        ("留样管理", ("留样",)),
        ("陪餐情况", ("陪餐",)),
        ("平台资料", ("平台", "上传")),
    ],
    LedgerType.WEEKLY_INSPECTION: [
        ("排查范围", ("范围", "区域", "环节")),
        ("发现问题", ("问题", "发现", "隐患")),
        ("整改情况", ("整改", "处置", "闭环")),
        ("复核结论", ("复核", "复查", "验证")),
    ],
    LedgerType.MONTHLY_SCHEDULE: [
        ("会议时间", ("会议", "调度", "时间")),
        ("参加人员", ("参加", "人员", "到会")),
        ("调度事项", ("调度", "议定", "部署")),
        ("整改责任", ("责任", "整改", "落实")),
    ],
    LedgerType.MORNING_CHECK: [
        ("人员健康观察", ("健康", "发热", "腹泻", "咳嗽")),
        ("手部伤口", ("伤口", "破损", "手套", "创可贴")),
        ("工作服与帽子", ("工作服", "帽子", "口罩")),
        ("晨检签字", ("签字", "签名", "晨检")),
    ],
    LedgerType.SAMPLE_RETENTION: [
        ("留样品种", ("品种", "菜品", "留样")),
        ("留样量", ("125g", "125克", "留样量", "克")),
        ("留样时间", ("时间", "餐次")),
        ("保存温度", ("温度", "冷藏", "0-4", "0—4")),
        ("保存时长", ("48", "小时", "时长")),
        ("销毁记录", ("销毁", "处置", "到期")),
    ],
    LedgerType.INGREDIENT_ACCEPTANCE: [
        ("供应商", ("供应商", "商家", "老张", "配送")),
        ("票证核验", ("票证", "检疫", "合格证", "送货单")),
        ("运输温度", ("温度", "℃", "冷链", "冷藏")),
        ("数量与包装", ("数量", "包装", "重量", "件数")),
        ("感官验收", ("感官", "颜色", "气味", "新鲜")),
        ("验收结论", ("合格", "拒收", "退货", "接收")),
    ],
    LedgerType.MEAL_ACCOMPANIMENT: [
        ("陪餐人员", ("陪餐", "校长", "老师", "家长")),
        ("餐次与地点", ("餐次", "午餐", "晚餐", "地点", "食堂")),
        ("餐食评价", ("评价", "口味", "分量", "满意")),
        ("问题与整改", ("问题", "整改", "反馈")),
    ],
    LedgerType.DUAL_LOCK: [
        ("第一责任人", ("第一", "责任人", "保管")),
        ("第二责任人", ("第二", "责任人", "保管")),
        ("双锁状态", ("双锁", "锁具", "上锁")),
        ("双人在场", ("双人", "同时", "在场")),
        ("出入库记录", ("出入库", "领用", "取用", "登记")),
    ],
}

_TRACE_HINTS: dict[LedgerType, list[str]] = {
    LedgerType.DAILY_CONTROL: ["晨检记录照片", "验收票证照片", "平台上传截图"],
    LedgerType.WEEKLY_INSPECTION: ["排查照片", "问题整改前后对比", "复核人签字"],
    LedgerType.MONTHLY_SCHEDULE: ["会议签到表", "会议记录", "整改责任清单"],
    LedgerType.MORNING_CHECK: ["晨检记录表", "异常人员处置记录", "负责人签字"],
    LedgerType.SAMPLE_RETENTION: ["留样标签照片", "留样柜照片", "销毁记录"],
    LedgerType.INGREDIENT_ACCEPTANCE: ["温度计读数照片", "送货单与检疫证明", "双人验收签字"],
    LedgerType.MEAL_ACCOMPANIMENT: ["陪餐水印照片", "陪餐评价表", "问题反馈截图"],
    LedgerType.DUAL_LOCK: ["双锁与钥匙保管照片", "双人签字记录", "出入库登记"],
}


def _parse_datetime(value: str) -> datetime | None:
    """解析常见日期时间格式。"""

    formats = (
        DATETIME_FORMAT,
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt)
        except (TypeError, ValueError):
            continue
    return None


def _normalize_persons(persons: list[str]) -> list[str]:
    """去重并清理人员姓名。"""

    seen: set[str] = set()
    result: list[str] = []
    for person in persons or []:
        name = str(person).strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _record_status(record_mode: RecordMode) -> str:
    """返回非缺项条目的状态。"""

    return (
        LedgerStatus.BACKFILL.value
        if record_mode is RecordMode.BACKFILL
        else LedgerStatus.REALTIME.value
    )


def _make_item(field: str, value: str, record_mode: RecordMode) -> dict[str, str]:
    """构造单个台账条目并统一状态。"""

    clean = (value or "").strip()
    if not clean or clean == PENDING_VALUE:
        return {"field": field, "value": PENDING_VALUE, "status": LedgerStatus.PENDING.value}
    return {"field": field, "value": clean, "status": _record_status(record_mode)}


def _mentions(text: str, keywords: tuple[str, ...]) -> bool:
    """判断文本是否出现任一关键词。"""

    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _build_readable_text(
    ledger_type: LedgerType,
    items: list[dict[str, str]],
    note: str,
) -> str:
    """把结构化台账转换为可复制的纯文本。"""

    lines = [f"【{ledger_type.value}台账草稿】"]
    for item in items:
        lines.append(f"- {item['field']}：{item['value']}（{item['status']}）")
    lines.append("")
    lines.append(f"说明：{note}")
    return "\n".join(lines)


@tool(TOOL_LEDGER, args_schema=LedgerInput)
def generate_ledger_entry(
    ledger_type: str,
    date_time: str,
    persons: list[str] | str | None = None,
    process_info: str = "",
    abnormal_and_action: str | None = None,
    dual_execution: str | None = None,
    record_mode: str = RecordMode.REALTIME.value,
    backfill_reason: str | None = None,
) -> dict[str, Any]:
    """生成日管控、周排查、月调度、晨检、留样、验菜、陪餐、双人双锁台账草稿。

    何时调用：
    - 用户要求生成任一台账（日管控/周排查/月调度/晨检/留样/验菜/陪餐/双人双锁）；
    - 异常处置完成后需要形成可复制上报的记录草稿；
    - 需要检查台账缺项或补录说明。

    何时不调用：
    - 仅询问台账制度依据，应使用 check_compliance_knowledge；
    - 没有台账类型或日期等基本信息，无法生成可执行草稿；
    - 要求直接代替责任人在正式平台提交（本工具只生成草稿）。

    规则：
    - backfill 必须提供 backfill_reason；事件时间晚于当前时间或明显无法校验时给出提示；
    - 缺项统一写“待补”，status=pending，不得伪装成已完成；
    - 输出仅为台账草稿，需填报人核对、签字并在正式平台提交。

    Returns:
        成功：{"ok": True, "ledger_type", "ledger_items", "readable_text",
              "note", "traces"}
        失败：{"ok": False, "error": "..."}
    """

    try:
        try:
            parsed_type = LedgerType(str(getattr(ledger_type, "value", ledger_type)))
        except ValueError as exc:
            raise ValueError(f"不支持的台账类型：{ledger_type}") from exc
        try:
            parsed_mode = RecordMode(str(getattr(record_mode, "value", record_mode)))
        except ValueError as exc:
            raise ValueError(f"不支持的记录模式：{record_mode}") from exc

        clean_datetime = (date_time or "").strip()
        if not clean_datetime:
            return {"ok": False, "error": "date_time 不能为空。"}

        notes: list[str] = []
        if parsed_mode is RecordMode.BACKFILL:
            if not (backfill_reason or "").strip():
                return {
                    "ok": False,
                    "error": "补录台账必须提供 backfill_reason，说明未实时记录的原因。",
                }
            event_dt = _parse_datetime(clean_datetime)
            if event_dt is None:
                notes.append("无法解析事件日期，补录时间先后关系需人工复核。")
            else:
                now = datetime.now()
                if event_dt.date() > now.date():
                    return {
                        "ok": False,
                        "error": "补录日期不能早于事件日期：事件时间晚于当前日期，请核对。",
                    }
                if event_dt > now:
                    return {
                        "ok": False,
                        "error": "事件时间晚于当前时间，无法判断为历史补录，请核对 date_time。",
                    }
                notes.append("已校验事件时间不晚于当前时间。")
        elif (backfill_reason or "").strip():
            notes.append("record_mode=realtime，但提供了补录原因；如为事后填写请改用 backfill。")

        clean_persons = _normalize_persons(
            persons if isinstance(persons, list) else [persons] if persons else []
        )
        person_text = "、".join(clean_persons) if clean_persons else PENDING_VALUE
        process_text = (process_info or "").strip()

        items: list[dict[str, str]] = [
            _make_item("台账类型", parsed_type.value, parsed_mode),
            _make_item("记录日期时间", clean_datetime, parsed_mode),
            _make_item("填报/相关人员", person_text, parsed_mode),
        ]

        combined_text = " ".join(
            part
            for part in (
                process_text,
                abnormal_and_action or "",
                dual_execution or "",
            )
            if part
        )

        if parsed_type is LedgerType.DUAL_LOCK and len(clean_persons) >= 2:
            items.append(_make_item("第一责任人", clean_persons[0], parsed_mode))
            items.append(_make_item("第二责任人", clean_persons[1], parsed_mode))

        for field, keywords in _TYPE_KEYWORDS[parsed_type]:
            if any(item["field"] == field for item in items):
                continue
            if _mentions(combined_text, keywords):
                items.append(_make_item(field, "已记录，详见过程记录", parsed_mode))
            else:
                items.append(
                    {
                        "field": field,
                        "value": PENDING_VALUE,
                        "status": LedgerStatus.PENDING.value,
                    }
                )

        items.append(_make_item("过程记录", process_text, parsed_mode))
        items.append(_make_item("异常及处置", abnormal_and_action or "", parsed_mode))

        if dual_execution or parsed_type is LedgerType.DUAL_LOCK:
            items.append(_make_item("双人执行/双人双锁", dual_execution or "", parsed_mode))

        if parsed_mode is RecordMode.BACKFILL:
            items.append(_make_item("补录原因", backfill_reason or "", parsed_mode))

        # 安全兜底：状态值必须来自 constants.py。
        for item in items:
            if item["status"] not in LEDGER_STATUS_VALUES:
                item["status"] = LedgerStatus.PENDING.value

        pending_count = sum(1 for item in items if item["status"] == LedgerStatus.PENDING.value)
        note = "本输出为台账草稿，需填报人核对、签字并在正式平台提交，不构成正式记录。"
        if pending_count:
            note += f" 当前有 {pending_count} 项待补，不得视为已完成。"
        if parsed_mode is RecordMode.BACKFILL:
            note += " 补录记录须保留原始照片或纸质记录索引。"
        if notes:
            note += " " + " ".join(notes)

        traces = ["现场照片（含时间水印）", "相关单据/票证照片", "填报人签字"]
        traces.extend(_TRACE_HINTS[parsed_type])
        if parsed_type is LedgerType.DUAL_LOCK:
            traces.append("双人双锁执行记录")
        # 去重并保持顺序。
        traces = list(dict.fromkeys(traces))

        schedule_id = 0
        schedule_date, schedule_time = split_datetime(clean_datetime)
        schedule = safe_create_schedule(
            date=schedule_date,
            time=schedule_time,
            content=f"生成{parsed_type.value}台账",
            source=SCHEDULE_SOURCE_LEDGER,
        )
        if schedule:
            schedule_id = int(schedule["id"])
            note += " 已同步到“我的日程”。"
        else:
            note += " 日程沉淀失败，但台账草稿已生成，可稍后手动补记。"

        return {
            "ok": True,
            "ledger_type": parsed_type.value,
            "ledger_items": items,
            "readable_text": _build_readable_text(parsed_type, items, note),
            "note": note,
            "traces": traces,
            "schedule_id": schedule_id,
        }
    except Exception as exc:  # noqa: BLE001 - 工具边界必须返回结构化错误
        logger.exception("台账工具执行失败")
        return {"ok": False, "error": f"台账工具执行失败：{exc}"}
