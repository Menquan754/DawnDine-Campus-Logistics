"""陪餐水印打卡图工具。

本文件职责：
- 新建水印模板：Pillow 规则分析样图，经 watermark_store 写入模板 JSON；
- 使用模板：调用 dawndine.services.watermark.render_watermark 生成 PNG；
- 出图成功后向 SQLite 日程表写入“完成陪餐/验收打卡”摘要。

依赖：dawndine.config、dawndine.enums、dawndine.schemas、dawndine.db、
      dawndine.services.watermark、dawndine.services.watermark_store、langchain-core。
被调用：dawndine.agent.graph（经 agent/tools/__init__.py）、app.py、测试脚本。
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from dawndine.config import (
    DEFAULT_TEMPLATE_NAME,
    FONT_FALLBACK_NOTE,
    IMAGE_EXTENSIONS,
    ROOT_DIR,
    WATERMARK_ENTRY_MISSING,
    WATERMARK_PREVIEW_NOTE,
)
from dawndine.db import safe_create_schedule
from dawndine.enums import SCHEDULE_SOURCE_WATERMARK, TOOL_WATERMARK
from dawndine.schemas import WatermarkInput
from dawndine.services.watermark import (
    analyze_sample_image,
    apply_style_overrides,
    build_dynamic_vars,
    build_template_from_analysis,
    font_available,
    preflight_template,
    render_watermark,
)
from dawndine.services.watermark_store import (
    _read_template_map,
    _safe_template_name,
    _unique_template_name,
    _write_template_map,
    delete_template,
    get_template,
    list_templates,
    reset_templates,
    update_template_style,
)

logger = logging.getLogger(__name__)

__all__ = [
    "delete_template",
    "generate_meal_accompaniment_record",
    "get_template",
    "list_templates",
    "reset_templates",
    "update_template_style",
]


def _resolve_existing_file(raw: str | None, label: str) -> Path:
    """解析并验证用户提供的图片路径。"""

    if not raw:
        raise ValueError(f"缺少{label}路径。")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (ROOT_DIR / path).resolve()
    else:
        path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}不存在：{path}")
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(f"{label}格式不支持：{path.suffix}，请使用 PNG/JPG/JPEG/WEBP/BMP。")
    return path


def _build_notes(
    template: dict[str, Any],
    location: str | None,
    rendered_font_available: bool,
    omitted: frozenset[str] = frozenset(),
) -> list[str]:
    """汇总渲染后的提示信息。"""

    notes = preflight_template(template)
    if "location" in omitted:
        notes.append("本次未在图上输出地点。")
    elif not location:
        notes.append("未提供地点，已按“待补”写入，不得臆造陪餐地点。")
    if "time" in omitted:
        notes.append("本次未在图上输出日期与时间，日程仍按生成时刻记录。")
    if not rendered_font_available:
        notes.append(FONT_FALLBACK_NOTE)
    if template.get("meta", {}).get("text_requires_review"):
        notes.append("模板文字来自标准标签，请人工确认后再正式使用。")
    return notes


@tool(TOOL_WATERMARK, args_schema=WatermarkInput)
def generate_meal_accompaniment_record(
    mode: str,
    template_name: str | None = None,
    user_requirement: str | None = None,
    sample_image_path: str | None = None,
    scene_image_path: str | None = None,
    location: str | None = None,
    manual_time: str | None = None,
    style_overrides: dict[str, Any] | None = None,
    omitted_fields: list[str] | None = None,
) -> dict[str, Any]:
    """生成陪餐水印打卡图，或从样图新建水印模板。

    何时调用：
    - 用户明确要求“生成陪餐水印图/打卡图/陪餐记录图”；
    - 用户说“用这张样图新建模板”并提供了样图；
    - 用户已有模板并要求用现场照片出图。

    何时不调用：
    - 用户只是询问陪餐制度、检查口径，没有出图要求；
    - 没有样图也没有可用模板时，不猜测模板参数，应提示上传样图或选择模板；
    - 涉及食材新鲜度等感官判断时，转现场确认。

    功能边界：
    - 仅解析样图输出参数，实际绘图由 Pillow 完成，不做复杂 CV、人脸识别或 OCR；
    - 禁止编造地点；location 缺失时写“待补”；
    - user_requirement 支持“最左上角/最右下角”“元素紧靠在一起”等描述，
      四角锚点按实际图片尺寸精确贴边，同组元素默认紧凑堆叠；
    - style_overrides 支持水印格式（full/standard/compact/datetime/location_time）、
      位置（四角或上下居中）、字号倍率、配色、透明度、间距和日期/时间格式；
    - style_overrides.columns 支持左右分栏：每栏独立锚点，一栏一行、先写的在上方，
      行内可用 {location}/{date}/{time}/{weekday}/{anti_counterfeit} 占位符；
    - omitted_fields 可传 location/time，表示图上不输出地点或日期时间；
      未勾选地点、或勾选地点但没填地址时传 location，图上就不会出现“待补”；
    - 水印默认偏左上/左下，避开画面中心 40%；用户坐标落入中心时在 note 警告；
    - 支持多模板保存、切换；辅助函数 delete_template 可用于删除；
    - mode=new_template 只保存模板并返回预览，不绘制正式打卡图；
    - mode=use_template 读取模板并生成 watermarked/{uuid}.png。

    Returns:
        成功：{"ok": True, "action": ..., "template"/"output_path": ..., ...}
        失败：{"ok": False, "error": "..."}
    """

    try:
        normalized_mode = str(getattr(mode, "value", mode))
        if normalized_mode == "new_template":
            if not sample_image_path:
                return {
                    "ok": False,
                    "error": WATERMARK_ENTRY_MISSING,
                }
            sample = _resolve_existing_file(sample_image_path, "样图")
            analysis = analyze_sample_image(sample)
            requested_name = _safe_template_name(template_name)
            templates = _read_template_map()
            final_name = _unique_template_name(requested_name, templates)

            template = build_template_from_analysis(
                analysis=analysis,
                template_name=final_name,
                sample_image_path=sample,
                user_requirement=user_requirement,
                style_overrides=style_overrides,
            )
            template["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            templates[final_name] = template
            _write_template_map(templates)

            notes = [WATERMARK_PREVIEW_NOTE]
            if final_name != requested_name:
                notes.append(f"模板名“{requested_name}”已存在，本次保存为“{final_name}”。")
            if template.get("meta", {}).get("text_confidence") == "low":
                notes.append("样图文字未做 OCR，标题和地点标签为默认文本，请人工校准。")
            logger.info("已创建水印模板：%s", final_name)
            return {
                "ok": True,
                "action": "template_created",
                "template_name": final_name,
                "template": template,
                "preview_note": " ".join(notes),
                "note": "模板已保存，但未生成打卡图；确认参数后使用 use_template 模式出图。",
            }

        if normalized_mode != "use_template":
            return {
                "ok": False,
                "error": f"不支持的 mode：{normalized_mode}，仅支持 new_template/use_template。",
            }

        templates = _read_template_map()
        if not templates:
            return {"ok": False, "error": WATERMARK_ENTRY_MISSING}
        selected_name = _safe_template_name(template_name or DEFAULT_TEMPLATE_NAME)
        if selected_name not in templates:
            available = "、".join(sorted(templates)) or "无"
            return {
                "ok": False,
                "error": f"模板“{selected_name}”不存在。可用模板：{available}。",
            }
        if not scene_image_path:
            return {
                "ok": False,
                "error": "使用模板生成打卡图时必须提供现场照片 scene_image_path。",
            }

        scene = _resolve_existing_file(scene_image_path, "现场照片")
        template = apply_style_overrides(templates[selected_name], style_overrides)
        omitted = frozenset(
            str(item).strip() for item in (omitted_fields or ()) if str(item).strip()
        )
        template_meta = template.get("meta") if isinstance(template.get("meta"), dict) else {}
        variables = build_dynamic_vars(
            location=location,
            manual_time=manual_time,
            date_format=template_meta.get("date_format"),
            time_format=template_meta.get("time_format"),
        )
        output_path = render_watermark(
            template=template,
            scene_path=scene,
            dynamic_vars=variables,
            omitted=sorted(omitted),
        )

        notes = _build_notes(template, location, font_available(), omitted)
        schedule_id = 0
        schedule = safe_create_schedule(
            date=variables.get("date_iso"),
            time=variables.get("time"),
            content="完成陪餐/验收打卡",
            source=SCHEDULE_SOURCE_WATERMARK,
        )
        if schedule:
            schedule_id = int(schedule["id"])
            notes.append("已同步到“我的日程”。")
        else:
            notes.append("日程沉淀失败，但图片已生成，可稍后手动补记。")
        note = " ".join(notes).strip() or "打卡图已生成，请核对文字与位置后使用。"
        return {
            "ok": True,
            "action": "render_watermark",
            "template_name": selected_name,
            "output_path": output_path,
            "dynamic_vars": variables,
            "note": note,
            "schedule_id": schedule_id,
        }
    except Exception as exc:  # noqa: BLE001 - 工具边界必须返回结构化错误
        logger.exception("水印工具执行失败")
        return {"ok": False, "error": f"水印工具执行失败：{exc}"}
