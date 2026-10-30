"""轻量寒暄与自我介绍回复。

本文件职责：
- 在进入大模型之前识别纯寒暄、自我介绍、能力询问和道谢；
- 让“你好”“你是谁”“你能做什么”即使没有 API Key 也能得到自然回复；
- 提供网页欢迎语，保证每个新会话打开就有完整自我介绍。

依赖：仅 Python 标准库。
被调用：app.py、cli.py、测试脚本。
"""

from __future__ import annotations

import re

__all__ = [
    "ASSISTANT_NAME",
    "CAPABILITY_REPLY",
    "THANKS_REPLY",
    "WELCOME_REPLY",
    "small_talk_reply",
]

ASSISTANT_NAME = "校园后勤助手"

WELCOME_REPLY = f"""你好！我是 **{ASSISTANT_NAME}**。
我服务学校后勤管理者、食堂食安员、库管、维修/保洁/宿管/绿化人员和值班老师，
覆盖食堂食安与后勤全域：食材安全、台账系统、后厨卫生、采购库存、陪餐反馈、
制度整改、日常咨询，以及维修报修、水电设施、宿舍、保洁环卫、绿化、资产盘点、
安全消防、节能、校车交通、消杀防疫、服务反馈和场馆保障。

我可以帮你：
- **合规判断**：根据现场现象和数值，给出结论、依据与处置动作；
- **知识查询**：查制度、操作标准、台账填法、平台操作和应急流程；
- **台账草稿**：日管控、周排查、月调度、晨检、留样、验菜、陪餐、双人双锁、采购、消毒；
- **异常闭环**：变质、异物、温度超标、证件缺失、虫鼠害、消毒不合格、人员健康异常；
- **数据查询**：查维修单、资产设备、库存与补货、巡检记录、供应商、健康证和服务反馈；
- **每日清单与检查应对**：提醒还缺什么，整理检查口径和证据位置；
- **陪餐/验收水印**：在左侧“图片水印”页上传样图和现场照片生成打卡图；
- **日程记录与分析**：把明确的事项、日期和时间写入“我的日程”，
  也可以分析今天/本周安排、待补时间、时间冲突和优先级。

直接描述一句现场情况就能开始，例如：
“验收冷鲜猪肉，配送单写 0—4℃，我实测 6℃。”
“教学楼三楼走廊灯不亮，报修后多久要完成？”
“查一下维修记录里还有几张待处理。”
"""

CAPABILITY_REPLY = f"""我是 **{ASSISTANT_NAME}**。我的工作围绕学校后勤日常管理，
覆盖食堂食安七大领域与后勤全域（维修、水电、宿舍、保洁、绿化、资产、采购仓储、
安全消防、节能、车辆、消杀、反馈、场馆），主要能帮你：

1. **判断合规**：给我现场现象、数值或票据情况，我按制度给结论和处置动作；
2. **查知识库**：餐具消毒参数、后厨卫生、采购库存、投诉处理、维修流程、宿舍管理、
   保洁绿化、资产盘点、消防安全、节能与消杀等；
3. **起草台账**：日管控、周排查、月调度、晨检、留样、验菜、陪餐、双人双锁、采购、消毒；
4. **处理异常**：整理临时处置、上报对象、整改期限和复核证据；
5. **准备检查**：生成检查口径、证据位置和常见扣分点提醒；
6. **查询台账数据**：维修工单、资产设备、库存预警、巡检异常、供应商、人员健康证、反馈；
7. **生成水印打卡图**：到左侧“🖼️ 图片水印”页上传样图与现场照片；
8. **记录与分析日程**：说“把某事项记到某天某时间”即可写入，
   也可以问“这周有什么安排、有没有时间冲突、哪些没填时间”。

你可以直接说：
- “验收冷鲜猪肉，配送单 0—4℃，我实测 6℃”
- “宿舍三楼热水停了两个小时，先怎么处理？”
- “库存里哪些保洁耗材低于补货线？”
- “帮我生成今天的日管控台账”
- “明天上午 9 点提醒我检查留样柜”
"""

THANKS_REPLY = (
    "不客气！如果还有现场情况需要判断、台账要起草、数据要查询，"
    "或想把事项记进日程，直接告诉我就行。"
)

_GREETING_PATTERN = re.compile(
    r"^(你好|您好|嗨|哈喽|hello|hi|hey|早上好|上午好|中午好|下午好|晚上好|"
    r"在吗|在不在|有人吗|好久不见)[!！。.~～?？\s]*$",
    re.IGNORECASE,
)
_INTRO_PATTERN = re.compile(
    r"(你是谁|你叫什么|介绍一下你|介绍下你|自我介绍|你是什么|你做什么的|"
    r"你是干什么的|你的功能|你有什么用)",
    re.IGNORECASE,
)
_CAPABILITY_PATTERN = re.compile(
    r"(你能做什么|你会做什么|你可以做什么|你能帮我做什么|你有哪些功能|"
    r"有什么功能|怎么使用|怎么用|使用说明|帮助|help)",
    re.IGNORECASE,
)
_THANKS_PATTERN = re.compile(r"^(谢谢|感谢|多谢|thanks|thankyou|thankyouverymuch)[!！。.~～\s]*$")


def _compact(text: str) -> str:
    """去掉空白和常见标点，便于短句匹配。"""

    return re.sub(r"[\s，,。.!！?？;；:：~～]+", "", text or "")


def small_talk_reply(message: str | None) -> str | None:
    """识别纯寒暄类消息并返回固定回复；不是寒暄时返回 None。

    只处理短消息，避免把“你好，帮我生成台账”这类业务请求拦截下来。
    """

    compact = _compact(message or "")
    if not compact or len(compact) > 28:
        return None

    lowered = compact.lower()
    if _THANKS_PATTERN.fullmatch(lowered):
        return THANKS_REPLY
    if _CAPABILITY_PATTERN.search(lowered):
        return CAPABILITY_REPLY
    if _INTRO_PATTERN.search(lowered):
        return CAPABILITY_REPLY
    if _GREETING_PATTERN.fullmatch(lowered):
        return WELCOME_REPLY
    if lowered in {"在", "来了", "我来了", "早上好呀"}:
        return WELCOME_REPLY
    return None
