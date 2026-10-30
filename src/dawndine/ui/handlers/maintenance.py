"""后勤维修回调。"""

from __future__ import annotations

import logging
from typing import Any

import gradio as gr

from dawndine.db import (
    count_maintenance_by_location,
    create_maintenance,
    delete_all_maintenance,
    delete_maintenance_records,
    list_maintenance,
    list_maintenance_rows,
    logistics_overview,
)
from dawndine.llm import resolve_api_key
from dawndine.services.maintenance import export_maintenance_workbook
from dawndine.services.vision import parse_maintenance_image
from dawndine.ui.handlers.common import _key_configured, _persist_upload, _short_error
from dawndine.ui.handlers.schedule import _coerce_schedule_id, _coerce_schedule_ids

logger = logging.getLogger(__name__)

def _maintenance_rows() -> list[list[Any]]:
    """读取全部维修记录（地点 A-Z 排序），异常时返回空表。"""

    try:
        return list_maintenance_rows()
    except Exception:  # noqa: BLE001 - UI 不应因数据库异常整体崩溃
        logger.exception("读取维修记录失败")
        return []


def _maintenance_stats_rows() -> list[list[Any]]:
    """读取各地维修数量统计，异常时返回空表。"""

    try:
        return count_maintenance_by_location()
    except Exception:  # noqa: BLE001
        logger.exception("统计维修记录失败")
        return []


def _maintenance_overview_md(
    rows: list[list[Any]] | None = None,
    stats: list[list[Any]] | None = None,
) -> str:
    """维修总量概览：记录数、覆盖地点数与待处理数。"""

    records = _maintenance_rows() if rows is None else rows
    places = _maintenance_stats_rows() if stats is None else stats
    total = len(records)
    if not total:
        return "📊 暂无维修记录：可上传维修单图片解析，或在下方手动补录。"
    pending = sum(1 for row in records if len(row) > 5 and str(row[5]) == "待处理")
    return f"📊 共 **{total}** 条维修记录，覆盖 **{len(places)}** 个地点，待处理 **{pending}** 条。"


def _maintenance_choices() -> list[tuple[str, int]]:
    """把维修明细转换为勾选选项：显示描述，值仍然是维修记录编号。"""

    choices: list[tuple[str, int]] = []
    for row in _maintenance_rows():
        try:
            maintenance_id = int(row[0])
        except (TypeError, ValueError):
            continue
        location = str(row[1] or "待补")
        issue = str(row[2] or "")[:24]
        status = str(row[5] or "")
        label = f"编号 {maintenance_id} · {location} · {issue} · {status}"
        choices.append((label.replace("  ", " ").strip(), maintenance_id))
    return choices


def _maintenance_pick_update(selected: Any = None) -> Any:
    """构造维修勾选列表更新；默认清空选择，避免误删。"""

    choices = _maintenance_choices()
    valid_ids = {item[1] for item in choices}
    wanted = selected if isinstance(selected, (list, tuple, set)) else [selected]
    values = [
        int(item)
        for item in wanted
        if _coerce_schedule_id(item) is not None and int(item) in valid_ids
    ]
    # CheckboxGroup 的 value 必须是列表；空选择用 [] 而不是 None。
    return gr.update(choices=choices, value=values)


def _coerce_maintenance_ids(value: Any) -> list[int]:
    """把多选勾选值统一成正整数编号列表（去重、保持顺序）。"""

    return _coerce_schedule_ids(value)


def _maintenance_selection_summary(selected: Any = None) -> str:
    """把已勾选的维修记录整理成“待删除清单”，供删除框直接展示。"""

    ids = _coerce_maintenance_ids(selected)
    if not ids:
        return (
            "🗑️ **待删除清单（0 条）**\n\n"
            "尚未勾选：点击任意一条维修记录即可勾选（整行均可点击），"
            "也可以按住鼠标从第一条拖到最后一条框选多行。"
        )
    rows_by_id: dict[int, list[Any]] = {}
    for row in _maintenance_rows():
        try:
            rows_by_id[int(row[0])] = row
        except (TypeError, ValueError, IndexError):
            continue
    lines = [f"🗑️ **待删除清单（{len(ids)} 条）**"]
    for maintenance_id in ids:
        row = rows_by_id.get(maintenance_id)
        if row is None:
            lines.append(f"- **编号 {maintenance_id}** · 当前列表中不可见")
            continue
        location = str(row[1] or "待补")
        issue = str(row[2] or "").strip()
        status = str(row[5] or "").strip()
        lines.append(f"- **编号 {maintenance_id}** · {location} · {issue} · {status}")
    return "\n".join(lines)


def logistics_overview_md() -> str:
    """返回设置弹窗里的后勤数据库实时记录数。"""

    try:
        counts = logistics_overview()
    except Exception as exc:  # noqa: BLE001
        logger.exception("读取后勤数据库概览失败")
        return f"数据库概览读取失败：{_short_error(exc)}"
    return (
        f"维修 **{counts['maintenance']}** 条｜资产 **{counts['assets']}** 条｜"
        f"库存 **{counts['inventory']}** 种｜巡检 **{counts['inspections']}** 条  \n"
        f"供应商 **{counts['suppliers']}** 家｜人员 **{counts['staff']}** 人｜"
        f"反馈 **{counts['feedback']}** 条｜日程 **{counts['schedules']}** 条"
    )


def refresh_maintenance_page() -> tuple[Any, ...]:
    """刷新维修明细、各地统计、总量概览与删除清单。"""

    rows = _maintenance_rows()
    stats = _maintenance_stats_rows()
    return (
        rows,
        stats,
        _maintenance_overview_md(rows, stats),
        _maintenance_pick_update(),
        _maintenance_selection_summary([]),
    )


def select_all_maintenance() -> tuple[Any, str]:
    """一键勾选当前全部维修记录。"""

    ids = [value for _, value in _maintenance_choices()]
    if not ids:
        return gr.skip(), "⚠️ 当前没有可勾选的维修记录。"
    return gr.update(value=ids), _maintenance_selection_summary(ids)


def clear_maintenance_selection() -> tuple[Any, str]:
    """取消全部勾选，并清空待删除清单。"""

    return gr.update(value=[]), _maintenance_selection_summary([])


def on_maintenance_selection(selected: Any) -> str:
    """勾选变化：同步刷新“待删除清单”。"""

    return _maintenance_selection_summary(selected)


def add_manual_maintenance(
    location: str,
    issue: str,
    reporter: str,
    report_date: str,
) -> tuple[Any, ...]:
    """手动新增一条维修记录（无需图片或 Key）。"""

    if not (issue or "").strip():
        return (
            "⚠️ 请填写故障描述。",
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
        )
    try:
        record = create_maintenance(
            location=location,
            issue=issue,
            reporter=reporter,
            report_date=report_date,
        )
        rows = _maintenance_rows()
        stats = _maintenance_stats_rows()
        return (
            f"✅ 已添加维修单（编号 {record['id']}）："
            f"{record['location']} · {record['issue']}"
            f"（报修人 {record['reporter']}，报修日期 {record['report_date']}，"
            f"状态 {record['status']}）",
            rows,
            stats,
            _maintenance_overview_md(rows, stats),
            _maintenance_pick_update(),
            _maintenance_selection_summary([]),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("手动添加维修单失败")
        return (
            f"⚠️ 添加失败：{_short_error(exc)}",
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
        )


def import_maintenance_from_image(
    image_path: str | None,
    ui_api_key: str,
) -> tuple[Any, ...]:
    """调用 Qwen-VL 解析维修单图片并写入一条维修记录。"""

    if not image_path:
        return (
            "⚠️ 请先上传维修单图片。",
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
        )
    if not _key_configured(ui_api_key):
        return (
            "⚠️ 图片解析需要 DashScope Key，请先在页脚“设置”中填写。",
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
        )
    try:
        saved = _persist_upload(image_path, "maintenance")
        parsed = parse_maintenance_image(str(saved), api_key=resolve_api_key(ui_api_key))
        record = create_maintenance(
            location=parsed["location"],
            issue=parsed["issue"],
            reporter=parsed["reporter"],
            report_date=parsed["report_date"],
        )
        rows = _maintenance_rows()
        stats = _maintenance_stats_rows()
        status = (
            f"✅ 已录入维修单：{record['location']} · {record['issue']}"
            f"（报修人 {record['reporter']}，报修日期 {record['report_date']}，"
            f"状态 {record['status']}）"
        )
        return (
            status,
            rows,
            stats,
            _maintenance_overview_md(rows, stats),
            _maintenance_pick_update(),
            _maintenance_selection_summary([]),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("维修单图片解析失败")
        return (
            f"⚠️ 解析失败：{_short_error(exc)}",
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
        )


def delete_selected_maintenance(maintenance_ids: Any) -> tuple[Any, ...]:
    """删除勾选列表中的一条或多条维修记录，并同步刷新表格与统计。"""

    parsed_ids = _coerce_maintenance_ids(maintenance_ids)
    if not parsed_ids:
        return (
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
            "⚠️ 请先勾选要删除的维修记录（点击整行或拖动框选）。",
        )
    try:
        deleted = delete_maintenance_records(parsed_ids)
        rows = _maintenance_rows()
        stats = _maintenance_stats_rows()
        if not deleted:
            return (
                rows,
                stats,
                _maintenance_overview_md(rows, stats),
                _maintenance_pick_update(),
                _maintenance_selection_summary([]),
                f"⚠️ 未找到所选维修记录（编号 {', '.join(map(str, parsed_ids))}），可能已被删除。",
            )
        joined = "、".join(f"编号 {item}" for item in parsed_ids)
        message = f"✅ 已删除 {deleted} 条维修记录：{joined}。"
        if deleted < len(parsed_ids):
            message += " 部分编号已不存在。"
        return (
            rows,
            stats,
            _maintenance_overview_md(rows, stats),
            _maintenance_pick_update(),
            _maintenance_selection_summary([]),
            message,
        )
    except Exception as exc:  # noqa: BLE001 - UI 操作不能导致页面崩溃
        logger.exception("删除维修记录失败")
        return (
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
            f"⚠️ 删除失败：{_short_error(exc)}",
        )


def clear_all_maintenance(confirmed: bool) -> tuple[Any, ...]:
    """清空全部维修记录；必须勾选确认框。"""

    if not confirmed:
        return (
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
            "⚠️ 请先勾选“我确认清空全部维修记录”。",
        )
    try:
        deleted = delete_all_maintenance()
        return (
            [],
            [],
            _maintenance_overview_md([], []),
            _maintenance_pick_update(),
            _maintenance_selection_summary([]),
            f"✅ 已清空 {deleted} 条维修记录。",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("清空维修记录失败")
        return (
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
            f"⚠️ 清空失败：{_short_error(exc)}",
        )


def export_maintenance_report() -> tuple[Any, str]:
    """导出维修总表：一个 Excel 文件同时包含明细与各地维修统计。"""

    records = list_maintenance()
    if not records:
        return gr.skip(), "⚠️ 当前没有维修记录可导出。"
    try:
        path = export_maintenance_workbook(records)
        places = count_maintenance_by_location()
        return (
            str(path),
            f"✅ 已导出维修总表：{path.name}"
            f"（明细 {len(records)} 条 · 统计 {len(places)} 个地点，"
            "含“维修明细”与“各地维修统计”两个工作表）",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("导出维修总表失败")
        return gr.skip(), f"⚠️ 导出失败：{_short_error(exc)}"
