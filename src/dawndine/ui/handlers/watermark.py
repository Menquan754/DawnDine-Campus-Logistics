"""页B：图片水印回调。"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import gradio as gr

from dawndine.agent.tools.watermark import (
    delete_template,
    generate_meal_accompaniment_record,
    get_template,
    update_template_style,
)
from dawndine.services.watermark import (
    attach_column_lines,
    describe_template_style,
    parse_column_lines,
)
from dawndine.ui.handlers.common import (
    _persist_upload,
    _short_error,
    _template_choices,
    _template_update,
)
from dawndine.ui.handlers.schedule import _schedule_rows

logger = logging.getLogger(__name__)


def _friendly_time_error(value: str | None) -> str | None:
    """校验水印手动时间格式。"""

    clean = (value or "").strip()
    if not clean:
        return None
    try:
        datetime.strptime(clean, "%Y-%m-%d %H:%M")
    except ValueError:
        return "手动时间格式应为 YYYY-MM-DD HH:MM，例如 2026-10-28 12:00。"
    return None


_STYLE_FORMAT_OPTIONS: dict[str, str] = {
    "不调整（保持模板）": "",
    "完整（标题+地点+日期+时间+防伪）": "full",
    "标准（标题+地点+日期+时间）": "standard",
    "简洁（标题+日期+时间）": "compact",
    "仅日期时间": "datetime",
    "仅地点+日期时间": "location_time",
}

_STYLE_POSITION_OPTIONS: dict[str, str | None] = {
    "不调整（跟随模板）": None,
    "左上角": "top-left",
    "右上角": "top-right",
    "左下角": "bottom-left",
    "右下角": "bottom-right",
    "顶部居中": "top-center",
    "底部居中": "bottom-center",
}

_STYLE_SIZE_OPTIONS: dict[str, float] = {
    "不调整（保持字号）": 0.0,
    "小（0.8 倍）": 0.8,
    "标准（1.0 倍）": 1.0,
    "大（1.25 倍）": 1.25,
    "特大（1.5 倍）": 1.5,
}

_STYLE_COLOR_OPTIONS: dict[str, dict[str, str]] = {
    "不调整（保持配色）": {},
    "白字深绿底（推荐）": {"color": "#FFFFFF", "bg_color": "#0B6E4F"},
    "白字深蓝底": {"color": "#FFFFFF", "bg_color": "#173A5E"},
    "白字黑底": {"color": "#FFFFFF", "bg_color": "#111111"},
    "黑字浅黄底": {"color": "#1A1A1A", "bg_color": "#F5E6A8"},
    "黄字黑底": {"color": "#FFD54A", "bg_color": "#111111"},
}

_STYLE_GAP_OPTIONS: dict[str, int | None] = {
    "不调整（保持间距）": None,
    "紧贴（推荐）": 2,
    "适中": 10,
    "宽松": 20,
}

_STYLE_DATE_OPTIONS: dict[str, str] = {
    "不调整（保持格式）": "",
    "2026.10.28": "dot",
    "2026-10-28": "iso",
    "2026年10月28日": "cn",
    "10-28": "short",
}

_STYLE_TIME_OPTIONS: dict[str, str] = {
    "不调整（保持格式）": "",
    "14:30": "hm",
    "14:30:05": "hms",
}

# 左右分栏内容的位置：与四角/上下居中锚点一一对应。
_COLUMN_POSITION_OPTIONS: dict[str, str] = {
    "左上角": "top-left",
    "右上角": "top-right",
    "左下角": "bottom-left",
    "右下角": "bottom-right",
    "顶部居中": "top-center",
    "底部居中": "bottom-center",
}
_COLUMN_ANCHOR_LABELS: dict[str, str] = {v: k for k, v in _COLUMN_POSITION_OPTIONS.items()}

# 生成图片页：地点/时间挂到哪一栏、在栏内最上面还是最下面。
_FIELD_COLUMN_OPTIONS: dict[str, int] = {
    "内容栏1（左）": 1,
    "内容栏2（右）": 2,
}
_FIELD_POSITION_OPTIONS: dict[str, str] = {
    "最上面": "top",
    "最下面": "bottom",
}

_TEMPLATE_POSITION_PROMPTS = {
    "自动（按样图）": "",
    "左上角": "水印放最左上角",
    "右上角": "水印放最右上角",
    "左下角": "水印放最左下角",
    "右下角": "水印放最右下角",
}
_TEMPLATE_SPACING_PROMPTS = {
    "紧贴（推荐）": "元素紧靠在一起",
    "默认": "",
    "宽松": "元素之间间距大一点",
}


def _build_style_overrides(
    format_label: str | None,
    position_label: str | None,
    size_label: str | None,
    color_label: str | None,
    opacity: float | None,
    gap_label: str | None,
    date_label: str | None = None,
    time_label: str | None = None,
    scale_value: float | None = None,
) -> dict[str, Any]:
    """把 UI 下拉值转换为模板 style_overrides。"""

    overrides: dict[str, Any] = {}
    format_key = _STYLE_FORMAT_OPTIONS.get((format_label or "").strip())
    if format_key:
        overrides["format"] = format_key
    anchor = _STYLE_POSITION_OPTIONS.get((position_label or "").strip())
    if anchor:
        overrides["anchor"] = anchor
    preset_scale = _STYLE_SIZE_OPTIONS.get((size_label or "").strip())
    if preset_scale:
        overrides["font_scale"] = preset_scale
    elif scale_value is not None:
        try:
            custom_scale = float(scale_value)
        except (TypeError, ValueError):
            custom_scale = 1.0
        # 1.0 视为不调整；其余按 0.05 取整，避免浮点噪声。
        if abs(custom_scale - 1.0) >= 0.01:
            overrides["font_scale"] = round(max(0.5, min(2.5, custom_scale)), 2)
    colors = _STYLE_COLOR_OPTIONS.get((color_label or "").strip())
    if colors:
        overrides.update(colors)
    if opacity is not None and float(opacity) > 0:
        overrides["bg_opacity"] = max(40, min(255, int(opacity)))
    gap = _STYLE_GAP_OPTIONS.get((gap_label or "").strip())
    if gap is not None:
        overrides["layout_gap"] = gap
    date_key = _STYLE_DATE_OPTIONS.get((date_label or "").strip())
    if date_key:
        overrides["date_format"] = date_key
    time_key = _STYLE_TIME_OPTIONS.get((time_label or "").strip())
    if time_key:
        overrides["time_format"] = time_key
    return overrides


def apply_watermark_style_from_ui(
    template_name: str | None,
    format_label: str | None,
    position_label: str | None,
    size_label: str | None,
    scale_value: float | None,
    color_label: str | None,
    opacity: float | None,
    gap_label: str | None,
    date_label: str | None,
    time_label: str | None,
) -> str:
    """把格式/位置/字号/配色/间距保存到当前模板。"""

    name = (template_name or "").strip()
    if not name:
        return "⚠️ 请先在“当前模板”中选择一个模板。"
    overrides = _build_style_overrides(
        format_label,
        position_label,
        size_label,
        color_label,
        opacity,
        gap_label,
        date_label,
        time_label,
        scale_value,
    )
    if not overrides:
        return "⚠️ 没有可应用的调整项。"
    try:
        template = update_template_style(name, overrides)
        if template is None:
            return f"⚠️ 模板“{name}”不存在或已损坏。"
        scale = overrides.get("font_scale")
        scale_text = f"字号×{scale:.2f}" if isinstance(scale, (int, float)) else "原字号"
        return (
            f"✅ 已保存模板“{name}”的样式："
            f"{format_label or '默认格式'} / {position_label or '跟随模板'} / "
            f"{scale_text} / {color_label or '原配色'}。"
            "下次生成图片即按新样式输出。"
        )
    except Exception as exc:  # noqa: BLE001 - 模板损坏不应阻塞 UI
        logger.exception("保存水印样式失败")
        return f"⚠️ 保存样式失败：{_short_error(exc)}"


def show_template_style(template_name: str | None) -> str:
    """回显当前模板的格式、位置、字号等样式，便于对照调整。"""

    name = (template_name or "").strip()
    if not name:
        return "先选择模板，这里会显示它当前的格式、位置和字号。"
    try:
        template = get_template(name)
    except Exception as exc:  # noqa: BLE001 - 模板损坏只提示，不阻塞 UI
        logger.exception("读取模板样式失败")
        return f"⚠️ 读取模板样式失败：{_short_error(exc)}"
    if not template:
        return f"⚠️ 模板“{name}”不存在。"
    return f"**当前样式**：{describe_template_style(template)}"


def _column_style_overrides(
    left_text: str | None,
    left_position: str | None,
    right_text: str | None,
    right_position: str | None,
) -> list[dict[str, Any]] | None:
    """把左右两栏内容转换为 columns 覆盖项；两栏都空时返回 None。

    两栏对应界面上的“内容栏1”“内容栏2”。
    """

    columns: list[dict[str, Any]] = []
    for text, label in ((left_text, left_position), (right_text, right_position)):
        lines = parse_column_lines(text)
        if not lines:
            continue
        columns.append(
            {
                "anchor": _COLUMN_POSITION_OPTIONS.get((label or "").strip()),
                "text": "\n".join(lines),
            }
        )
    return columns or None


def apply_watermark_columns_from_ui(
    template_name: str | None,
    left_text: str | None,
    left_position: str | None,
    right_text: str | None,
    right_position: str | None,
) -> str:
    """把内容栏1 / 内容栏2 的内容与各自位置保存到当前模板。"""

    name = (template_name or "").strip()
    if not name:
        return "⚠️ 请先在“当前模板”中选择一个模板。"
    columns = _column_style_overrides(left_text, left_position, right_text, right_position)
    if not columns:
        return "⚠️ 请至少在一栏填写内容（每行一条）。"
    try:
        template = update_template_style(name, {"columns": columns})
        if template is None:
            return f"⚠️ 模板“{name}”不存在或已损坏。"
        summary = "；".join(
            f"{_COLUMN_ANCHOR_LABELS.get(str(column['anchor']), '默认位置')} "
            f"{len(column['text'].splitlines())} 行"
            for column in columns
        )
        anchors = [str(column["anchor"]) for column in columns]
        same_position = len(set(anchors)) < len(anchors)
        hint = "两栏位置相同，会合并成同一组按顺序排列。" if same_position else ""
        return (
            f"✅ 已保存内容栏到模板“{name}”：{summary}。{hint}"
            "内容栏按填写顺序从上到下排列，地点/日期/时间用 {location}/{date}/{time} 占位。"
        )
    except Exception as exc:  # noqa: BLE001 - 模板损坏不应阻塞 UI
        logger.exception("保存水印分栏失败")
        return f"⚠️ 保存分栏失败：{_short_error(exc)}"


def clear_watermark_columns_from_ui(
    template_name: str | None,
) -> tuple[str, Any, Any, Any, Any]:
    """清除模板的内容栏，恢复原始标题/地点/日期等内容。"""

    name = (template_name or "").strip()
    if not name:
        return "⚠️ 请先在“当前模板”中选择一个模板。", gr.skip(), gr.skip(), gr.skip(), gr.skip()
    try:
        template = update_template_style(name, {"columns": []})
        if template is None:
            return (
                f"⚠️ 模板“{name}”不存在或已损坏。",
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
            )
        return (
            f"✅ 已清除模板“{name}”的内容栏，已恢复原始内容。",
            "",
            "左上角",
            "",
            "右上角",
        )
    except Exception as exc:  # noqa: BLE001 - 模板损坏不应阻塞 UI
        logger.exception("清除水印分栏失败")
        return (
            f"⚠️ 清除分栏失败：{_short_error(exc)}",
            gr.skip(),
            gr.skip(),
            gr.skip(),
            gr.skip(),
        )


def load_template_columns(
    template_name: str | None,
) -> tuple[Any, Any, Any, Any]:
    """切换模板时，把已保存的内容栏内容与位置回填到输入框。"""

    name = (template_name or "").strip()
    template: dict[str, Any] | None = None
    if name:
        try:
            template = get_template(name)
        except Exception:  # noqa: BLE001 - 回填失败不应阻塞页面
            logger.exception("读取模板分栏失败")
    meta = template.get("meta") if isinstance(template, dict) else None
    columns = meta.get("columns") if isinstance(meta, Mapping) else None

    texts = {"left": "", "right": ""}
    positions = {"left": "左上角", "right": "右上角"}
    if isinstance(columns, list):
        for index, column in enumerate(columns[:2]):
            if not isinstance(column, Mapping):
                continue
            side = "left" if index == 0 else "right"
            texts[side] = "\n".join(str(line) for line in column.get("lines") or [])
            positions[side] = _COLUMN_ANCHOR_LABELS.get(
                str(column.get("anchor") or ""), positions[side]
            )
    return texts["left"], positions["left"], texts["right"], positions["right"]


def create_template_from_upload(
    sample_image: str | None,
    template_name: str | None,
    user_requirement: str | None,
    position: str | None = "自动（按样图）",
    spacing: str | None = "紧贴（推荐）",
    format_label: str | None = None,
    size_label: str | None = None,
    color_label: str | None = None,
    opacity: float | None = None,
) -> tuple[Any, ...]:
    """保存样图并创建水印模板。"""

    if not sample_image:
        return "⚠️ 请先上传一张样图。", gr.skip(), None
    try:
        sample = _persist_upload(sample_image, "sample")
        parts = [
            _TEMPLATE_POSITION_PROMPTS.get((position or "").strip(), ""),
            _TEMPLATE_SPACING_PROMPTS.get((spacing or "").strip(), ""),
            (user_requirement or "").strip(),
        ]
        requirement = "，".join(part for part in parts if part) or None
        style_overrides = _build_style_overrides(
            format_label,
            position,
            size_label,
            color_label,
            opacity,
            spacing,
        )
        result = generate_meal_accompaniment_record.invoke(
            {
                "mode": "new_template",
                "template_name": (template_name or "default").strip() or "default",
                "sample_image_path": str(sample),
                "user_requirement": requirement,
                "style_overrides": style_overrides or None,
            }
        )
        if not result.get("ok"):
            return f"⚠️ 模板创建失败：{result.get('error', '未知错误')}", gr.skip(), result
        name = str(result.get("template_name") or "default")
        return (
            f"✅ 已创建模板“{name}”。请核对文字、位置和字号，确认后再生成图片。",
            _template_update(name),
            result,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("创建水印模板失败")
        return f"⚠️ 模板创建失败：{_short_error(exc)}", gr.skip(), {"ok": False, "error": str(exc)}


def delete_template_from_ui(
    template_name: str | None,
    confirmed: bool,
) -> tuple[Any, str, str]:
    """删除选中的水印模板，并刷新模板下拉框。"""

    if not confirmed:
        return gr.skip(), "⚠️ 请先勾选“我确认删除该模板”。", gr.skip()
    name = (template_name or "").strip()
    if not name:
        return gr.skip(), "⚠️ 请先选择一个要删除的模板。", gr.skip()
    try:
        if not delete_template(name):
            return gr.skip(), f"⚠️ 模板“{name}”不存在或已删除。", gr.skip()
        choices = _template_choices()
        value = choices[0] if choices else None
        dropdown = gr.update(choices=choices, value=value)
        return (
            dropdown,
            f"✅ 已删除模板“{name}”。",
            f"🧹 模板“{name}”已删除，当前模板：{value or '无（请先上传样图新建）'}。",
        )
    except Exception as exc:  # noqa: BLE001 - 模板损坏不应阻塞 UI
        logger.exception("删除水印模板失败")
        return gr.skip(), f"⚠️ 删除失败：{_short_error(exc)}", gr.skip()


def render_watermark_from_upload(
    template_name: str | None,
    scene_image: str | None,
    location: str | None,
    manual_time: str | None,
    left_text: str | None = None,
    left_position: str | None = None,
    right_text: str | None = None,
    right_position: str | None = None,
    use_location: bool = True,
    use_time: bool = True,
    field_column: str | None = None,
    field_position: str | None = None,
) -> tuple[Any, ...]:
    """生成图片，并刷新水印与日程表。

    地点/时间是否上图由 use_location / use_time 决定：
    - 勾选地点且填写地址才输出，勾选但留空则不输出地点（不再写“待补”）；
    - 勾选时间且留空时使用当前时间；取消勾选则图上不出现日期和时间。
    启用内容栏时，地点/时间会并入 field_column 指定栏的 field_position 位置
    （最上面或最下面）；未启用内容栏则按模板原有位置输出。
    左右分栏内容填了就会临时套用（不写回模板），方便先预览再保存。
    """

    if not scene_image:
        return None, "", "⚠️ 请先上传现场照片。", None, gr.skip()
    if not template_name:
        return None, "", "⚠️ 请先创建或选择水印模板。", None, gr.skip()
    time_error = _friendly_time_error(manual_time)
    if time_error:
        return None, "", f"⚠️ {time_error}", {"ok": False, "error": time_error}, gr.skip()
    location_text = (location or "").strip()
    time_text = (manual_time or "").strip()
    include_location = bool(use_location and location_text)
    omit_fields = [] if include_location else ["location"]
    if not use_time:
        omit_fields.append("time")
    try:
        scene = _persist_upload(scene_image, "scene")
        columns = _column_style_overrides(left_text, left_position, right_text, right_position)
        notes: list[str] = []
        columns_touched = False
        if columns:
            extra_lines: list[str] = []
            if include_location:
                extra_lines.append(f"地点：{location_text}")
            if use_time:
                extra_lines.append("{date} {time}")
            merged = attach_column_lines(
                columns,
                extra_lines,
                _FIELD_COLUMN_OPTIONS.get((field_column or "").strip(), 1),
                _FIELD_POSITION_OPTIONS.get((field_position or "").strip(), "bottom"),
            )
            if merged:
                columns = merged
                columns_touched = True
                column_label = (field_column or "内容栏1（左）").strip()
                position_label = (field_position or "最下面").strip()
                attached = []
                if include_location:
                    attached.append("地点")
                if use_time:
                    attached.append("时间")
                notes.append(f"{'、'.join(attached)}已并入{column_label}的{position_label}。")
        else:
            notes.append("当前未设置内容栏，地点/时间按模板原有位置输出。")
        result = generate_meal_accompaniment_record.invoke(
            {
                "mode": "use_template",
                "template_name": template_name,
                "scene_image_path": str(scene),
                "location": location_text or None,
                "manual_time": time_text or None,
                "style_overrides": {"columns": columns} if columns else None,
                "omitted_fields": omit_fields or None,
            }
        )
        if not result.get("ok"):
            return (
                None,
                "",
                f"⚠️ 图片生成失败：{result.get('error', '未知错误')}",
                result,
                gr.skip(),
            )
        if use_time and not time_text:
            notes.append("未填写时间，已使用当前时间。")
        if use_location and not location_text:
            notes.append("已勾选地点但未填写，本次不输出地点。")
        elif not use_location:
            notes.append("未勾选地点，本次不输出地点。")
        if not use_time:
            notes.append("未勾选时间，本次不输出日期与时间。")
        path = str(result.get("output_path") or "")
        note = str(result.get("note", ""))
        column_note = "本次按填写的内容栏临时出图（未写入模板）。" if columns_touched else ""
        extra = " ".join(notes)
        return (
            path or None,
            path,
            f"✅ 图片已生成。{note}{column_note}{extra}".strip(),
            result,
            _schedule_rows(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("生成水印图失败")
        return None, "", f"⚠️ 图片生成失败：{_short_error(exc)}", {"ok": False}, gr.skip()


# ---------------------------------------------------------------------------
# 页B：图片水印分步界面（仅切换区域显隐，不改任何后端逻辑）
# ---------------------------------------------------------------------------
_WATERMARK_AREAS: tuple[str, ...] = ("home", "new", "render", "manage")


def _watermark_area_updates(active: str) -> tuple[Any, ...]:
    """返回首页/新建/生成/管理四个区域的 visible 更新。"""

    return tuple(gr.update(visible=area == active) for area in _WATERMARK_AREAS)


def show_watermark_home() -> tuple[Any, ...]:
    """关闭当前表单，回到图片水印首页。"""

    return _watermark_area_updates("home")


def show_watermark_new() -> tuple[Any, ...]:
    """展示“新建水印模板”区域。"""

    return _watermark_area_updates("new")


def show_watermark_render() -> tuple[Any, ...]:
    """展示“生成图片”区域。"""

    return _watermark_area_updates("render")


def show_watermark_manage() -> tuple[Any, ...]:
    """展示“管理已有模板”区域。"""

    return _watermark_area_updates("manage")
