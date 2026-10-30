"""日程服务：只读分析 + PNG 图片导出。

本文件职责：
- 读取本地日程并输出结构化分析（总数、来源分布、日期分布、今日/本周、冲突、待补）；
- 生成中文 Markdown 摘要，供“我的日程”页与对话回答直接使用；
- 用 Pillow 把日程行渲染成带表头的 PNG 表格图，便于导出、打印与转发；
- 分析过程不修改数据库，只做只读分析。

依赖：dawndine.config、dawndine.db、dawndine.services.watermark、Pillow。
被调用：dawndine.agent.tools.schedule、app.py、测试脚本。
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from dawndine.config import EXPORTS_DIR
from dawndine.db import list_schedules
from dawndine.services.watermark import find_chinese_font

logger = logging.getLogger(__name__)

__all__ = [
    "PENDING_TIME",
    "WEEKDAY_NAMES",
    "analyze_schedules",
    "format_analysis_markdown",
    "render_schedule_image",
]

PENDING_TIME = "待补"
WEEKDAY_NAMES = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def _parse_date(value: str | None) -> datetime | None:
    """解析 YYYY-MM-DD，失败返回 None。"""

    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _parse_time_minutes(value: str | None) -> int | None:
    """把 HH:MM 转成分钟数，便于排序；待补或非法返回 None。"""

    text = (value or "").strip()
    if not text or text == PENDING_TIME:
        return None
    parts = text.split(":")
    if len(parts) < 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return hour * 60 + minute


def analyze_schedules(limit: int = 2000) -> dict[str, Any]:
    """分析全部日程，返回结构化统计与建议。

    Args:
        limit: 最多分析的日程条数。

    Returns:
        {
          "ok": True,
          "total": 12,
          "pending": 3,
          "today": [...],
          "this_week_count": 5,
          "conflicts": [{"date": ..., "time": ..., "items": [...]}],
          "by_date": [{"date": ..., "count": ...}],
          "by_source": [{"source": ..., "count": ...}],
          "upcoming": [...],
          "overdue": [...],
          "suggestions": [...],
        }
    """

    try:
        schedules = list_schedules(limit=limit)
    except Exception as exc:  # noqa: BLE001 - 工具边界必须返回结构化错误
        logger.exception("日程分析读取失败")
        return {"ok": False, "error": f"读取日程失败：{exc}"}

    now = datetime.now()
    today_text = now.strftime("%Y-%m-%d")
    week_end = (now + timedelta(days=7)).strftime("%Y-%m-%d")

    total = len(schedules)
    pending = [item for item in schedules if str(item.get("time") or "") == PENDING_TIME]
    overdue = [
        item
        for item in schedules
        if (parsed := _parse_date(str(item.get("date") or "")))
        and parsed.strftime("%Y-%m-%d") < today_text
    ]
    today_items = [item for item in schedules if str(item.get("date") or "") == today_text]
    week_items = [
        item
        for item in schedules
        if (parsed := _parse_date(str(item.get("date") or "")))
        and today_text <= parsed.strftime("%Y-%m-%d") <= week_end
    ]

    conflict_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in schedules:
        date_text = str(item.get("date") or "")
        time_text = str(item.get("time") or "")
        if not date_text or date_text == PENDING_TIME or _parse_time_minutes(time_text) is None:
            continue
        conflict_groups.setdefault((date_text, time_text), []).append(item)
    conflicts = [
        {
            "date": date_text,
            "time": time_text,
            "count": len(items),
            "items": [str(item.get("content") or "") for item in items],
        }
        for (date_text, time_text), items in sorted(conflict_groups.items())
        if len(items) > 1
    ]

    date_counter = Counter(str(item.get("date") or "待补") for item in schedules)
    by_date = [
        {"date": date_text, "count": count} for date_text, count in date_counter.most_common(10)
    ]
    source_counter = Counter(str(item.get("source") or "未知") for item in schedules)
    by_source = [
        {"source": source, "count": count} for source, count in source_counter.most_common()
    ]

    def _sort_key(item: dict[str, Any]) -> tuple[str, int]:
        date_text = str(item.get("date") or "9999-99-99")
        if date_text == PENDING_TIME:
            date_text = "9999-99-99"
        return date_text, _parse_time_minutes(str(item.get("time") or "")) or 24 * 60

    upcoming = sorted(
        [
            item
            for item in schedules
            if (parsed := _parse_date(str(item.get("date") or "")))
            and parsed.strftime("%Y-%m-%d") >= today_text
            and parsed.strftime("%Y-%m-%d") <= week_end
        ],
        key=_sort_key,
    )[:5]

    suggestions: list[str] = []
    if total == 0:
        suggestions.append("当前没有日程，可上传通知截图导入，或在页面底部手动添加。")
    if pending:
        suggestions.append(f"有 {len(pending)} 条日程时间为“待补”，建议补全后再打卡或上报。")
    if overdue:
        suggestions.append(f"有 {len(overdue)} 条日程日期已过，确认是否需要补做或删除。")
    if conflicts:
        first = conflicts[0]
        suggestions.append(
            f"{first['date']} {first['time']} 有 {first['count']} 条日程冲突，"
            "建议错峰安排并留出检查时间。"
        )
    if today_items:
        ordered = sorted(today_items, key=_sort_key)
        first = ordered[0]
        suggestions.append(
            f"今天有 {len(today_items)} 条安排，最早一条是 {first.get('date')} "
            f"{first.get('time')} · {first.get('content')}。"
        )
    if by_source:
        top = by_source[0]
        suggestions.append(
            f"日程主要来源是“{top['source']}”（{top['count']} 条），可据此核对办理渠道。"
        )
    if not suggestions:
        suggestions.append("日程结构正常，可按日期顺序推进。")

    weekday = WEEKDAY_NAMES[now.weekday()]
    return {
        "ok": True,
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
        "weekday": weekday,
        "total": total,
        "pending_count": len(pending),
        "today_count": len(today_items),
        "week_count": len(week_items),
        "overdue_count": len(overdue),
        "today": [
            {"date": item.get("date"), "time": item.get("time"), "content": item.get("content")}
            for item in sorted(today_items, key=_sort_key)
        ],
        "pending": [
            {"date": item.get("date"), "content": item.get("content")} for item in pending[:5]
        ],
        "overdue": [
            {"date": item.get("date"), "time": item.get("time"), "content": item.get("content")}
            for item in sorted(overdue, key=_sort_key)[-5:]
        ],
        "conflicts": conflicts,
        "by_date": by_date,
        "by_source": by_source,
        "upcoming": [
            {
                "date": item.get("date"),
                "time": item.get("time"),
                "content": item.get("content"),
                "source": item.get("source"),
            }
            for item in upcoming
        ],
        "suggestions": suggestions,
    }


def format_analysis_markdown(report: dict[str, Any]) -> str:
    """把分析结果转成可直接展示的 Markdown。"""

    if not report.get("ok"):
        return f"⚠️ {report.get('error', '日程分析失败')}"
    lines = [
        f"### 日程分析 · 共 {report['total']} 条",
        f"（统计时间 {report['generated_at']} {report['weekday']}）",
        "",
        f"- 今天：{report['today_count']} 条｜未来 7 天：{report['week_count']} 条",
        f"- 时间为“待补”：{report['pending_count']} 条｜日期已过：{report['overdue_count']} 条",
        f"- 时间冲突：{len(report['conflicts'])} 组",
    ]
    if report["today"]:
        lines.append("\n**今天安排**")
        for item in report["today"]:
            lines.append(f"- {item['time']} · {item['content']}")
    if report["upcoming"]:
        lines.append("\n**未来 7 天（前 5 条）**")
        for item in report["upcoming"]:
            lines.append(f"- {item['date']} {item['time']} · {item['content']}（{item['source']}）")
    if report["conflicts"]:
        lines.append("\n**冲突时段**")
        for group in report["conflicts"][:5]:
            joined = "；".join(group["items"])
            lines.append(f"- {group['date']} {group['time']}：{joined}")
    if report["by_source"]:
        joined = "、".join(f"{item['source']} {item['count']} 条" for item in report["by_source"])
        lines.append(f"\n**来源分布**：{joined}")
    if report["suggestions"]:
        lines.append("\n**建议**")
        for suggestion in report["suggestions"]:
            lines.append(f"- {suggestion}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 日程图片导出（原 modules/schedule_image.py）
# ---------------------------------------------------------------------------
IMAGE_WIDTH = 1080
MARGIN = 48
TABLE_WIDTH = IMAGE_WIDTH - MARGIN * 2
HEADER_HEIGHT = 64
ROW_MIN_HEIGHT = 62
LINE_HEIGHT = 32
BODY_FONT_SIZE = 22
HEADER_FONT_SIZE = 21
TITLE_FONT_SIZE = 34
FOOTER_FONT_SIZE = 18

COLUMN_RATIOS: tuple[tuple[str, float], ...] = (
    ("日期", 0.19),
    ("时间", 0.12),
    ("事项", 0.47),
    ("来源", 0.22),
)
COLUMN_WIDTHS: tuple[int, ...] = tuple(int(TABLE_WIDTH * ratio) for _, ratio in COLUMN_RATIOS)

# 导出文件名使用 ASCII 视图标识，避免中文文件名在浏览器下载/分享时被转码。
_VIEW_SLUGS = {
    "全部": "all",
    "今天": "today",
    "未来 7 天": "week",
    "待补时间": "pending",
}

COLOR_BG = "#F2F7F6"
COLOR_CARD = "#FFFFFF"
COLOR_HEADER = "#0F766E"
COLOR_HEADER_TEXT = "#FFFFFF"
COLOR_INK = "#18332C"
COLOR_MUTED = "#657B75"
COLOR_LINE = "#DCE9E5"
COLOR_ROW_ALT = "#F5FAF8"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """加载中文字体；缺失时退回 Pillow 默认字体。"""

    safe = max(10, int(size))
    path = find_chinese_font()
    if path is not None:
        try:
            return ImageFont.truetype(str(path), safe)
        except OSError:
            logger.warning("日程图字体加载失败，回退默认字体：%s", path)
    try:
        return ImageFont.load_default(size=safe)
    except TypeError:  # Pillow 较老版本
        return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: Any) -> int:
    """计算文字像素宽度，兼容不同 Pillow 版本。"""

    box = draw.textbbox((0, 0), text, font=font)
    return int(box[2] - box[0])


def _wrap(
    text: str,
    draw: ImageDraw.ImageDraw,
    font: Any,
    max_width: int,
    max_lines: int = 3,
) -> list[str]:
    """按像素宽度逐字换行，超出最大行数时加省略号。"""

    clean = (text or "").replace("\n", " ").strip()
    if not clean:
        return [""]
    lines: list[str] = []
    current = ""
    for char in clean:
        candidate = current + char
        if _text_width(draw, candidate, font) <= max_width or not current:
            current = candidate
            continue
        lines.append(current)
        current = char
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if not lines:
        lines = [clean[:1]]
    drawn = "".join(lines)
    if len(drawn) < len(clean):
        last = lines[-1]
        while last and _text_width(draw, last + "…", font) > max_width:
            last = last[:-1]
        lines[-1] = f"{last}…" if last else "…"
    return lines


def _cell_text(value: Any, fallback: str = "") -> str:
    """把单元格值转成可读文本。"""

    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _row_values(row: Sequence[Any] | Mapping[str, Any]) -> tuple[str, str, str, str]:
    """从 Dataframe 行或字典行中取出日期、时间、事项、来源。"""

    if isinstance(row, Mapping):
        return (
            _cell_text(row.get("date"), "待补"),
            _cell_text(row.get("time"), "待补"),
            _cell_text(row.get("content"), "未填写事项"),
            _cell_text(row.get("source"), "未知"),
        )
    values = list(row) + [None] * 6
    return (
        _cell_text(values[1], "待补"),
        _cell_text(values[2], "待补"),
        _cell_text(values[3], "未填写事项"),
        _cell_text(values[4], "未知"),
    )


def render_schedule_image(
    rows: Sequence[Sequence[Any] | Mapping[str, Any]],
    view: str = "全部",
    output_dir: Path | None = None,
) -> Path:
    """把日程行渲染成 PNG，返回图片路径。

    Args:
        rows: 日程行，支持 Dataframe 数组行或数据库字典行。
        view: 视图名称（全部/今天/未来 7 天/待补时间），仅用于标题。
        output_dir: 输出目录，默认 exports/。
    """

    target_dir = Path(output_dir) if output_dir else EXPORTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    body_font = _font(BODY_FONT_SIZE)
    header_font = _font(HEADER_FONT_SIZE)
    title_font = _font(TITLE_FONT_SIZE)
    footer_font = _font(FOOTER_FONT_SIZE)

    probe = Image.new("RGB", (10, 10))
    probe_draw = ImageDraw.Draw(probe)

    table_rows: list[list[list[str]]] = []
    for row in rows:
        date_text, time_text, content_text, source_text = _row_values(row)
        cells = [
            _wrap(date_text, probe_draw, body_font, COLUMN_WIDTHS[0] - 24, 1),
            _wrap(time_text, probe_draw, body_font, COLUMN_WIDTHS[1] - 24, 1),
            _wrap(content_text, probe_draw, body_font, COLUMN_WIDTHS[2] - 24),
            _wrap(source_text, probe_draw, body_font, COLUMN_WIDTHS[3] - 24, 1),
        ]
        table_rows.append(cells)

    row_heights = [max(ROW_MIN_HEIGHT, LINE_HEIGHT * len(cells[2]) + 24) for cells in table_rows]
    title_block = 128
    footer_block = 92
    table_height = HEADER_HEIGHT + sum(row_heights)
    if not table_rows:
        table_height = HEADER_HEIGHT + 120
    height = title_block + table_height + footer_block

    image = Image.new("RGB", (IMAGE_WIDTH, height), COLOR_BG)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (MARGIN - 12, 24, IMAGE_WIDTH - MARGIN + 12, height - 24),
        radius=28,
        fill=COLOR_CARD,
        outline=COLOR_LINE,
        width=2,
    )

    draw.text(
        (MARGIN, 52),
        f"我的日程 · {_cell_text(view, '全部')}",
        font=title_font,
        fill=COLOR_INK,
    )
    subtitle = f"共 {len(table_rows)} 条 · 导出时间 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    draw.text((MARGIN, 100), subtitle, font=footer_font, fill=COLOR_MUTED)

    table_top = title_block
    table_left = MARGIN
    draw.rectangle(
        (table_left, table_top, table_left + TABLE_WIDTH, table_top + HEADER_HEIGHT),
        fill=COLOR_HEADER,
    )
    x = table_left
    for (label, _), width in zip(COLUMN_RATIOS, COLUMN_WIDTHS, strict=True):
        draw.text((x + 14, table_top + 20), label, font=header_font, fill=COLOR_HEADER_TEXT)
        x += width

    cursor_y = table_top + HEADER_HEIGHT
    if not table_rows:
        draw.text(
            (table_left + 24, cursor_y + 40),
            "暂无日程记录",
            font=title_font,
            fill=COLOR_MUTED,
        )
        cursor_y += 120
    for index, (cells, row_height) in enumerate(zip(table_rows, row_heights, strict=True)):
        if index % 2 == 1:
            draw.rectangle(
                (table_left, cursor_y, table_left + TABLE_WIDTH, cursor_y + row_height),
                fill=COLOR_ROW_ALT,
            )
        draw.line(
            (table_left, cursor_y + row_height, table_left + TABLE_WIDTH, cursor_y + row_height),
            fill=COLOR_LINE,
            width=1,
        )
        x = table_left
        for column_index, lines in enumerate(cells):
            width = COLUMN_WIDTHS[column_index]
            text_y = cursor_y + 16
            for line in lines:
                draw.text((x + 12, text_y), line, font=body_font, fill=COLOR_INK)
                text_y += LINE_HEIGHT
            x += width
        cursor_y += row_height

    draw.rectangle(
        (table_left, table_top, table_left + TABLE_WIDTH, cursor_y),
        outline=COLOR_LINE,
        width=1,
    )

    draw.text(
        (MARGIN, height - 62),
        "由校园后勤助手生成 · 日程数据来自本地 SQLite，请以平台记录为准",
        font=footer_font,
        fill=COLOR_MUTED,
    )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    view_text = _cell_text(view, "全部")
    suffix = _VIEW_SLUGS.get(view_text) or "all"
    output_path = target_dir / f"schedule-{suffix}-{stamp}.png"
    image.save(output_path, format="PNG", optimize=True)
    logger.info("日程图片已导出：%s（%s 条）", output_path, len(table_rows))
    return output_path
