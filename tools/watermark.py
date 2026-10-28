"""陪餐水印打卡图工具。

本文件职责：
- 新建水印模板：Pillow 规则分析样图，写 data/templates/watermark_style_template.json；
- 使用模板：调用 modules/watermark_render.render_watermark 生成 PNG；
- 出图成功后向 SQLite 日程表写入“完成陪餐/验收打卡”摘要；
- 提供模板列表、读取、删除等非工具辅助函数。

依赖：constants.py、schemas.py、modules/watermark_render.py、modules/db.py、
      langchain-core。
被调用：graph.py（经 tools/__init__.py）、app.py、测试脚本。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from constants import (
    DEFAULT_TEMPLATE_NAME,
    FONT_FALLBACK_NOTE,
    IMAGE_EXTENSIONS,
    ROOT_DIR,
    SCHEDULE_SOURCE_WATERMARK,
    TEMPLATE_FILE,
    TEMPLATES_DIR,
    TOOL_WATERMARK,
    WATERMARK_ENTRY_MISSING,
    WATERMARK_PREVIEW_NOTE,
)
from modules.db import safe_create_schedule
from modules.watermark_render import (
    analyze_sample_image,
    apply_style_overrides,
    build_dynamic_vars,
    build_template_from_analysis,
    font_available,
    preflight_template,
    render_watermark,
)
from schemas import WatermarkInput

logger = logging.getLogger(__name__)

_TEMPLATE_NAME_PATTERN = re.compile(r"^[\w\u4e00-\u9fff-]{1,40}$")


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


def _safe_template_name(raw: str | None) -> str:
    """校验模板名，阻止路径穿越。"""

    name = (raw or DEFAULT_TEMPLATE_NAME).strip()
    if not _TEMPLATE_NAME_PATTERN.fullmatch(name):
        raise ValueError("模板名只能包含中文、字母、数字、下划线和短横线，长度 1—40。")
    return name


def _read_template_map() -> dict[str, Any]:
    """读取模板 JSON；文件不存在时返回空字典。"""

    if not TEMPLATE_FILE.is_file():
        return {}
    try:
        data = json.loads(TEMPLATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"模板文件损坏，无法读取：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("模板文件结构错误：根节点必须是对象。")
    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def _write_template_map(templates: dict[str, Any]) -> None:
    """原子写入模板 JSON，避免中断造成半文件。"""

    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    temporary = TEMPLATE_FILE.with_name(TEMPLATE_FILE.name + ".tmp")
    temporary.write_text(
        json.dumps(templates, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(TEMPLATE_FILE)


def list_templates() -> list[str]:
    """返回当前已保存的模板名列表。"""

    try:
        return sorted(_read_template_map().keys())
    except ValueError:
        logger.exception("读取模板列表失败")
        return []


def get_template(template_name: str) -> dict[str, Any] | None:
    """按名称读取模板，不存在时返回 None。"""

    return _read_template_map().get(template_name)


def delete_template(template_name: str) -> bool:
    """删除指定模板；不存在时返回 False。"""

    templates = _read_template_map()
    if template_name not in templates:
        return False
    del templates[template_name]
    _write_template_map(templates)
    logger.info("已删除水印模板：%s", template_name)
    return True


def _unique_template_name(requested: str, existing: dict[str, Any]) -> str:
    """为新模板生成不冲突的名称。"""

    if requested not in existing:
        return requested
    index = 2
    while f"{requested}_{index}" in existing:
        index += 1
    return f"{requested}_{index}"


def _build_notes(
    template: dict[str, Any],
    location: str | None,
    rendered_font_available: bool,
) -> list[str]:
    """汇总渲染后的提示信息。"""

    notes = preflight_template(template)
    if not location:
        notes.append("未提供地点，已按“待补”写入，不得臆造陪餐地点。")
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
        variables = build_dynamic_vars(location=location, manual_time=manual_time)
        output_path = render_watermark(
            template=template,
            scene_path=scene,
            dynamic_vars=variables,
        )

        notes = _build_notes(template, location, font_available())
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
