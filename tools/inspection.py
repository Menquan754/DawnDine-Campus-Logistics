"""监管检查应对口径与材料索引工具。

本文件职责：
- 按检查场景和问题生成不超过 30 字的应答口径；
- 给出依据、材料名称、材料位置提示、常见扣分点和补正建议；
- 涉及补录或 AI 预警时补充专门口径，不虚构归档路径。

依赖：constants.py、schemas.py、langchain-core。
被调用：graph.py（经 tools/__init__.py）、测试脚本。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from constants import (
    INSPECTION_ANSWER_MAX_CHARS,
    TOOL_INSPECTION,
    RecordMode,
)
from schemas import InspectionInput

logger = logging.getLogger(__name__)

_ARCHIVE_HINT = "请核对本校归档目录（食安专柜或平台后台）"

_AREA_LABELS = {
    "dual_lock": "双人双锁",
    "sample": "留样管理",
    "morning": "晨检与人员卫生",
    "acceptance": "验菜与冷链验收",
    "meal": "陪餐管理",
    "ai": "AI 预警",
    "generic": "综合管理",
}

_AREA_KEYWORDS: dict[str, tuple[str, ...]] = {
    "dual_lock": ("双人双锁", "双锁", "钥匙", "双人双检"),
    "sample": ("留样", "125g", "48小时", "48 小时"),
    "morning": ("晨检", "伤口", "健康证", "发热", "手部"),
    "acceptance": ("验菜", "验收", "冷链", "票证", "温度", "索证"),
    "meal": ("陪餐", "评价表", "拍照"),
    "ai": ("ai", "预警", "抓拍", "摄像头", "智能识别"),
}

_ANSWER_SCRIPTS = {
    "dual_lock": "双人同时在场、双锁分人保管，记录可查",
    "sample": "每餐每样留125g，冷藏48小时并记录",
    "morning": "每日岗前晨检，异常人员调离并记录",
    "acceptance": "票证齐全、温度合格、双人验收签字",
    "meal": "陪餐拍照上传，评价表当餐填写",
    "ai": "预警已经人工复核，结论以现场为准",
}

_EVIDENCE = {
    "dual_lock": ["双人双锁登记表", "钥匙保管记录", "双人签字及出入库登记"],
    "sample": ["留样记录", "留样标签照片", "留样柜温度记录", "销毁记录"],
    "morning": ["晨检记录", "从业人员健康证明", "异常人员处置记录"],
    "acceptance": ["验菜记录", "送货单及检疫证明", "温度读数照片", "双人验收签字"],
    "meal": ["陪餐水印照片", "陪餐评价表", "问题反馈及整改记录"],
    "ai": ["AI 预警原始截图或编号", "人工复核记录", "现场处置照片"],
    "generic": ["食品安全管理制度", "自查记录", "培训记录"],
}

_DEDUCTIONS = {
    "dual_lock": ["只有一人到场", "两把钥匙由同一人保管", "登记表缺双人签字", "出入库记录不连续"],
    "sample": ["留样量不足 125g", "未满 48 小时即销毁", "标签缺时间/餐次", "温度记录不全"],
    "morning": ["晨检记录代签", "手部伤口未防护仍接触直接入口食品", "健康证明过期"],
    "acceptance": ["票证与批次不一致", "温度超 0—4℃仍入库", "验收人未签字"],
    "meal": ["陪餐照片无时间地点", "评价表事后集中补填", "问题未闭环"],
    "ai": ["只有系统预警截图，无人工复核", "把 AI 预警直接当违规结论", "复核人未签字"],
    "generic": ["资料散放无法调取", "记录日期前后矛盾", "签字缺失"],
}

_CORRECTIONS = {
    "dual_lock": ["补齐双人签字与钥匙保管记录", "核对双锁是否分别由两人管理"],
    "sample": ["补足 125g 并按餐次贴签", "核对 0—4℃ 与 48 小时保存要求"],
    "morning": ["补齐当日晨检记录", "对伤口人员调整岗位并记录处置"],
    "acceptance": ["补齐票证并核对批次", "附温度读数照片和复测记录"],
    "meal": ["补拍带时间地点的陪餐照片", "当餐填写评价表并记录问题整改"],
    "ai": ["补做人工复核并签字", "保留原图、预警编号和排除误报说明"],
    "generic": ["按目录归档并建立索引", "补齐签字和日期，不补造原始数据"],
}


def _detect_area(question: str, related_area: str | None) -> str:
    """识别检查问题所属领域。"""

    text = f"{related_area or ''} {question or ''}".lower()
    for area, keywords in _AREA_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return area
    return "generic"


def _limit_answer(text: str) -> str:
    """保证应答口径不超过配置的最大字符数。"""

    clean = (text or "").strip()
    if len(clean) <= INSPECTION_ANSWER_MAX_CHARS:
        return clean
    return clean[: INSPECTION_ANSWER_MAX_CHARS - 1].rstrip("，、；; ") + "。"


@tool(TOOL_INSPECTION, args_schema=InspectionInput)
def inspection_response_guide(
    scene: str,
    question: str,
    related_area: str | None = None,
    record_mode: str | None = None,
) -> dict[str, Any]:
    """生成监管检查/校内自查的应答口径、材料索引和补正建议。

    何时调用：
    - 用户问“检查怎么答/材料在哪/怎么解释/被问到某项怎么办”；
    - 涉及双人双锁、留样、晨检、验菜、陪餐或 AI 预警的检查应对；
    - 需要准备检查材料或补正记录。

    何时不调用：
    - 用户要求生成台账、执行异常闭环或制作水印图；
    - 只是询问制度内容，没有检查应对场景；
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
        )

        evidence = list(_EVIDENCE[area])
        deductions = list(_DEDUCTIONS[area])
        corrections = list(_CORRECTIONS[area])
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
        return {
            "ok": True,
            "answer_script": script,
            "basis": basis,
            "evidence": list(dict.fromkeys(evidence)),
            "evidence_locations": list(dict.fromkeys(evidence_locations)),
            "common_deductions": deductions,
            "corrections": list(dict.fromkeys(corrections)),
            "backfill_explanation": backfill_explanation,
            "note": note,
        }
    except Exception as exc:  # noqa: BLE001 - 工具边界必须返回结构化错误
        logger.exception("检查应对工具执行失败")
        return {"ok": False, "error": f"检查应对工具执行失败：{exc}"}
