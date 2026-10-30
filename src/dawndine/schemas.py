"""DawnDine 工具输入模型与输出数据结构。

本文件职责：
- 集中定义七个 @tool 的 Pydantic 输入模型，工具文件只引用、不重复定义；
- 集中定义输出 TypedDict，明确 ok / error / 业务字段契约；
- 状态枚举统一来自 dawndine.enums，避免不同文件拼写漂移。

依赖：dawndine.enums、pydantic、typing。
被调用：agent/tools/*.py、agent/graph.py、ui/*.py、cli.py、测试脚本。
"""

from __future__ import annotations

import re
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dawndine.enums import (
    SCHEDULE_SOURCE_CHAT,
    SCHEDULE_SOURCE_VALUES,
    AbnormalSource,
    LedgerType,
    RecordMode,
    WatermarkMode,
)

__all__ = [
    "ToolInput",
    "WatermarkInput",
    "ComplianceInput",
    "KnowledgeSearchInput",
    "LedgerInput",
    "ChecklistInput",
    "AbnormalInput",
    "InspectionInput",
    "ScheduleInput",
    "ScheduleAnalysisInput",
    "LogisticsQueryInput",
    "ToolError",
    "WatermarkTemplateField",
    "WatermarkOutput",
    "ComplianceOutput",
    "KnowledgeHit",
    "KnowledgeOutput",
    "LedgerItem",
    "LedgerOutput",
    "ChecklistItem",
    "ChecklistTodo",
    "ChecklistOutput",
    "AbnormalOutput",
    "InspectionOutput",
    "ScheduleRecord",
    "ScheduleOutput",
]


class ToolInput(BaseModel):
    """所有工具输入模型的基类：忽略多余字段，自动去除首尾空白。"""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class WatermarkInput(ToolInput):
    """陪餐打卡水印图工具输入。

    new_template：分析 sample_image_path 并保存模板，不绘图；
    use_template：读取模板与 scene_image_path，由 Pillow 绘图。
    """

    mode: WatermarkMode = Field(
        ...,
        description="new_template=上传样图新建模板；use_template=使用已有模板生成打卡图。",
    )
    template_name: str | None = Field(
        default=None,
        description="模板名称；use_template 时省略则使用 default。",
    )
    user_requirement: str | None = Field(
        default=None,
        description=(
            "用户对水印文字或布局的自然语言要求，可省略。支持“最左上角/最右下角”"
            "“元素紧靠在一起/间距小”等描述。"
        ),
    )
    sample_image_path: str | None = Field(
        default=None,
        description="样图绝对或相对路径；new_template 模式必填。",
    )
    scene_image_path: str | None = Field(
        default=None,
        description="现场照片路径；use_template 模式必填。",
    )
    location: str | None = Field(
        default=None,
        description="陪餐地点；不能编造，未提供则写“待补”。",
    )
    manual_time: str | None = Field(
        default=None,
        description="手动指定时间，格式 YYYY-MM-DD HH:MM；省略则取当前时间。",
    )
    style_overrides: dict[str, Any] | None = Field(
        default=None,
        description=(
            "人工调整的模板参数，可省略。支持：format（full/standard/compact/"
            "datetime/location_time）、anchor（top-left/top-right/bottom-left/"
            "bottom-right/top-center/bottom-center）、font_scale（0.5—2.5）、"
            "font_size、color、bg_color、bg_opacity、round_radius、layout_gap、"
            "date_format（dot/iso/cn/short）、time_format（hm/hms）。"
            "需要左右分栏时传 columns，形如 "
            "[{'anchor': 'bottom-left', 'text': '第一行\\n第二行'}, "
            "{'anchor': 'bottom-right', 'text': '陪餐人：张三'}], "
            "每栏一行一条、按填写顺序从上到下排列；空列表表示清除分栏、还原模板内容。"
            "也可用 left_content/left_anchor/right_content/right_anchor 简写。"
        ),
    )

    omitted_fields: list[str] | None = Field(
        default=None,
        description=(
            "图上不输出的字段，可选 location/time，可省略。缺省表示都输出；"
            "未勾选地点、或勾选地点但没有填写地址时传 location，避免出现“待补”；"
            "未勾选时间时传 time，图上不再显示日期与时间。"
        ),
    )

    @field_validator("manual_time")
    @classmethod
    def validate_manual_time(cls, value: str | None) -> str | None:
        """校验手动时间格式，避免把非法时间写入水印。"""

        if not value:
            return None
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", value):
            raise ValueError("manual_time 必须为 YYYY-MM-DD HH:MM 格式")
        return value


class ComplianceInput(ToolInput):
    """合规知识检索工具输入。"""

    stage: str = Field(
        ...,
        min_length=1,
        description="监管环节，如冷链验收、留样管理、晨检、切配、陪餐。",
    )
    object_name: str = Field(
        ...,
        min_length=1,
        description="检查对象，如冷鲜猪肉、留样盒、刀具菜板、从业人员。",
    )
    phenomenon: str = Field(
        ...,
        min_length=1,
        description="现场现象或问题描述，必须基于用户提供的信息。",
    )
    key_values: str | None = Field(
        default=None,
        description="关键数值，如温度6℃、留样110g、已放置30小时。",
    )
    region_or_school: str | None = Field(
        default=None,
        description="地区或学校名称，用于提示本地规定差异，可省略。",
    )


class KnowledgeSearchInput(ToolInput):
    """校园后勤知识库检索工具输入。"""

    question: str = Field(
        ...,
        min_length=1,
        description=(
            "用户要查的具体问题，如“餐具消毒怎么操作”“冷藏温度标准是多少”"
            "“宿舍热水停了怎么处理”“维修工单多久回访”“资产盘点怎么做”。"
        ),
    )
    domain: str | None = Field(
        default=None,
        description=(
            "可选领域：食材与食品安全、台账与系统操作、后厨与环境卫生、"
            "采购库存与成本、陪餐与师生反馈、制度整改与应急、日常咨询、"
            "维修与设施设备、宿舍后勤、保洁环卫与绿化、资产采购与仓储、"
            "安全消防与节能、服务反馈与场馆保障。"
        ),
    )
    top_k: int = Field(
        default=3,
        ge=1,
        le=8,
        description="返回的知识片段数量，默认 3；问题复杂时可提高到 5。",
    )


class LedgerInput(ToolInput):
    """台账生成工具输入。"""

    ledger_type: LedgerType = Field(
        ...,
        description=("台账类型：日管控/周排查/月调度/晨检/留样/验菜/陪餐/双人双锁/采购/消毒。"),
    )
    date_time: str = Field(
        ...,
        min_length=1,
        description="台账对应日期时间，建议格式 YYYY-MM-DD HH:MM。",
    )
    persons: list[str] = Field(
        default_factory=list,
        description="相关人员姓名列表；未提供则条目记为“待补”。",
    )
    process_info: str = Field(
        default="",
        description="过程与结果描述，尽量包含现场动作、数量和结论。",
    )
    abnormal_and_action: str | None = Field(
        default=None,
        description="异常及已采取的处置，可省略。",
    )
    dual_execution: str | None = Field(
        default=None,
        description="双人执行、双人双锁情况，可省略。",
    )
    record_mode: RecordMode = Field(
        default=RecordMode.REALTIME,
        description="realtime=实时记录；backfill=补录，补录必须说明原因。",
    )
    backfill_reason: str | None = Field(
        default=None,
        description="补录原因；record_mode=backfill 时必填。",
    )

    @field_validator("persons", mode="before")
    @classmethod
    def normalize_persons(cls, value: Any) -> list[str]:
        """兼容 LLM 传入字符串或列表两种形式。"""

        if value is None:
            return []
        if isinstance(value, str):
            cleaned = value.replace("、", ",").replace("，", ",").replace("/", ",")
            cleaned = cleaned.replace("\n", ",")
            return [item.strip() for item in cleaned.split(",") if item.strip()]
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()]


class ChecklistInput(ToolInput):
    """每日清单提醒工具输入。"""

    date: str = Field(..., min_length=1, description="清单日期，建议 YYYY-MM-DD。")
    done_items: list[str] = Field(
        default_factory=list,
        description="已完成的日常事项。",
    )
    undone_items: list[str] = Field(
        default_factory=list,
        description="明确尚未完成的事项。",
    )
    abnormal_items: list[str] = Field(
        default_factory=list,
        description="现场已发现的异常事项。",
    )
    board_knife_usage: str | None = Field(
        default=None,
        description="刀具菜板使用情况，如已分色、未分色、未填写记录。",
    )
    device_status: dict[str, str] | None = Field(
        default=None,
        description="设备状态，如 {'留样柜': '不可用'}；不可用项标“转人工核查”。",
    )

    @field_validator("done_items", "undone_items", "abnormal_items", mode="before")
    @classmethod
    def normalize_items(cls, value: Any) -> list[str]:
        """兼容字符串与列表输入。"""

        if value is None:
            return []
        if isinstance(value, str):
            cleaned = value.replace("、", ",").replace("，", ",").replace("\n", ",")
            return [item.strip() for item in cleaned.split(",") if item.strip()]
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()]


class AbnormalInput(ToolInput):
    """异常闭环工具输入。"""

    abnormal_type: str = Field(
        ...,
        min_length=1,
        description="异常类型，如温度超标、票证不全、留样量不足、设备不可用。",
    )
    found_time: str = Field(
        ...,
        min_length=1,
        description="发现时间，建议格式 YYYY-MM-DD HH:MM。",
    )
    found_by: str = Field(..., min_length=1, description="发现人姓名或岗位。")
    target: str = Field(..., min_length=1, description="异常对象，如某批冷鲜猪肉。")
    description: str = Field(..., min_length=1, description="异常现象和现场事实。")
    source: AbnormalSource = Field(
        default=AbnormalSource.HUMAN,
        description="human=人工发现；ai_capture=AI抓拍；device_alert=设备告警。",
    )
    ai_raw_content: str | None = Field(
        default=None,
        description="AI抓拍或设备告警原文；source 非 human 时建议提供。",
    )
    temp_action: str | None = Field(
        default=None,
        description="现场已采取的临时处置，可省略。",
    )


class InspectionInput(ToolInput):
    """检查应对工具输入。"""

    scene: str = Field(
        ...,
        min_length=1,
        description="检查场景，如市场监管局检查、学校内部自查、家长开放日。",
    )
    question: str = Field(..., min_length=1, description="检查人员提出的问题。")
    related_area: str | None = Field(
        default=None,
        description="涉及领域，如双人双锁、留样、晨检、验菜、陪餐。",
    )
    record_mode: RecordMode | None = Field(
        default=None,
        description="涉及补录时传 backfill；否则可省略。",
    )


class ScheduleInput(ToolInput):
    """日程写入工具输入。"""

    date: str = Field(
        ...,
        min_length=1,
        description="日期，格式 YYYY-MM-DD；用户说今天时使用当前日期。",
    )
    time: str = Field(
        ...,
        min_length=1,
        description="时间，格式 HH:MM；用户未说时间时填“待补”。",
    )
    content: str = Field(..., min_length=1, description="日程事项，必须具体可读。")
    source: str = Field(
        default=SCHEDULE_SOURCE_CHAT,
        description="来源：对话/手动/水印/台账/异常/图片导入。",
    )

    @field_validator("source", mode="before")
    @classmethod
    def normalize_source(cls, value: Any) -> str:
        """来源不在枚举内时回退到“对话”。"""

        clean = str(value or "").strip()
        return clean if clean in SCHEDULE_SOURCE_VALUES else SCHEDULE_SOURCE_CHAT


class ScheduleAnalysisInput(ToolInput):
    """日程分析工具输入。"""

    limit: int = Field(
        default=2000,
        ge=1,
        le=2000,
        description="最多分析的日程条数，默认 2000，一般无需修改。",
    )


class LogisticsQueryInput(ToolInput):
    """后勤台账查询工具输入（只读）。"""

    kind: str = Field(
        ...,
        min_length=1,
        description=(
            "要查询的数据类型：概览/维修/资产/库存/库存预警/巡检/供应商/人员/反馈。"
            "也接受“维修记录”“设备台账”“物资库存”等自然说法。"
        ),
    )
    keyword: str = Field(
        default="",
        description="可选关键字，按地点、名称、人员、内容等模糊匹配；不需要则留空。",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=200,
        description="最多返回条数，默认 20；用户要求“全部”时可提高到 100。",
    )


# ---------------------------------------------------------------------------
# 输出 TypedDict（总字段便于工具按 ok 分支填充）
# ---------------------------------------------------------------------------
class ToolError(TypedDict):
    """统一失败返回。"""

    ok: bool
    error: str


class WatermarkTemplateField(TypedDict, total=False):
    """水印模板中的固定元素。"""

    text: str | None
    color: str | None
    bg_color: str | None
    round_radius: int | None
    font_size: int | None
    x_norm: float | None
    y_norm: float | None


class WatermarkOutput(TypedDict, total=False):
    """水印工具输出。"""

    ok: bool
    error: str
    action: str
    template: dict[str, Any]
    template_name: str
    output_path: str
    dynamic_vars: dict[str, str]
    note: str
    preview_note: str
    schedule_id: int


class ComplianceOutput(TypedDict, total=False):
    """合规工具输出。"""

    ok: bool
    error: str
    conclusion: str
    basis: str
    action_hint: str
    retention_hint: str
    confidence: str
    sources: list[str]
    record_id: int


class KnowledgeHit(TypedDict, total=False):
    """单条知识片段。"""

    source: str
    content: str
    score: float


class KnowledgeOutput(TypedDict, total=False):
    """知识检索工具输出。"""

    ok: bool
    error: str
    domain: str
    question: str
    hits: list[KnowledgeHit]
    sources: list[str]
    key_points: list[str]
    note: str


class LedgerItem(TypedDict, total=False):
    """台账条目。"""

    field: str
    value: str
    status: str


class LedgerOutput(TypedDict, total=False):
    """台账工具输出。"""

    ok: bool
    error: str
    ledger_type: str
    ledger_items: list[LedgerItem]
    readable_text: str
    note: str
    traces: list[str]
    schedule_id: int
    record_id: int


class ChecklistItem(TypedDict, total=False):
    """每日清单条目。"""

    category: str
    status: str
    evidence: str
    note: str


class ChecklistTodo(TypedDict, total=False):
    """每日清单待办。"""

    item: str
    owner_hint: str
    deadline: str


class ChecklistOutput(TypedDict, total=False):
    """每日清单工具输出。"""

    ok: bool
    error: str
    date: str
    checklist: list[ChecklistItem]
    kb_matched: list[dict[str, str]]
    gaps: list[str]
    todos: list[ChecklistTodo]
    link_suggestions: list[str]
    note: str
    record_id: int


class AbnormalOutput(TypedDict, total=False):
    """异常闭环工具输出。"""

    ok: bool
    error: str
    abnormal_id: str
    source: str
    risk_description: str
    temp_action: str
    report_to: list[str]
    rectification_deadline: str
    review_method: str
    evidence_checklist: list[str]
    closure_draft: str
    closure_status: str
    allow_false_positive: bool
    note: str
    schedule_id: int
    basis_snippets: list[str]
    record_id: int


class InspectionOutput(TypedDict, total=False):
    """检查应对工具输出。"""

    ok: bool
    error: str
    answer_script: str
    basis: str
    basis_snippets: list[str]
    sources: list[str]
    evidence: list[str]
    evidence_locations: list[str]
    scene_focus: list[str]
    common_deductions: list[str]
    corrections: list[str]
    backfill_explanation: str
    note: str
    record_id: int


class ScheduleRecord(TypedDict, total=False):
    """单条日程记录。"""

    id: int
    date: str
    time: str
    content: str
    source: str
    created_at: str


class ScheduleOutput(TypedDict, total=False):
    """日程工具输出。"""

    ok: bool
    error: str
    schedule: ScheduleRecord
    note: str
