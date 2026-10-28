"""Qwen-VL 图片日程解析。

本文件职责：
- 把上传的日程截图/通知图片压缩后交给当前视觉模型
  （默认 qwen3-vl-plus，可用 DASHSCOPE_VL_MODEL 覆盖）；
- 要求模型输出严格 JSON，解析日期、时间、事项、地点；
- 将地点并入事项文本，供 SQLite 日程表统一存储；
- 解析失败、Key 缺失、空结果均返回可读中文错误。

依赖：config/llm.py、modules/db.py、constants.py、Pillow、langchain-core。
被调用：app.py（我的日程 → 上传图片导入）。
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from PIL import Image, ImageDraw, ImageOps

from config.llm import api_key_configured, get_vision_llm, get_vision_model_name
from constants import (
    MISSING_API_KEY_MESSAGE,
    SCHEDULE_IMPORT_MAX_RECORDS,
    SCHEDULE_SOURCE_IMAGE,
)
from modules.db import normalize_date, normalize_time

logger = logging.getLogger(__name__)


def _message_text(message: Any) -> str:
    """从模型消息中提取文本。"""

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
    """压缩图片并转换为 data URI，避免请求体过大。"""

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


def _probe_data_uri() -> str:
    """生成 96×96 测试图，用于视觉模型连通性探测。"""

    image = Image.new("RGB", (96, 96), (233, 245, 240))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 87, 87), outline=(15, 118, 110), width=3)
    draw.text((38, 40), "OK", fill=(20, 52, 43))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _friendly_vision_error(exc: Exception) -> str:
    """把模型不存在等错误归一为可执行中文提示。"""

    detail = str(exc)
    model_name = get_vision_model_name()
    if "model_not_found" in detail or "Model not exist" in detail or "404" in detail:
        return (
            f"视觉模型不可用：{model_name}。请确认百炼账号已开通该模型，"
            "或在 .env 设置 DASHSCOPE_VL_MODEL 后重启。"
        )
    return f"视觉模型调用失败：{detail[:280]}"


def probe_vision_model(api_key: str) -> dict[str, Any]:
    """用小测试图检测当前 Key 与视觉模型是否可用。

    Returns:
        {"ok": bool, "model": str, "reply": str, "error": str}
    """

    model_name = get_vision_model_name()
    if not api_key_configured(api_key):
        return {
            "ok": False,
            "model": model_name,
            "reply": "",
            "error": MISSING_API_KEY_MESSAGE,
        }
    try:
        model = get_vision_llm(api_key=api_key)
        response = model.invoke(
            [
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": "这是一张 96×96 的测试图。请只回复 OK。",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": _probe_data_uri()},
                        },
                    ]
                )
            ]
        )
        return {
            "ok": True,
            "model": model_name,
            "reply": _message_text(response).strip()[:200],
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001 - 诊断结果必须可读
        logger.warning("视觉模型探测失败：%s", exc)
        return {
            "ok": False,
            "model": model_name,
            "reply": "",
            "error": _friendly_vision_error(exc),
        }


def _parse_json_array(raw: str) -> list[dict[str, Any]]:
    """从模型输出中解析 JSON 数组。"""

    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        array_match = re.search(r"\[.*\]", text, re.DOTALL)
        object_match = re.search(r"\{.*\}", text, re.DOTALL)
        if array_match:
            data = json.loads(array_match.group(0))
        elif object_match:
            data = json.loads(object_match.group(0))
        else:
            raise ValueError("视觉模型未返回可解析的 JSON") from None

    if isinstance(data, dict):
        for key in ("schedules", "records", "items", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        raise ValueError("视觉模型返回的 JSON 不是数组")
    return [item for item in data if isinstance(item, dict)]


def parse_schedule_image(image_path: str, api_key: str = "") -> dict[str, Any]:
    """解析图片中的日程信息。

    Args:
        image_path: 图片路径。
        api_key: 当前会话 Key；为空时回退 .env。

    Returns:
        {"records": [{"date", "time", "content", "source"}], "note": "..."}

    Raises:
        FileNotFoundError: 图片不存在。
        RuntimeError: 未配置 API Key。
        ValueError: 模型输出无法解析。
    """

    if not api_key_configured(api_key):
        raise RuntimeError(MISSING_API_KEY_MESSAGE)

    path = Path(image_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"日程图片不存在：{path}")

    today = datetime.now().strftime("%Y-%m-%d")
    system_prompt = (
        "你是学校食堂日程信息抽取器。只输出一个 JSON 数组，不要 Markdown 围栏。"
        "每项字段为 date、time、content、location。"
        "date 用 YYYY-MM-DD，time 用 HH:MM；无法识别的字段写 null。"
        "content 必须简洁描述事项；location 可空。"
        "不要编造图片中没有的日期、时间、地点或事项。"
    )
    human_prompt = (
        f"今天是 {today}。请读取图片中的通知、排班或日程，抽取所有可确认的日程。"
        f"最多返回 {SCHEDULE_IMPORT_MAX_RECORDS} 条。若图片没有日程，返回 []。"
    )
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=[
                {"type": "text", "text": human_prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": _image_to_data_uri(path)},
                },
            ]
        ),
    ]

    model = get_vision_llm(api_key=api_key)
    try:
        response = model.invoke(messages)
    except Exception as exc:
        raise RuntimeError(_friendly_vision_error(exc)) from exc
    raw = _message_text(response)
    items = _parse_json_array(raw)

    records: list[dict[str, str]] = []
    skipped = 0
    for item in items[:SCHEDULE_IMPORT_MAX_RECORDS]:
        content = str(item.get("content") or item.get("事项") or "").strip()
        location = str(item.get("location") or item.get("地点") or "").strip()
        if not content:
            skipped += 1
            continue
        if location and location not in content:
            content = f"{content}（地点：{location}）"

        raw_date = item.get("date")
        try:
            date_text = normalize_date(str(raw_date)) if raw_date else "待补"
        except ValueError:
            skipped += 1
            continue

        raw_time = item.get("time")
        try:
            time_text = normalize_time(str(raw_time)) if raw_time else "待补"
        except ValueError:
            time_text = "待补"

        records.append(
            {
                "date": date_text,
                "time": time_text,
                "content": content,
                "source": SCHEDULE_SOURCE_IMAGE,
            }
        )

    note = f"视觉模型解析完成：可导入 {len(records)} 条。"
    if skipped:
        note += f" 跳过 {skipped} 条缺少事项或日期非法的记录。"
    if not records:
        note = "图片中未识别到可导入的日程，请换一张更清晰的图片或手动添加。"
    logger.info("图片日程解析完成：可导入=%s，跳过=%s", len(records), skipped)
    return {"records": records, "note": note}
