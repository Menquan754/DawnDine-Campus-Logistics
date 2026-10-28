"""DawnDine 全局常量与枚举。

本文件职责：
- 集中定义工具名、状态枚举、强制触发关键词、默认线程与全部路径常量；
- 提供运行目录初始化函数，避免各业务模块散落目录字符串。

依赖：仅 Python 标准库。
被调用：schemas、config、tools、modules、graph、app、cli、main。
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

# ---------------------------------------------------------------------------
# 应用级常量
# ---------------------------------------------------------------------------
APP_NAME = "DawnDine"
APP_TITLE = "校园食堂后勤助手"
APP_SUBTITLE = "合规判断 · 异常处置 · 台账草稿 · 日程沉淀 · 检查应对 · 陪餐水印"
APP_DISCLAIMER = "本工具输出为建议与草稿，不替代现场判断与责任认定。"
DEFAULT_THREAD_ID = "dawn-dine"
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 7860

# ---------------------------------------------------------------------------
# 路径常量（全部为绝对路径，业务文件不得自行拼接目录字符串）
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
TEMPLATES_DIR = DATA_DIR / "templates"
CHROMA_DIR = DATA_DIR / "chroma"
UPLOADS_DIR = ROOT_DIR / "uploads"
WATERMARKED_DIR = ROOT_DIR / "watermarked"
TEMPLATE_FILE = TEMPLATES_DIR / "watermark_style_template.json"
DB_PATH = DATA_DIR / "dawndine.db"
ENV_FILE = ROOT_DIR / ".env"

RUNTIME_DIRS: tuple[Path, ...] = (
    DATA_DIR,
    KNOWLEDGE_DIR,
    TEMPLATES_DIR,
    CHROMA_DIR,
    UPLOADS_DIR,
    WATERMARKED_DIR,
)


# ---------------------------------------------------------------------------
# 工具名常量
# ---------------------------------------------------------------------------
class ToolName(StrEnum):
    """七个业务工具的唯一注册名。"""

    WATERMARK = "generate_meal_accompaniment_record"
    COMPLIANCE = "check_compliance_knowledge"
    LEDGER = "generate_ledger_entry"
    CHECKLIST = "daily_checklist_reminder"
    ABNORMAL = "create_abnormal_closure"
    INSPECTION = "inspection_response_guide"
    SCHEDULE = "add_schedule"


TOOL_WATERMARK = ToolName.WATERMARK.value
TOOL_COMPLIANCE = ToolName.COMPLIANCE.value
TOOL_LEDGER = ToolName.LEDGER.value
TOOL_CHECKLIST = ToolName.CHECKLIST.value
TOOL_ABNORMAL = ToolName.ABNORMAL.value
TOOL_INSPECTION = ToolName.INSPECTION.value
TOOL_SCHEDULE = ToolName.SCHEDULE.value
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
# LangGraph / 提示词兜底关键词
# ---------------------------------------------------------------------------
FORCED_TRIGGER_KEYWORDS: tuple[str, ...] = (
    "温度",
    "留样",
    "125g",
    "台账",
    "日管控",
    "周排查",
    "月调度",
    "水印",
    "验收",
    "执行",
    "确认",
    "可以",
    "调用",
)

SENSORY_KEYWORDS: tuple[str, ...] = (
    "新鲜",
    "新鲜度",
    "异味",
    "发酸",
    "变质",
    "口感",
    "颜色不对",
    "闻起来",
)

# ---------------------------------------------------------------------------
# 水印与图片
# ---------------------------------------------------------------------------
DEFAULT_TEMPLATE_NAME = "default"
WATERMARK_PREVIEW_NOTE = "模板参数仅作初始化，请人工确认文字、位置与字号后再绘图。"
WATERMARK_ENTRY_MISSING = "请上传样图新建模板，或选择已有模板。"
CENTER_AVOID_RATIO = 0.40
DEFAULT_FONT_SIZE = 28
FONT_FALLBACK_NOTE = "未找到微软雅黑等中文字体，已使用 Pillow 默认字体，中文可能显示异常。"
SYSTEM_FONT_CANDIDATES: tuple[Path, ...] = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
)
IMAGE_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

# ---------------------------------------------------------------------------
# 日程沉淀
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
SCHEDULE_TABLE_HEADERS: tuple[str, ...] = ("ID", "日期", "时间", "事项", "来源", "创建时间")
SCHEDULE_IMPORT_MAX_RECORDS = 50

# ---------------------------------------------------------------------------
# 检查应对 / RAG / 文本格式
# ---------------------------------------------------------------------------
INSPECTION_ANSWER_MAX_CHARS = 30
RAG_TOP_K = 3
RAG_CHUNK_SIZE = 500
RAG_CHUNK_OVERLAP = 80
RAG_COLLECTION_NAME = "dawndine_knowledge"

# ---------------------------------------------------------------------------
# LLM 配置常量
# ---------------------------------------------------------------------------
DASHSCOPE_API_KEY_ENV = "DASHSCOPE_API_KEY"
DASHSCOPE_VL_MODEL_ENV = "DASHSCOPE_VL_MODEL"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
QWEN_MODEL = "qwen-plus"
QWEN_VL_MODEL = "qwen3-vl-plus"
QWEN_EMBEDDING_MODEL = "text-embedding-v1"
LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 2000
LLM_TIMEOUT_SECONDS = 60
LLM_MAX_RETRIES = 2
LLM_PLACEHOLDER_API_KEY = "sk-dawndine-placeholder"
MISSING_API_KEY_MESSAGE = (
    "未检测到 DASHSCOPE_API_KEY。请复制 .env.example 为 .env，填入阿里云百炼 API Key 后重启。"
)

# LangGraph 单轮最多允许的节点跳转次数，防止工具循环。
GRAPH_RECURSION_LIMIT = 12

# ---------------------------------------------------------------------------
# 日期与日志格式
# ---------------------------------------------------------------------------
DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%d %H:%M"
WATERMARK_DATE_FORMAT = "%Y.%m.%d"
WATERMARK_TIME_FORMAT = "%H:%M"
WEEKDAY_NAMES: tuple[str, ...] = (
    "星期一",
    "星期二",
    "星期三",
    "星期四",
    "星期五",
    "星期六",
    "星期日",
)
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def ensure_runtime_dirs() -> None:
    """创建所有运行时目录；幂等，可重复调用。"""

    for directory in RUNTIME_DIRS:
        directory.mkdir(parents=True, exist_ok=True)
