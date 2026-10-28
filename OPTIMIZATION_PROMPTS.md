# DawnDine 优化执行提示词（逐步可跑版）

> 用法：**一次只发一段提示词**。每段跑完、你亲眼验收、`git commit` 之后再发下一段。
> 顺序不能乱 —— 步骤 1 建立回滚点，步骤 2 是后面所有步骤的地基。

---

## 0. 使用纪律（先看这段）

1. **先建 git，再动手。** 项目当前没有版本控制。第 1 步提示词会先帮你 `git init` 并提交基线；没有这一步，后面任何改动都无法回滚。
2. **一步一提交。** 每段提示词跑完，验收通过就 `git add -A && git commit -m "stepN: xxx"`。改坏了 `git checkout -- .` 直接回到上一步。
3. **每段提示词都是自包含的。** 里面有项目路径、现状、精确改动点、硬约束、自测要求，直接整段复制给任意 AI 编码助手即可。
4. **AI 说"做完了"≠ 做对了。** 每段末尾都有「自测」，要求它把输出贴给你；你只看两样：自测是否通过、有没有动不该动的文件。

改动顺序总览：

| 步骤 | 内容 | 收益 | 风险 |
|---|---|---|---|
| 1 | git 基线 | 有回滚能力 | 无 |
| 2 | records 表落库 | ★★★ 从演示品变业务系统 | 低 |
| 3 | 收紧强制触发词 | ★★ 省钱、去误触 | 低 |
| 4 | 日程删除/编辑/今日视图 | ★★★ 实际最痛点 | 中 |
| 5 | RAG 扩到 3 个工具 | ★★★ 答辩硬伤 | 中高 |
| 6 | 补 pytest | ★★ 答辩加分 | 低 |
| 7 | 拆 app.py | ★ 可维护性 | 高 |
| 8 | VL 辅助水印模板 | ★★ 体验提升 | 中 |

---

## 步骤 1 · 建立安全网（必做，10 分钟）

```
【任务】给 DawnDine 项目建立 git 基线，之后的改动都要能一键回滚。

【项目】D:\DawnDine --Campus Canteen Logistics Agent
Python + LangGraph + Gradio 的校园食堂助手，用 uv 管理依赖。
当前目录不是 git 仓库。

【要做的事】
1) 检查 .gitignore 是否存在及内容是否合理。必须忽略：.venv/、__pycache__/、*.pyc、
   .env、data/dawndine.db*、data/chroma/、.ruff_cache/、.idea/、uploads/、watermarked/
   注意：data/knowledge/ 和 data/templates/ 要**保留**（是业务数据，要进版本库）；
   data/*.db 必须忽略（本地数据，不进库）。
   若 .gitignore 缺项就补齐，已有条目保留不动。
2) git init，并把默认分支设为 main。
3) git add -A && git commit -m "baseline: 优化前完整快照"
4) 提交后执行 git ls-files | wc -l 和 git status --porcelain，确认工作区干净。
5) 额外做一次物理备份：把 data/dawndine.db 复制为 data/dawndine.db.bak-20261028
   （数据库文件不入库，但改动前必须有物理备份）。

【硬约束】
- 不要修改任何 .py 文件
- 不要删除 __pycache__ 或 .venv
- 不要在 commit 里包含 .env 或任何 sk- 开头的 Key

【输出】报告 .gitignore 补了哪些行、提交了多少个文件、数据库备份路径、git status 是否干净。
```

---

## 步骤 2 · 原始草稿落库（最高优先级）

> 现状：`modules/db.py` 只有 `schedules` 一张表。台账的 `ledger_items`、异常的 `closure_draft`、清单的 `todos` 生成完就被丢弃，只留一行「生成XX台账」摘要。加一张 `records` 表就能让整个系统从"聊天玩具"变成有沉淀的业务系统。

```
【任务】给 DawnDine 增加 records 落库表，让所有工具生成的完整草稿可回查、可导出。

【项目】D:\DawnDine --Campus Canteen Logistics Agent
技术栈：Python 3.11/3.12 + LangGraph 0.3 + Gradio 5 + SQLite + Chroma，uv 管理。
现有数据层 modules/db.py 已有：_connection() 上下文管理器（自动 commit/rollback）、
init_db() 执行 _SCHEMA 建表脚本、DB_PATH 来自 constants.py。
7 个工具：compliance / ledger / checklist / abnormal / inspection / watermark / schedule。

【目标】

1) modules/db.py 的 _SCHEMA 末尾追加（不要改动 schedules 表任何结构）：
   CREATE TABLE IF NOT EXISTS records (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       kind TEXT NOT NULL,
       title TEXT NOT NULL,
       source TEXT NOT NULL DEFAULT '',
       schedule_id INTEGER,
       payload_json TEXT NOT NULL,
       created_at TEXT NOT NULL
   );
   CREATE INDEX IF NOT EXISTS idx_records_kind_created ON records(kind, created_at DESC);

2) constants.py 在「日程沉淀」段之后新起一段「历史留痕」：
   RECORD_KIND_LEDGER = "ledger"
   RECORD_KIND_ABNORMAL = "abnormal"
   RECORD_KIND_CHECKLIST = "checklist"
   RECORD_KIND_INSPECTION = "inspection"
   RECORD_KIND_COMPLIANCE = "compliance"
   RECORD_KIND_WATERMARK = "watermark"
   RECORD_KIND_VALUES: tuple[str, ...] = (上面全部)

3) modules/db.py 新增 4 个函数，风格严格对齐现有代码（中文 docstring 含 Args/Returns、
   logger、类型注解）：
   - save_record(kind: str, title: str, payload: dict, source: str = "",
                 schedule_id: int | None = None) -> int
   - safe_save_record(同签名) -> int | None
       吞掉所有异常，logger.exception 后返回 None，绝不影响主业务
   - list_records(kind: str | None = None, limit: int = 50) -> list[dict]
       返回时把 payload_json 反序列化进 payload 字段；limit 做 max(1, min(limit, 500)) 保护
   - get_record(record_id: int) -> dict | None
   序列化统一 json.dumps(payload, ensure_ascii=False, default=str)。
   kind 不在 RECORD_KIND_VALUES 时按传入值原样存，但日志 warning。

4) 在 5 个工具的成功返回处落库。做法统一为：
   result = {...}                    # 现有返回 dict
   rid = safe_save_record(...)       # 落库
   result["record_id"] = rid or 0    # 只新增这一个字段
   return result

   具体：
   - tools/ledger.py → generate_ledger_entry
     kind=RECORD_KIND_LEDGER, title=f"{parsed_type.value}台账", payload=result,
     schedule_id=schedule_id（该变量已存在）
   - tools/abnormal.py → create_abnormal_closure
     kind=RECORD_KIND_ABNORMAL, title=f"{abnormal_type}异常：{target}",
     payload=result, schedule_id=schedule_id
   - tools/checklist.py → daily_checklist_reminder
     kind=RECORD_KIND_CHECKLIST, title=f"{clean_date} 每日清单", payload=result
   - tools/inspection.py → inspection_response_guide
     kind=RECORD_KIND_INSPECTION, title=f"检查应对：{clean_scene}", payload=result
   - tools/compliance.py → check_compliance_knowledge
     ⚠️ 该函数有**两处成功 return**：一处是 _sensory_only 短路返回，一处是正常返回。
     两处都必须落库，kind=RECORD_KIND_COMPLIANCE，title=f"{stage}/{object_name}"。
     不要只改一处。

   每个被改的工具文件，按现有注释风格在文件头「本文件职责：」里补一行：
   「- 成功后把完整结果写入 records 表，供历史回查。」

5) 落库失败时的行为：record_id 为 0，并在 note 字段末尾追加
   「草稿已生成，但历史留痕未写入。」（note 不存在的工具就跳过这句）

【硬约束】
- 落库异常绝不能让工具抛错或返回 ok=False
- 不改变任何现有返回字段的语义，只新增 record_id
- 不修改 schedule 工具的落库逻辑
- 本步不碰 app.py
- 不升级依赖、不新增三方包
- 保持代码风格：from __future__ import annotations、中文 docstring、logging.getLogger(__name__)

【自测】
1) python -c 连 data/dawndine.db，打印 records 表结构和索引，确认存在
2) 直接 import 并各跑一次最小样例：
   - generate_ledger_entry(ledger_type="日管控", date_time="2026-10-28 09:00", process_info="晨检已完成")
   - create_abnormal_closure(abnormal_type="温度超标", found_time="2026-10-28 09:10",
     found_by="张三", target="冷库", description="读数 8℃")
   - daily_checklist_reminder(date="2026-10-28", done_items=["晨检已完成"])
   断言三者 record_id > 0，且 list_records() 能取回 payload["ok"] is True
3) grep 一遍 payload_json 中是否有 "api_key" 或 "sk-"，必须为 0 命中
4) 确认 schedules 表行数仍在增长（原有摘要没被破坏）

【输出】逐文件列出改动点，贴自测的实际输出。不要贴大段代码。
```

---

## 步骤 3 · 收紧强制触发词（省成本，去误触）

> 现状：`constants.py` 的 `FORCED_TRIGGER_KEYWORDS` 里有 `"可以"` `"确认"` `"执行"` `"调用"`，而 `graph.py` 的 `_matches_forced_trigger` 是纯子串匹配。用户说一句「这样可以吗」，就会触发第二次完整 LLM 调用，成本和延迟直接翻倍。

```
【任务】收紧 DawnDine 的强制触发词，消除闲聊被误判为"必须调工具"的问题。

【项目】D:\DawnDine --Campus Canteen Logistics Agent
相关代码：constants.py 的 FORCED_TRIGGER_KEYWORDS（约 183 行）；
graph.py 的 _matches_forced_trigger（约 92 行）与 agent_node 里的重试逻辑（约 139-151 行）。

【现状问题】
FORCED_TRIGGER_KEYWORDS = ("温度","留样","125g","台账","日管控","周排查","月调度",
                          "水印","验收","执行","确认","可以","调用")
其中"执行/确认/可以/调用"是极高频口语词，纯子串匹配导致"这样可以吗""你确认一下"
都会命中，触发二次 LLM invoke。_has_tool_result_since_last_human 只能挡住工具返回那一轮，
挡不住这类闲聊轮。

【目标】

1) constants.py：
   - 从 FORCED_TRIGGER_KEYWORDS 中删除 "执行" "确认" "可以" "调用"
   - 保留：温度、留样、125g、台账、日管控、周排查、月调度、水印、验收
   - 新增三个常量：
     FORCED_TRIGGER_SHORT_TERMS = ("温度", "留样", "水印", "验收")
       # 这些短词单独出现不足以强制，必须与动作词共现
     FORCED_TRIGGER_ACTION_WORDS = ("生成", "做个", "做一次", "帮我", "检查", "判断",
                                   "记录", "上报", "怎么", "如何", "标准", "要求",
                                   "多少", "几小时", "能不能", "够不够", "是否")
     CONFIRM_ONLY_PATTERN = (
         r"^(好的?|行|可以|嗯+|对|对的|没问题|确认|收到|明白|知道了|ok|OK)[。！.!~～\s]*$"
     )

2) graph.py 重写 _matches_forced_trigger，签名不变（text: str) -> bool：
   a. text.strip() 为空 → False
   b. re.fullmatch(CONFIRM_ONLY_PATTERN, text) 命中 → False（纯确认/应答不强制）
   c. 遍历 FORCED_TRIGGER_KEYWORDS：若命中，且该词不在 SHORT_TERMS 中 → True
   d. 若命中的都在 SHORT_TERMS 中 → 需要同时命中任意 FORCED_TRIGGER_ACTION_WORDS 才 True
   e. 其余 → False
   保留原 docstring 风格，补一行说明短词共现规则。

3) 不改动的地方：重试逻辑本身、_has_tool_result_since_last_human、_FORCED_RETRY_PROMPT、SYSTEM_PROMPT。

【硬约束】
- 不改 agent_node 的调用顺序与控制流
- 不引入新依赖（re 是标准库）
- 词表改动必须同步在 constants.py 里注释说明"为什么删掉执行/确认/可以/调用"

【自测】写一个临时脚本（跑完删除），逐条断言并打印结果：
  "这样可以吗"                      → False
  "确认一下"                        → False
  "调用一下工具"                    → False
  "好的"                            → False
  "帮我生成日管控台账"              → True
  "留样 125g 够不够"                → True
  "冷库温度 8 度怎么办"             → True
  "帮我看看水印怎么弄"              → True
  "验收需要注意什么标准"            → True
  "今天食堂人多吗"                  → False
把 10 条断言的实际结果贴出来，必须全绿。
```

---

## 步骤 4 · 日程删除 / 编辑 / 今日视图

> 现状：`gr.Dataframe(interactive=False)` 只读，`modules/db.py` 没有 update/delete。VL 图片导入一次最多灌 50 条，导错了无法撤销 —— 这是实际用起来最痛的地方。

```
【任务】给 DawnDine「我的日程」页加删除、修改和视图筛选。

【项目】D:\DawnDine --Campus Canteen Logistics Agent
相关文件：modules/db.py（日程 CRUD）、app.py（页 C 在 build_demo() 内的 page_schedule 块，
约 1120-1190 行；事件绑定在 build_demo 末尾）、constants.py（SCHEDULE_TABLE_HEADERS）。

【现状】
db 层只有 create_schedule / list_schedules / list_schedule_rows / bulk_create_schedules。
UI 上日程表 interactve=False，只能看不能改，误导入无法撤销。

【目标】

1) modules/db.py 新增两个函数（风格对齐现有代码）：
   - delete_schedule(schedule_id: int) -> bool
       DELETE FROM schedules WHERE id=?，rowcount > 0 返回 True；不存在的 id 返回 False 不抛错
   - update_schedule(schedule_id: int, date: str | None = None,
                     time: str | None = None, content: str | None = None) -> dict | None
       只更新传入的非 None 字段；date/time 走 normalize_date/normalize_time；
       content 传空字符串抛 ValueError；id 不存在返回 None；成功返回更新后的完整行

2) list_schedules 增加三个可选参数，默认 None 时行为与现在**完全一致**：
   date_from: str | None = None, date_to: str | None = None, only_pending: bool = False

3) app.py 页 C 在日程表下方新增面板「修改 / 删除单条」：
   - gr.Number(label="日程 ID", precision=0, minimum=1)
   - gr.Checkbox(label="我确认要删除该条日程")
   - 一个「删除」按钮（variant="stop"）+ 一个「修改」按钮（variant="secondary"）
   - 修改用三个 Textbox：日期、时间、事项，占位符写「留空表示不修改」
   - 新增一个 gr.Markdown 显示操作结果（不要复用 schedule_status，那是图片导入的）
   - 删除未勾选确认框时不执行，回显 "⚠️ 请先勾选确认框"

4) 视图筛选：日程表标题旁加 gr.Radio(["全部","今天","未来 7 天","待补时间"]，value="全部")
   - change 事件按区间重新查询（在 db 层用 SQL 过滤，不要在 app 层筛全量内存数据）
   - "待补时间" 对应 "time" = '待补'

5) 所有新增回调沿用现有风格：返回 tuple、失败用 "⚠️" 前缀、logger.exception、api_name=False
   （新增的内部刷新事件不需要暴露 API）

【硬约束】
- 不把 Dataframe 改成 interactive=True，不做整表回写（批量覆盖风险太高）
- 不删除或重排现有组件，只新增
- 不改 image 导入逻辑
- 不新增三方包

【自测】
1) 手动加一条 → 表格出现 → 填 ID 并勾选 → 删除 → 表格少一行
2) 重启应用（进程重开）→ 该条仍不存在（确认是真删库，不是只刷 UI）
3) 修改一条的日期 → 表格顺序随之变化；不填的字段保持不变
4) 切换「今天」→ 只剩今天的记录；切「待补时间」→ 只剩时间为"待补"的
5) 未勾选确认框点删除 → 提示出现且数据未删
```

---

## 步骤 5 · RAG 接到另外三个工具（答辩最容易被打穿的点）

> 现状：只有 `tools/compliance.py` 走了 Chroma，其余六个工具全是硬编码字典。你把 `data/knowledge` 换成本校真实制度后，检查应对、每日清单、异常闭环的**口径一个字都不会变**。

```
【任务】把 DawnDine 的 RAG 从「只有合规判断在用」扩展到检查应对、每日清单、异常闭环三个工具，
并给 UI 加知识库重建入口。

【项目】D:\DawnDine --Campus Canteen Logistics Agent

【现状】
modules/rag_store.py 提供 search(query, k=RAG_TOP_K, api_key="") 和 rebuild_index(api_key)，
内部按 Key 指纹切换 embedding 客户端，全程在锁内串行。
tools/compliance.py 是唯一调用方，通过 `config: RunnableConfig = None` +
`from config.llm import api_key_from_config` 拿当前会话 Key。
其余三个工具完全不接收 config，也没有 api_key：
- tools/inspection.py：_ANSWER_SCRIPTS / _EVIDENCE / _DEDUCTIONS / _CORRECTIONS 全硬编码
- tools/checklist.py：_CATEGORY_KEYWORDS 硬编码，_match_category 未命中返回 None
- tools/abnormal.py：_deadline / _temporary_action / _evidence_checklist 硬编码

【目标】

1) 三个工具函数（inspection_response_guide / daily_checklist_reminder / create_abnormal_closure）
   参数表末尾加 `config: RunnableConfig = None,  # type: ignore[assignment]`，
   函数体开头 `api_key = api_key_from_config(config)`。
   照抄 compliance.py 的写法和 import 路径。
   ⚠️ checklist 和 abnormal 是普通 @tool 函数，加 config 后必须确认 ToolNode 仍能正常注入
   （LangGraph 的 ToolNode 会注入 RunnableConfig，不需要在 args_schema 里声明）。

2) tools/inspection.py
   - 新增 _kb_basis(query: str, api_key: str) -> tuple[list[str], list[str]]：
       调 search(query=query, k=RAG_TOP_K, api_key=api_key)，
       每个命中取 content 前 200 字（超长加 "…"），组成 basis_snippets；
       来源文件名去重后作为 sources。
       任何异常 catch 后返回 ([], [])，logger.warning 只记异常摘要和命中数。
   - 返回 dict 新增两个字段：
       "basis_snippets": list[str]   # 制度原文摘录
       "sources": list[str]          # 来源文件名
   - basis 字段在原有文案末尾追加 "（本校制度摘录见 basis_snippets）"
   - ⚠️ answer_script **保持现有规则表不变**，不要改成 LLM 生成（有 30 字硬限制，规则更稳）

3) tools/checklist.py
   - _match_category 返回 None 时，用该条事项文本做一次 KB 检索，取命中片段里出现的
     CHECKLIST_CATEGORIES 板块名做兜底归属（片段中出现哪个板块名就归哪个）
   - 加进程内缓存：用 functools.lru_cache(maxsize=256) 包一层内部函数，key 用 (文本, Key 指纹)，
     Key 指纹取 hashlib.sha256(api_key)[:12]，不要在缓存 key 里放明文 Key
   - 检索异常必须 catch 后返回 None，退回现状（该条归为未匹配/UNFILLED）
   - 返回 dict 新增 "kb_matched": list[dict]，每项 {"item","category","source"}，
     只记录靠 KB 兜底成功的条目（规则直接命中的不要记）

4) tools/abnormal.py
   - 只新增 "basis_snippets" 字段（检索 query 用 f"{abnormal_type} {description}"）
   - ⚠️ 绝对不要改 _deadline / _temporary_action / _evidence_checklist / _report_targets
     的现有判断逻辑 —— 那部分是经过设计的安全兜底

5) app.py「系统设置」区新增「重建知识库索引」按钮：
   - 回调调 modules.rag_store.rebuild_index(api_key=resolve_api_key(ui_api_key))
   - 成功回显 f"✅ 索引重建完成：{count} 个片段"
   - Key 未配置时直接回显 MISSING_API_KEY_MESSAGE，不发起调用
   - 异常回显 "⚠️ 重建失败：" + 摘要，logger.exception

【硬约束】
- 所有 KB 检索必须在 try/except 内，失败静默降级，三个工具的 ok=True 不受影响
- 不新增任何 LLM 调用（除 compliance 已有）。检索就是检索，不要再 invoke 模型
- 不改 data/knowledge 下的任何文件
- 日志里不打印检索原文，只打印 query 前 60 字和命中数
- 不新增三方包

【自测】
1) 在 data/knowledge 下临时创建 test_rule.txt，内容写一条判据明显的句子，例如
   「测试条款：留样冰箱温度须保持 0—4℃，每日记录两次。」
2) 点 UI 重建索引 → 回显片段数 > 0
3) 调 inspection_response_guide(scene="监管检查", question="留样冰箱温度记录怎么看")，
   断言 sources 里含 "test_rule.txt"，basis_snippets 非空
4) 调 daily_checklist_reminder，传一条规则匹配不到的事项（例如"值班室空调需要清洗"），
   确认 kb_matched 或至少不报错
5) 清空环境变量里的 Key 再调三个工具 → 全部 ok=True，新增字段为空列表
6) 自测完删除 test_rule.txt 并重建一次索引
```

---

## 步骤 6 · 补 pytest（答辩加分，成本最低）

> 现状：`pyproject.toml` 声明了 `testpaths = ["tests"]`，但 `tests/` 目录不存在，依赖里也没有 pytest。README 那张"已执行测试"表是手工跑的。

```
【任务】给 DawnDine 补齐 tests/，让 pyproject 里声明的 testpaths 真正生效。

【项目】D:\DawnDine --Campus Canteen Logistics Agent
pyproject.toml 已有 [tool.pytest.ini_options] testpaths=["tests"] addopts="-q"，
但 tests/ 目录不存在，且 dependencies 里没有 pytest。要求 Python 3.11/3.12，uv 管理。

【目标】

1) 安装测试依赖：`uv add --dev pytest`
   只允许用 uv，不要 pip install。确认 pyproject 的 dev 依赖段生成正确。

2) tests/conftest.py
   - 把项目根目录加入 sys.path（保证能 import constants / modules / tools）
   - 提供 tmp_db fixture：
       monkeypatch.setattr("modules.db.DB_PATH", tmp_path / "test.db")
       from modules.db import init_db; init_db()
     teardown 不需要特殊处理，tmp_path 自动清理
   - ⚠️ modules/db.py 用的是模块级 DB_PATH 常量，必须 patch 模块属性而不是环境变量

3) 至少 12 个用例，按模块拆成 test_db.py / test_tools.py / test_graph.py：
   test_db.py
   - normalize_date：4 种格式各一条 + 空值取今天 + "待补" 原样返回 + 非法值抛 ValueError
   - normalize_time：HH:MM / HH:MM:SS / 空值 → "待补" / 非法抛 ValueError
   - split_datetime：完整日期时间 / 只有日期 → 时间"待补" / 垃圾值不抛错
   - create_schedule + list_schedules：插入两条后按日期倒序，待补排最后
   - delete_schedule：删已有返回 True，重复删返回 False
   test_tools.py
   - abnormal._closure_status：human + 有临时处置 → "rectifying"；ai_capture → "pending"
   - compliance._sensory_only：纯感官 True；含数字 False
   - checklist._status_for_category：异常 > 未完成 > 已完成 > 未填报 四级优先级
   - checklist._match_category：四个板块各一条代表性文本
   - inspection._detect_area：双人双锁 / 留样 / AI 预警 各一条
   - inspection._limit_answer：超长文本被截断且长度 <= 30
   test_graph.py
   - graph._matches_forced_trigger：沿用步骤 3 的 10 条断言（若未执行步骤 3，
     改为当前行为的 6 条基础断言）

4) 不联网：不测 compliance / vision 的真实 LLM 路径，不测 rag_store 的真实 embedding

【硬约束】
- 不为迁就测试修改生产代码；如果测出一个真 bug，单独报告，不要顺手改
- 测试必须能在无网络、无 API Key、无 Chroma 的情况下全绿
- 不打桩整个模块，只 patch 必要的点

【自测】
uv run pytest -q  → 贴出通过数量
uv run ruff check .  → 贴出结果（E/F/I/UP/B 规则）
必须在项目根目录执行，`uv run` 会自动用 .venv
```

---

## 步骤 7 · 拆 app.py（纯搬运，风险最高，放最后）

> 现状：1349 行单文件，CSS 270 行 + 三页布局 + 17 处事件绑定 + 业务逻辑全混在一起。

```
【任务】把 1349 行的 app.py 拆成 ui/ 包。这是纯搬运重构，不允许任何行为变化。

【项目】D:\DawnDine --Campus Canteen Logistics Agent
app.py 结构：模块级工具函数（_message_text/_normalize_history/_parse_tool_payload/
_key_status/_template_choices/_schedule_rows 等）→ 业务回调（chat/clear_chat/
create_template_from_upload/render_watermark_from_upload/refresh_schedules/
add_manual_schedule/import_schedule_from_image/switch_page）→ _CSS（约 270 行）
→ build_demo()（约 450 行，三页组件 + 全部事件绑定）→ launch()。

【分三批做，每批做完都要能正常启动并 commit】

第 1 批（低风险）：抽 CSS
  - 新建 ui/theme.py，把 _CSS 字符串整体搬过去，导出 CSS
  - app.py 改成 from ui.theme import CSS as _CSS
  - 只搬字符串，一个字符都不改

第 2 批（中风险）：抽「我的日程」页
  - 新建 ui/schedule_page.py
  - 用 @dataclass 定义 SchedulePage，字段是页内所有 gr 组件引用
  - build_schedule_page(...) -> SchedulePage 负责创建组件，
    事件绑定仍然留在 build_demo()（用返回的组件引用去 bind）
  - app.py 的 add_manual_schedule / refresh_schedules / import_schedule_from_image
    一并搬到 ui/schedule_page.py

第 3 批（中风险）：抽「图片水印」页
  - 同第 2 批的方式，新建 ui/watermark_page.py
  - create_template_from_upload / render_watermark_from_upload / _template_choices /
    _template_update / _persist_upload 一起搬过去

【不要做的事】
- 不要动聊天页（风险最高，收益最低，留到最后）
- 不要重命名任何函数（保持外部可 import）
- 不要改任何文案、CSS 数值、组件参数、默认值
- 不要用 gradio 新 API，不要引入 @gr.render
- 不要把事件绑定挪进页面函数里（会导致 build_demo 无法统一管理依赖）

【硬约束】
- 每批完成后必须 `uv run python -c "import app; app.build_demo()"` 无异常
- 每批完成后必须实际启动一次，逐页点一遍
- 不新增三方包

【自测（每批都跑）】
1) uv run python -c "import app; app.build_demo()" 通过
2) 启动应用：聊天页发一条消息、水印页生成一张图、日程页加一条日程，三页都正常
3) grep 统计搬迁前后的回调函数名数量一致
4) 报告 app.py 行数的变化（拆分后应显著下降）
```

---

## 步骤 8 · VL 辅助水印模板（体验提升）

> 现状：已经有 `qwen3-vl-plus`，却只用来解析日程截图。`analyze_sample_image` 靠规则采样猜配色，标题写死「校园食堂陪餐」，地点永远「待补」，`text_confidence` 恒为 low。

```
【任务】用项目已有的 qwen3-vl-plus 给水印模板做图像理解，替代规则采样。

【项目】D:\DawnDine --Campus Canteen Logistics Agent
相关文件：modules/watermark_render.py（analyze_sample_image）、modules/vision.py
（现有的 VL 调用方式，照抄它的 client 构造）、constants.py（QWEN_VL_MODEL 等）。

【先做的事】
读 modules/watermark_render.py，确认 analyze_sample_image 当前的入参、返回字段、
以及 text_confidence 现在是怎么算的。**保持入参和返回字段完全不变**，只换内部实现。

【目标】

1) analyze_sample_image 内部改为两段：先 VL 理解，再规则兜底

2) VL 调用：照抄 modules/vision.py 里 qwen3-vl-plus 的 client 构造方式
   （DashScope compatible-mode OpenAI 客户端，图片以 base64 或 file:// 传入），
   让它返回严格 JSON：
   {
     "title": "图中顶部或明显位置的主标题文字，看不清给空字符串",
     "subtitle": "副标题/说明文字，没有给空字符串",
     "location": "图中能读到的地点文字，读不到给空字符串",
     "time_position": "left|center|right",
     "text_color": "#RRGGBB，主文字颜色",
     "panel_color": "#RRGGBB，半透明底衬颜色",
     "has_existing_watermark": true/false,
     "confidence": "high|medium|low"
   }
   提示词必须明确：只描述图中真实可见的文字，不要编造地点和日期，
   不确定的字段返回空字符串，颜色用十六进制、允许近似。

3) 合并策略：
   - VL 字段非空 → 覆盖规则采样值；为空 → 保留规则值
   - text_color / panel_color 必须用正则 ^#[0-9A-Fa-f]{6}$ 校验，非法则回退规则采样
   - text_confidence：VL 返回 high/medium 且 title 非空 → 用 VL 的 confidence；
     否则沿用现有的 low 逻辑
   - has_existing_watermark=True 时，在返回的 note 字段追加
     「检测到样图已有水印，请人工确认是否需要去除」

4) 兜底：VL 调用任何异常（无 Key、超时、JSON 解析失败）→ 完整回退到现有规则采样，
   函数不得抛错，只 logger.warning

【硬约束】
- 不改 render_watermark 的绘图逻辑
- 不改模板 JSON（data/templates/watermark_style_template.json）的字段结构
- 不新增三方包（用项目已有的 openai 兼容客户端 / dashscope）
- 不把 API Key 写进日志或返回 dict

【自测】
1) 用 uploads/ 下任意一张样图跑一次 analyze_sample_image，打印返回 dict，
   确认 title 不再是写死的"校园食堂陪餐"、text_confidence 有变化
2) 清空 Key 再跑一次，确认完整回落到规则值且不报错
3) 用一张纯色空白图跑一次，确认 VL 返回空字符串时不会写出"None"或"null"到模板里
```

---

## 附：验收总表

每步做完，用这张表确认：

| 检查项 | 怎么验 |
|---|---|
| 只有该改的文件被改 | `git status --porcelain` 对比预期文件列表 |
| 能启动 | `uv run python -c "import app; app.build_demo()"` |
| 三页可用 | 启动后逐页点一遍（发消息 / 生成图 / 加日程） |
| 无新增依赖 | `git diff pyproject.toml`，除步骤 6 的 pytest 外应为空 |
| 原功能没退化 | 走一遍：合规判断 → 生成台账 → 异常闭环 → 每日清单 → 检查应对 → 水印 → 日程 |
| 数据可回查 | 步骤 2 之后：`records` 表行数随工具调用增长 |

## 附：一句话触发方式

如果用的是支持直接执行的编码助手，把提示词前面的 `【任务】` 段整段粘进去即可。想更省事可以这样说：

- 「执行 OPTIMIZATION_PROMPTS.md 的步骤 2，做完按文档里的自测跑一遍并把输出贴出来」
- 「只做步骤 3，不要顺手改别的文件」

## 附：不建议现在做的

- **全局锁 `_CHAT_LOCK` 改细粒度**：单机演示不会踩到，改错了反而引入并发 bug。
- **Dataframe 改成可编辑整表回写**：删除 + 单条修改已经解决 90% 的痛点，整表回写要处理脏数据和并发覆盖。
- **MemorySaver 换持久化 checkpointer**：演示场景够用，换 SQLite checkpointer 会引入 schema 迁移问题。
- **`rag_store` 的 `store._collection.count()` 改公开 API**：确实是私有 API，但只在 chromadb 大版本升级时才会碎，等真升级时一起改。
