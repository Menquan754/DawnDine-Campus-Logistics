"""日程工具：写入日程与分析日程。

本文件职责：
- 当用户在对话中明确要求“记录日程/提醒/安排”时，把结构化日程写入 SQLite；
- 当用户问“我的日程/本周安排/有没有冲突/待补哪些”时，读取并分析日程；
- 返回结构化结果，供 Agent 继续生成五段式回答。

依赖：dawndine.enums、dawndine.schemas、dawndine.db、dawndine.services.schedule、
      langchain-core。
被调用：dawndine.agent.graph（经 agent/tools/__init__.py）、app.py。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from dawndine.db import create_schedule
from dawndine.enums import SCHEDULE_SOURCE_CHAT, TOOL_SCHEDULE, TOOL_SCHEDULE_ANALYSIS
from dawndine.schemas import ScheduleAnalysisInput, ScheduleInput
from dawndine.services.schedule import analyze_schedules as analyze_schedule_data

logger = logging.getLogger(__name__)


@tool(TOOL_SCHEDULE_ANALYSIS, args_schema=ScheduleAnalysisInput)
def analyze_schedules(limit: int = 2000) -> dict[str, Any]:
    """分析本地日程：总数、今日/本周安排、待补时间、日期已过、时间冲突与来源分布。

    何时调用：
    - 用户问“我的日程/这周有什么安排/今天要做什么”；
    - 用户问“有没有时间冲突/哪些安排没填时间/有没有过期未办”；
    - 用户要求对日程做总结、复盘、优先级建议。

    何时不调用：
    - 用户要求新增/修改日程（用 add_schedule 或页面表单）；
    - 用户只是问某条日程的具体内容且已在对话中给出（不必查库）；
    - 用户要求导出图片（在“我的日程”页点“导出图片”）。

    说明：
    - 只读分析，不修改数据库；
    - 不得编造日程，返回为空时如实说明“当前没有日程”；
    - 分析结果只是建议，最终以平台记录和现场安排为准。

    Returns:
        成功：{"ok": True, "total": ..., "today": [...], "conflicts": [...], "suggestions": [...]}
        失败：{"ok": False, "error": "..."}
    """

    return analyze_schedule_data(limit=limit)


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
