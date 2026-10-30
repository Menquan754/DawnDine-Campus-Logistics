"""Pillow 水印解析与绘制底层。

本文件职责：
- 用基础采样和简单规则分析样图的色块位置、主色、字号等参数；
- 优先用 qwen3-vl-plus 理解样图文字、配色与时间位置，失败时完整回退规则采样；
- 按四角锚点或归一化坐标在照片上绘制半透明圆角色块和白色文字；
- 同一角的水印元素按组紧贴堆叠，避免元素之间出现大段空白；
- 生成时间、日期、中文星期、8 位防伪码，并输出 PNG；
- 检测水印锚点是否落入画面中心 40% 区域。

依赖：dawndine.config、dawndine.llm、Pillow、langchain-core。
被调用：dawndine.agent.tools.watermark、dawndine.services.schedule、测试脚本。
"""

from __future__ import annotations

import base64
import copy
import io
import json
import logging
import re
import secrets
import string
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps, ImageStat

from dawndine.config import (
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
from dawndine.llm import get_env_api_key, get_vision_llm

logger = logging.getLogger(__name__)

DEFAULT_BG_COLOR = "#0B6E4F"
DEFAULT_TEXT_COLOR = "#FFFFFF"
DEFAULT_BG_OPACITY = 190
DEFAULT_ROUND_RADIUS = 10
DEFAULT_LOCATION = "待补"
DEFAULT_LAYOUT_GAP = 6
# 勾选“不使用地点/时间”时，按占位符识别并跳过对应元素与整行分栏内容。
LOCATION_PLACEHOLDERS = ("{location}",)
TIME_PLACEHOLDERS = ("{date}", "{time}", "{weekday}")
ANCHOR_VALUES: tuple[str, ...] = (
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
    "top-center",
    "bottom-center",
)
ANTI_COUNTERFEIT_ALPHABET = string.ascii_uppercase + string.digits

# 水印文字格式预设：控制显示哪些元素与动态变量。
WATERMARK_FORMAT_PRESETS: dict[str, dict[str, Any]] = {
    "full": {
        "label": "完整（标题+地点+日期+时间+防伪）",
        "roles": ("title", "location"),
        "dynamic": ("date", "time", "anti_counterfeit"),
    },
    "standard": {
        "label": "标准（标题+地点+日期+时间）",
        "roles": ("title", "location"),
        "dynamic": ("date", "time"),
    },
    "compact": {
        "label": "简洁（标题+日期+时间）",
        "roles": ("title",),
        "dynamic": ("date", "time"),
    },
    "datetime": {
        "label": "仅日期时间",
        "roles": (),
        "dynamic": ("date", "time"),
    },
    "location_time": {
        "label": "仅地点+日期时间",
        "roles": ("location",),
        "dynamic": ("date", "time"),
    },
}

DATE_FORMAT_OPTIONS: dict[str, str] = {
    "dot": "%Y.%m.%d",
    "iso": "%Y-%m-%d",
    "cn": "%Y年%m月%d日",
    "short": "%m-%d",
}
TIME_FORMAT_OPTIONS: dict[str, str] = {
    "hm": "%H:%M",
    "hms": "%H:%M:%S",
}


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


_HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
_VL_TIME_X = {"left": 0.035, "center": 0.38, "right": 0.68}
_VL_SAMPLE_SYSTEM_PROMPT = """你是学校食堂水印样图的视觉分析器。
只输出一个 JSON 对象，不要 Markdown 围栏，不要额外解释。字段必须完整：
{
  "title": "图中顶部或明显位置的主标题文字，看不清给空字符串",
  "subtitle": "副标题/说明文字，没有给空字符串",
  "location": "图中能读到的地点文字，读不到给空字符串",
  "time_position": "left|center|right",
  "text_color": "#RRGGBB，主文字颜色",
  "panel_color": "#RRGGBB，半透明底衬颜色",
  "has_existing_watermark": true 或 false,
  "confidence": "high|medium|low"
}
只描述图中真实可见的文字，不要编造地点、日期、机构或人物。
不确定的字段返回空字符串；颜色用十六进制表示，允许近似色。
time_position 只能返回 left、center、right 之一。
"""


def _message_text(message: Any) -> str:
    """从视觉模型消息中提取文本。"""

    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(content or "")


def _image_to_data_uri(path: Path, max_side: int = 1600) -> str:
    """压缩样图并转换为 data URI，避免视觉请求体过大。"""

    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    if max(image.size) > max_side:
        ratio = max_side / max(image.size)
        image = image.resize(
            (max(1, round(image.width * ratio)), max(1, round(image.height * ratio))),
            Image.Resampling.LANCZOS,
        )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=86, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _parse_vl_json(raw: str) -> dict[str, Any]:
    """解析 VL 返回的单对象 JSON。"""

    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("VL 未返回可解析的 JSON 对象") from None
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("VL 返回的 JSON 不是对象")
    return data


def _clean_vl_text(value: Any) -> str:
    """清洗 VL 文本字段，避免把 None/null 写进模板。"""

    if not isinstance(value, str):
        return ""
    clean = value.strip()
    if clean.casefold() in {"none", "null", "nan"}:
        return ""
    return clean


def _valid_hex_color(value: Any) -> str:
    """校验 VL 颜色并返回大写十六进制；非法返回空字符串。"""

    if not isinstance(value, str):
        return ""
    clean = value.strip()
    return clean.upper() if _HEX_COLOR_PATTERN.fullmatch(clean) else ""


def _analyze_sample_vl(image_path: Path) -> dict[str, Any] | None:
    """调用 qwen3-vl-plus 理解样图；任何异常返回 None。"""

    api_key = get_env_api_key()
    if not api_key:
        logger.warning("水印样图 VL 分析跳过：未配置 DASHSCOPE_API_KEY。")
        return None
    try:
        model = get_vision_llm(api_key=api_key)
        response = model.invoke(
            [
                SystemMessage(content=_VL_SAMPLE_SYSTEM_PROMPT),
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": "请分析这张水印样图的文字、配色和已有水印情况。",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": _image_to_data_uri(image_path)},
                        },
                    ]
                ),
            ]
        )
        return _parse_vl_json(_message_text(response))
    except Exception as exc:  # noqa: BLE001 - VL 失败必须回退规则采样
        logger.warning("水印样图 VL 分析失败：%s", type(exc).__name__)
        return None


def _merge_vl_analysis(analysis: dict[str, Any], vl: Mapping[str, Any]) -> None:
    """把 VL 字段合并进规则分析，未识别字段保留规则值。"""

    fixed = list(analysis.get("fixed_elements") or [])
    dynamic = dict(analysis.get("dynamic_vars") or {})
    meta = dict(analysis.get("meta") or {})

    title = _clean_vl_text(vl.get("title"))
    subtitle = _clean_vl_text(vl.get("subtitle"))
    location = _clean_vl_text(vl.get("location"))
    text_color = _valid_hex_color(vl.get("text_color"))
    panel_color = _valid_hex_color(vl.get("panel_color"))
    time_position = str(vl.get("time_position") or "").strip().lower()
    confidence = str(vl.get("confidence") or "").strip().lower()

    if title and fixed:
        fixed[0]["text"] = title
    if location and len(fixed) > 1:
        fixed[1]["text"] = f"地点：{location}"

    if text_color:
        for element in fixed:
            element["color"] = text_color
        for config in dynamic.values():
            config["color"] = text_color
    if panel_color:
        for element in fixed:
            element["bg_color"] = panel_color
        for config in dynamic.values():
            config["bg_color"] = panel_color
    if time_position in _VL_TIME_X:
        for config in dynamic.values():
            config["x_norm"] = _VL_TIME_X[time_position]

    if title and confidence in {"high", "medium"}:
        meta["text_confidence"] = confidence
    if text_color and panel_color and confidence in {"high", "medium"}:
        meta["color_confidence"] = confidence
    meta["analysis_method"] = "qwen3-vl-plus + pillow_region_sampling"
    meta["ocr_used"] = True
    meta["note"] = "qwen3-vl-plus 视觉理解 + 规则采样；文字与配色需人工确认。"
    if subtitle:
        meta["note"] += f" 样图副标题：{subtitle}"
    if vl.get("has_existing_watermark") is True:
        meta["note"] += " 检测到样图已有水印，请人工确认是否需要去除"

    analysis["fixed_elements"] = fixed
    analysis["dynamic_vars"] = dynamic
    analysis["meta"] = meta


def analyze_sample_image(path: str | Path) -> dict[str, Any]:
    """用 qwen3-vl-plus + 基础规则分析水印样图。

    先让视觉模型识别图中真实可见的标题、地点、配色和时间位置；模型不可用、
    无 Key 或返回异常时完整回退到原有 Pillow 区域采样。坐标全部归一化到 0—1。

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

    analysis: dict[str, Any] = {
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

    try:
        vl_analysis = _analyze_sample_vl(image_path)
        if vl_analysis is not None:
            _merge_vl_analysis(analysis, vl_analysis)
    except Exception as exc:  # noqa: BLE001 - VL 任何异常都必须回退规则
        logger.warning("水印样图 VL 合并失败：%s", type(exc).__name__)
    return analysis


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


def _coerce_anchor(value: Any) -> str | None:
    """校验锚点；支持四角与上下居中，非法值返回 None。"""

    if not isinstance(value, str):
        return None
    clean = value.strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "tl": "top-left",
        "tr": "top-right",
        "bl": "bottom-left",
        "br": "bottom-right",
        "left-top": "top-left",
        "right-top": "top-right",
        "left-bottom": "bottom-left",
        "right-bottom": "bottom-right",
        "top": "top-center",
        "bottom": "bottom-center",
        "middle-top": "top-center",
        "middle-bottom": "bottom-center",
        "top-middle": "top-center",
        "bottom-middle": "bottom-center",
    }
    clean = aliases.get(clean, clean)
    return clean if clean in ANCHOR_VALUES else None


def _infer_anchor(x_norm: Any, y_norm: Any) -> str | None:
    """根据旧模板坐标推断四角锚点，兼容历史模板。

    只有明显靠近边缘的坐标才会被推断为锚点；居中元素仍按自由坐标绘制。
    这样旧模板（如 x=0.035 / 0.62）无需手工改 JSON 也能自动贴角。
    """

    x = _coerce_float(x_norm, 0.5)
    y = _coerce_float(y_norm, 0.5)
    horizontal = "left" if x <= 0.15 else "right" if x >= 0.55 else None
    vertical = "top" if y <= 0.18 else "bottom" if y >= 0.55 else None
    if horizontal is not None and vertical is not None:
        return f"{vertical}-{horizontal}"
    return None


def _resolve_anchor(config: Mapping[str, Any]) -> str | None:
    """优先读取显式 anchor，其次从 x_norm / y_norm 推断。"""

    explicit = _coerce_anchor(config.get("anchor"))
    if explicit is not None:
        return explicit
    return _infer_anchor(config.get("x_norm"), config.get("y_norm"))


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
    anchor = _coerce_anchor(element.get("anchor"))
    if anchor is not None:
        normalized["anchor"] = anchor
    if element.get("role"):
        normalized["role"] = str(element["role"])
    return normalized


_LAYOUT_X = {"left": 0.035, "center": 0.34, "right": 0.965}
_LAYOUT_TOP_Y = {
    "title": 0.035,
    "location": 0.10,
    "date": 0.165,
    "time": 0.23,
    "anti": 0.30,
}
_LAYOUT_BOTTOM_Y = {
    "title": 0.62,
    "location": 0.70,
    "date": 0.74,
    "time": 0.81,
    "anti": 0.88,
}
_LAYOUT_TARGETS = ("title", "location", "date", "time", "anti")
_LAYOUT_ALL_WORDS = ("水印", "整体", "全部", "所有", "整个")
_LAYOUT_NEGATIVE_WORDS = ("不要", "别", "避免", "不能", "勿", "不挡")
_LAYOUT_DETAIL_WORDS = ("打卡信息", "时间信息", "底部信息")
_LAYOUT_TIGHT_WORDS = (
    "紧靠",
    "紧凑",
    "挨着",
    "贴着",
    "贴在一起",
    "靠在一起",
    "连在一起",
    "间距小",
    "间距调小",
    "间距太远",
    "间距太大",
    "太远了",
    "不要间距",
    "不留间距",
)
_LAYOUT_LOOSE_WORDS = ("间距大", "间隔大", "分开一点", "留点间距", "拉开一点")
_LAYOUT_COLOR_WORDS = {
    "深蓝色": "#0B2E4F",
    "深蓝": "#0B2E4F",
    "藏青色": "#0B1F33",
    "浅蓝色": "#4FBDF9",
    "蓝色": "#1565C0",
    "白色": "#FFFFFF",
    "黑色": "#111111",
    "深绿色": "#0B6E4F",
    "绿色": "#2E7D32",
    "红色": "#B71C1C",
    "黄色": "#F9A825",
}
_LAYOUT_COLOR_PATTERN = re.compile(
    "|".join(re.escape(word) for word in sorted(_LAYOUT_COLOR_WORDS, key=len, reverse=True))
)


def _layout_clauses(text: str) -> list[str]:
    """按中文标点拆分位置要求，保留同一分句内的多个元素。"""

    clauses: list[str] = []
    for chunk in re.split(r"[，,。；;\n]+", text or ""):
        clean = chunk.strip()
        if not clean:
            continue
        parts = [part.strip() for part in clean.split("、") if part.strip()]
        if len(parts) > 1 and sum(1 for part in parts if _layout_position(part) is not None) >= 2:
            clauses.extend(parts)
        else:
            clauses.append(clean)
    return clauses


def _layout_targets(clause: str) -> set[str]:
    """从分句中识别需要移动的元素；未指定时返回空集合。"""

    text = re.sub(r"\s+", "", clause)
    if any(word in text for word in _LAYOUT_ALL_WORDS):
        return set(_LAYOUT_TARGETS)

    targets: set[str] = set()
    if any(word in text for word in ("标题", "主标题", "校园食堂陪餐", "食堂陪餐", "陪餐打卡")):
        targets.add("title")
    if "地点" in text or "地址" in text:
        targets.add("location")
    if "打卡时间" in text:
        targets.update({"date", "time"})
    else:
        if "日期" in text:
            targets.add("date")
        if "时间" in text:
            targets.add("time")
    if "防伪" in text or "编码" in text:
        targets.add("anti")
    if any(word in text for word in _LAYOUT_DETAIL_WORDS):
        targets.update({"date", "time", "anti"})
    return targets


def _layout_color_roles(clause: str) -> list[tuple[str, str]]:
    """识别文字/底色颜色要求，返回 [(role, #RRGGBB)]。"""

    text = re.sub(r"\s+", "", clause)
    roles: list[tuple[str, str]] = []
    for match in _LAYOUT_COLOR_PATTERN.finditer(text):
        word = match.group(0)
        color = _LAYOUT_COLOR_WORDS[word]
        tail = text[match.end() : match.end() + 8]
        if any(word in tail for word in ("底色", "背景", "底衬", "底")):
            role = "panel"
        elif any(word in tail for word in ("文字", "字体", "字")):
            role = "text"
        else:
            rgb = ImageColor.getrgb(color)
            role = "text" if sum(rgb) / 3 > 190 else "panel"
        roles.append((role, color))
    return roles


def _layout_position(clause: str) -> tuple[str | None, str | None] | None:
    """从分句识别 (水平位置, 垂直位置)，无法识别返回 None。"""

    text = re.sub(r"\s+", "", clause)
    if any(word in text for word in _LAYOUT_NEGATIVE_WORDS):
        return None

    corner = re.search(r"(左上|右上|左下|右下)", text)
    if corner:
        mapping = {
            "左上": ("left", "top"),
            "右上": ("right", "top"),
            "左下": ("left", "bottom"),
            "右下": ("right", "bottom"),
        }
        return mapping[corner.group(1)]

    vertical: str | None = None
    if any(
        word in text for word in ("顶部", "上方", "上边", "顶边", "上部", "靠上", "偏上", "最上")
    ):
        vertical = "top"
    elif any(
        word in text for word in ("底部", "下方", "下边", "底边", "下部", "靠下", "偏下", "最下")
    ):
        vertical = "bottom"

    horizontal: str | None = None
    if "左" in text:
        horizontal = "left"
    elif "右" in text:
        horizontal = "right"
    elif any(word in text for word in ("居中", "中间", "中心", "正中", "中央")):
        horizontal = "center"

    if vertical is not None or horizontal is not None:
        return horizontal, vertical
    return None


def _layout_refs(template: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """返回模板中可移动元素的可变引用。"""

    refs: dict[str, dict[str, Any]] = {}
    fixed = list(template.get("fixed_elements") or [])
    if fixed:
        refs["title"] = fixed[0]
    if len(fixed) > 1:
        refs["location"] = fixed[1]
    dynamic = dict(template.get("dynamic_vars") or {})
    for key in ("date", "time", "anti_counterfeit"):
        if key in dynamic:
            refs["anti" if key == "anti_counterfeit" else key] = dynamic[key]
    return refs


def _place_item(
    item: dict[str, Any],
    name: str,
    horizontal: str | None,
    vertical: str | None,
) -> None:
    """把一个元素放到指定角落；缺省方向按现有坐标推断。"""

    x_norm = _coerce_float(item.get("x_norm"), 0.035)
    y_norm = _coerce_float(item.get("y_norm"), 0.05)
    if horizontal is None:
        horizontal = "left" if x_norm <= 0.5 else "right"
    if vertical is None:
        vertical = "top" if y_norm <= 0.5 else "bottom"

    if horizontal == "center":
        item.pop("anchor", None)
        item["x_norm"] = _LAYOUT_X["center"]
        item["y_norm"] = _LAYOUT_TOP_Y[name] if vertical == "top" else _LAYOUT_BOTTOM_Y[name]
        return

    # 四角锚点在渲染时按实际图片尺寸精确贴边，比固定 0.62 更靠边。
    item["anchor"] = f"{vertical}-{horizontal}"
    item["x_norm"] = _LAYOUT_X[horizontal]
    item["y_norm"] = _LAYOUT_TOP_Y[name] if vertical == "top" else _LAYOUT_BOTTOM_Y[name]


def _layout_gap_requirement(clause: str) -> int | None:
    """识别“紧靠/间距太大”等间距要求，返回渲染间距像素。"""

    text = re.sub(r"\s+", "", clause or "")
    if any(word in text for word in _LAYOUT_TIGHT_WORDS):
        return 2
    if any(word in text for word in _LAYOUT_LOOSE_WORDS):
        return 14
    return None


def apply_layout_requirement(
    template: Mapping[str, Any],
    requirement: str | None,
) -> dict[str, Any]:
    """按自然语言位置/配色要求调整水印，返回新模板。

    支持常见中文表达：
    - 左上/右上/左下/右下（写入四角锚点，渲染时精确贴边）；
    - 顶部、底部、左侧、右侧、居中；
    - 标题、地点、日期、时间、防伪码、整体/水印；
    - “紧靠/紧凑/间距太大”等元素间距描述；
    - 深蓝色底色、白色文字等常见配色描述。
    """

    result = copy.deepcopy(dict(template))
    if not requirement or not requirement.strip():
        return result

    refs = _layout_refs(result)
    applied = False
    active_position: tuple[str | None, str | None] | None = None

    for clause in _layout_clauses(requirement):
        position = _layout_position(clause)
        targets = _layout_targets(clause)

        if position is not None:
            active_position = position
            layout_targets = targets or set(_LAYOUT_TARGETS)
            horizontal, vertical = position
            for name in layout_targets:
                item = refs.get(name)
                if item is None:
                    continue
                _place_item(item, name, horizontal, vertical)
                applied = True
        elif active_position is not None and targets:
            # “带上防伪编码”“地点信息等”这类省略位置的后续描述，
            # 沿用最近一次明确位置。
            horizontal, vertical = active_position
            for name in targets:
                item = refs.get(name)
                if item is None:
                    continue
                _place_item(item, name, horizontal, vertical)
                applied = True

        gap = _layout_gap_requirement(clause)
        if gap is not None:
            result.setdefault("meta", {})["layout_gap"] = gap
            applied = True

        color_roles = _layout_color_roles(clause)
        if color_roles:
            for role, color in color_roles:
                for name in _LAYOUT_TARGETS:
                    item = refs.get(name)
                    if item is None:
                        continue
                    if role == "text":
                        item["color"] = color
                    else:
                        item["bg_color"] = color
            applied = True

    if applied:
        meta = dict(result.get("meta") or {})
        note = str(meta.get("sample_note") or "").strip()
        suffix = "已按描述调整水印位置/样式。"
        meta["sample_note"] = f"{note} {suffix}".strip()
        result["meta"] = meta
    return result


def build_template_from_analysis(
    analysis: Mapping[str, Any],
    template_name: str = DEFAULT_TEMPLATE_NAME,
    sample_image_path: str | Path | None = None,
    user_requirement: str | None = None,
    style_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """把样图分析结果补齐为标准模板。

    样图无法可靠识别文字，因此标题与地点使用标准标签；地点在渲染时
    若未提供会写“待补”，不猜测真实地点。user_requirement 中的位置描述会
    在标准模板之后应用，style_overrides 仍保留最终覆盖优先级。
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
    template = apply_layout_requirement(template, user_requirement)
    if style_overrides:
        template = apply_style_overrides(template, style_overrides)
    return template


_ANCHOR_LABELS = {
    "top-left": "左上角",
    "top-right": "右上角",
    "bottom-left": "左下角",
    "bottom-right": "右下角",
    "top-center": "顶部居中",
    "bottom-center": "底部居中",
}
_DATE_FORMAT_LABELS = {
    "dot": "2026.10.28",
    "iso": "2026-10-28",
    "cn": "2026年10月28日",
    "short": "10-28",
}
_TIME_FORMAT_LABELS = {"hm": "14:30", "hms": "14:30:05"}


def _restore_format_content(template: dict[str, Any]) -> None:
    """若模板应用过格式预设，先还原完整元素，保证格式切换可逆。

    格式预设会把暂时不显示的元素从模板里裁掉；这里用 meta.format_backup
    找回完整内容，样式调整才能作用到所有元素上。
    """

    meta = template.get("meta")
    if not isinstance(meta, Mapping):
        return
    backup = meta.get("format_backup")
    if not isinstance(backup, Mapping):
        return
    fixed = backup.get("fixed_elements")
    dynamic = backup.get("dynamic_vars")
    if isinstance(fixed, list):
        template["fixed_elements"] = [dict(item) for item in fixed if isinstance(item, Mapping)]
    if isinstance(dynamic, Mapping):
        template["dynamic_vars"] = {
            str(name): dict(config)
            for name, config in dynamic.items()
            if isinstance(config, Mapping)
        }


def _store_format_content(template: dict[str, Any]) -> None:
    """把当前完整元素快照写入 meta.format_backup，供后续切换格式还原。"""

    meta = template.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        template["meta"] = meta
    meta["format_backup"] = {
        "fixed_elements": copy.deepcopy(list(template.get("fixed_elements") or [])),
        "dynamic_vars": copy.deepcopy(dict(template.get("dynamic_vars") or {})),
    }


def describe_template_style(template: Mapping[str, Any]) -> str:
    """概括模板当前的格式、位置、字号、配色与日期时间格式，用于 UI 回显。"""

    meta = template.get("meta")
    if not isinstance(meta, Mapping):
        meta = {}

    parts: list[str] = []
    format_key = str(meta.get("format") or "").strip().lower()
    preset = WATERMARK_FORMAT_PRESETS.get(format_key)
    columns = meta.get("columns")
    has_columns = isinstance(columns, list) and bool(columns)
    if has_columns:
        parts.append("内容：内容栏1 / 内容栏2（用户自定义文字）")
    else:
        parts.append(f"内容：{preset['label'] if preset else '按样图自定义'}")
    if has_columns:
        column_desc = "；".join(
            f"{_ANCHOR_LABELS.get(str(item.get('anchor')), str(item.get('anchor')))}"
            f" {len(item.get('lines') or [])} 行"
            for item in columns
            if isinstance(item, Mapping)
        )
        parts.append(f"分栏：{column_desc}")

    elements = [item for item in template.get("fixed_elements") or [] if isinstance(item, Mapping)]
    dynamic = {
        str(name): config
        for name, config in (template.get("dynamic_vars") or {}).items()
        if isinstance(config, Mapping)
    }
    anchors = [_resolve_anchor(item) for item in elements]
    anchors.extend(_resolve_anchor(config) for config in dynamic.values())
    used = {anchor for anchor in anchors if anchor}
    if used:
        label = "、".join(_ANCHOR_LABELS.get(anchor, anchor) for anchor in sorted(used))
        if any(anchor is None for anchor in anchors):
            label += "（部分元素按样图坐标）"
        parts.append(f"位置：{label}")
    else:
        parts.append("位置：按样图坐标")

    sizes = [_coerce_int(item.get("font_size"), DEFAULT_FONT_SIZE, 10) for item in elements] + [
        _coerce_int(config.get("font_size"), DEFAULT_FONT_SIZE, 10) for config in dynamic.values()
    ]
    if sizes:
        low, high = min(sizes), max(sizes)
        parts.append(f"字号：{low}" if low == high else f"字号：{low}—{high}")

    gap = meta.get("layout_gap")
    if gap is None:
        parts.append("间距：默认紧贴（随图片尺寸约 3—8 px）")
    else:
        parts.append(f"间距：{_coerce_int(gap, DEFAULT_LAYOUT_GAP, 0)} px")

    colors = [str(item.get("color") or DEFAULT_TEXT_COLOR) for item in elements] + [
        str(config.get("color") or DEFAULT_TEXT_COLOR) for config in dynamic.values()
    ]
    backgrounds = [str(item.get("bg_color") or DEFAULT_BG_COLOR) for item in elements] + [
        str(config.get("bg_color") or DEFAULT_BG_COLOR) for config in dynamic.values()
    ]
    if colors and backgrounds:
        text_color = max(set(colors), key=colors.count)
        bg_color = max(set(backgrounds), key=backgrounds.count)
        parts.append(f"配色：{text_color} 字 / {bg_color} 底")

    date_key = str(meta.get("date_format") or "dot").strip().lower()
    time_key = str(meta.get("time_format") or "hm").strip().lower()
    parts.append(
        f"日期：{_DATE_FORMAT_LABELS.get(date_key, _DATE_FORMAT_LABELS['dot'])}"
        f"；时间：{_TIME_FORMAT_LABELS.get(time_key, _TIME_FORMAT_LABELS['hm'])}"
    )
    return "；".join(parts)


def apply_watermark_format(template: Mapping[str, Any], format_key: str | None) -> dict[str, Any]:
    """按预设切换水印显示内容，返回新模板，不修改原对象。

    Args:
        template: 已生成的水印模板。
        format_key: full/standard/compact/datetime/location_time；未知值原样返回。

    Returns:
        过滤固定元素和动态变量后的模板；meta.format 记录当前预设。

    Raises:
        ValueError: 过滤后没有任何可绘制元素。
    """

    result = copy.deepcopy(dict(template))
    key = str(format_key or "").strip().lower()
    preset = WATERMARK_FORMAT_PRESETS.get(key)
    if preset is None:
        return result

    # 先还原完整内容，再按新预设过滤；快照保证“简洁 → 完整”可切回。
    _restore_format_content(result)
    _store_format_content(result)

    allowed_roles = set(preset["roles"])
    allowed_dynamic = set(preset["dynamic"])
    kept_elements: list[dict[str, Any]] = []
    for element in result.get("fixed_elements") or []:
        role = str(element.get("role") or "").strip()
        if role and role not in allowed_roles:
            continue
        kept_elements.append(dict(element))
    result["fixed_elements"] = kept_elements
    result["dynamic_vars"] = {
        name: dict(config)
        for name, config in (result.get("dynamic_vars") or {}).items()
        if name in allowed_dynamic
    }
    if not result["fixed_elements"] and not result["dynamic_vars"]:
        raise ValueError(f"水印格式 {key} 过滤后没有可绘制内容。")

    result.setdefault("meta", {})["format"] = key
    # 统一走一次规范化，保证颜色、锚点、字号仍合法。
    result["fixed_elements"] = [
        _normalize_element(item, item.get("text", "")) for item in result["fixed_elements"]
    ]
    for config in result["dynamic_vars"].values():
        anchor = _coerce_anchor(config.get("anchor"))
        if anchor is None:
            config.pop("anchor", None)
        else:
            config["anchor"] = anchor
    return result


COLUMN_POSITION_DEFAULT = {"left": "top-left", "right": "top-right"}
_COLUMN_LINE_PREFIX = re.compile(r"^\s*(?:[-•·*]|\d+\s*[.、)）])\s*")


def parse_column_lines(raw: Any) -> list[str]:
    """把一栏内容拆成多条水印文字，保留输入顺序（先写的在上方）。"""

    if isinstance(raw, (list, tuple)):
        candidates = [str(item) for item in raw]
    else:
        candidates = str(raw or "").splitlines()
    lines: list[str] = []
    for candidate in candidates:
        clean = _COLUMN_LINE_PREFIX.sub("", str(candidate or "")).strip()
        if clean:
            lines.append(clean)
    return lines


def _column_base_style(template: Mapping[str, Any]) -> dict[str, Any]:
    """沿用模板里第一个元素的配色与字号，作为分栏条目的默认样式。"""

    for element in template.get("fixed_elements") or []:
        if not isinstance(element, Mapping):
            continue
        return {
            "color": _coerce_color(element.get("color"), DEFAULT_TEXT_COLOR),
            "bg_color": _coerce_color(element.get("bg_color"), DEFAULT_BG_COLOR),
            "round_radius": _coerce_int(element.get("round_radius"), DEFAULT_ROUND_RADIUS, 0),
            "font_size": _coerce_int(element.get("font_size"), DEFAULT_FONT_SIZE, 10),
            "bg_opacity": _coerce_int(element.get("bg_opacity"), DEFAULT_BG_OPACITY, 0),
        }
    return {
        "color": DEFAULT_TEXT_COLOR,
        "bg_color": DEFAULT_BG_COLOR,
        "round_radius": DEFAULT_ROUND_RADIUS,
        "font_size": DEFAULT_FONT_SIZE,
        "bg_opacity": DEFAULT_BG_OPACITY,
    }


def _parse_columns(columns: Any) -> list[dict[str, Any]]:
    """解析分栏配置，过滤空栏并统一锚点。"""

    parsed: list[dict[str, Any]] = []
    if not isinstance(columns, Sequence) or isinstance(columns, (str, bytes)):
        return parsed
    for index, column in enumerate(columns):
        if not isinstance(column, Mapping):
            continue
        anchor = _coerce_anchor(column.get("anchor"))
        if anchor is None:
            side = "left" if index == 0 else "right"
            anchor = COLUMN_POSITION_DEFAULT[side]
        lines = parse_column_lines(column.get("text") or column.get("lines"))
        if not lines:
            continue
        parsed.append({"anchor": anchor, "lines": lines})
        if len(parsed) >= 2:
            break
    return parsed


def apply_watermark_columns(
    template: Mapping[str, Any], columns: Sequence[Mapping[str, Any]] | None
) -> dict[str, Any]:
    """按左右分栏内容重建水印：每条内容一行，顺序即从上到下的堆叠顺序。

    Args:
        template: 已生成的水印模板。
        columns: 分栏列表，每项形如 {"anchor": "bottom-left", "text": "第一行\\n第二行"}；
            传入空列表表示清除分栏、还原模板原始内容。

    Returns:
        新模板：fixed_elements 为分栏文字（含 {location}/{date}/{time} 等占位符），
        动态变量清空，meta.columns 记录当前分栏；清除时还原 content_backup。
    """

    result = copy.deepcopy(dict(template))
    _restore_format_content(result)
    meta = result.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        result["meta"] = meta

    parsed = _parse_columns(columns)
    backup = meta.get("content_backup")
    if not parsed and not isinstance(backup, Mapping):
        # 模板从未用过左右分栏，清除操作按无操作处理，避免误清快照与字号基准。
        return result
    if not isinstance(backup, Mapping):
        backup = {
            "fixed_elements": copy.deepcopy(list(result.get("fixed_elements") or [])),
            "dynamic_vars": copy.deepcopy(dict(result.get("dynamic_vars") or {})),
            "format": meta.get("format"),
            "layout_gap": meta.get("layout_gap"),
        }

    if not parsed:
        # 清除分栏：还原原始内容，并清掉与分栏相关的快照与基准。
        result["fixed_elements"] = copy.deepcopy(list(backup.get("fixed_elements") or []))
        result["dynamic_vars"] = copy.deepcopy(dict(backup.get("dynamic_vars") or {}))
        if backup.get("layout_gap") is not None:
            meta["layout_gap"] = backup["layout_gap"]
        saved_format = backup.get("format")
        if isinstance(saved_format, str) and saved_format.strip():
            meta["format"] = saved_format
        else:
            meta.pop("format", None)
        for key in ("columns", "content_backup", "format_backup", "base_font_sizes"):
            meta.pop(key, None)
        return result

    if not isinstance(backup.get("fixed_elements"), list) and result.get("fixed_elements"):
        backup["fixed_elements"] = copy.deepcopy(list(result.get("fixed_elements") or []))
    meta["content_backup"] = backup

    base = _column_base_style(result)
    elements: list[dict[str, Any]] = []
    for column in parsed:
        for line in column["lines"]:
            item = dict(base)
            item["text"] = line
            item["anchor"] = column["anchor"]
            elements.append(item)

    result["fixed_elements"] = [_normalize_element(item, item.get("text", "")) for item in elements]
    # 分栏模式由用户显式定义内容，不再叠加动态日期/时间/防伪块。
    result["dynamic_vars"] = {}
    meta["columns"] = parsed
    meta.pop("format", None)
    meta.pop("format_backup", None)
    meta.pop("base_font_sizes", None)
    return result


def attach_column_lines(
    columns: Sequence[Mapping[str, Any]] | None,
    lines: Sequence[str],
    column: int = 1,
    position: str = "bottom",
) -> list[dict[str, Any]] | None:
    """把地点/时间等附加行并入指定内容栏的最上面或最下面。

    Args:
        columns: 形如 [{"anchor": ..., "text": ...}, ...]，可为空。
        lines: 要附加的行，例如 "地点：{location}"、"{date} {time}"；空行忽略。
        column: 目标内容栏序号，从 1 开始；超出范围时并入最后一栏。
        position: "top" 为最上面，"bottom" 为最下面。

    Returns:
        合并后的新列表；columns 为空或没有可附加的行时返回 None。
    """

    extra = [str(line).strip() for line in lines or () if str(line).strip()]
    if not columns or not extra:
        return None

    result: list[dict[str, Any]] = []
    for item in columns:
        if not isinstance(item, Mapping):
            continue
        result.append({"anchor": item.get("anchor"), "text": str(item.get("text") or "")})
    if not result:
        return None

    try:
        index = int(column) - 1
    except (TypeError, ValueError):
        index = 0
    index = max(0, min(index, len(result) - 1))

    base = parse_column_lines(result[index]["text"])
    merged = extra + base if str(position).strip().lower() == "top" else base + extra
    result[index]["text"] = "\n".join(merged)
    return result


def apply_style_overrides(
    template: Mapping[str, Any], overrides: Mapping[str, Any] | None
) -> dict[str, Any]:
    """应用人工样式覆盖，返回新模板，不修改原对象。

    支持：
    - 通用样式键：font_size、color、bg_color、round_radius、bg_opacity；
    - font_scale：统一缩放字号；
    - format：按预设切换水印内容（full/standard/compact/datetime/location_time）；
    - date_format / time_format：日期与时间显示格式；
    - columns：左右分栏内容，形如 [{"anchor": ..., "text": ...}, ...]；空列表清除分栏；
    - left_content/left_anchor/right_content/right_anchor：分栏内容的简写；
    - fixed_elements：按索引或 role 合并；
    - dynamic_vars：按 key 合并。
    """

    result = copy.deepcopy(dict(template))
    if not overrides:
        return result

    # 样式应作用到全部元素上，先还原格式预设裁掉的隐藏元素。
    _restore_format_content(result)

    # 先应用左右分栏，后续配色/字号/位置才能作用到用户自己写的内容上。
    columns: Any = overrides.get("columns")
    if columns is None and ("left_content" in overrides or "right_content" in overrides):
        columns = [
            {"text": overrides.get("left_content"), "anchor": overrides.get("left_anchor")},
            {"text": overrides.get("right_content"), "anchor": overrides.get("right_anchor")},
        ]
    columns_applied = False
    if columns is not None:
        result = apply_watermark_columns(result, columns)
        columns_applied = True

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
        # 绝对字号已重置，后续倍率以新字号为基准。
        if isinstance(result.get("meta"), dict):
            result["meta"].pop("base_font_sizes", None)

    if "font_scale" in overrides:
        try:
            scale = float(overrides["font_scale"])
        except (TypeError, ValueError):
            scale = 1.0
        scale = max(0.5, min(2.5, scale))
        meta = result.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            result["meta"] = meta
        bases = meta.get("base_font_sizes")
        if not isinstance(bases, dict):
            bases = {}

        def _scaled(config: Mapping[str, Any], key: str) -> int:
            """按首次记录的字号基准缩放，避免多次保存不断叠加。"""

            base = bases.get(key)
            if not isinstance(base, (int, float)) or base < 10:
                base = _coerce_int(config.get("font_size"), DEFAULT_FONT_SIZE, 10)
                bases[key] = base
            return max(10, round(float(base) * scale))

        for index, element in enumerate(result.get("fixed_elements", [])):
            key = f"fixed:{element.get('role') or index}"
            element["font_size"] = _scaled(element, key)
        for name, config in (result.get("dynamic_vars") or {}).items():
            config["font_size"] = _scaled(config, f"dynamic:{name}")
        meta["base_font_sizes"] = bases

    if "anchor" in overrides:
        anchor = _coerce_anchor(overrides["anchor"])
        for element in result.get("fixed_elements", []):
            if anchor is None:
                element.pop("anchor", None)
            else:
                element["anchor"] = anchor
        for config in result.get("dynamic_vars", {}).values():
            if anchor is None:
                config.pop("anchor", None)
            else:
                config["anchor"] = anchor

    if "layout_gap" in overrides:
        result.setdefault("meta", {})["layout_gap"] = _coerce_int(
            overrides["layout_gap"], DEFAULT_LAYOUT_GAP, 0
        )

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

    format_key = overrides.get("format", overrides.get("watermark_format"))
    if columns_applied:
        # 分栏内容由用户完全指定，不再按内容预设裁剪。
        format_key = None
    elif not (isinstance(format_key, str) and format_key.strip()):
        meta = result.get("meta")
        stored = meta.get("format") if isinstance(meta, Mapping) else None
        format_key = stored if isinstance(stored, str) and stored.strip() else None

    # 先记录完整内容快照，再按格式过滤，保证“简洁 → 完整”能切回来。
    _store_format_content(result)
    if isinstance(format_key, str) and format_key.strip():
        result = apply_watermark_format(result, format_key)

    for key in ("date_format", "time_format"):
        if key in overrides:
            value = str(overrides[key] or "").strip().lower()
            if value:
                result.setdefault("meta", {})[key] = value

    # 覆盖后再次规范化，防止非法颜色、非法锚点或越界坐标。
    result["fixed_elements"] = [
        _normalize_element(item, item.get("text", "")) for item in result.get("fixed_elements", [])
    ]
    for config in result.get("dynamic_vars", {}).values():
        anchor = _coerce_anchor(config.get("anchor"))
        if anchor is None:
            config.pop("anchor", None)
        else:
            config["anchor"] = anchor
    return result


# ---------------------------------------------------------------------------
# 动态变量与渲染
# ---------------------------------------------------------------------------
def generate_anti_counterfeit() -> str:
    """生成 8 位大写字母与数字随机防伪码，每次不同。"""

    return "".join(secrets.choice(ANTI_COUNTERFEIT_ALPHABET) for _ in range(8))


def build_dynamic_vars(
    location: str | None,
    manual_time: str | None = None,
    date_format: str | None = None,
    time_format: str | None = None,
) -> dict[str, str]:
    """构造动态水印变量；manual_time 同时决定日期、时间与星期。

    Args:
        location: 现场地点；空值写“待补”。
        manual_time: 手动指定时间，格式 YYYY-MM-DD HH:MM；空值取当前时间。
        date_format: dot/iso/cn/short，控制日期显示样式。
        time_format: hm/hms，控制是否显示秒。

    Returns:
        含 location、date、date_only、date_iso、time、weekday、anti_counterfeit 的字典。
    """

    if manual_time:
        try:
            moment = datetime.strptime(manual_time, DATETIME_FORMAT)
        except ValueError as exc:
            raise ValueError("manual_time 必须为 YYYY-MM-DD HH:MM 格式") from exc
    else:
        moment = datetime.now()

    date_pattern = DATE_FORMAT_OPTIONS.get(str(date_format or "dot"), WATERMARK_DATE_FORMAT)
    time_pattern = TIME_FORMAT_OPTIONS.get(str(time_format or "hm"), WATERMARK_TIME_FORMAT)
    date_text = moment.strftime(date_pattern)
    weekday = WEEKDAY_NAMES[moment.weekday()]
    return {
        "location": (location or "").strip() or DEFAULT_LOCATION,
        "date": f"{date_text} {weekday}",
        "date_only": date_text,
        "date_iso": moment.strftime("%Y-%m-%d"),
        "time": moment.strftime(time_pattern),
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


def _measure_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    config: Mapping[str, Any],
    width: int,
    height: int,
) -> dict[str, Any]:
    """计算一个圆角标签的尺寸，不落笔。"""

    max_text_width = int(width * 0.62)
    font = _fit_font(
        draw,
        text,
        _coerce_int(config.get("font_size"), DEFAULT_FONT_SIZE, 10),
        max_text_width,
    )
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    padding_x = max(10, round(width * 0.012))
    padding_y = max(6, round(height * 0.009))
    return {
        "text": text,
        "config": config,
        "font": font,
        "bbox": bbox,
        "width": text_width + padding_x * 2,
        "height": text_height + padding_y * 2,
        "padding_x": padding_x,
        "padding_y": padding_y,
        "x": 0,
        "y": 0,
    }


def _layout_margin(width: int, height: int) -> int:
    """返回水印离图片边缘的最小留白。"""

    return max(8, min(40, round(min(width, height) * 0.02)))


def _layout_gap(template: Mapping[str, Any], width: int, height: int) -> int:
    """返回同一角水印元素之间的间距；默认紧贴但保留可读间隔。"""

    meta = template.get("meta")
    if isinstance(meta, Mapping) and meta.get("layout_gap") is not None:
        return min(48, _coerce_int(meta.get("layout_gap"), DEFAULT_LAYOUT_GAP, 0))
    # 默认紧贴：768×1024 约 3px，大图也不会超过 8px。
    return max(2, min(8, round(min(width, height) * 0.004)))


def _is_field_omitted(element: Mapping[str, Any], omitted: frozenset[str]) -> bool:
    """判断固定元素是否因未勾选“地点/时间”而需要跳过。"""

    if not omitted:
        return False
    role = str(element.get("role") or "").strip()
    text = str(element.get("text") or "")
    if "location" in omitted and (
        role == "location" or any(token in text for token in LOCATION_PLACEHOLDERS)
    ):
        return True
    if "time" in omitted and any(token in text for token in TIME_PLACEHOLDERS):
        return True
    return False


def _collect_render_items(
    template: Mapping[str, Any],
    variables: Mapping[str, str],
    omitted: frozenset[str] = frozenset(),
) -> list[tuple[str, Mapping[str, Any]]]:
    """按固定元素、日期、时间、防伪码顺序收集本轮要绘制的文字。

    omitted 中的字段不参与绘制：
    - "location"：跳过地点元素，以及任何含 {location} 的行（分栏内容同样生效）；
    - "time"：跳过日期/时间元素，以及任何含 {date}/{time}/{weekday} 的行。
    """

    items: list[tuple[str, Mapping[str, Any]]] = []
    for element in template.get("fixed_elements") or []:
        if not isinstance(element, Mapping):
            continue
        if _is_field_omitted(element, omitted):
            continue
        text = _format_text(element.get("text"), variables).strip()
        if text:
            items.append((text, element))

    dynamic_config = template.get("dynamic_vars") or {}
    for key in ("date", "time", "anti_counterfeit"):
        if "time" in omitted and key in ("date", "time"):
            continue
        config = dynamic_config.get(key)
        if not isinstance(config, Mapping):
            continue
        value = variables.get(key, "")
        label = str(config.get("label") or "")
        text = f"{label}{value}".strip()
        if text:
            items.append((text, config))
    return items


def plan_watermark_blocks(
    template: Mapping[str, Any],
    variables: Mapping[str, str],
    width: int,
    height: int,
    omitted: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """计算水印元素的最终像素位置。

    同一锚点的元素作为一个整体堆叠：左上/右上/上居中从顶部开始，左下/右下/
    下居中从底部向上对齐；左列贴左边、右列贴右边、居中列水平居中。这样
    “最左上角/最右下角”不会停在画面中间，元素之间也保持紧凑。

    Args:
        omitted: 不参与绘制的字段集合，可含 "location"、"time"。

    Returns:
        每项包含 text、config、font、x、y、width、height 等字段。
    """

    if width < 1 or height < 1:
        raise ValueError("画布尺寸必须为正整数")

    scratch = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
    groups: dict[str, list[dict[str, Any]]] = {}
    free_blocks: list[dict[str, Any]] = []

    for text, config in _collect_render_items(template, variables, omitted):
        block = _measure_block(scratch, text, config, width, height)
        anchor = _resolve_anchor(config)
        if anchor is None:
            free_blocks.append(block)
        else:
            groups.setdefault(anchor, []).append(block)

    margin = _layout_margin(width, height)
    gap = _layout_gap(template, width, height)
    planned: list[dict[str, Any]] = []

    for anchor, blocks in groups.items():
        vertical, horizontal = anchor.split("-", 1)
        total_height = sum(block["height"] for block in blocks) + gap * (len(blocks) - 1)
        if vertical == "top":
            cursor_y = margin
        else:
            cursor_y = height - margin - total_height
        cursor_y = max(4, min(cursor_y, max(4, height - total_height - 4)))

        for block in blocks:
            if horizontal == "left":
                x = margin
            elif horizontal == "center":
                x = (width - block["width"]) / 2
            else:
                x = width - margin - block["width"]
            x = max(4, min(x, max(4, width - block["width"] - 4)))
            block["x"] = int(x)
            block["y"] = int(cursor_y)
            cursor_y += block["height"] + gap
            planned.append(block)

    for block in free_blocks:
        x = int(_coerce_float(block["config"].get("x_norm"), 0.035) * width)
        y = int(_coerce_float(block["config"].get("y_norm"), 0.05) * height)
        block["x"] = max(4, min(x, max(4, width - block["width"] - 4)))
        block["y"] = max(4, min(y, max(4, height - block["height"] - 4)))
        planned.append(block)

    return planned


def _paint_block(draw: ImageDraw.ImageDraw, block: Mapping[str, Any]) -> None:
    """按已计算好的位置绘制圆角标签与文字。"""

    x = int(block["x"])
    y = int(block["y"])
    box_width = int(block["width"])
    box_height = int(block["height"])
    padding_x = int(block["padding_x"])
    padding_y = int(block["padding_y"])
    bbox = block["bbox"]
    config = block["config"]

    radius = min(
        _coerce_int(config.get("round_radius"), DEFAULT_ROUND_RADIUS, 0),
        max(0, box_height // 2),
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
    draw.text(
        (text_xy[0] + 1, text_xy[1] + 1), block["text"], font=block["font"], fill=(0, 0, 0, 150)
    )
    draw.text(text_xy, block["text"], font=block["font"], fill=(*fill, 255))


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
        # 四角锚点会按实际图片尺寸贴边，不参与中心区域告警。
        if _resolve_anchor(config) is not None:
            continue
        if left <= x <= right and top <= y <= bottom:
            warnings.append(f"“{label}”位于画面中心 40% 区域，可能遮挡关键画面。")
    return warnings


def render_watermark(
    template: Mapping[str, Any],
    scene_path: str | Path,
    dynamic_vars: Mapping[str, str],
    output_dir: str | Path = WATERMARKED_DIR,
    omitted: Sequence[str] = (),
) -> str:
    """按模板锚点/坐标绘制水印并返回输出 PNG 的绝对路径。

    先按四角锚点或归一化坐标计算位置，再绘制 RGBA 半透明圆角色块与白字。
    输出文件名使用 UUID，避免覆盖历史图片。

    Args:
        omitted: 不输出的字段，可含 "location"（地点）、"time"（日期与时间）。
            UI 未勾选“使用陪餐地点/使用时间”时传入，图上不再出现对应文字。
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

    blocks = plan_watermark_blocks(
        template,
        variables,
        width,
        height,
        frozenset(str(item).strip() for item in omitted),
    )
    if not blocks:
        raise ValueError("模板没有可绘制的文字，请先填写标题、地点或动态变量")

    for block in blocks:
        _paint_block(draw, block)

    composed = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    destination = output_path / f"{uuid.uuid4().hex}.png"
    composed.save(destination, format="PNG", optimize=True)
    absolute = str(destination.resolve())
    logger.info("水印图已生成：%s", absolute)
    return absolute
