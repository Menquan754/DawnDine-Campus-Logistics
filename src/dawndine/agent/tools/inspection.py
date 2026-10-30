"""监管检查应对口径与材料索引工具。

本文件职责：
- 按检查场景和问题生成不超过 30 字的应答口径；
- 给出依据、材料名称、材料位置提示、常见扣分点和补正建议；
- 涉及补录或 AI 预警时补充专门口径，不虚构归档路径；
- 成功后把完整结果写入 records 表，供历史回查。

依赖：dawndine.config、dawndine.enums、dawndine.schemas、dawndine.db、
      dawndine.knowledge.rag、langchain-core。
被调用：dawndine.agent.graph（经 agent/tools/__init__.py）、测试脚本。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from dawndine.config import INSPECTION_ANSWER_MAX_CHARS, RAG_TOP_K
from dawndine.db import safe_save_record
from dawndine.enums import RECORD_KIND_INSPECTION, TOOL_INSPECTION, RecordMode
from dawndine.knowledge.rag import search
from dawndine.llm import api_key_from_config
from dawndine.schemas import InspectionInput

logger = logging.getLogger(__name__)

_ARCHIVE_HINT = "请核对本校归档目录（食安专柜或平台后台）"

_AREA_LABELS = {
    "dual_lock": "双人双锁",
    "sample": "留样管理",
    "morning": "晨检与人员卫生",
    "acceptance": "验菜与冷链验收",
    "meal": "陪餐管理",
    "ai": "AI 预警",
    "hygiene": "后厨环境卫生",
    "disinfection": "餐具清洗消毒",
    "purchase": "采购与库存",
    "pest": "虫鼠防制",
    "emergency": "应急处置",
    "generic": "综合管理",
}

_AREA_KEYWORDS: dict[str, tuple[str, ...]] = {
    "dual_lock": ("双人双锁", "双锁", "钥匙", "双人双检"),
    "sample": ("留样", "125g", "48小时", "48 小时"),
    "morning": ("晨检", "伤口", "健康证", "发热", "手部", "工作服", "口罩"),
    "acceptance": ("验菜", "验收", "冷链", "票证", "索证", "温度"),
    "meal": ("陪餐", "评价表", "拍照"),
    "ai": ("ai", "预警", "抓拍", "摄像头", "智能识别"),
    "disinfection": ("餐具", "消毒", "保洁", "有效氯", "消毒柜", "洗碗机"),
    "hygiene": ("后厨", "地面", "台面", "排水沟", "垃圾桶", "废弃物", "卫生"),
    "pest": ("虫", "鼠", "蟑螂", "蝇", "防蝇", "防鼠", "消杀"),
    "purchase": ("采购", "库存", "先进先出", "临期", "盘点", "损耗", "供应商"),
    "emergency": ("应急", "食物中毒", "停水", "停电", "故障", "预案", "燃气", "火灾"),
}

_ANSWER_SCRIPTS = {
    "dual_lock": "双人同时在场、双锁分人保管，记录可查",
    "sample": "每餐每样留125g，冷藏48小时并记录",
    "morning": "每日岗前晨检，异常人员调离并记录",
    "acceptance": "票证齐全、温度合格、双人验收签字",
    "meal": "陪餐拍照上传，评价表当餐填写",
    "ai": "预警已经人工复核，结论以现场为准",
    "hygiene": "每日清洁消毒，地面无积水无油污",
    "disinfection": "一刮二洗三冲四消毒五保洁，记录可查",
    "purchase": "定点采购、票证齐全、先进先出",
    "pest": "设施完好定期检查，发现即封存消杀",
    "emergency": "先停供封存报告，再整改复查",
}

_EVIDENCE = {
    "dual_lock": ["双人双锁登记表", "钥匙保管记录", "双人签字及出入库登记"],
    "sample": ["留样记录", "留样标签照片", "留样柜温度记录", "销毁记录"],
    "morning": ["晨检记录", "从业人员健康证明", "异常人员处置记录"],
    "acceptance": ["验菜记录", "送货单及检疫证明", "温度读数照片", "双人验收签字"],
    "meal": ["陪餐水印照片", "陪餐评价表", "问题反馈及整改记录"],
    "ai": ["AI 预警原始截图或编号", "人工复核记录", "现场处置照片"],
    "hygiene": ["后厨清洁记录", "现场照片", "整改前后对比", "检查签字"],
    "disinfection": ["消毒记录", "温度或浓度照片", "保洁柜照片", "操作人签字"],
    "purchase": ["采购台账", "供货商资质与票证", "验收入库单", "盘点记录"],
    "pest": ["防蝇防鼠设施检查记录", "消杀记录", "设施修补照片", "虫鼠迹处置记录"],
    "emergency": ["应急预案", "演练记录", "事件处置记录", "报告与复查记录"],
    "generic": ["食品安全管理制度", "自查记录", "培训记录"],
}

_DEDUCTIONS = {
    "dual_lock": ["只有一人到场", "两把钥匙由同一人保管", "登记表缺双人签字", "出入库记录不连续"],
    "sample": ["留样量不足 125g", "未满 48 小时即销毁", "标签缺时间/餐次", "温度记录不全"],
    "morning": ["晨检记录代签", "手部伤口未防护仍接触直接入口食品", "健康证明过期"],
    "acceptance": ["票证与批次不一致", "温度超 0—4℃仍入库", "验收人未签字"],
    "meal": ["陪餐照片无时间地点", "评价表事后集中补填", "问题未闭环"],
    "ai": ["只有系统预警截图，无人工复核", "把 AI 预警直接当违规结论", "复核人未签字"],
    "hygiene": ["地面有积水或油污", "排水沟积渣有异味", "垃圾桶未加盖", "清洁记录缺失"],
    "disinfection": ["消毒时间不足", "温度或浓度不达标", "消毒后未入保洁柜", "保洁柜内存放杂物"],
    "purchase": ["无采购台账或票证缺失", "未执行先进先出", "临期食材无处理记录", "账实不符"],
    "pest": ["防蝇帘/挡鼠板破损", "发现鼠迹未处理", "消杀记录缺失", "食品区使用剧毒鼠药"],
    "emergency": ["无应急预案或未演练", "事件发生后未封存现场", "报告不及时", "停水停电无备用方案"],
    "generic": ["资料散放无法调取", "记录日期前后矛盾", "签字缺失"],
}

_CORRECTIONS = {
    "dual_lock": ["补齐双人签字与钥匙保管记录", "核对双锁是否分别由两人管理"],
    "sample": ["补足 125g 并按餐次贴签", "核对 0—4℃ 与 48 小时保存要求"],
    "morning": ["补齐当日晨检记录", "对伤口人员调整岗位并记录处置"],
    "acceptance": ["补齐票证并核对批次", "附温度读数照片和复测记录"],
    "meal": ["补拍带时间地点的陪餐照片", "当餐填写评价表并记录问题整改"],
    "ai": ["补做人工复核并签字", "保留原图、预警编号和排除误报说明"],
    "hygiene": ["立即清洁并保持干燥", "补齐清洁记录和检查签字"],
    "disinfection": ["按要求重新消毒并记录参数", "清理保洁柜并分开存放"],
    "purchase": ["补齐采购台账和票证", "按先进先出整理库存并登记临期"],
    "pest": ["修补防蝇防鼠设施", "补做消杀并留存服务记录"],
    "emergency": ["完善预案并组织演练", "补齐事件处置和复查记录"],
    "generic": ["按目录归档并建立索引", "补齐签字和日期，不补造原始数据"],
}

_SCENE_HINTS: tuple[tuple[tuple[str, ...], list[str]], ...] = (
    (
        ("市场", "监管", "执法", "食安办"),
        ["许可证与健康证", "进货查验与票证", "留样与消毒记录", "加工过程控制", "整改闭环材料"],
    ),
    (
        ("学校", "后勤", "自查", "内部"),
        ["日管控周排查月调度记录", "陪餐记录", "平台资料上传", "双人双锁记录"],
    ),
    (
        ("家长", "开放日", "参观"),
        ["当日菜单与留样", "后厨卫生与着装", "陪餐安排", "意见反馈渠道"],
    ),
)

_MAX_SCENE_FOCUS = 5


def _scene_focus(scene: str) -> list[str]:
    """按检查场景给出重点准备材料，不虚构具体文件路径。"""

    text = scene or ""
    for keywords, focus in _SCENE_HINTS:
        if any(keyword in text for keyword in keywords):
            return list(focus)
    return []


def _detect_area(question: str, related_area: str | None) -> str:
    """识别检查问题所属领域；按命中关键词数量取最具体领域。"""

    text = f"{related_area or ''} {question or ''}".lower()
    scores = {
        area: sum(1 for keyword in keywords if keyword.lower() in text)
        for area, keywords in _AREA_KEYWORDS.items()
    }
    best_area = max(scores, key=scores.get)
    return best_area if scores[best_area] > 0 else "generic"


def _limit_answer(text: str) -> str:
    """保证应答口径不超过配置的最大字符数。"""

    clean = (text or "").strip()
    if len(clean) <= INSPECTION_ANSWER_MAX_CHARS:
        return clean
    return clean[: INSPECTION_ANSWER_MAX_CHARS - 1].rstrip("，、；; ") + "。"


def _kb_basis(query: str, api_key: str) -> tuple[list[str], list[str]]:
    """检索本校制度，返回摘录与去重后的来源文件名。"""

    clean_query = (query or "").strip()
    if not clean_query or not api_key:
        return [], []
    try:
        hits = search(query=clean_query, k=RAG_TOP_K, api_key=api_key)
    except Exception as exc:  # noqa: BLE001 - 检索失败必须静默降级
        logger.warning(
            "检查应对知识检索失败：%s，命中=%s",
            type(exc).__name__,
            0,
        )
        return [], []

    snippets: list[str] = []
    sources: list[str] = []
    for item in hits:
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        snippet = content[:200].rstrip()
        if len(content) > 200:
            snippet += "…"
        snippets.append(snippet)
        source = str(item.get("source") or "").strip()
        if source:
            sources.append(source)
    return snippets, list(dict.fromkeys(sources))


@tool(TOOL_INSPECTION, args_schema=InspectionInput)
def inspection_response_guide(
    scene: str,
    question: str,
    related_area: str | None = None,
    record_mode: str | None = None,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """生成监管检查/校内自查的应答口径、材料索引和补正建议。

    何时调用：
    - 用户问“检查怎么答/材料在哪/怎么解释/被问到某项怎么办”；
    - 涉及双人双锁、留样、晨检、验菜、陪餐、AI 预警、后厨卫生、餐具消毒、
      采购库存、虫鼠防制或应急的检查应对；
    - 需要准备检查材料或补正记录。

    何时不调用：
    - 用户要求生成台账、执行异常闭环或制作水印图；
    - 只是询问制度内容，没有检查应对场景（可用 search_food_safety_knowledge）；
    - 要求提供具体归档文件路径但学校目录未知时，只能提示核对本校归档目录。

    规则：
    - answer_script 不超过 30 字；
    - 涉及补录时附“补录原因说明口径”和原始留痕索引；
    - 涉及 AI 预警时口径必须含“已经人工复核”或等价表述；
    - 材料位置不确定时统一写“请核对本校归档目录”，不得虚构路径；
    - 不替代责任认定，不声称已经提交材料。

    Returns:
        成功：{"ok": True, "answer_script", "basis", "evidence",
              "evidence_locations", "common_deductions", "corrections",
              "backfill_explanation", "note"}
        失败：{"ok": False, "error": "..."}
    """

    try:
        api_key = api_key_from_config(config)
        clean_scene = (scene or "").strip()
        clean_question = (question or "").strip()
        if not clean_scene or not clean_question:
            return {"ok": False, "error": "检查场景和问题不能为空。"}

        parsed_mode: RecordMode | None = None
        if record_mode:
            try:
                parsed_mode = RecordMode(str(getattr(record_mode, "value", record_mode)))
            except ValueError as exc:
                raise ValueError(f"不支持的记录模式：{record_mode}") from exc

        area = _detect_area(clean_question, related_area)
        is_ai = area == "ai" or any(
            word in f"{clean_question} {related_area or ''}".lower()
            for word in ("ai", "预警", "抓拍", "摄像头")
        )
        is_backfill = parsed_mode is RecordMode.BACKFILL

        if is_ai and is_backfill:
            script = "预警已经人工复核，补录原因已注明"
        elif is_ai:
            script = _ANSWER_SCRIPTS["ai"]
        elif area in _ANSWER_SCRIPTS:
            script = _ANSWER_SCRIPTS[area]
        else:
            script = "资料在食安专柜，现场可立即调取"
        script = _limit_answer(script)

        basis = (
            "《学校食品安全与营养健康管理规定》及本校食品安全管理制度；"
            "具体条款和口径以本地最新规定为准，本工具不编造条款号或文号。"
            "（本校制度摘录见 basis_snippets）"
        )
        basis_snippets, sources = _kb_basis(
            f"{clean_scene} {clean_question}",
            api_key,
        )

        evidence = list(_EVIDENCE[area])
        deductions = list(_DEDUCTIONS[area])
        corrections = list(_CORRECTIONS[area])
        scene_focus = _scene_focus(clean_scene)[:_MAX_SCENE_FOCUS]
        evidence_locations = [f"{name}：{_ARCHIVE_HINT}" for name in evidence]
        if scene_focus:
            evidence.extend([f"检查重点材料：{item}" for item in scene_focus])
            evidence_locations = [f"{name}：{_ARCHIVE_HINT}" for name in evidence]

        backfill_explanation = ""
        if is_backfill:
            backfill_explanation = (
                "补录原因说明口径：因（待补：具体原因）未实时录入，"
                "于（待补：补录日期）补录；原始留痕为（待补：纸质记录/照片/系统截图），"
                "索引为（待补：编号或存放位置），可与本记录核对。"
            )
            evidence.extend(["原始留痕索引（待补）", "补录原因说明及审核人签字"])
            evidence_locations = [f"{name}：{_ARCHIVE_HINT}" for name in evidence]
            corrections.append("补录必须写清原因并保留原始记录，不得补造日期或代签。")

        if is_ai:
            basis += " AI 预警仅作线索，必须经人工复核并保留复核记录。"
            corrections.append("口径中明确“已经人工复核”，并准备原图、编号和排除误报说明。")

        if is_backfill and not is_ai:
            script = "补录已说明原因，原始记录可核对"
            script = _limit_answer(script)

        note = (
            f"检查场景：{clean_scene}；领域：{_AREA_LABELS[area]}。"
            "本工具只提供应答口径和材料准备建议，不虚构归档路径，不代替学校正式答复。"
        )
        result = {
            "ok": True,
            "answer_script": script,
            "basis": basis,
            "basis_snippets": basis_snippets,
            "sources": sources,
            "evidence": list(dict.fromkeys(evidence)),
            "evidence_locations": list(dict.fromkeys(evidence_locations)),
            "scene_focus": scene_focus,
            "common_deductions": deductions,
            "corrections": list(dict.fromkeys(corrections)),
            "backfill_explanation": backfill_explanation,
            "note": note,
        }
        record_id = safe_save_record(
            kind=RECORD_KIND_INSPECTION,
            title=f"检查应对：{clean_scene}",
            payload=result,
        )
        result["record_id"] = record_id or 0
        if not record_id:
            result["note"] = f"{result['note'].rstrip()} 草稿已生成，但历史留痕未写入。"
        return result
    except Exception as exc:  # noqa: BLE001 - 工具边界必须返回结构化错误
        logger.exception("检查应对工具执行失败")
        return {"ok": False, "error": f"检查应对工具执行失败：{exc}"}
