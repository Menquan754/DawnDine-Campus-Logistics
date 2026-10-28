# 校园食堂后勤助手

> DawnDine 重构版：左侧导航 + 三页工作台的校园食堂食安 Agent。  
> **本工具输出为建议与草稿，不替代现场判断与责任认定。**

项目基于 LangGraph + LangChain + Qwen（DashScope）+ Chroma + SQLite + Gradio + Pillow。
它面向传统食堂管理模式：没有智能秤、AI 摄像头、智能留样柜直连，现场判断仍依赖人工。
系统不替代感官判断，只做合规判断、异常处置引导、台账草稿、流程提醒、检查应对、
陪餐水印和日程沉淀。

---

## 1. 重构后的能力

### 三个工作区

| 页面 | 能力 |
|---|---|
| 💬 食堂助手 | 多轮对话、工具调用、五个快捷工具、独立会话记忆 |
| 🖼️ 图片水印 | 样图建模板、现场图出图、output_path、自动写入日程 |
| 📅 我的日程 | Qwen-VL 图片导入、Dataframe 全量展示、手动添加 |

### 关键升级

1. **多页面 SaaS 工作台**：左侧导航 + 右侧工作区，蓝绿/白灰配色，卡片化布局；
2. **动态 API Key**：每会话在系统设置输入百炼 Key，存 `gr.State`，不写数据库/日志；
3. **动态 Thread ID**：每个浏览器会话生成独立 UUID，避免对话记忆串线；
4. **SQLite 日程库**：`data/dawndine.db`，每页共享；
5. **自动日程沉淀**：台账、异常、水印成功后自动写入摘要；
6. **Qwen-VL 图片日程**：上传通知截图，解析日期/时间/事项/地点并入库；
7. **七个工具**：原六工具 + `add_schedule`。

---

## 2. 技术栈

```text
Python 3.12
LangGraph 0.3.34
LangChain 0.3.30 / langchain-core 0.3.86
langchain-openai 0.3.35
langchain-community 0.3.31
langchain-chroma 0.2.6
ChromaDB 1.5.9
DashScope SDK 2.0.2
Gradio 5.50.0
Pillow 11.3.0
Pydantic 2.12.3
SQLite: Python 标准库 sqlite3（无需新增依赖）
```

模型：

```text
对话/合规    qwen-plus
图片日程     qwen3-vl-plus（可用 DASHSCOPE_VL_MODEL 覆盖）
Embedding   text-embedding-v1
端点        https://dashscope.aliyuncs.com/compatible-mode/v1
thinking    enable_thinking=False
```

### 依赖更新

本次重构**不需要新增第三方包**：

- SQLite 使用 Python 内置 `sqlite3`；
- Qwen-VL 复用已安装的 `langchain-openai` 与 `dashscope`；
- 日程表格复用 Gradio 的 `gr.Dataframe`。

已有环境执行：

```powershell
uv sync
```

从零开始的 uv 安装命令：

```powershell
uv add "langgraph>=0.2.0,<0.4.0" "langchain>=0.3.27,<0.4.0" "langchain-core>=0.3.0,<0.4.0" "langchain-openai>=0.2.0,<0.4.0" "langchain-community>=0.3.0,<0.4.0" "langchain-chroma>=0.2.0,<0.3.0" "langchain-text-splitters>=0.3.0,<0.4.0" "chromadb>=1.0.20,<2.0.0" "gradio>=5.0.0,<6.0.0" "pillow>=10.0.0,<13.0.0" "pydantic>=2.7.0,<3.0.0" "python-dotenv>=1.0.0,<2.0.0" "dashscope>=1.20.0,<3.0.0" "uuid>=1.30"
```

---

## 3. 目录结构

```text
DawnDine --Campus Canteen Logistics Agent/
├── 启动DawnDine.bat               # 双击启动网页
├── 配置APIKey.bat                 # 首次创建 .env 并打开记事本
├── main.py                       # 入口：默认 Web，--cli 控制台
├── app.py                        # 左导航三页工作台
├── cli.py                        # 命令行对话
├── graph.py                      # LangGraph 图 + 动态 Key + Thread
├── schemas.py                    # 七个工具输入模型/输出 TypedDict
├── constants.py                  # 路径/工具名/状态/来源/模型名
├── config/
│   ├── __init__.py
│   ├── llm.py                    # get_llm / get_vision_llm 工厂
│   └── prompts.py                # SYSTEM_PROMPT
├── tools/
│   ├── __init__.py               # 导出 TOOLS
│   ├── watermark.py              # 工具1 水印 + 自动日程
│   ├── compliance.py             # 工具2 合规 + 动态 Key
│   ├── ledger.py                 # 工具3 台账 + 自动日程
│   ├── checklist.py              # 工具4 每日清单
│   ├── abnormal.py               # 工具5 异常 + 自动日程
│   ├── inspection.py             # 工具6 检查应对
│   └── schedule.py               # 工具7 写入日程
├── modules/
│   ├── __init__.py
│   ├── db.py                     # SQLite 日期库
│   ├── vision.py                 # Qwen-VL 图片日程解析
│   ├── watermark_render.py       # Pillow 采样/绘制
│   └── rag_store.py              # Chroma 检索/动态 Key
├── data/
│   ├── knowledge/                # 3 个示例制度 txt
│   ├── templates/                # 水印模板 JSON
│   └── dawndine.db               # 运行时生成，已 gitignore
├── watermarked/                  # PNG 输出
├── uploads/                      # 图片上传
├── .idea/runConfigurations/      # PyCharm Web/CLI
├── .env.example
├── .gitignore
├── pyproject.toml
├── uv.lock
├── README.md
└── ARCHITECTURE.md
```

---

## 4. 快速开始

### 4.1 双击启动

1. 首次双击 `配置APIKey.bat`，填写 `DASHSCOPE_API_KEY`；
2. 双击 `启动DawnDine.bat`；
3. 打开 <http://127.0.0.1:7860>；
4. 保持黑色命令行窗口打开，关闭窗口即停止服务。

如果服务已启动，再次双击只会打开页面，不会重复占用 7860 端口。

### 4.2 终端启动

```powershell
uv sync
uv run main.py
```

CLI：

```powershell
uv run main.py --cli
```

`.env`：

```dotenv
DASHSCOPE_API_KEY=replace-with-your-dashscope-key

# 可选：视觉模型；默认 qwen3-vl-plus
DASHSCOPE_VL_MODEL=qwen3-vl-plus
```

> 旧的 `qwen-vl-plus` 已于 2026-07-13 下线，继续使用会返回
> `404 model_not_found: Model not exist.`。当前默认视觉模型为 `qwen3-vl-plus`。

---

## 5. 动态 Key 与会话隔离

### 5.1 Key 优先级

```text
本次会话在“系统设置”填写的 Key
        ↓ 没有时
.env 中的 DASHSCOPE_API_KEY
        ↓ 没有时
聊天/知识库/图片解析提示配置 Key
```

### 5.2 安全边界

- 页面使用 `gr.Textbox(type="password")`；
- Key 只保存在当前浏览器的 `gr.State`；
- 保存后清空密码输入框；
- 不写入 SQLite；
- 不写入应用日志；
- 不进入聊天消息内容；
- `get_llm(api_key)` / `get_vision_llm(api_key)` 每次按请求创建客户端；
- 系统设置中提供“检测视觉模型”按钮，用 96×96 测试图快速验证 Key、模型与网络。

### 5.3 Thread ID

页面 `.load` 时：

```python
session_id = uuid.uuid4().hex
```

同时写入：

- `thread_id_state`：供 LangGraph `configurable.thread_id`；
- `thread_display`：页面只读显示，便于确认隔离。

每个浏览器会话独立。清空对话只删除当前 thread 的 MemorySaver 记录。

---

## 6. 页面说明

### A. 食堂助手

- 多轮消息流；
- 五个快捷按钮：
  - ＋合规判断
  - ＋异常上报
  - ＋生成台账
  - ＋每日清单
  - ＋检查应对
- 点击按钮会依次完成：
  1. 向输入框写入预设 Prompt 前缀；
  2. 自动提交；
  3. 触发 LangGraph。
- 台账、异常、日程工具执行后，右侧/日程页数据自动刷新。

### B. 图片水印

- 上传样图 → 新建模板；
- 上传现场照片 → 生成打卡图；
- 预览 PNG、复制 output_path；
- 地点缺失自动写“待补”；
- 成功后自动写入日程：
  - 来源：`水印`
  - 内容：`完成陪餐/验收打卡`

### C. 我的日程

1. 顶部图片导入：Qwen-VL 解析日期/时间/事项/地点；
2. 中部 Dataframe：全部日程，按日期/时间倒序；
3. 底部手动表单：日期、时间、事项、添加按钮。

切换回“我的日程”会自动重新读取数据库；也可以点“刷新”。

---

## 7. 七个工具

| 工具 | 说明 | 自动日程 |
|---|---|---|
| `generate_meal_accompaniment_record` | 水印模板/出图 | 是：完成陪餐/验收打卡 |
| `check_compliance_knowledge` | Chroma + Qwen 合规 JSON | 否 |
| `generate_ledger_entry` | 八类台账草稿 | 是：生成XX台账 |
| `daily_checklist_reminder` | 四板块清单 | 否 |
| `create_abnormal_closure` | 异常闭环 | 是：上报XX异常 |
| `inspection_response_guide` | 检查口径 | 否 |
| `add_schedule` | 写入 SQLite 日程 | 本身即写入 |

所有工具仍遵守：

- Pydantic 输入模型集中在 `schemas.py`；
- 返回 `{"ok": True, ...}` 或 `{"ok": False, "error": ...}`；
- 不抛未处理异常给 UI；
- 状态值来自 `constants.py`。

---

## 8. SQLite 数据模型

表 `schedules`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | 自增 |
| `date` | TEXT | YYYY-MM-DD 或“待补” |
| `time` | TEXT | HH:MM 或“待补” |
| `content` | TEXT | 事项 |
| `source` | TEXT | 手动/水印/台账/异常/对话/图片导入 |
| `created_at` | TEXT | 本地创建时间 |

排序：

```sql
ORDER BY ("date" = '待补') ASC,
         "date" DESC,
         ("time" = '待补') ASC,
         "time" DESC,
         id DESC
```

即：有日期的在前，待补日期置底；同日内时间倒序。

来源枚举在 `constants.py`：

```python
SCHEDULE_SOURCE_MANUAL = "手动"
SCHEDULE_SOURCE_WATERMARK = "水印"
SCHEDULE_SOURCE_LEDGER = "台账"
SCHEDULE_SOURCE_ABNORMAL = "异常"
SCHEDULE_SOURCE_CHAT = "对话"
SCHEDULE_SOURCE_IMAGE = "图片导入"
```

---

## 9. Qwen-VL 图片日程

实现位置：`modules/vision.py`。

模型：

```text
默认：qwen3-vl-plus
覆盖：.env 中 DASHSCOPE_VL_MODEL=qwen3-vl-plus
旧模型：qwen-vl-plus 已于 2026-07-13 下线，返回 404
```

设置页提供“检测视觉模型”按钮：用 96×96 测试图调用当前 Key 和视觉模型，
快速判断是模型未开通、Key 问题还是网络问题。

流程：

```text
上传图片
  → Pillow 压缩到最长边 1600
  → base64 data URI
  → get_vision_llm(current_key)
  → qwen3-vl-plus 输出 JSON 数组
  → 校验日期/时间/事项
  → 地点并入事项
  → bulk_create_schedules
  → 刷新 Dataframe
```

约束：

- 只从图片提取可确认内容，不编造缺失字段；
- 日期/时间缺失或无法识别时写“待补”，待补日期排最后；
- 每次最多导入 50 条；
- 没有 Key 时返回明确提示，不崩溃。

---

## 10. LangGraph 与动态 Key

```text
START
  → agent（get_llm(api_key).bind_tools(TOOLS, tool_choice="auto")）
      ├─ 无 tool_calls → 五段式回答 → END
      └─ 有 tool_calls
            → ToolNode（config 透传 api_key）
            → 工具执行
            → ToolMessage
            → agent 生成最终回答
```

- `api_key` 通过 `RunnableConfig.configurable.api_key` 在内存中传递；
- `check_compliance_knowledge` 从 `RunnableConfig` 读取 Key，并传给 RAG 与 LLM；
- Key 不进入 State 或聊天历史；
- `ToolNode(TOOLS, handle_tool_errors=True)`；
- `MemorySaver` 全局唯一，thread_id 按页面会话变化；
- `stream_mode="updates"`。

更多细节见 [ARCHITECTURE.md](ARCHITECTURE.md)。

---

## 11. PyCharm

1. 打开项目根目录；
2. Settings → Project → Python Interpreter → Existing：
   `.venv\Scripts\python.exe`
3. 运行配置：
   - `DawnDine-Web`：`uv run main.py`
   - `DawnDine-CLI`：`uv run main.py --cli`
4. 如运行配置未显示，检查 Shell Script 插件，或直接在 Terminal 执行 `uv run main.py`。

---

## 12. 已执行测试

| 测试 | 结果 |
|---|---|
| `uv sync --check` | 通过 |
| `ruff check` / `ruff format --check` | 通过 |
| Web 启动 `127.0.0.1:7860` | HTTP 200 |
| 三页导航切换 | 通过 |
| 每浏览器 thread_id 唯一 | 通过，两个新会话返回不同 UUID |
| 动态 Key 保存/清除 | 通过，状态变化正常、输入框清空 |
| 工具动态 Key 透传 | 通过，ToolNode 内 compliance 收到测试 Key |
| SQLite 建表/新增/查询 | 通过 |
| 共享会话下 key 状态 | 通过 |
| 台账自动日程 | 通过，`schedule_id > 0` |
| 异常自动日程 | 通过，`schedule_id > 0` |
| 水印自动日程 | 通过，来源=水印 |
| `add_schedule` 图调用 | 通过，Human → AI tool_call → ToolMessage → AI |
| 日程表按日期/时间倒序 | 通过 |
| 手动添加日程 | 通过 |
| 图片解析无 Key 提示 | 通过 |
| Qwen-VL 解析（FakeModel，用户图1） | 通过，11 条记录含地点合并 |
| 视觉模型 404 映射 | 通过，中文提示含模型名与排查方法 |
| 水印（用户图2样图 + 图3现场图） | 通过，PNG 生成、地点/时间正确、自动日程 |
| 视觉模型连通性按钮 | 已实现，真实调用待 Key |
| 水印出图 | 通过，PNG + output_path + 日程 |
| 移动端 500px 布局 | 通过，无横向滚动 |
| 无 Key 聊天 | 通过，中文提示 |
| 页面免责声明 | 通过 |

### 尚未真实联调

当前环境仍未配置真实 `DASHSCOPE_API_KEY`，因此：

- 真实 Qwen 对话未调用；
- 真实 Qwen-VL 识别未调用；
- 真实 DashScope Embedding 未调用；
- 以上部分用 FakeLLM / FakeVision / FakeEmbeddings 验证代码路径。

填 Key 后请补测：

1. 多轮对话与工具调用；
2. 图片日程导入；
3. 合规知识库首次入库；
4. 三页数据联动。

---

## 13. 已知限制

1. **Qwen tool_choice 只用 auto**
   不传 required，靠提示词 + 强制关键词重试兜底；模型仍可能偶尔不调工具。
2. **Qwen-VL 依赖网络与 Key**
   默认 `qwen3-vl-plus`；旧 `qwen-vl-plus` 已下线。图片解析失败会提示模型名与排查方向，不会编造日程。
3. **视觉模型对模糊图片有误差**
   导入后请人工核对表格再使用。
4. **日程表不做复杂权限**
   单机本地使用；多人部署需增加用户表与权限。
5. **Key 存在服务端会话内存**
   浏览器关闭/服务器重启即失效，符合“仅当前会话”设计。
6. **水印中文字体依赖系统**
   优先 msyh.ttc，缺失时 fallback 并在 note 提示。
7. **样图分析不做 OCR**
   模板文字需人工确认。
8. **MemorySaver 纯内存**
   服务重启后对话历史丢失，但 SQLite 日程不丢。
9. **控制台可能看到 LangGraph 未来弃用提示**
   不影响当前运行。

---

## 14. 仍需手动完成

| 事项 | 操作 | 验证 |
|---|---|---|
| 填 Key | 系统设置中填写并保存，或 `.env` | 状态变绿，聊天可用 |
| 测试真实 Qwen | 对话“帮我生成今天的日管控台账” | 状态出现“正在调用工具” |
| 测试 Qwen-VL | 系统设置 → 保存 Key → 检测视觉模型；我的日程 → 上传通知截图 | 模型检测通过，表格新增记录 |
| 校准模板 | 改 JSON 的 text/坐标/字号 | 水印位置符合学校模板 |
| 替换制度 | 更新 data/knowledge，重建索引 | sources 命中新文件 |
| PyCharm | 解释器指向 .venv | Python Console 路径一致 |
| 字体 | 检查 msyh.ttc | 中文正常或 fallback 提示 |

---

## 15. 安全与免责声明

- Key 不显示在前端日志、不写入 SQLite、不进入聊天内容；
- 图片仅在本机服务器处理，不上传训练集；
- 所有输出为建议、提醒、草稿；
- 不声称已上报、已整改、已生成正式记录；
- 不替代现场感官判断和责任认定；
- AI/设备线索必须人工复核；
- 正式记录须由学校责任人核对、签字并按本地最新规定归档。
