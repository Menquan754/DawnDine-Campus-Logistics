"""Pillow 水印解析与绘制底层。

本文件职责：
- 用基础采样和简单规则分析样图的色块位置、主色、字号等参数；
- 按归一化坐标在照片上绘制半透明圆角色块和白色文字；
- 生成时间、日期、中文星期、8 位防伪码，并输出 PNG；
- 检测水印锚点是否落入画面中心 40% 区域。

依赖：constants.py、Pillow。
被调用：tools/watermark.py、测试脚本。
"""

from __future__ import annotations

import copy
import logging
import secrets
import string
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps, ImageStat

from constants import (
    CENTER_AVOID_RATIO,
    DATETIME_FORMAT,
    DEFAULT_FONT_SIZE,
    DEFAULT_TEMPLATE_NAME,
    SYSTEM_FONT_CANDIDATES,
    WATERMARK_DATE_FORMAT,
    WATERMARK_TIME_FORMAT,
    WATERMARKED_DIR,
    WEEKDAY_NAMES,
)

logger = logging.getLogger(__name__)

DEFAULT_BG_COLOR = "#0B6E4F"
DEFAULT_TEXT_COLOR = "#FFFFFF"
DEFAULT_BG_OPACITY = 190
DEFAULT_ROUND_RADIUS = 10
DEFAULT_LOCATION = "待补"
ANTI_COUNTERFEIT_ALPHABET = string.ascii_uppercase + string.digits


# ---------------------------------------------------------------------------
# 字体
# ---------------------------------------------------------------------------
def find_chinese_font() -> Path | None:
    """返回首个可用的中文字体路径；全部缺失时返回 None。"""

    for candidate in SYSTEM_FONT_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def font_available() -> bool:
    """系统中是否存在可用的中文字体。"""

    return find_chinese_font() is not None


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """加载中文字体；缺失时 fallback 到 Pillow 默认字体。"""

    safe_size = max(10, int(size))
    font_path = find_chinese_font()
    if font_path is not None:
        try:
            return ImageFont.truetype(str(font_path), safe_size)
        except OSError:
            logger.warning("中文字体加载失败，回退默认字体：%s", font_path)
    try:
        return ImageFont.load_default(size=safe_size)
    except TypeError:  # Pillow 较老版本
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# 颜色与样图分析
# ---------------------------------------------------------------------------
def _clamp_channel(value: float) -> int:
    """把颜色通道限制在 0—255。"""

    return max(0, min(255, int(round(value))))


def _to_hex(rgb: tuple[int, int, int]) -> str:
    """把 RGB 元组转换为 #RRGGBB。"""

    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _ensure_dark_enough(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """保证色块适合承载白色文字；过亮时整体压暗。"""

    luminance = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    if luminance <= 165:
        return rgb
    factor = 0.55
    return tuple(_clamp_channel(channel * factor) for channel in rgb)  # type: ignore[return-value]


def _sample_region_color(image: Image.Image, box: tuple[int, int, int, int]) -> str | None:
    """对一个区域做量化采样，返回适合作底色的主色；失败返回 None。"""

    try:
        region = image.crop(box)
        if region.width < 4 or region.height < 4:
            return None

        small = region.resize((48, 48), Image.Resampling.LANCZOS).convert("RGB")
        quantized = small.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette() or []
        counts = quantized.getcolors(maxcolors=48 * 48) or []

        candidates: list[tuple[float, tuple[int, int, int]]] = []
        for count, palette_index in counts:
            base = palette_index * 3
            if base + 2 >= len(palette):
                continue
            rgb = (palette[base], palette[base + 1], palette[base + 2])
            brightness = sum(rgb) / 3
            # 排除纯白、纯黑和明显过曝区域。
            if brightness > 238 or brightness < 18:
                continue
            saturation = max(rgb) - min(rgb)
            score = float(count) * (1.0 + min(saturation, 120) / 120.0)
            candidates.append((score, rgb))

        if candidates:
            best = max(candidates, key=lambda item: item[0])[1]
            return _to_hex(_ensure_dark_enough(best))

        # 没有通过筛选的候选色时，退回区域中位数，仍做对比度处理。
        median = ImageStat.Stat(region.resize((24, 24))).median
        rgb = (_clamp_channel(median[0]), _clamp_channel(median[1]), _clamp_channel(median[2]))
        return _to_hex(_ensure_dark_enough(rgb))
    except (OSError, ValueError, IndexError) as exc:
        logger.debug("样图区域取色失败：%s", exc)
        return None


def analyze_sample_image(path: str | Path) -> dict[str, Any]:
    """用基础规则分析水印样图。

    只做区域采样与色块判断，不做 OCR、目标检测或复杂 CV。
    文字内容无法从图片可靠识别，因此 text 统一返回 None，由上层用标准
    标签补齐并由用户确认；坐标全部归一化到 0—1。

    Args:
        path: 样图路径。

    Returns:
        含 fixed_elements、dynamic_vars、canvas 与 meta 的模板骨架。

    Raises:
        FileNotFoundError: 样图不存在。
        ValueError: 文件不是可读图片。
    """

    image_path = Path(path).expanduser().resolve()
    if not image_path.is_file():
        raise FileNotFoundError(f"样图不存在：{image_path}")

    try:
        with Image.open(image_path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, ValueError) as exc:
        raise ValueError(f"样图无法读取：{exc}") from exc

    width, height = image.size
    if width < 80 or height < 80:
        raise ValueError("样图尺寸过小，至少需要 80×80 像素")

    top_box = (0, 0, int(width * 0.38), int(height * 0.22))
    bottom_box = (0, int(height * 0.70), int(width * 0.46), height)
    top_bg = _sample_region_color(image, top_box)
    bottom_bg = _sample_region_color(image, bottom_box)
    color_confidence = "medium" if top_bg and bottom_bg else "low"

    title_size = max(18, round(width * 0.028))
    location_size = max(16, round(width * 0.022))
    detail_size = max(15, round(width * 0.019))
    radius = max(6, round(width * 0.009))
    top_bg = top_bg or DEFAULT_BG_COLOR
    bottom_bg = bottom_bg or DEFAULT_BG_COLOR

    fixed_elements: list[dict[str, Any]] = [
        {
            "role": "title",
            "text": None,
            "color": DEFAULT_TEXT_COLOR,
            "bg_color": top_bg,
            "round_radius": radius,
            "font_size": title_size,
            "x_norm": 0.035,
            "y_norm": 0.035,
        },
        {
            "role": "location",
            "text": None,
            "color": DEFAULT_TEXT_COLOR,
            "bg_color": top_bg,
            "round_radius": radius,
            "font_size": location_size,
            "x_norm": 0.035,
            "y_norm": 0.115,
        },
    ]

    dynamic_vars: dict[str, dict[str, Any]] = {
        "date": {
            "label": "日期：",
            "x_norm": 0.035,
            "y_norm": 0.775,
            "format": WATERMARK_DATE_FORMAT,
            "color": DEFAULT_TEXT_COLOR,
            "bg_color": bottom_bg,
            "round_radius": radius,
            "font_size": detail_size,
        },
        "time": {
            "label": "时间：",
            "x_norm": 0.035,
            "y_norm": 0.835,
            "format": WATERMARK_TIME_FORMAT,
            "color": DEFAULT_TEXT_COLOR,
            "bg_color": bottom_bg,
            "round_radius": radius,
            "font_size": detail_size,
        },
        "anti_counterfeit": {
            "label": "防伪码：",
            "x_norm": 0.035,
            "y_norm": 0.895,
            "format": "",
            "color": DEFAULT_TEXT_COLOR,
            "bg_color": bottom_bg,
            "round_radius": radius,
            "font_size": detail_size,
        },
    }

    return {
        "fixed_elements": fixed_elements,
        "dynamic_vars": dynamic_vars,
        "canvas": {"width": width, "height": height},
        "meta": {
            "source_image": str(image_path),
            "analysis_method": "pillow_region_sampling",
            "ocr_used": False,
            "text_confidence": "low",
            "color_confidence": color_confidence,
            "note": "未做 OCR，固定文字需人工确认；坐标与配色为规则采样初值。",
        },
    }


# ---------------------------------------------------------------------------
# 模板构建与样式覆盖
# ---------------------------------------------------------------------------
def _coerce_float(value: Any, fallback: float) -> float:
    """将任意值转换为 0—1 浮点数，失败时用 fallback。"""

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(0.0, min(1.0, numeric))


def _coerce_int(value: Any, fallback: int, minimum: int = 0) -> int:
    """将任意值转换为整数并限制最小值。"""

    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return fallback


def _coerce_color(value: Any, fallback: str) -> str:
    """校验 #RRGGBB 颜色，失败时用 fallback。"""

    if not isinstance(value, str):
        return fallback
    try:
        ImageColor.getrgb(value)
    except ValueError:
        return fallback
    return value.upper() if value.startswith("#") else value


def _normalize_element(element: Mapping[str, Any], default_text: str) -> dict[str, Any]:
    """规范化单个水印元素，补齐缺失字段。"""

    normalized: dict[str, Any] = {
        "text": str(element.get("text") or default_text),
        "color": _coerce_color(element.get("color"), DEFAULT_TEXT_COLOR),
        "bg_color": _coerce_color(element.get("bg_color"), DEFAULT_BG_COLOR),
        "round_radius": _coerce_int(element.get("round_radius"), DEFAULT_ROUND_RADIUS, 0),
        "font_size": _coerce_int(element.get("font_size"), DEFAULT_FONT_SIZE, 10),
        "x_norm": _coerce_float(element.get("x_norm"), 0.035),
        "y_norm": _coerce_float(element.get("y_norm"), 0.05),
        "bg_opacity": _coerce_int(element.get("bg_opacity"), DEFAULT_BG_OPACITY, 0),
    }
    if element.get("role"):
        normalized["role"] = str(element["role"])
    return normalized


def build_template_from_analysis(
    analysis: Mapping[str, Any],
    template_name: str = DEFAULT_TEMPLATE_NAME,
    sample_image_path: str | Path | None = None,
    user_requirement: str | None = None,
    style_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """把样图分析结果补齐为标准模板。

    样图无法可靠识别文字，因此标题与地点使用标准标签；地点在渲染时
    若未提供会写“待补”，不猜测真实地点。
    """

    raw_fixed = list(analysis.get("fixed_elements") or [])
    raw_dynamic = dict(analysis.get("dynamic_vars") or {})

    def fixed_at(index: int, default_text: str) -> dict[str, Any]:
        item = raw_fixed[index] if index < len(raw_fixed) else {}
        return _normalize_element(item, default_text)

    title = fixed_at(0, "校园食堂陪餐")
    location = fixed_at(1, "地点：{location}")
    title["role"] = "title"
    location["role"] = "location"

    dynamic_defaults: dict[str, dict[str, Any]] = {
        "date": {
            "label": "日期：",
            "x_norm": 0.035,
            "y_norm": 0.775,
            "format": WATERMARK_DATE_FORMAT,
            "color": DEFAULT_TEXT_COLOR,
            "bg_color": DEFAULT_BG_COLOR,
            "round_radius": DEFAULT_ROUND_RADIUS,
            "font_size": 24,
            "bg_opacity": DEFAULT_BG_OPACITY,
        },
        "time": {
            "label": "时间：",
            "x_norm": 0.035,
            "y_norm": 0.835,
            "format": WATERMARK_TIME_FORMAT,
            "color": DEFAULT_TEXT_COLOR,
            "bg_color": DEFAULT_BG_COLOR,
            "round_radius": DEFAULT_ROUND_RADIUS,
            "font_size": 24,
            "bg_opacity": DEFAULT_BG_OPACITY,
        },
        "anti_counterfeit": {
            "label": "防伪码：",
            "x_norm": 0.035,
            "y_norm": 0.895,
            "format": "",
            "color": DEFAULT_TEXT_COLOR,
            "bg_color": DEFAULT_BG_COLOR,
            "round_radius": DEFAULT_ROUND_RADIUS,
            "font_size": 24,
            "bg_opacity": DEFAULT_BG_OPACITY,
        },
    }

    normalized_dynamic: dict[str, Any] = {}
    for key, defaults in dynamic_defaults.items():
        merged = {**defaults, **dict(raw_dynamic.get(key) or {})}
        merged["x_norm"] = _coerce_float(merged.get("x_norm"), defaults["x_norm"])
        merged["y_norm"] = _coerce_float(merged.get("y_norm"), defaults["y_norm"])
        merged["font_size"] = _coerce_int(merged.get("font_size"), defaults["font_size"], 10)
        merged["round_radius"] = _coerce_int(
            merged.get("round_radius"), defaults["round_radius"], 0
        )
        merged["color"] = _coerce_color(merged.get("color"), DEFAULT_TEXT_COLOR)
        merged["bg_color"] = _coerce_color(merged.get("bg_color"), DEFAULT_BG_COLOR)
        merged["bg_opacity"] = _coerce_int(merged.get("bg_opacity"), DEFAULT_BG_OPACITY, 0)
        normalized_dynamic[key] = merged

    canvas = dict(analysis.get("canvas") or {})
    template: dict[str, Any] = {
        "template_name": template_name,
        "source_image": str(sample_image_path or analysis.get("meta", {}).get("source_image", "")),
        "user_requirement": user_requirement or "",
        "canvas": {
            "width": _coerce_int(canvas.get("width"), 1080, 80),
            "height": _coerce_int(canvas.get("height"), 1920, 80),
        },
        "fixed_elements": [title, location],
        "dynamic_vars": normalized_dynamic,
        "meta": {
            "created_by": "analyze_sample_image + rules",
            "text_requires_review": True,
            "sample_note": analysis.get("meta", {}).get("note", ""),
        },
    }
    if style_overrides:
        template = apply_style_overrides(template, style_overrides)
    return template


def apply_style_overrides(
    template: Mapping[str, Any], overrides: Mapping[str, Any] | None
) -> dict[str, Any]:
    """应用人工样式覆盖，返回新模板，不修改原对象。

    支持：
    - 通用样式键：font_size、color、bg_color、round_radius、bg_opacity；
    - font_scale：统一缩放字号；
    - fixed_elements：按索引或 role 合并；
    - dynamic_vars：按 key 合并。
    """

    result = copy.deepcopy(dict(template))
    if not overrides:
        return result

    common_keys = ("color", "bg_color", "round_radius", "bg_opacity")
    for key in common_keys:
        if key in overrides:
            if key in ("color", "bg_color"):
                value = _coerce_color(overrides[key], DEFAULT_BG_COLOR)
            elif key == "bg_opacity":
                value = _coerce_int(overrides[key], DEFAULT_BG_OPACITY, 0)
            else:
                value = _coerce_int(overrides[key], DEFAULT_ROUND_RADIUS, 0)
            for element in result.get("fixed_elements", []):
                element[key] = value
            for config in result.get("dynamic_vars", {}).values():
                config[key] = value

    if "font_size" in overrides:
        size = _coerce_int(overrides["font_size"], DEFAULT_FONT_SIZE, 10)
        for element in result.get("fixed_elements", []):
            element["font_size"] = size
        for config in result.get("dynamic_vars", {}).values():
            config["font_size"] = size

    if "font_scale" in overrides:
        try:
            scale = float(overrides["font_scale"])
        except (TypeError, ValueError):
            scale = 1.0
        scale = max(0.5, min(2.5, scale))
        for element in result.get("fixed_elements", []):
            element["font_size"] = max(10, round(int(element.get("font_size", 24)) * scale))
        for config in result.get("dynamic_vars", {}).values():
            config["font_size"] = max(10, round(int(config.get("font_size", 24)) * scale))

    fixed_overrides = overrides.get("fixed_elements")
    if isinstance(fixed_overrides, list):
        elements = result.get("fixed_elements", [])
        for index, patch in enumerate(fixed_overrides):
            if not isinstance(patch, Mapping):
                continue
            if index < len(elements):
                target = elements[index]
            else:
                role = patch.get("role")
                target = next(
                    (item for item in elements if role and item.get("role") == role),
                    None,
                )
            if target is not None:
                target.update(dict(patch))

    dynamic_overrides = overrides.get("dynamic_vars")
    if isinstance(dynamic_overrides, Mapping):
        for key, patch in dynamic_overrides.items():
            if key in result.get("dynamic_vars", {}) and isinstance(patch, Mapping):
                result["dynamic_vars"][key].update(dict(patch))

    # 覆盖后再次规范化，防止非法颜色或越界坐标。
    result["fixed_elements"] = [
        _normalize_element(item, item.get("text", "")) for item in result.get("fixed_elements", [])
    ]
    return result


# ---------------------------------------------------------------------------
# 动态变量与渲染
# ---------------------------------------------------------------------------
def generate_anti_counterfeit() -> str:
    """生成 8 位大写字母与数字随机防伪码，每次不同。"""

    return "".join(secrets.choice(ANTI_COUNTERFEIT_ALPHABET) for _ in range(8))


def build_dynamic_vars(location: str | None, manual_time: str | None = None) -> dict[str, str]:
    """构造动态水印变量；manual_time 同时决定日期、时间与星期。"""

    if manual_time:
        try:
            moment = datetime.strptime(manual_time, DATETIME_FORMAT)
        except ValueError as exc:
            raise ValueError("manual_time 必须为 YYYY-MM-DD HH:MM 格式") from exc
    else:
        moment = datetime.now()

    date_text = moment.strftime(WATERMARK_DATE_FORMAT)
    weekday = WEEKDAY_NAMES[moment.weekday()]
    return {
        "location": (location or "").strip() or DEFAULT_LOCATION,
        "date": f"{date_text} {weekday}",
        "date_only": date_text,
        "date_iso": moment.strftime("%Y-%m-%d"),
        "time": moment.strftime(WATERMARK_TIME_FORMAT),
        "weekday": weekday,
        "anti_counterfeit": generate_anti_counterfeit(),
    }


def _format_text(raw: Any, variables: Mapping[str, str]) -> str:
    """替换文本中的 {location} 等占位符，未知占位符保持原样。"""

    text = str(raw or "")
    for key, value in variables.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def _rgba(color: str, opacity: int) -> tuple[int, int, int, int]:
    """把十六进制颜色转换为带透明度的 RGBA。"""

    try:
        rgb = ImageColor.getrgb(color)
    except ValueError:
        rgb = ImageColor.getrgb(DEFAULT_BG_COLOR)
    return rgb[0], rgb[1], rgb[2], max(0, min(255, int(opacity)))


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    requested_size: int,
    max_width: int,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """文字过宽时逐步缩小字号，避免越过画面边缘。"""

    size = max(10, int(requested_size))
    font = _load_font(size)
    while size > 10:
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            break
        size = max(10, size - 2)
        font = _load_font(size)
    return font


def _draw_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    config: Mapping[str, Any],
    width: int,
    height: int,
) -> tuple[float, float, float, float] | None:
    """绘制一个圆角标签并返回其归一化边界框。"""

    clean_text = str(text or "").strip()
    if not clean_text:
        return None

    max_text_width = int(width * 0.62)
    font = _fit_font(
        draw,
        clean_text,
        _coerce_int(config.get("font_size"), DEFAULT_FONT_SIZE, 10),
        max_text_width,
    )
    bbox = draw.textbbox((0, 0), clean_text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    padding_x = max(10, round(width * 0.012))
    padding_y = max(6, round(height * 0.009))

    box_width = text_width + padding_x * 2
    box_height = text_height + padding_y * 2
    x = int(_coerce_float(config.get("x_norm"), 0.035) * width)
    y = int(_coerce_float(config.get("y_norm"), 0.05) * height)
    x = max(4, min(x, max(4, width - box_width - 4)))
    y = max(4, min(y, max(4, height - box_height - 4)))

    radius = min(
        _coerce_int(config.get("round_radius"), DEFAULT_ROUND_RADIUS, 0),
        box_height // 2,
    )
    bg = _rgba(
        _coerce_color(config.get("bg_color"), DEFAULT_BG_COLOR),
        _coerce_int(config.get("bg_opacity"), DEFAULT_BG_OPACITY, 0),
    )
    draw.rounded_rectangle(
        (x, y, x + box_width, y + box_height),
        radius=radius,
        fill=bg,
    )

    text_color = _coerce_color(config.get("color"), DEFAULT_TEXT_COLOR)
    try:
        fill = ImageColor.getrgb(text_color)
    except ValueError:
        fill = (255, 255, 255)
    text_xy = (x + padding_x, y + padding_y - bbox[1])
    # 轻微阴影提升复杂照片背景上的可读性。
    draw.text((text_xy[0] + 1, text_xy[1] + 1), clean_text, font=font, fill=(0, 0, 0, 150))
    draw.text(text_xy, clean_text, font=font, fill=(*fill, 255))

    return (
        x / width,
        y / height,
        (x + box_width) / width,
        (y + box_height) / height,
    )


def preflight_template(template: Mapping[str, Any]) -> list[str]:
    """检查模板锚点是否越界或落入画面中心 40%。"""

    warnings: list[str] = []
    left = (1.0 - CENTER_AVOID_RATIO) / 2.0
    right = 1.0 - left
    top = left
    bottom = right

    checks: list[tuple[str, Mapping[str, Any]]] = []
    for index, element in enumerate(template.get("fixed_elements") or []):
        label = str(element.get("text") or element.get("role") or f"固定元素{index + 1}")
        checks.append((label, element))
    for key, config in (template.get("dynamic_vars") or {}).items():
        if isinstance(config, Mapping):
            checks.append((str(config.get("label") or key), config))

    for label, config in checks:
        try:
            x = float(config.get("x_norm"))
            y = float(config.get("y_norm"))
        except (TypeError, ValueError):
            warnings.append(f"“{label}”缺少有效坐标，请人工校准。")
            continue
        if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
            warnings.append(f"“{label}”坐标超出 0—1 范围，可能被裁切。")
        if left <= x <= right and top <= y <= bottom:
            warnings.append(f"“{label}”位于画面中心 40% 区域，可能遮挡关键画面。")
    return warnings


def render_watermark(
    template: Mapping[str, Any],
    scene_path: str | Path,
    dynamic_vars: Mapping[str, str],
    output_dir: str | Path = WATERMARKED_DIR,
) -> str:
    """按模板坐标绘制水印并返回输出 PNG 的绝对路径。

    先绘制 RGBA 半透明圆角色块，再绘制白字；坐标按图片宽高换算。
    输出文件名使用 UUID，避免覆盖历史图片。
    """

    scene = Path(scene_path).expanduser().resolve()
    if not scene.is_file():
        raise FileNotFoundError(f"现场照片不存在：{scene}")

    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        with Image.open(scene) as source:
            base = ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, ValueError) as exc:
        raise ValueError(f"现场照片无法读取：{exc}") from exc

    width, height = base.size
    if width < 80 or height < 80:
        raise ValueError("现场照片尺寸过小，至少需要 80×80 像素")

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    variables = dict(dynamic_vars)
    variables.setdefault("location", DEFAULT_LOCATION)

    if not template.get("fixed_elements") and not template.get("dynamic_vars"):
        raise ValueError("模板为空，至少需要一个水印元素")

    for element in template.get("fixed_elements") or []:
        if not isinstance(element, Mapping):
            continue
        text = _format_text(element.get("text"), variables)
        _draw_text_block(draw, text, element, width, height)

    dynamic_config = template.get("dynamic_vars") or {}
    for key in ("date", "time", "anti_counterfeit"):
        config = dynamic_config.get(key)
        if not isinstance(config, Mapping):
            continue
        value = variables.get(key, "")
        label = str(config.get("label") or "")
        _draw_text_block(draw, f"{label}{value}", config, width, height)

    composed = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    destination = output_path / f"{uuid.uuid4().hex}.png"
    composed.save(destination, format="PNG", optimize=True)
    absolute = str(destination.resolve())
    logger.info("水印图已生成：%s", absolute)
    return absolute
