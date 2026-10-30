"""DawnDine 领域枚举与业务字面量。

本文件职责：
- 定义工具注册名、台账/异常/清单/合规等业务状态枚举；
- 定义日程来源、维修/资产/巡检/反馈状态等中文业务字面量；
- 提供各枚举的合法取值元组，供 Pydantic 校验与 SQLite 归一化使用。

不包含：路径、环境变量、端口等运行期配置（见 dawndine.config）。

依赖：仅 Python 标准库。
被调用：dawndine.schemas、dawndine.db、dawndine 工具与服务层。
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "ToolName",
    "TOOL_WATERMARK",
    "TOOL_COMPLIANCE",
    "TOOL_KNOWLEDGE",
    "TOOL_LEDGER",
    "TOOL_CHECKLIST",
    "TOOL_ABNORMAL",
    "TOOL_INSPECTION",
    "TOOL_SCHEDULE",
    "TOOL_SCHEDULE_ANALYSIS",
    "TOOL_LOGISTICS_QUERY",
    "TOOL_NAMES",
    "RecordMode",
    "LedgerStatus",
    "ClosureStatus",
    "ChecklistStatus",
    "AbnormalSource",
    "Conclusion",
    "Confidence",
    "WatermarkMode",
    "LedgerType",
    "RECORD_MODE_VALUES",
    "LEDGER_STATUS_VALUES",
    "CLOSURE_STATUS_VALUES",
    "CHECKLIST_STATUS_VALUES",
    "ABNORMAL_SOURCE_VALUES",
    "LEDGER_TYPE_VALUES",
    "CONCLUSION_VALUES",
    "CONFIDENCE_VALUES",
    "CHECKLIST_ACCEPTANCE",
    "CHECKLIST_PLATFORM_DUAL",
    "CHECKLIST_PREP_KNIFE",
    "CHECKLIST_MEAL",
    "CHECKLIST_CATEGORIES",
    "SCHEDULE_SOURCE_MANUAL",
    "SCHEDULE_SOURCE_WATERMARK",
    "SCHEDULE_SOURCE_LEDGER",
    "SCHEDULE_SOURCE_ABNORMAL",
    "SCHEDULE_SOURCE_CHAT",
    "SCHEDULE_SOURCE_IMAGE",
    "SCHEDULE_SOURCE_VALUES",
    "MAINTENANCE_STATUS_PENDING",
    "MAINTENANCE_STATUS_VALUES",
    "ASSET_STATUS_VALUES",
    "INSPECTION_RESULT_VALUES",
    "INSPECTION_STATUS_VALUES",
    "FEEDBACK_STATUS_VALUES",
    "LOGISTICS_DATA_KINDS",
    "RECORD_KIND_LEDGER",
    "RECORD_KIND_ABNORMAL",
    "RECORD_KIND_CHECKLIST",
    "RECORD_KIND_INSPECTION",
    "RECORD_KIND_COMPLIANCE",
    "RECORD_KIND_WATERMARK",
    "RECORD_KIND_VALUES",
]


# ---------------------------------------------------------------------------
# 工具名常量
# ---------------------------------------------------------------------------
class ToolName(StrEnum):
    """业务工具的唯一注册名。"""

    WATERMARK = "generate_meal_accompaniment_record"
    COMPLIANCE = "check_compliance_knowledge"
    KNOWLEDGE = "search_food_safety_knowledge"
    LEDGER = "generate_ledger_entry"
    CHECKLIST = "daily_checklist_reminder"
    ABNORMAL = "create_abnormal_closure"
    INSPECTION = "inspection_response_guide"
    SCHEDULE = "add_schedule"
    SCHEDULE_ANALYSIS = "analyze_schedules"
    LOGISTICS_QUERY = "query_logistics_records"


TOOL_WATERMARK = ToolName.WATERMARK.value
TOOL_COMPLIANCE = ToolName.COMPLIANCE.value
TOOL_KNOWLEDGE = ToolName.KNOWLEDGE.value
TOOL_LEDGER = ToolName.LEDGER.value
TOOL_CHECKLIST = ToolName.CHECKLIST.value
TOOL_ABNORMAL = ToolName.ABNORMAL.value
TOOL_INSPECTION = ToolName.INSPECTION.value
TOOL_SCHEDULE = ToolName.SCHEDULE.value
TOOL_SCHEDULE_ANALYSIS = ToolName.SCHEDULE_ANALYSIS.value
TOOL_LOGISTICS_QUERY = ToolName.LOGISTICS_QUERY.value
TOOL_NAMES: tuple[str, ...] = tuple(tool.value for tool in ToolName)


# ---------------------------------------------------------------------------
# 业务状态枚举（所有输出状态值必须从这里取 .value）
# ---------------------------------------------------------------------------
class RecordMode(StrEnum):
    """台账记录模式。"""

    REALTIME = "realtime"
    BACKFILL = "backfill"


class LedgerStatus(StrEnum):
    """台账条目状态。"""

    REALTIME = "realtime"
    BACKFILL = "backfill"
    PENDING = "pending"


class ClosureStatus(StrEnum):
    """异常闭环状态。"""

    PENDING = "pending"
    RECTIFYING = "rectifying"
    REVIEWING = "reviewing"
    CLOSED = "closed"


class ChecklistStatus(StrEnum):
    """每日清单条目状态。"""

    DONE = "done"
    NOT_DONE = "not_done"
    ABNORMAL = "abnormal"
    UNFILLED = "unfilled"


class AbnormalSource(StrEnum):
    """异常线索来源。"""

    HUMAN = "human"
    AI_CAPTURE = "ai_capture"
    DEVICE_ALERT = "device_alert"


class Conclusion(StrEnum):
    """合规判断结论。"""

    COMPLIANT = "合规"
    NON_COMPLIANT = "不合规"
    UNCERTAIN = "存疑"
    NEEDS_ONSITE = "需现场确认"


class Confidence(StrEnum):
    """判断置信度。"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class WatermarkMode(StrEnum):
    """水印工具工作模式。"""

    NEW_TEMPLATE = "new_template"
    USE_TEMPLATE = "use_template"


class LedgerType(StrEnum):
    """可生成的台账类型。"""

    DAILY_CONTROL = "日管控"
    WEEKLY_INSPECTION = "周排查"
    MONTHLY_SCHEDULE = "月调度"
    MORNING_CHECK = "晨检"
    SAMPLE_RETENTION = "留样"
    INGREDIENT_ACCEPTANCE = "验菜"
    MEAL_ACCOMPANIMENT = "陪餐"
    DUAL_LOCK = "双人双锁"
    PURCHASE = "采购"
    DISINFECTION = "消毒"


RECORD_MODE_VALUES: tuple[str, ...] = tuple(item.value for item in RecordMode)
LEDGER_STATUS_VALUES: tuple[str, ...] = tuple(item.value for item in LedgerStatus)
CLOSURE_STATUS_VALUES: tuple[str, ...] = tuple(item.value for item in ClosureStatus)
CHECKLIST_STATUS_VALUES: tuple[str, ...] = tuple(item.value for item in ChecklistStatus)
ABNORMAL_SOURCE_VALUES: tuple[str, ...] = tuple(item.value for item in AbnormalSource)
LEDGER_TYPE_VALUES: tuple[str, ...] = tuple(item.value for item in LedgerType)
CONCLUSION_VALUES: tuple[str, ...] = tuple(item.value for item in Conclusion)
CONFIDENCE_VALUES: tuple[str, ...] = tuple(item.value for item in Confidence)

# ---------------------------------------------------------------------------
# 每日清单四大板块
# ---------------------------------------------------------------------------
CHECKLIST_ACCEPTANCE = "验收与全流程监督"
CHECKLIST_PLATFORM_DUAL = "平台资料上传与双人双检双人双锁"
CHECKLIST_PREP_KNIFE = "切配清洗与刀具菜板"
CHECKLIST_MEAL = "陪餐拍照与评价表"
CHECKLIST_CATEGORIES: tuple[str, ...] = (
    CHECKLIST_ACCEPTANCE,
    CHECKLIST_PLATFORM_DUAL,
    CHECKLIST_PREP_KNIFE,
    CHECKLIST_MEAL,
)

# ---------------------------------------------------------------------------
# 日程来源
# ---------------------------------------------------------------------------
SCHEDULE_SOURCE_MANUAL = "手动"
SCHEDULE_SOURCE_WATERMARK = "水印"
SCHEDULE_SOURCE_LEDGER = "台账"
SCHEDULE_SOURCE_ABNORMAL = "异常"
SCHEDULE_SOURCE_CHAT = "对话"
SCHEDULE_SOURCE_IMAGE = "图片导入"
SCHEDULE_SOURCE_VALUES: tuple[str, ...] = (
    SCHEDULE_SOURCE_MANUAL,
    SCHEDULE_SOURCE_WATERMARK,
    SCHEDULE_SOURCE_LEDGER,
    SCHEDULE_SOURCE_ABNORMAL,
    SCHEDULE_SOURCE_CHAT,
    SCHEDULE_SOURCE_IMAGE,
)

# ---------------------------------------------------------------------------
# 后勤维修与后勤全域数据字面量
# ---------------------------------------------------------------------------
MAINTENANCE_STATUS_PENDING = "待处理"
MAINTENANCE_STATUS_VALUES: tuple[str, ...] = ("待处理", "处理中", "已完成", "已取消")
ASSET_STATUS_VALUES: tuple[str, ...] = ("在用", "闲置", "维修中", "报废")
INSPECTION_RESULT_VALUES: tuple[str, ...] = ("正常", "异常")
INSPECTION_STATUS_VALUES: tuple[str, ...] = ("待整改", "整改中", "已闭环")
FEEDBACK_STATUS_VALUES: tuple[str, ...] = ("待处理", "处理中", "已办结")
LOGISTICS_DATA_KINDS: tuple[str, ...] = (
    "维修",
    "资产",
    "库存",
    "巡检",
    "供应商",
    "人员",
    "反馈",
)

# ---------------------------------------------------------------------------
# 历史留痕
# ---------------------------------------------------------------------------
RECORD_KIND_LEDGER = "ledger"
RECORD_KIND_ABNORMAL = "abnormal"
RECORD_KIND_CHECKLIST = "checklist"
RECORD_KIND_INSPECTION = "inspection"
RECORD_KIND_COMPLIANCE = "compliance"
RECORD_KIND_WATERMARK = "watermark"
RECORD_KIND_VALUES: tuple[str, ...] = (
    RECORD_KIND_LEDGER,
    RECORD_KIND_ABNORMAL,
    RECORD_KIND_CHECKLIST,
    RECORD_KIND_INSPECTION,
    RECORD_KIND_COMPLIANCE,
    RECORD_KIND_WATERMARK,
)
