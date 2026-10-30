"""页C：我的日程回调。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import gradio as gr

from dawndine.db import (
    bulk_create_schedules,
    create_schedule,
    delete_all_schedules,
    delete_schedules,
    list_schedule_rows,
    normalize_date,
    normalize_time,
    update_schedule,
)
from dawndine.enums import SCHEDULE_SOURCE_MANUAL
from dawndine.llm import resolve_api_key
from dawndine.services.schedule import (
    analyze_schedules as analyze_schedule_data,
)
from dawndine.services.schedule import format_analysis_markdown, render_schedule_image
from dawndine.services.vision import parse_schedule_image
from dawndine.ui.handlers.common import _key_configured, _persist_upload, _short_error

logger = logging.getLogger(__name__)

def _schedule_rows(view: str = "全部") -> list[list[Any]]:
    """按当前视图读取最新日程行，异常时返回空表并记录日志。"""

    date_from, date_to, only_pending = _schedule_view_range(view)
    try:
        return list_schedule_rows(
            date_from=date_from,
            date_to=date_to,
            only_pending=only_pending,
        )
    except Exception:  # noqa: BLE001 - UI 不应因数据库异常整体崩溃
        logger.exception("读取日程失败")
        return []


def _schedule_view_range(view: str) -> tuple[str | None, str | None, bool]:
    """把视图名称转换为 SQL 过滤参数。"""

    today = datetime.now().strftime("%Y-%m-%d")
    if view == "今天":
        return today, today, False
    if view == "未来 7 天":
        end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        return today, end, False
    if view == "待补时间":
        return None, None, True
    return None, None, False


def _schedule_choices(view: str = "全部") -> list[tuple[str, int]]:
    """把当前视图的日程转换为勾选选项：显示描述，值仍然是日程编号。"""

    choices: list[tuple[str, int]] = []
    for row in _schedule_rows(view):
        try:
            schedule_id = int(row[0])
        except (TypeError, ValueError):
            continue
        date_text = str(row[1] or "待补")
        time_text = str(row[2] or "")
        content = str(row[3] or "")[:26]
        label = f"编号 {schedule_id} · {date_text} {time_text} · {content}"
        choices.append((label.replace("  ", " ").strip(), schedule_id))
    return choices


def _schedule_pick_update(view: str = "全部", selected: Any = None) -> Any:
    """构造日程勾选列表更新；默认清空选择，避免误删。"""

    choices = _schedule_choices(view)
    valid_ids = {item[1] for item in choices}
    wanted = selected if isinstance(selected, (list, tuple, set)) else [selected]
    values = [
        int(item)
        for item in wanted
        if _coerce_schedule_id(item) is not None and int(item) in valid_ids
    ]
    # CheckboxGroup 的 value 必须是列表；空选择用 [] 而不是 None。
    return gr.update(choices=choices, value=values)


def refresh_schedule_pick(view: str = "全部") -> Any:
    """刷新“一键勾选 / 框选删除”列表。"""

    return _schedule_pick_update(view)


def refresh_schedule_pick_and_box(view: str = "全部") -> tuple[Any, str]:
    """刷新勾选列表并同步清空“待删除清单”显示框。"""

    return _schedule_pick_update(view), _schedule_selection_summary([], view)


def _schedule_selection_summary(selected: Any, view: str = "全部") -> str:
    """把已勾选的日程整理成“待删除清单”，供删除框直接展示。"""

    ids = _coerce_schedule_ids(selected)
    if not ids:
        return (
            "🗑️ **待删除清单（0 条）**\n\n"
            "尚未勾选：点击任意一条日程即可勾选（整行均可点击），"
            "也可以按住鼠标从第一条拖到最后一条框选多行。"
        )
    rows_by_id: dict[int, list[Any]] = {}
    for row in _schedule_rows(view):
        try:
            rows_by_id[int(row[0])] = row
        except (TypeError, ValueError, IndexError):
            continue
    lines = [f"🗑️ **待删除清单（{len(ids)} 条）**"]
    for schedule_id in ids:
        row = rows_by_id.get(schedule_id)
        if row is None:
            lines.append(f"- **编号 {schedule_id}** · 当前视图中不可见")
            continue
        date_text = str(row[1] or "待补")
        time_text = str(row[2] or "").strip()
        content = str(row[3] or "").strip()
        moment = f"{date_text} {time_text}".strip()
        lines.append(f"- **编号 {schedule_id}** · {moment} · {content}")
    return "\n".join(lines)


def select_all_schedules(view: str = "全部") -> tuple[Any, str]:
    """一键勾选当前视图的全部日程。"""

    ids = [value for _, value in _schedule_choices(view)]
    if not ids:
        return gr.skip(), "⚠️ 当前视图没有可勾选的日程。"
    return gr.update(value=ids), _schedule_selection_summary(ids, view)


def clear_schedule_selection(view: str = "全部") -> tuple[Any, str]:
    """取消全部勾选，并清空待删除清单。"""

    return gr.update(value=[]), _schedule_selection_summary([], view)


def _coerce_schedule_ids(value: Any) -> list[int]:
    """把多选下拉的返回值统一成正整数 ID 列表（去重、保持顺序）。"""

    raw_items = value if isinstance(value, (list, tuple, set)) else [value]
    ids: list[int] = []
    for item in raw_items:
        parsed = _coerce_schedule_id(item)
        if parsed is not None and parsed not in ids:
            ids.append(parsed)
    return ids


def _schedule_id_from_pick(value: Any) -> Any:
    """多选下拉只选中一条时，把它填入“修改日程 ID”。"""

    ids = _coerce_schedule_ids(value)
    return gr.update(value=ids[0]) if len(ids) == 1 else gr.skip()


def on_schedule_selection(selected: Any, view: str = "全部") -> tuple[Any, str]:
    """勾选变化：只选一条时回填日程 ID，同时刷新“待删除清单”。"""

    return _schedule_id_from_pick(selected), _schedule_selection_summary(selected, view)

def refresh_schedules(view: str = "全部") -> list[list[Any]]:
    """按当前视图刷新日程表。"""

    return _schedule_rows(view)


def export_schedule_image(view: str = "全部") -> tuple[Any, str, str]:
    """把当前视图的日程导出为 PNG 表格图，并返回预览、状态与本地路径。"""

    rows = _schedule_rows(view)
    try:
        path = render_schedule_image(rows, view=view)
        return (
            str(path),
            f"✅ 已导出 {len(rows)} 条日程：{path.name}",
            str(path),
        )
    except Exception as exc:  # noqa: BLE001 - 导出失败不应影响页面
        logger.exception("日程图片导出失败")
        return None, f"⚠️ 导出失败：{_short_error(exc)}", ""


def analyze_schedule_view() -> str:
    """分析全部日程并生成可直接展示的 Markdown 摘要。"""

    try:
        return format_analysis_markdown(analyze_schedule_data())
    except Exception as exc:  # noqa: BLE001
        logger.exception("日程分析失败")
        return f"⚠️ 日程分析失败：{_short_error(exc)}"


def _coerce_schedule_id(value: Any) -> int | None:
    """把 gr.Number 返回值转换为正整数 ID。"""

    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not number.is_integer() or number < 1:
        return None
    return int(number)


def delete_selected_schedules(
    schedule_ids: Any,
    view: str,
) -> tuple[Any, Any, Any, str]:
    """删除勾选列表中的一条或多条日程，并同步刷新表格、勾选列表与删除框。"""

    parsed_ids = _coerce_schedule_ids(schedule_ids)
    if not parsed_ids:
        return gr.skip(), gr.skip(), gr.skip(), "⚠️ 请先勾选要删除的日程（点击整行或拖动框选）。"
    try:
        deleted = delete_schedules(parsed_ids)
        if not deleted:
            return (
                _schedule_rows(view),
                _schedule_pick_update(view),
                _schedule_selection_summary([], view),
                f"⚠️ 未找到所选日程（编号 {', '.join(map(str, parsed_ids))}），可能已被删除。",
            )
        joined = "、".join(f"编号 {item}" for item in parsed_ids)
        message = f"✅ 已删除 {deleted} 条日程：{joined}。"
        if deleted < len(parsed_ids):
            message += " 部分编号已不存在（编号会被后续新增日程优先复用）。"
        return (
            _schedule_rows(view),
            _schedule_pick_update(view),
            _schedule_selection_summary([], view),
            message,
        )
    except Exception as exc:  # noqa: BLE001 - UI 操作不能导致页面崩溃
        logger.exception("删除日程失败")
        return gr.skip(), gr.skip(), gr.skip(), f"⚠️ 删除失败：{_short_error(exc)}"


def clear_all_schedules(
    confirmed: bool,
    view: str,
) -> tuple[Any, Any, Any, str]:
    """清空全部日程；必须勾选确认框。"""

    if not confirmed:
        return gr.skip(), gr.skip(), gr.skip(), "⚠️ 请先勾选“我确认清空全部日程”。"
    try:
        deleted = delete_all_schedules()
        return (
            _schedule_rows(view),
            _schedule_pick_update(view),
            _schedule_selection_summary([], view),
            f"✅ 已清空 {deleted} 条日程。",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("清空日程失败")
        return gr.skip(), gr.skip(), gr.skip(), f"⚠️ 清空失败：{_short_error(exc)}"


def update_schedule_from_ui(
    schedule_id: Any,
    date_value: str,
    time_value: str,
    content: str,
    view: str,
) -> tuple[Any, str]:
    """按编号修改单条日程；空字段表示不修改。"""

    parsed_id = _coerce_schedule_id(schedule_id)
    if parsed_id is None:
        return gr.skip(), "⚠️ 请输入有效的日程编号。"

    new_date = (date_value or "").strip() or None
    new_time = (time_value or "").strip() or None
    new_content = (content or "").strip() or None
    if new_date is None and new_time is None and new_content is None:
        return gr.skip(), "⚠️ 请至少填写一个要修改的字段。"

    try:
        updated = update_schedule(
            parsed_id,
            date=new_date,
            time=new_time,
            content=new_content,
        )
        if updated is None:
            return _schedule_rows(view), f"⚠️ 未找到编号为 {parsed_id} 的日程。"
        return _schedule_rows(view), f"✅ 已修改日程编号 {parsed_id}。"
    except Exception as exc:  # noqa: BLE001 - UI 操作不能导致页面崩溃
        logger.exception("修改日程失败")
        return gr.skip(), f"⚠️ 修改失败：{_short_error(exc)}"


def add_manual_schedule(
    date_value: str,
    time_value: str,
    content: str,
) -> tuple[Any, ...]:
    """手动新增一条日程。"""

    if not (content or "").strip():
        return gr.skip(), "⚠️ 请填写日程事项。", gr.skip()
    try:
        date_text = normalize_date(date_value)
        time_text = normalize_time(time_value)
        record = create_schedule(
            date=date_text,
            time=time_text,
            content=content,
            source=SCHEDULE_SOURCE_MANUAL,
        )
        return (
            _schedule_rows(),
            f"✅ 已添加日程（编号 {record['id']}）："
            f"{record['date']} {record['time']} {record['content']}",
            "",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("手动添加日程失败")
        return gr.skip(), f"⚠️ 添加失败：{_short_error(exc)}", gr.skip()


def import_schedule_from_image(
    image_path: str | None,
    ui_api_key: str,
) -> tuple[Any, ...]:
    """调用 Qwen-VL 解析图片并批量写入日程。"""

    if not image_path:
        return "⚠️ 请先上传日程图片。", gr.skip()
    if not _key_configured(ui_api_key):
        return "⚠️ 图片解析需要 DashScope Key，请先在页脚“设置”中填写。", gr.skip()
    try:
        saved = _persist_upload(image_path, "schedule")
        parsed = parse_schedule_image(str(saved), api_key=resolve_api_key(ui_api_key))
        records = parsed["records"]
        if not records:
            return f"⚠️ {parsed['note']}", _schedule_rows()
        inserted = bulk_create_schedules(records)
        if not inserted:
            return "⚠️ 图片解析到日程，但写入失败，请检查日期/时间格式。", _schedule_rows()
        return (
            f"✅ 已导入 {len(inserted)} 条日程。{parsed['note']}",
            _schedule_rows(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("图片导入日程失败")
        return f"⚠️ 导入失败：{_short_error(exc)}", gr.skip()
