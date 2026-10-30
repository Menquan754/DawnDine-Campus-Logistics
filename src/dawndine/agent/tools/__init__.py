"""DawnDine 业务工具注册表。

本文件职责：
- 导入十个 @tool 并导出唯一 TOOLS 列表；
- 作为 agent/graph.py 获取工具集合的入口，避免 graph 直接依赖各工具文件。

依赖：dawndine.agent.tools 各模块、langchain-core。
被调用：dawndine.agent.graph、测试脚本。
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from dawndine.agent.tools.abnormal import create_abnormal_closure
from dawndine.agent.tools.checklist import daily_checklist_reminder
from dawndine.agent.tools.compliance import check_compliance_knowledge
from dawndine.agent.tools.inspection import inspection_response_guide
from dawndine.agent.tools.knowledge import search_food_safety_knowledge
from dawndine.agent.tools.ledger import generate_ledger_entry
from dawndine.agent.tools.logistics import query_logistics_records
from dawndine.agent.tools.schedule import add_schedule, analyze_schedules
from dawndine.agent.tools.watermark import generate_meal_accompaniment_record

TOOLS: list[BaseTool] = [
    check_compliance_knowledge,
    search_food_safety_knowledge,
    generate_ledger_entry,
    daily_checklist_reminder,
    create_abnormal_closure,
    inspection_response_guide,
    generate_meal_accompaniment_record,
    add_schedule,
    analyze_schedules,
    query_logistics_records,
]

__all__ = ["TOOLS"]
