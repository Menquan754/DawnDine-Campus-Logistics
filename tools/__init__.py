"""DawnDine 业务工具注册表。

本文件职责：
- 导入七个 @tool 并导出唯一 TOOLS 列表；
- 作为 graph.py 获取工具集合的入口，避免 graph 直接依赖各工具文件。

依赖：tools/*.py、langchain-core。
被调用：graph.py、测试脚本。
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from tools.abnormal import create_abnormal_closure
from tools.checklist import daily_checklist_reminder
from tools.compliance import check_compliance_knowledge
from tools.inspection import inspection_response_guide
from tools.ledger import generate_ledger_entry
from tools.schedule import add_schedule
from tools.watermark import generate_meal_accompaniment_record

TOOLS: list[BaseTool] = [
    check_compliance_knowledge,
    generate_ledger_entry,
    daily_checklist_reminder,
    create_abnormal_closure,
    inspection_response_guide,
    generate_meal_accompaniment_record,
    add_schedule,
]

__all__ = ["TOOLS"]
