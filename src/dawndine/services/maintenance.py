"""后勤维修 Excel 导出。

本文件职责：
- 把 maintenance 表的记录转换为 pandas DataFrame（地点 A-Z 排序）；
- 生成“地点 / 维修数量”的各地维修统计；
- 用 openpyxl 把明细与统计合并导出到一个工作簿（两个工作表），文件名保持 ASCII。

依赖：dawndine.config、pandas、openpyxl。
被调用：app.py（后勤维修 → 导出总表）。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from dawndine.config import EXPORTS_DIR, MAINTENANCE_STATS_HEADERS, MAINTENANCE_TABLE_HEADERS

logger = logging.getLogger(__name__)

__all__ = [
    "DETAIL_COLUMNS",
    "DETAIL_SHEET",
    "SUMMARY_COLUMNS",
    "SUMMARY_SHEET",
    "build_detail_frame",
    "build_summary_frame",
    "export_maintenance_workbook",
]

DETAIL_COLUMNS: list[str] = list(MAINTENANCE_TABLE_HEADERS)
SUMMARY_COLUMNS: list[str] = list(MAINTENANCE_STATS_HEADERS)
DETAIL_SHEET = "维修明细"
SUMMARY_SHEET = "各地维修统计"

_FIELD_MAP: dict[str, str] = {
    "id": "编号",
    "location": "地点",
    "issue": "故障描述",
    "reporter": "报修人",
    "report_date": "报修日期",
    "status": "状态",
    "created_at": "录入时间",
}

_DETAIL_WIDTHS: tuple[int, ...] = (8, 22, 46, 12, 14, 10, 20)
_SUMMARY_WIDTHS: tuple[int, ...] = (26, 12)


def _location_sort_key(column: pd.Series) -> pd.Series:
    """地点排序键：英文忽略大小写，中文按字符升序。"""

    return column.astype(str).str.casefold()


def build_detail_frame(records: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """把维修记录转成明细表，地点 A-Z 排序；空数据保留表头。"""

    rows = [
        {label: record.get(field, "") for field, label in _FIELD_MAP.items()} for record in records
    ]
    frame = pd.DataFrame(rows, columns=DETAIL_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values("地点", key=_location_sort_key, kind="stable")
    return frame.reset_index(drop=True)


def build_summary_frame(records: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """按地点汇总维修数量，结果同样按地点 A-Z 排序；空数据保留表头。"""

    detail = build_detail_frame(records)
    if detail.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    counts = detail.groupby("地点", sort=False).size()
    summary = counts.reset_index(name="维修数量")
    return summary[SUMMARY_COLUMNS].reset_index(drop=True)


def _output_path(prefix: str) -> Path:
    """生成 exports/ 下的 ASCII 文件名，避免浏览器下载时中文被转码。"""

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return EXPORTS_DIR / f"{prefix}-{datetime.now():%Y%m%d-%H%M%S}.xlsx"


def _style_sheet(worksheet: Any, widths: Sequence[int]) -> None:
    """表头加粗、居中，并按列设置宽度、冻结首行，方便直接打印/筛选。"""

    header_font = Font(bold=True)
    for column_index, width in enumerate(widths, start=1):
        letter = get_column_letter(column_index)
        worksheet.column_dimensions[letter].width = width
        cell = worksheet[f"{letter}1"]
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    worksheet.freeze_panes = "A2"


def export_maintenance_workbook(records: Sequence[Mapping[str, Any]]) -> Path:
    """把维修明细与各地统计合并导出为一个 Excel（两个工作表），返回文件路径。"""

    detail = build_detail_frame(records)
    summary = build_summary_frame(records)
    path = _output_path("maintenance-report")
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        detail.to_excel(writer, index=False, sheet_name=DETAIL_SHEET)
        summary.to_excel(writer, index=False, sheet_name=SUMMARY_SHEET)
        _style_sheet(writer.sheets[DETAIL_SHEET], _DETAIL_WIDTHS)
        _style_sheet(writer.sheets[SUMMARY_SHEET], _SUMMARY_WIDTHS)
    logger.info(
        "维修总表已导出：%s（明细 %s 条 / 统计 %s 个地点）",
        path,
        len(detail),
        len(summary),
    )
    return path
