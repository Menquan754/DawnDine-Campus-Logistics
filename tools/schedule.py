"""日程写入工具。

本文件职责：
- 当用户在对话中明确要求“记录日程/提醒/安排”时，把结构化日程写入 SQLite；
- 返回写入后的完整记录，供 Agent 继续生成五段式回答。

依赖：constants.py、schemas.py、modules/db.py、langchain-core。
被调用：graph.py（经 tools/__init__.py）。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from constants import SCHEDULE_SOURCE_CHAT, TOOL_SCHEDULE
from modules.db import create_schedule
from schemas import ScheduleInput

logger = logging.getLogger(__name__)


@tool(TOOL_SCHEDULE, args_schema=ScheduleInput)
def add_schedule(
    date: str,
    time: str,
    content: str,
    source: str = SCHEDULE_SOURCE_CHAT,
) -> dict[str, Any]:
    """把一条明确日程写入本地 SQLite，并在“我的日程”页面展示。

    何时调用：
    - 用户明确说“帮我记录/添加/保存日程、安排、提醒”；
    - 用户给出日期、时间、事项，要求沉淀到日程表；
    - 台账、异常、水印之外的普通工作安排。

    何时不调用：
    - 用户只是询问日程表里有什么（应读取数据库，不是写入）；
    - 缺少日期或事项，无法形成可执行日程时，先向用户追问；
    - 用户要求生成台账、异常闭环或水印（调用对应专用工具，它们会自行沉淀）。

    说明：
    - date 支持 YYYY-MM-DD / YYYY/MM/DD；
    - time 支持 HH:MM；确实未知时传“待补”；
    - content 必须具体、可读，不得编造用户未提供的安排；
    - 写入成功后才可声称“已记录”，失败时不得编造。

    Returns:
        成功：{"ok": True, "schedule": {...}, "note": "..."}
        失败：{"ok": False, "error": "..."}
    """

    try:
        record = create_schedule(
            date=date,
            time=time,
            content=content,
            source=source or SCHEDULE_SOURCE_CHAT,
        )
        return {
            "ok": True,
            "schedule": record,
            "note": "日程已写入本地 SQLite，可在“我的日程”页面查看。",
        }
    except Exception as exc:  # noqa: BLE001 - 工具边界必须返回结构化错误
        logger.exception("日程写入失败")
        return {"ok": False, "error": f"日程写入失败：{exc}"}
