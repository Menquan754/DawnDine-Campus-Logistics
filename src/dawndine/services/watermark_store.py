"""水印模板存储服务（纯业务，与 UI / Agent 框架解耦）。

本文件职责：
- 读写 data/templates/watermark_style_template.json 中的多套模板；
- 校验模板名，写入时采用临时文件 + 原子替换，避免中断造成半文件；
- 提供模板列表、读取、删除、清空与样式更新等 CRUD 能力。

依赖：dawndine.config、dawndine.services.watermark、Python 标准库。
被调用：dawndine.agent.tools.watermark、app.py、测试脚本。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from dawndine.config import DEFAULT_TEMPLATE_NAME, TEMPLATE_FILE, TEMPLATES_DIR
from dawndine.services.watermark import apply_style_overrides

logger = logging.getLogger(__name__)

__all__ = [
    "delete_template",
    "get_template",
    "list_templates",
    "reset_templates",
    "update_template_style",
]

_TEMPLATE_NAME_PATTERN = re.compile(r"^[\w\u4e00-\u9fff-]{1,40}$")


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


def reset_templates() -> int:
    """删除全部水印模板，返回删除数量（用于设置区的 Agent 初始化）。"""

    templates = _read_template_map()
    count = len(templates)
    if count:
        _write_template_map({})
        logger.warning("已清空全部水印模板：%s 个", count)
    return count


def update_template_style(
    template_name: str,
    style_overrides: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """保存模板样式调整（格式/位置/字号/配色/间距）。

    Args:
        template_name: 已存在的模板名。
        style_overrides: 传给 apply_style_overrides 的覆盖项，支持
            format、anchor、font_scale、font_size、color、bg_color、
            bg_opacity、round_radius、layout_gap、date_format、time_format。

    Returns:
        更新后的模板；模板不存在时返回 None。
    """

    name = _safe_template_name(template_name)
    templates = _read_template_map()
    if name not in templates:
        return None
    template = apply_style_overrides(templates[name], style_overrides)
    template["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    templates[name] = template
    _write_template_map(templates)
    logger.info("已更新水印模板样式：%s", name)
    return template


def _unique_template_name(requested: str, existing: dict[str, Any]) -> str:
    """为新模板生成不冲突的名称。"""

    if requested not in existing:
        return requested
    index = 2
    while f"{requested}_{index}" in existing:
        index += 1
    return f"{requested}_{index}"
