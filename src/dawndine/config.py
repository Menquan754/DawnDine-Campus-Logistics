"""DawnDine 运行时配置：应用元信息、路径、环境变量与服务参数。

本文件职责：
- 集中定义应用元信息、服务端口、全部路径常量与运行目录初始化；
- 集中定义 LLM / RAG / 日志格式 / 强制触发关键词等运行期可调参数；
- 提供 get_server_host / get_server_port / get_server_share 环境变量读取函数。

不包含：业务状态枚举（见 dawndine.enums）、工具输入模型（见 dawndine.schemas）。

依赖：仅 Python 标准库。
被调用：dawndine 全部子模块。
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "APP_NAME",
    "APP_TITLE",
    "APP_SUBTITLE",
    "APP_DISCLAIMER",
    "APP_VERSION",
    "APP_BUILD_NOTE",
    "DEFAULT_THREAD_ID",
    "get_server_host",
    "get_server_port",
    "get_server_share",
    "ROOT_DIR",
    "DATA_DIR",
    "KNOWLEDGE_DIR",
    "TEMPLATES_DIR",
    "CHROMA_DIR",
    "KNOWLEDGE_MANIFEST_FILE",
    "WIKI_FILE",
    "KG_HTML_FILE",
    "UPLOADS_DIR",
    "WATERMARKED_DIR",
    "EXPORTS_DIR",
    "TEMPLATE_FILE",
    "DB_PATH",
    "ENV_FILE",
    "RUNTIME_DIRS",
    "FORCED_TRIGGER_KEYWORDS",
    "FORCED_TRIGGER_SHORT_TERMS",
    "FORCED_TRIGGER_ACTION_WORDS",
    "CONFIRM_ONLY_PATTERN",
    "SENSORY_KEYWORDS",
    "DEFAULT_TEMPLATE_NAME",
    "WATERMARK_PREVIEW_NOTE",
    "WATERMARK_ENTRY_MISSING",
    "CENTER_AVOID_RATIO",
    "DEFAULT_FONT_SIZE",
    "FONT_FALLBACK_NOTE",
    "SYSTEM_FONT_CANDIDATES",
    "IMAGE_EXTENSIONS",
    "SCHEDULE_TABLE_HEADERS",
    "SCHEDULE_IMPORT_MAX_RECORDS",
    "MAINTENANCE_TABLE_HEADERS",
    "MAINTENANCE_STATS_HEADERS",
    "INSPECTION_ANSWER_MAX_CHARS",
    "RAG_TOP_K",
    "RAG_CHUNK_SIZE",
    "RAG_CHUNK_OVERLAP",
    "RAG_AUTO_CONTEXT_MAX_ITEMS",
    "RAG_AUTO_CONTEXT_MAX_CHARS",
    "RAG_COLLECTION_NAME",
    "DASHSCOPE_API_KEY_ENV",
    "DASHSCOPE_VL_MODEL_ENV",
    "DASHSCOPE_ALLOW_ENV_KEY_ENV",
    "DASHSCOPE_BASE_URL",
    "QWEN_MODEL",
    "QWEN_VL_MODEL",
    "QWEN_EMBEDDING_MODEL",
    "LLM_TEMPERATURE",
    "LLM_MAX_TOKENS",
    "LLM_TIMEOUT_SECONDS",
    "LLM_MAX_RETRIES",
    "LLM_PLACEHOLDER_API_KEY",
    "MISSING_API_KEY_MESSAGE",
    "GRAPH_RECURSION_LIMIT",
    "DATE_FORMAT",
    "DATETIME_FORMAT",
    "WATERMARK_DATE_FORMAT",
    "WATERMARK_TIME_FORMAT",
    "WEEKDAY_NAMES",
    "LOG_FORMAT",
    "LOG_DATE_FORMAT",
    "ensure_runtime_dirs",
]


def _env_flag(name: str, default: bool = False) -> bool:
    """读取 0/1 风格的环境变量。"""

    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    """读取整数环境变量；非法时回退默认值。"""

    try:
        return int((os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# 应用级常量
# ---------------------------------------------------------------------------
APP_NAME = "DawnDine"
APP_TITLE = "校园后勤助手"
APP_SUBTITLE = "食堂食安 · 维修报修 · 资产巡检 · 采购库存 · 日程台账 · 陪餐水印"
APP_DISCLAIMER = "本工具输出为建议与草稿，不替代现场判断与责任认定。"
# 版本号用于确认浏览器加载的是最新代码；每次功能更新递增。
APP_VERSION = "v2.5"
APP_BUILD_NOTE = (
    "后勤维修编号删除后由新记录优先复用（先补最小空号，再顺延最大值） · "
    "维修明细勾选删除/一键清空 · 明细与各地统计合并导出为一个 Excel 总表 · "
    "维修单手动补录与总量概览"
)
DEFAULT_THREAD_ID = "dawn-dine"


def get_server_host() -> str:
    """网页监听地址；默认仅本机，公开部署时显式改为 0.0.0.0。"""

    return (os.getenv("DAWNDINE_HOST") or "127.0.0.1").strip() or "127.0.0.1"


def get_server_port() -> int:
    """网页端口；默认 7860。"""

    return _env_int("DAWNDINE_PORT", 7860)


def get_server_share() -> bool:
    """是否生成 Gradio 临时公网链接。"""

    return _env_flag("DAWNDINE_SHARE", False)


# ---------------------------------------------------------------------------
# 路径常量（全部为绝对路径，业务文件不得自行拼接目录字符串）
# ---------------------------------------------------------------------------
def _project_root() -> Path:
    """项目根目录：源码布局为 <root>/src/dawndine，可用 DAWNDINE_HOME 覆盖。"""

    override = (os.getenv("DAWNDINE_HOME") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


ROOT_DIR = _project_root()
DATA_DIR = ROOT_DIR / "data"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
TEMPLATES_DIR = DATA_DIR / "templates"
CHROMA_DIR = DATA_DIR / "chroma"
KNOWLEDGE_MANIFEST_FILE = CHROMA_DIR / "knowledge_manifest.json"
WIKI_FILE = KNOWLEDGE_DIR / "wiki.json"
KG_HTML_FILE = DATA_DIR / "kg.html"
UPLOADS_DIR = ROOT_DIR / "uploads"
WATERMARKED_DIR = ROOT_DIR / "watermarked"
EXPORTS_DIR = ROOT_DIR / "exports"
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
    EXPORTS_DIR,
)

# ---------------------------------------------------------------------------
# LangGraph / 提示词兜底关键词
# ---------------------------------------------------------------------------
# 说明：原词表中的“执行 / 确认 / 可以 / 调用”是高频口语词，
# 纯子串匹配会把“这样可以吗”“确认一下”等闲聊误判为强制触发，
# 导致第二次完整 LLM invoke；这里移除它们，短词改为动作词共现。
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
)
FORCED_TRIGGER_SHORT_TERMS: tuple[str, ...] = ("温度", "留样", "水印", "验收")
FORCED_TRIGGER_ACTION_WORDS: tuple[str, ...] = (
    "生成",
    "做个",
    "做一次",
    "帮我",
    "检查",
    "判断",
    "记录",
    "上报",
    "怎么",
    "如何",
    "标准",
    "要求",
    "多少",
    "几小时",
    "能不能",
    "够不够",
    "是否",
)
CONFIRM_ONLY_PATTERN = (
    r"^(好的?|行|可以|嗯+|对|对的|没问题|确认|收到|明白|知道了|ok|OK)[。！.!~～\s]*$"
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
# 日程沉淀（表头）
# ---------------------------------------------------------------------------
SCHEDULE_TABLE_HEADERS: tuple[str, ...] = ("编号", "日期", "时间", "事项", "来源", "创建时间")
SCHEDULE_IMPORT_MAX_RECORDS = 50

# ---------------------------------------------------------------------------
# 后勤维修（表头）
# ---------------------------------------------------------------------------
MAINTENANCE_TABLE_HEADERS: tuple[str, ...] = (
    "编号",
    "地点",
    "故障描述",
    "报修人",
    "报修日期",
    "状态",
    "录入时间",
)
MAINTENANCE_STATS_HEADERS: tuple[str, ...] = ("地点", "维修数量")

# ---------------------------------------------------------------------------
# 检查应对 / RAG / 文本格式
# ---------------------------------------------------------------------------
INSPECTION_ANSWER_MAX_CHARS = 30
# 知识面扩展到七大领域后，提高召回数量，避免只命中单一制度片段。
RAG_TOP_K = 5
RAG_CHUNK_SIZE = 500
RAG_CHUNK_OVERLAP = 80
# 单轮自动注入 system 提示的知识片段上限与字符数，避免挤占对话上下文。
RAG_AUTO_CONTEXT_MAX_ITEMS = 3
RAG_AUTO_CONTEXT_MAX_CHARS = 900
RAG_COLLECTION_NAME = "dawndine_knowledge"

# ---------------------------------------------------------------------------
# LLM 配置常量
# ---------------------------------------------------------------------------
DASHSCOPE_API_KEY_ENV = "DASHSCOPE_API_KEY"
DASHSCOPE_VL_MODEL_ENV = "DASHSCOPE_VL_MODEL"
# 0=false 时网页会话不再回退到 .env，强制每位访客自带 Key，适合公开部署。
DASHSCOPE_ALLOW_ENV_KEY_ENV = "DAWNDINE_ALLOW_ENV_KEY"
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
