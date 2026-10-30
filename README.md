# DawnDine · 校园后勤助手

> 食堂食安 + 后勤全域的校园后勤 Agent：LangGraph 工具编排、Gradio 工作台、本地 SQLite 台账、
> 三层知识库（制度 txt + 结构化 Wiki + 知识图谱）、陪餐水印与日程沉淀。
> **本工具输出为建议与草稿，不替代现场判断与责任认定。**

面向没有智能秤、AI 摄像头、智能留样柜、物联网水电表的传统校园后勤场景：
现场判断仍由人工完成，系统负责合规判定、异常处置引导、台账草稿、流程提醒、
检查应对、陪餐水印、维修派工、资产/库存/巡检记录与日程沉淀。

覆盖范围：

- **食堂食安**：食材验收、留样、晨检、餐消、后厨卫生、采购库存、陪餐反馈、制度整改；
- **后勤全域**：维修报修、水电设施、学生宿舍、保洁环卫、垃圾分类、绿化养护、
  资产设备、非食材采购仓储、安全门禁消防、节能降耗、校车交通、消杀防疫、
  服务反馈、教室场馆与会议保障。

---

## 1. 一键运行

### 1.1 Windows 双击（推荐给非开发者）

```text
scripts\windows\
├── 首次安装.bat      # 只运行一次：检测 uv → 创建 .venv → 安装依赖 → 建运行目录
├── 配置APIKey.bat    # 创建 .env 并打开记事本，填入 DASHSCOPE_API_KEY
└── 启动DawnDine.bat  # 日常启动，自动复用/重启本地服务并打开浏览器
```

首次使用顺序：`首次安装.bat` → `配置APIKey.bat` → `启动DawnDine.bat`。
也可以直接双击 `启动DawnDine.bat`：检测到缺少 `.venv` 时会自动先执行首次安装。
Key 不是必填：不配置 `.env` 也能打开工作台，每位访客在页面底部“设置”里填写自己的 Key 即可。
根目录保留同名 `.bat` 作为薄封装，双击后直接调用 `scripts\windows\` 下的脚本。

### 1.2 终端命令

```powershell
# 安装依赖（自动创建 .venv）
uv sync

# 启动网页（默认 http://127.0.0.1:7860）
uv run dawndine

# 等价的模块方式
uv run src/dawndine/__main__.py
```

常用参数：

```powershell
uv run dawndine --cli                     # 命令行对话
uv run dawndine --host 0.0.0.0 --port 7860  # 局域网共享
uv run dawndine --share                   # Gradio 临时公网链接（需联网）
uv run dawndine --no-browser              # 启动后不自动打开浏览器
```

### 1.3 首次安装脚本做了什么

1. 检测 `uv`；缺失时提示安装（`powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` 或 `pip install uv`）；
2. 在项目根目录执行 `uv sync`，自动创建 `.venv` 并按 `uv.lock` 安装锁定版本；
3. 调用 `python -m dawndine --help` 预热导入，同时由 `ensure_runtime_dirs()` 创建
   `data/`、`data/knowledge`、`data/templates`、`data/chroma`、`uploads/`、`watermarked/`、`exports/`；
4. 复制 `.env.example` 为 `.env`（仅在不存在时），并提示下一步配置 Key。

> 克隆下来的仓库不含 `.venv`、`data/chroma`、`data/dawndine.db` 等运行期产物，
> 上述脚本会在首次运行时自动补齐，无需手工建目录。

### 1.4 环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 10/11（脚本为 `.bat`；其他系统可用 `uv sync` + `uv run dawndine`） |
| Python | 3.11 ~ 3.12（`.python-version` 已固定，uv 会自动下载对应版本） |
| 包管理器 | [uv](https://docs.astral.sh/uv/) 0.13+ |
| 网络 | 安装依赖、调用 DashScope、首次建 Chroma 索引时需要 |

---

## 2. 配置 API Key

`.env`（由 `.env.example` 复制而来）：

```dotenv
DASHSCOPE_API_KEY=replace-with-your-dashscope-key

# 可选：视觉模型，默认 qwen3-vl-plus
DASHSCOPE_VL_MODEL=qwen3-vl-plus

# 可选：网页服务
DAWNDINE_HOST=127.0.0.1
DAWNDINE_PORT=7860
DAWNDINE_SHARE=0

# 公开部署建议设为 0：网页不再回退到服务器 .env 中的共享 Key
DAWNDINE_ALLOW_ENV_KEY=1
```

Key 获取：<https://bailian.console.aliyun.com/> 。

Key 优先级：

```text
本会话在“设置”里填写的 Key
        ↓ 没有且 DAWNDINE_ALLOW_ENV_KEY=1
.env 中的 DASHSCOPE_API_KEY
        ↓ 都没有
聊天 / 知识库 / 图片解析给出配置提示
```

页面 Key 只存在当前浏览器的 `gr.State`，不写数据库、不写日志、不进聊天内容；
刷新页面即获得全新 Key 会话与独立 `thread_id`。

---

## 3. 目录结构

```text
DawnDine --Campus Canteen Logistics Agent/
├── pyproject.toml                 # hatchling 构建 + [project.scripts] dawndine
├── uv.lock                        # 锁定依赖版本
├── .python-version
├── .env.example / .env            # .env 已 gitignore
├── README.md / ARCHITECTURE.md / CHANGELOG.md
├── 首次安装.bat                   # 薄封装 → scripts/windows
├── 启动DawnDine.bat               # 薄封装 → scripts/windows
├── 配置APIKey.bat                 # 薄封装 → scripts/windows
├── scripts/
│   └── windows/
│       ├── 首次安装.bat
│       ├── 配置APIKey.bat
│       └── 启动DawnDine.bat
├── src/
│   └── dawndine/
│       ├── __init__.py
│       ├── __main__.py            # CLI 参数解析 + 日志/目录/DB 初始化 + 分发
│       ├── cli.py                 # 命令行对话
│       ├── config.py              # 应用元信息、路径、环境变量、RAG/LLM 参数
│       ├── enums.py               # 业务状态枚举
│       ├── schemas.py             # 十个工具的输入模型 / 输出 TypedDict
│       ├── llm.py                 # get_llm / get_vision_llm 工厂
│       ├── prompts.py             # SYSTEM_PROMPT 与回答规范
│       ├── db.py                  # SQLite 九张业务表
│       ├── knowledge/
│       │   ├── rag.py             # Chroma 检索 / 指纹自动重建
│       │   ├── wiki.py            # Wiki 结构化知识加载与筛选
│       │   └── graph_builder.py   # networkx + pyvis 知识图谱
│       ├── services/
│       │   ├── vision.py          # Qwen-VL 图片日程 / 维修单解析
│       │   ├── schedule.py        # 日程分析 + 日程图片导出
│       │   ├── maintenance.py     # 维修明细/统计合并 Excel
│       │   ├── watermark.py       # Pillow 采样与四角锚点绘制
│       │   ├── watermark_store.py # 模板读写等纯业务逻辑
│       │   └── smalltalk.py       # 寒暄 / 自我介绍
│       ├── agent/
│       │   ├── graph.py           # LangGraph 图 + 动态 Key + Thread
│       │   └── tools/             # 十个工具（见下表）
│       └── ui/
│           ├── theme.py           # CSS / 主题 / JS 脚本
│           ├── app.py             # build_demo() 装配 + launch()
│           ├── pages/             # assistant / watermark / maintenance / schedule / knowledge / settings
│           └── handlers/          # 事件回调：session / chat / watermark / schedule / maintenance / knowledge / common
├── data/
│   ├── knowledge/                 # 30 份制度 txt + wiki.json（120 条结构化知识）
│   └── templates/                 # 水印模板 JSON
├── uploads/  watermarked/  exports/   # 运行期产物，均保留 .gitkeep
├── tests/                         # pytest 用例
└── OPTIMIZATION_PROMPTS.md        # 历史优化任务清单
```

运行时自动生成且不入库：`data/dawndine.db`、`data/chroma/`、`data/kg.html`、
`uploads/*`、`watermarked/*`、`exports/*`、`.runlogs/`、`.venv/`。

---

## 4. 功能概览

| 页面 | 能力 |
|---|---|
| 💬 后勤助手 | 多轮对话、工具调用、快捷工具模板、后勤台账查询、日程复盘、独立会话记忆 |
| 🖼️ 图片水印 | 样图建模板、格式/位置/字号可调、内容栏 1/2、地点时间可勾选、出图并自动写日程 |
| 🔧 后勤维修 | Qwen-VL 维修单解析、手动补录、编号复用、按地点 A-Z 排序、统计与合并导出 Excel |
| 📅 我的日程 | Qwen-VL 图片导入、表格展示、编号复用、PNG 导出、分析、勾选/框选删除、清空 |
| 📚 知识库 | 120 条 Wiki 检索、分类筛选、分类—实体—关联知识图谱 |

十个工具：

| 工具 | 说明 |
|---|---|
| `create_watermark` | 生成陪餐水印并自动写入日程 |
| `compliance_check` | 合规判断（可动态注入 Key） |
| `search_knowledge` | 知识检索（食堂七大 + 后勤全域） |
| `generate_ledger` | 台账草稿 + 自动日程 |
| `daily_checklist` | 每日清单 |
| `handle_abnormal` | 异常闭环 + 自动日程 |
| `inspection_response` | 检查应对 |
| `add_schedule` | 写入日程 |
| `analyze_schedules` | 日程分析（今日/本周/冲突/待补） |
| `query_logistics_records` | 本地 SQLite 九类只读查询 |

回答逻辑：三步分诊（安全 → 诉求类型 → 信息是否足够）→ 四类回答（合规 / 结论要点 /
查询结果 / 处置优先级），安全应急优先，统一五段式并留痕。

---

## 5. 开发与验证

```powershell
uv sync                 # 安装/同步依赖
uv run pytest           # 全部单元测试
uv run ruff check .     # 代码规范（E,F,I,UP,B；line-length 100）
uv run ruff format .    # 可选格式化
```

构建与安装为可分发 CLI：

```powershell
uv build                       # 生成 dist/*.whl 与 sdist
uv tool install dist\dawndine-*.whl   # 安装后可直接运行 dawndine
```

---

## 6. 常见问题

| 现象 | 处理 |
|---|---|
| 双击启动提示找不到 `uv` | 先运行 `scripts\windows\首次安装.bat`，或手动安装 uv 后重开窗口 |
| 页面能开，聊天提示缺少 Key | 运行 `配置APIKey.bat` 填 `DASHSCOPE_API_KEY`，或直接在页面“设置”里填 |
| `404 model_not_found`（视觉） | 旧 `qwen-vl-plus` 已下线，改用 `qwen3-vl-plus` 或设置 `DASHSCOPE_VL_MODEL` |
| 端口被占用 | 设置 `DAWNDINE_PORT=7861` 后重启，或关闭占用程序 |
| 知识库检索为空 | 设置里“重建 Chroma 索引”，或删除 `data/chroma/` 后重启自动重建 |
| 知识图谱空白 | 缺少 `networkx` / `pyvis`，执行 `uv sync` |
| 中文水印字体异常 | 安装微软雅黑/黑体（`C:/Windows/Fonts/msyh.ttc` 等）后重启 |
| 想清空全部本地数据 | 设置 → Agent 初始化；或删除 `data/dawndine.db`、`data/chroma/`、`exports/`、`watermarked/` |

---

## 7. 技术栈

```text
Python 3.11~3.12        LangGraph 0.3.x        LangChain 0.3.x
langchain-openai        langchain-chroma       ChromaDB 1.x
DashScope SDK           Gradio 5.x             Pillow 11.x
pandas 2.3.x            openpyxl 3.1.x         networkx 3.x / pyvis 0.3.x
Pydantic 2.x            SQLite（标准库 sqlite3）uv（依赖与虚拟环境）
```

模型：对话/合规 `qwen-plus`，图片解析 `qwen3-vl-plus`（可用 `DASHSCOPE_VL_MODEL` 覆盖），
Embedding `text-embedding-v1`，端点 `https://dashscope.aliyuncs.com/compatible-mode/v1`，
`enable_thinking=False`。

---

## 8. 安全与边界

- Key 仅存于浏览器会话 `gr.State`，不落库、不写日志、不进消息；
- `DAWNDINE_ALLOW_ENV_KEY=0` 时强制访客自带 Key，适合公网/多人共用；
- 默认只监听 `127.0.0.1`；`--share` 生成的公网链接在有效期内任何人可访问；
- 本地数据全部在项目目录内，删除即清空，不上传云端；
- 输出为建议与草稿，**不替代现场判断与责任认定**。

---

## 9. 免责声明

本项目用于校园后勤日常记录、合规提示与流程辅助，不构成食品安全的最终判定，
不替代监管执法、检验检测与现场责任人的判断。使用本工具产生的台账、报告与
水印图片，请由现场负责人复核后使用。
