"""校园后勤知识库检索工具。

本文件职责：
- 面向食堂食安与后勤全域（维修、宿舍、保洁、绿化、资产、采购仓储、安全消防、
  节能、车辆、消杀、服务反馈、场馆保障）的操作规范、制度流程、台账填写、
  检查整改、应急与日常咨询问题，检索本地知识库并返回可引用片段与要点；
- 只做检索与摘录，不二次调用模型，不编造制度、条款号或数值；
- 无命中时明确提示“知识库未覆盖”，由主模型追问或建议核实本校制度。

依赖：dawndine.llm、dawndine.config、dawndine.enums、dawndine.knowledge.rag、
      dawndine.schemas、langchain-core。
被调用：dawndine.agent.graph（经 agent/tools/__init__.py）、测试脚本。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from dawndine.config import RAG_TOP_K
from dawndine.enums import TOOL_KNOWLEDGE
from dawndine.knowledge.rag import search
from dawndine.llm import api_key_from_config
from dawndine.schemas import KnowledgeSearchInput

logger = logging.getLogger(__name__)

DOMAIN_FOOD_SAFETY = "食材与食品安全"
DOMAIN_LEDGER = "台账与系统操作"
DOMAIN_KITCHEN = "后厨与环境卫生"
DOMAIN_PURCHASE = "采购库存与成本"
DOMAIN_FEEDBACK = "陪餐与师生反馈"
DOMAIN_RULES = "制度整改与应急"
DOMAIN_DAILY = "日常咨询"
DOMAIN_MAINTENANCE = "维修与设施设备"
DOMAIN_DORM = "宿舍后勤"
DOMAIN_CLEANING = "保洁环卫与绿化"
DOMAIN_ASSET = "资产采购与仓储"
DOMAIN_SECURITY = "安全消防与节能"
DOMAIN_SERVICE = "服务反馈与场馆保障"
DOMAIN_GENERAL = "综合"

DOMAIN_LABELS: tuple[str, ...] = (
    DOMAIN_FOOD_SAFETY,
    DOMAIN_LEDGER,
    DOMAIN_KITCHEN,
    DOMAIN_PURCHASE,
    DOMAIN_FEEDBACK,
    DOMAIN_RULES,
    DOMAIN_DAILY,
    DOMAIN_MAINTENANCE,
    DOMAIN_DORM,
    DOMAIN_CLEANING,
    DOMAIN_ASSET,
    DOMAIN_SECURITY,
    DOMAIN_SERVICE,
)

# 关键词顺序即优先级：先命中更具体的领域，避免“温度”等通用词误分类。
_DOMAIN_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        DOMAIN_FOOD_SAFETY,
        (
            "留样",
            "验收",
            "索证",
            "票证",
            "检疫",
            "变质",
            "异物",
            "消毒",
            "清洗",
            "储存",
            "冷藏",
            "冷冻",
            "生熟",
        ),
    ),
    (
        DOMAIN_LEDGER,
        ("台账", "记录", "打卡", "水印", "平台", "系统", "表单", "上传", "导出", "报错", "巡检"),
    ),
    (
        DOMAIN_KITCHEN,
        (
            "后厨",
            "地面",
            "台面",
            "排水沟",
            "垃圾桶",
            "废弃物",
            "健康证",
            "工作服",
            "口罩",
            "帽子",
            "洗手",
            "晨检",
            "设备",
            "冰柜",
            "蒸箱",
            "洗碗机",
            "虫",
            "鼠",
            "蝇",
            "蟑螂",
        ),
    ),
    (
        DOMAIN_PURCHASE,
        ("采购", "下单", "配送", "库存", "先进先出", "临期", "盘点", "损耗", "成本", "供应商"),
    ),
    (
        DOMAIN_FEEDBACK,
        ("投诉", "反馈", "陪餐", "菜单", "营养", "忌口", "过敏", "清真", "排队", "价格", "口味"),
    ),
    (
        DOMAIN_RULES,
        ("制度", "检查", "整改", "复查", "闭环", "应急", "停水", "停电", "食物中毒", "预案"),
    ),
    (DOMAIN_DAILY, ("开放时间", "几点", "窗口", "申领", "物资", "保洁用品", "厨具", "领用")),
    (
        DOMAIN_MAINTENANCE,
        (
            "维修",
            "报修",
            "漏水",
            "渗水",
            "跳闸",
            "断电",
            "灯管",
            "照明",
            "水龙头",
            "下水道",
            "堵塞",
            "马桶",
            "空调",
            "电梯",
            "锅炉",
            "热水器",
            "直饮水",
            "门窗",
            "门锁",
            "课桌椅",
            "插座",
            "配电",
        ),
    ),
    (
        DOMAIN_DORM,
        ("宿舍", "住宿", "查寝", "晚归", "寝室", "洗衣", "热水", "门禁卡"),
    ),
    (
        DOMAIN_CLEANING,
        (
            "保洁",
            "环卫",
            "垃圾",
            "清运",
            "卫生间",
            "绿化",
            "草坪",
            "花木",
            "修剪",
            "消杀",
            "除四害",
        ),
    ),
    (
        DOMAIN_ASSET,
        (
            "资产",
            "编号",
            "盘点",
            "报废",
            "保修",
            "调拨",
            "备件",
            "办公用品",
            "耗材",
            "入库",
            "出库",
            "补货线",
            "仓储",
            "仓库",
        ),
    ),
    (
        DOMAIN_SECURITY,
        (
            "门禁",
            "访客",
            "监控",
            "消防",
            "灭火器",
            "疏散",
            "用电安全",
            "节能",
            "能耗",
            "校车",
            "停车",
            "车辆",
            "充电桩",
        ),
    ),
    (
        DOMAIN_SERVICE,
        ("满意度", "回访", "服务评价", "服务态度", "场馆", "会议保障", "考场", "教室保障"),
    ),
)

_POINT_PATTERN = re.compile(r"^(?:\d+[.、)]|[一二三四五六七八九十]+、|[-•·])\s*(.+)$")
_SENTENCE_END = re.compile(r"[。；;！!？?]")


def detect_domain(question: str, domain: str | None = None) -> str:
    """按关键词识别问题所属领域；无法判断时返回“综合”。"""

    text = f"{domain or ''} {question or ''}".lower()
    if not text.strip():
        return DOMAIN_GENERAL
    best_label = DOMAIN_GENERAL
    best_score = 0
    for label, keywords in _DOMAIN_KEYWORDS:
        score = sum(1 for keyword in keywords if keyword.lower() in text)
        if score > best_score:
            best_label = label
            best_score = score
    return best_label


def _shorten(text: str, limit: int) -> str:
    """截断长文本并保留可读结尾。"""

    clean = (text or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip("，、；;。 ") + "…"


def extract_key_points(hits: list[dict[str, Any]], limit: int = 8) -> list[str]:
    """从检索片段中抽取编号或短句，形成可直接引用的要点列表。"""

    points: list[str] = []
    for hit in hits:
        content = str(hit.get("content") or "")
        matched = False
        for line in content.splitlines():
            candidate = line.strip()
            match = _POINT_PATTERN.match(candidate)
            if not match:
                continue
            point = _shorten(match.group(1), 90)
            if point and point not in points:
                points.append(point)
                matched = True
                if len(points) >= limit:
                    return points
        if matched:
            continue
        # 没有编号结构时，取第一句作为补充要点。
        first_sentence = _SENTENCE_END.split(content.strip(), maxsplit=1)[0]
        point = _shorten(first_sentence, 90)
        if point and len(point) >= 6 and point not in points:
            points.append(point)
            if len(points) >= limit:
                return points
    return points


@tool(TOOL_KNOWLEDGE, args_schema=KnowledgeSearchInput)
def search_food_safety_knowledge(
    question: str,
    domain: str | None = None,
    top_k: int = 3,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """检索本地校园后勤知识库（食堂食安 + 维修/宿舍/保洁/绿化/资产/安全等全域）。

    何时调用：
    - 用户问“怎么做/什么标准/多久/多少/怎么填/怎么处理/在哪申领”等操作或咨询问题；
    - 涉及食材验收、留样、异常上报、储存、餐具消毒、台账、平台操作、
      后厨卫生、人员卫生、设备与虫鼠防制、采购库存、陪餐反馈、检查整改、应急、日常咨询；
    - 涉及维修报修、水电设施、宿舍、保洁环卫、垃圾分类、绿化、资产盘点、
      非食材采购仓储、安全消防、门禁访客、节能、校车交通、消杀防疫、服务反馈、
      教室场馆与会议保障等后勤全域问题；
    - 需要给出制度依据或操作步骤，而本地知识库可能有对应内容。

    何时不调用：
    - 需要四值合规结论的阈值判断，用 check_compliance_knowledge；
    - 需要生成台账、异常闭环、检查口径、水印图或写日程，用对应专用工具；
    - 需要查询本地维修/资产/库存/巡检等台账数据，用 query_logistics_records；
    - 纯寒暄、纯闲聊或与学校后勤无关的问题。

    规则：
    - 只返回知识库原文摘录和要点，不编造条款号、检查人员、地点或数值；
    - 无命中时如实说明“知识库未覆盖”，提示核对本校最新制度；
    - 摘录与用户描述冲突时，以现场事实和本校最新规定为准。

    Returns:
        成功：{"ok": True, "domain", "question", "hits", "sources",
              "key_points", "note"}
        失败：{"ok": False, "error": "..."}
    """

    try:
        clean_question = (question or "").strip()
        if not clean_question:
            return {"ok": False, "error": "question 不能为空，请说明要查询的具体问题。"}

        api_key = api_key_from_config(config)
        resolved_domain = detect_domain(clean_question, domain)
        safe_k = max(1, min(int(top_k or 3), 8))
        query = (
            f"{resolved_domain} {clean_question}"
            if resolved_domain != DOMAIN_GENERAL
            else clean_question
        )
        hits = search(query=query, k=max(safe_k, RAG_TOP_K), api_key=api_key)

        results: list[dict[str, Any]] = []
        sources: list[str] = []
        for item in hits:
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            source = str(item.get("source") or "未知来源").strip()
            results.append(
                {
                    "source": source,
                    "content": _shorten(content, 420),
                    "score": float(item.get("score") or 0.0),
                }
            )
            if source and source not in sources:
                sources.append(source)
        results = results[:safe_k]

        key_points = extract_key_points(results)
        if not results:
            note = (
                "知识库未检索到相关条目。请核对本校最新制度或补充知识文件后重建索引；"
                "不要把通用经验当作正式规定输出。"
            )
        else:
            note = (
                f"领域：{resolved_domain}。以上为知识库原文摘录，具体条款、数值和流程"
                "以本校最新制度及属地监管部门要求为准；涉及感官判断须现场确认。"
            )
        return {
            "ok": True,
            "domain": resolved_domain,
            "question": clean_question,
            "hits": results,
            "sources": sources,
            "key_points": key_points,
            "note": note,
        }
    except Exception as exc:  # noqa: BLE001 - 工具边界必须返回结构化错误
        logger.exception("知识检索工具执行失败")
        return {"ok": False, "error": f"知识检索工具执行失败：{exc}"}
