"""异常处置与闭环草稿工具。

本文件职责：
- 根据异常来源、类型和现场描述生成风险说明、临时处置、上报对象、整改时限、
  复核方式、留痕清单与闭环记录草稿；
- 对 AI 抓拍和设备告警强制加入人工复核与误报标记，不直接认定违规；
- 成功后向 SQLite 日程表写入“上报XX异常”摘要；
- 成功后把完整结果写入 records 表，供历史回查。

依赖：dawndine.config、dawndine.enums、dawndine.schemas、dawndine.db、
      dawndine.knowledge.rag、langchain-core。
被调用：dawndine.agent.graph（经 agent/tools/__init__.py）、测试脚本。
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from dawndine.config import RAG_TOP_K
from dawndine.db import safe_create_schedule, safe_save_record, split_datetime
from dawndine.enums import (
    ABNORMAL_SOURCE_VALUES,
    CLOSURE_STATUS_VALUES,
    RECORD_KIND_ABNORMAL,
    SCHEDULE_SOURCE_ABNORMAL,
    TOOL_ABNORMAL,
    AbnormalSource,
    ClosureStatus,
)
from dawndine.knowledge.rag import search
from dawndine.llm import api_key_from_config
from dawndine.schemas import AbnormalInput

logger = logging.getLogger(__name__)

_SOURCE_LABELS: dict[AbnormalSource, str] = {
    AbnormalSource.HUMAN: "人工发现",
    AbnormalSource.AI_CAPTURE: "AI 抓拍预警",
    AbnormalSource.DEVICE_ALERT: "设备告警",
}


def _temporary_action(abnormal_type: str, description: str, provided: str | None) -> str:
    """生成临时处置建议；用户提供时优先。"""

    if provided and provided.strip():
        return provided.strip()
    text = f"{abnormal_type} {description}"
    if any(word in text for word in ("疑似", "食物中毒", "多人不适", "多人呕吐", "多人腹泻")):
        return (
            "立即停止供餐或停止相关菜品供应，封存同餐次留样、可疑食材、餐具和工具，"
            "保护现场，组织不适人员就医并报告学校负责人，按应急预案上报属地部门。"
        )
    if any(word in text for word in ("异物", "塑料", "金属", "玻璃", "毛发", "虫子")):
        return (
            "立即停止该菜品供应，封存同锅次食品和同餐次留样，保留异物原物及包装，"
            "不得丢弃或清洗，隔离相关工器具并通知食安员现场复核。"
        )
    if any(word in text for word in ("虫", "鼠", "蟑螂", "蝇", "鼠粪", "鼠迹")):
        return (
            "停止相关区域操作，封存可能被污染的食品和餐具，保护现场并排查污染范围，"
            "安排非供餐时段清洁消杀、封堵孔洞，被污染食品不得清洗后继续使用。"
        )
    if any(word in text for word in ("变质", "霉变", "发酸", "异味", "胀袋", "过期")):
        return (
            "立即隔离该批次并贴停用标识，保留包装、批次和票证，停止使用且不得清洗改作他用，"
            "报告食安员确认后按制度销毁或退货。"
        )
    if any(word in text for word in ("餐具", "消毒", "保洁", "有效氯", "消毒柜")):
        return (
            "隔离相关餐具并重新清洗消毒，核对消毒方式、温度或浓度、时长，"
            "检查保洁柜是否密闭清洁，复检合格前不得使用。"
        )
    if any(word in text for word in ("健康证", "发热", "腹泻", "呕吐", "伤口", "皮肤", "咳嗽")):
        return (
            "立即暂停该人员接触直接入口食品的工作，安排就医或调离岗位，"
            "记录健康状况和处置去向，补办健康证明后方可返岗。"
        )
    if any(word in text for word in ("温度", "冷链", "冷藏", "解冻")):
        return "暂停收货或使用该批次，单独隔离并复测温度，保持现场原状等待复核。"
    if any(word in text for word in ("票证", "检疫", "合格证", "送货单")):
        return "暂停入库并单独存放，票证补齐并核验一致前不得进入加工区。"
    if "留样" in text:
        return "立即封存现有留样，核对同批次、留样量与时间，必要时按规定补足并记录。"
    if any(word in text for word in ("双锁", "钥匙", "锁具")):
        return "暂停该柜/库房取用，核对双人双锁状态与钥匙保管记录，转人工现场核查。"
    if any(word in text for word in ("设备", "柜", "温度计", "报警")):
        return "停止依赖该设备，改用人工方式核查并记录，设备故障转设备管理员处理。"
    return "暂停相关操作，保护现场，通知食安员到场复核，未经确认不得继续使用或处置。"


def _report_targets(
    abnormal_type: str,
    description: str,
    source: AbnormalSource,
) -> list[str]:
    """给出上报对象建议，不虚构具体人名。"""

    targets = ["食堂负责人", "食安监管员"]
    text = f"{abnormal_type} {description}"
    if any(word in text for word in ("温度", "冷链", "票证", "验菜")):
        targets.append("学校后勤管理部门")
    if any(word in text for word in ("疑似", "食物中毒", "多人不适", "多人呕吐", "多人腹泻")):
        targets.extend(["校医/学校卫生负责人", "按学校应急预案上报属地监管部门"])
    if any(word in text for word in ("异物", "变质", "霉变", "过期")):
        targets.extend(["供货商/配送单位", "学校后勤管理部门"])
    if any(word in text for word in ("虫", "鼠", "蟑螂", "蝇")):
        targets.extend(["学校后勤管理部门", "专业消杀机构（必要时）"])
    if any(word in text for word in ("餐具", "消毒", "保洁")):
        targets.extend(["厨师长/洗碗间负责人", "设备管理员"])
    if any(word in text for word in ("健康证", "发热", "伤口", "皮肤")):
        targets.append("校医/学校卫生负责人")
    if source is AbnormalSource.AI_CAPTURE:
        targets.append("AI 预警复核人/信息管理员")
    if source is AbnormalSource.DEVICE_ALERT:
        targets.append("设备管理员")
    return list(dict.fromkeys(targets))


def _deadline(abnormal_type: str, description: str) -> str:
    """给出整改时限建议。"""

    text = f"{abnormal_type} {description}"
    if any(word in text for word in ("疑似", "食物中毒", "多人不适", "多人呕吐", "多人腹泻")):
        return "立即封存并报告，按学校应急预案和属地规定时限处置。"
    if any(word in text for word in ("异物", "变质", "霉变", "虫", "鼠", "蟑螂", "蝇")):
        return "立即停用封存，当日完成初步排查与消杀，24 小时内提交整改并复查。"
    if any(word in text for word in ("餐具", "消毒", "保洁")):
        return "当餐内重新清洗消毒并复检，当日完成记录和整改。"
    if any(word in text for word in ("健康证", "发热", "腹泻", "伤口", "皮肤")):
        return "立即调离并就医，健康证明补办或症状消失并经确认后方可返岗。"
    if any(word in text for word in ("温度", "冷链", "冷藏")):
        return "30 分钟内隔离复测，2 小时内完成初步复核并报告。"
    if any(word in text for word in ("票证", "检疫", "合格证", "送货单")):
        return "当日完成补正；无法补正的按制度拒收或隔离，不得先使用后补。"
    if "留样" in text:
        return "当餐内完成核对与补足，48 小时保存期内不得擅自销毁。"
    return "24 小时内完成初步整改并提交复核材料。"


def _evidence_checklist(
    abnormal_type: str,
    source: AbnormalSource,
) -> list[str]:
    """按异常类型生成留痕清单。"""

    evidence = [
        "现场照片（含时间/地点信息，能反映异常部位）",
        "异常对象或批次标识照片",
        "处置前后对比照片",
        "发现人和复核人签字",
        "上报记录截图或通话记录",
    ]
    text = abnormal_type
    if any(word in text for word in ("温度", "冷链", "冷藏")):
        evidence.extend(["温度计读数照片", "复测温度记录", "冷链票据/送货单"])
    if any(word in text for word in ("票证", "检疫", "合格证", "送货单")):
        evidence.extend(["送货单", "检疫/合格证明", "供应商资质复印件"])
    if "留样" in text:
        evidence.extend(["留样标签照片", "留样量称重照片", "留样柜温度记录"])
    if any(word in text for word in ("双锁", "钥匙", "锁具")):
        evidence.extend(["双锁状态照片", "钥匙保管/领用记录", "双人在场签字"])
    if any(word in text for word in ("异物",)):
        evidence.extend(["异物原物及尺寸参照照片", "同批次食品和留样照片", "菜品留样与销毁记录"])
    if any(word in text for word in ("变质", "霉变", "过期", "异味")):
        evidence.extend(["包装与批次照片", "销毁或退货记录", "同批次排查记录"])
    if any(word in text for word in ("虫", "鼠", "蟑螂", "蝇")):
        evidence.extend(["虫鼠痕迹照片", "消杀服务记录", "设施修补前后照片"])
    if any(word in text for word in ("餐具", "消毒", "保洁")):
        evidence.extend(["消毒温度/浓度照片", "消毒记录表", "保洁柜状态照片"])
    if any(word in text for word in ("健康证", "发热", "伤口", "皮肤")):
        evidence.extend(["健康证明或体检记录", "晨检记录", "岗位调整/就医记录"])
    if source is not AbnormalSource.HUMAN:
        evidence.extend(["AI/设备原始截图或告警编号（待补）", "人工复核记录"])
    return list(dict.fromkeys(evidence))


def _closure_status(source: AbnormalSource, had_temp_action: bool) -> str:
    """确定初始闭环状态；AI/设备告警未经人工确认只能 pending。"""

    if source in {AbnormalSource.AI_CAPTURE, AbnormalSource.DEVICE_ALERT}:
        return ClosureStatus.PENDING.value
    if had_temp_action:
        return ClosureStatus.RECTIFYING.value
    return ClosureStatus.PENDING.value


@tool(TOOL_ABNORMAL, args_schema=AbnormalInput)
def create_abnormal_closure(
    abnormal_type: str,
    found_time: str,
    found_by: str,
    target: str,
    description: str,
    source: str = AbnormalSource.HUMAN.value,
    ai_raw_content: str | None = None,
    temp_action: str | None = None,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """生成食品安全异常处置与闭环草稿。

    何时调用：
    - 用户描述“发现了/看到了/有问题/温度不对/票证不全/留样不够”等异常；
    - 用户要求记录、上报、整改或形成闭环；
    - AI 抓拍或设备告警经人工复核后需要建立处置记录。

    何时不调用：
    - 只是询问一般制度、检查口径或台账模板；
    - 没有异常对象、时间、发现人等基本事实；
    - 要求直接认定责任或处罚（本工具不替代责任认定）。

    关键规则：
    - source=ai_capture/device_alert 时必须包含“请人工复核确认”，
      allow_false_positive=true，初始 closure_status=pending，
      未经人工确认不得进入 confirmed/closed；
    - 只生成处置草稿，不声称已经上报或整改完成；
    - 涉及疑似食物中毒等紧急情况，提示立即走学校应急预案，不以工具结果替代报告。

    Returns:
        成功：{"ok": True, "abnormal_id", "risk_description", "temp_action",
              "report_to", "rectification_deadline", "review_method",
              "evidence_checklist", "closure_draft", "closure_status",
              "allow_false_positive", "note"}
        失败：{"ok": False, "error": "..."}
    """

    try:
        api_key = api_key_from_config(config)
        try:
            parsed_source = AbnormalSource(str(getattr(source, "value", source)))
        except ValueError as exc:
            raise ValueError(f"不支持的异常来源：{source}") from exc
        if parsed_source.value not in ABNORMAL_SOURCE_VALUES:
            raise ValueError("异常来源不在允许范围。")

        required = {
            "abnormal_type": abnormal_type,
            "found_time": found_time,
            "found_by": found_by,
            "target": target,
            "description": description,
        }
        missing = [name for name, value in required.items() if not str(value or "").strip()]
        if missing:
            return {"ok": False, "error": f"缺少异常基本信息：{', '.join(missing)}"}

        abnormal_type = abnormal_type.strip()
        found_time = found_time.strip()
        found_by = found_by.strip()
        target = target.strip()
        description = description.strip()

        had_temp_action = bool((temp_action or "").strip())
        action = _temporary_action(abnormal_type, description, temp_action)
        source_label = _SOURCE_LABELS[parsed_source]
        risk = (
            f"{found_time}，{found_by}发现“{target}”存在{abnormal_type}线索，"
            f"来源为{source_label}。现场描述：{description}。"
            "该描述仅作为风险线索，需现场复核和证据核验，暂不作违规或责任认定。"
        )

        if parsed_source in {AbnormalSource.AI_CAPTURE, AbnormalSource.DEVICE_ALERT}:
            risk += " 请人工复核确认，排除误报后方可进入后续处置。"

        raw_content = (ai_raw_content or "").strip() or "待补"
        report_to = _report_targets(abnormal_type, description, parsed_source)
        deadline = _deadline(abnormal_type, description)
        review_method = (
            "双人现场复核：核对实物批次、复测关键数值、比对票证/照片，"
            "由复核人签字确认；AI/设备线索须先排除误报。"
        )
        evidence = _evidence_checklist(abnormal_type, parsed_source)
        status = _closure_status(parsed_source, had_temp_action)
        if status not in CLOSURE_STATUS_VALUES:
            status = ClosureStatus.PENDING.value

        abnormal_id = f"DD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2).upper()}"
        closure_draft = "\n".join(
            [
                f"异常编号：{abnormal_id}",
                f"发现时间：{found_time}",
                f"发现人：{found_by}",
                f"异常对象：{target}",
                f"异常类型：{abnormal_type}",
                f"线索来源：{source_label}（{parsed_source.value}）",
                f"原始内容：{raw_content}",
                f"现场描述：{description}",
                f"临时处置：{action}",
                f"上报对象：{'、'.join(report_to)}",
                f"整改时限建议：{deadline}",
                f"复核方式：{review_method}",
                f"闭环状态：{status}",
                "复核结论：待补（须由人工填写）",
                "复核人签字：待补",
            ]
        )

        note = "本输出为异常闭环草稿，不替代责任认定，也不表示已经上报或完成整改。"
        allow_false_positive = parsed_source is not AbnormalSource.HUMAN
        if allow_false_positive:
            note += " AI/设备线索存在误报可能，必须人工复核确认。"
        if any(
            word in f"{abnormal_type} {description}"
            for word in ("疑似", "食物中毒", "多人不适", "多人呕吐", "多人腹泻")
        ):
            note += " 如涉及疑似食品安全事件，请立即按学校应急预案报告，不要等待系统处理。"

        schedule_id = 0
        schedule_date, schedule_time = split_datetime(found_time)
        schedule = safe_create_schedule(
            date=schedule_date,
            time=schedule_time,
            content=f"上报{abnormal_type}异常：{target}",
            source=SCHEDULE_SOURCE_ABNORMAL,
        )
        if schedule:
            schedule_id = int(schedule["id"])
            note += " 已同步到“我的日程”。"
        else:
            note += " 日程沉淀失败，但异常草稿已生成，可稍后手动补记。"

        basis_snippets: list[str] = []
        query = f"{abnormal_type} {description}".strip()
        if query and api_key:
            try:
                hits = search(query=query, k=RAG_TOP_K, api_key=api_key)
            except Exception as exc:  # noqa: BLE001 - 检索失败必须静默降级
                logger.warning(
                    "异常知识检索失败：%s，query=%s，命中=%s",
                    type(exc).__name__,
                    query[:60],
                    0,
                )
            else:
                for item in hits:
                    content = str(item.get("content") or "").strip()
                    if not content:
                        continue
                    snippet = content[:200].rstrip()
                    if len(content) > 200:
                        snippet += "…"
                    basis_snippets.append(snippet)

        result = {
            "ok": True,
            "abnormal_id": abnormal_id,
            "source": parsed_source.value,
            "risk_description": risk,
            "temp_action": action,
            "report_to": report_to,
            "rectification_deadline": deadline,
            "review_method": review_method,
            "evidence_checklist": evidence,
            "closure_draft": closure_draft,
            "closure_status": status,
            "allow_false_positive": allow_false_positive,
            "note": note,
            "schedule_id": schedule_id,
            "basis_snippets": basis_snippets,
        }
        record_id = safe_save_record(
            kind=RECORD_KIND_ABNORMAL,
            title=f"{abnormal_type}异常：{target}",
            payload=result,
            schedule_id=schedule_id,
        )
        result["record_id"] = record_id or 0
        if not record_id:
            result["note"] = f"{result['note'].rstrip()} 草稿已生成，但历史留痕未写入。"
        return result
    except Exception as exc:  # noqa: BLE001 - 工具边界必须返回结构化错误
        logger.exception("异常闭环工具执行失败")
        return {"ok": False, "error": f"异常闭环工具执行失败：{exc}"}
