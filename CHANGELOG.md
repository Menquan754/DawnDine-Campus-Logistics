# Changelog

本项目遵循语义化版本：`MAJOR.MINOR.PATCH`。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

---

## [2.5.0] - 2026-10-30

### Changed — 四阶段架构重构

**第一阶段：骨架与底层基建**

- 源码迁入 `src/` 布局，构建后端改为 `hatchling`，新增 `[project.scripts]`
  `dawndine = "dawndine.__main__:main"`；
- `constants.py` 拆分为 `config.py`（路径 / 环境变量 / 运行参数）与 `enums.py`（业务状态枚举）；
- `schemas.py`、`config/llm.py`、`config/prompts.py`、`modules/db.py` 迁入
  `src/dawndine/{schemas,llm,prompts,db}.py`；
- 严格化 `.gitignore`：`.venv`、`__pycache__`、`data/*.db*`、`data/chroma/`、
  `uploads/*`、`watermarked/*`、`exports/*`、`.env`、日志与截图目录。

**第二阶段：业务与 Agent 层**

- 知识层：`rag_store.py → knowledge/rag.py`、`wiki_store.py → knowledge/wiki.py`、
  `kg_builder.py → knowledge/graph_builder.py`；
- 服务层：`watermark_render.py → services/watermark.py`、
  `schedule_analysis + schedule_image → services/schedule.py`、
  `maintenance_report.py → services/maintenance.py`、`vision.py`、`smalltalk.py`；
- 新增 `services/watermark_store.py`，把模板读写等纯业务逻辑从工具中抽离；
- `graph.py → agent/graph.py`，`tools/* → agent/tools/*`，全部改为绝对路径导入。

**第三阶段：UI 解耦与入口**

- `ui/theme.py` 收纳 CSS、主题与 document 级 JS；
- `ui/pages/` 拆为 assistant / watermark / maintenance / schedule / knowledge / settings；
- `ui/handlers/` 收纳 session / chat / watermark / schedule / maintenance / knowledge / common 回调；
- `ui/app.py` 只保留 `build_demo()` 与 `launch()`；
- 新增 `src/dawndine/__main__.py`（`--web/--cli/--host/--port/--share/--no-browser`）；
- 删除根目录 `app.py`、`main.py`、`cli.py`，`cli.py` 迁入 `src/dawndine/cli.py`。

**第四阶段：开源收尾**

- 重写 `README.md` 与 `ARCHITECTURE.md`，新增 `CHANGELOG.md`；
- 新增 `scripts/windows/首次安装.bat`、`配置APIKey.bat`、`启动DawnDine.bat`；
  根目录同名脚本改为薄封装；
- 首次安装脚本自动执行 `uv sync`、创建 `.venv`、拷贝 `.env`，并由
  `ensure_runtime_dirs()` 自动生成 `data/`、`data/chroma/`、`uploads/`、`watermarked/`、`exports/`；
- 保留各运行目录 `.gitkeep`，保证 clone 后目录结构完整。

### Verified

- `uv run pytest`：192 passed；
- `uv run ruff check .`：通过；
- `build_demo()`：332 组件 / 84 事件；
- 端口实测 HTTP 200。

---

## [2.4.0] - 2026-10-28

### Added

- 后勤维修：Qwen-VL 维修单解析、手动补录、总量概览；
- 维修编号复用（先补最小空号，再顺延 `MAX(id)+1`）；
- 维修明细整行勾选 / 拖动框选 / 一键删除 / 确认清空；
- 维修明细与各地统计合并导出为一个 Excel 总表（两个工作表）；
- 后勤台账只读查询工具 `query_logistics_records`（九类查询）；
- 后勤全域 SQLite 扩展：资产、库存、巡检、供应商、人员、反馈。

### Changed

- 日程与维修列表统一“编号”列与删除后编号复用规则；
- 明细与统计均按地点 `COLLATE NOCASE ASC` 排序。

---

## [2.3.0] - 2026-10-20

### Added

- 知识图谱页：networkx 建图、pyvis 渲染 `data/kg.html`、悬停信息框与防抽搐物理参数；
- 结构化 Wiki 知识（120 条，E001 起统一编号）；
- 知识库按 manifest 指纹自动重建 Chroma；
- 日程分析（今日 / 本周 / 待补 / 过期 / 冲突 / 来源）与 PNG 表格导出。

### Changed

- 知识库扩展为「制度 txt + 结构化 Wiki + 知识图谱」三层；
- 视觉模型默认切换为 `qwen3-vl-plus`（旧 `qwen-vl-plus` 下线）。

---

## [2.2.0] - 2026-10-12

### Added

- 图片水印分步入口：新建模板 / 生成图片 / 管理模板；
- 内容栏 1 / 2，各自位置，先写内容在上；
- 地点、时间可勾选，留空时按规则省略或使用当前时间；
- 模板删除、样式回显、字号倍率微调。

### Fixed

- 样式切换可逆，倍率重复保存不再累积；
- 四角锚点（最左上 / 最右下）精确贴边。

---

## [2.1.0] - 2026-10-01

### Added

- 左侧导航多页工作台（助手 / 水印 / 日程 / 知识库）；
- 系统设置弹窗：API Key、视觉模型检测、索引重建、数据库概览、Agent 初始化、主题；
- 动态 API Key（`gr.State`）与独立 `thread_id` 会话隔离；
- 深色 / 浅色 / 跟随系统主题。

---

## [2.0.0] - 2026-09-20

### Added

- LangGraph Agent：`agent ↔ ToolNode`，十个工具；
- SQLite 日程库与自动日程沉淀；
- 三层分诊与四类回答规范；
- 图片日程解析（Qwen-VL）。

### Removed

- 早期单页线性布局与硬编码 Key 读取路径。

---

## [0.1.0] - 2026-09-01

### Added

- 初始版本：食堂食安问答、合规判断、台账草稿、每日清单、异常处置、检查应对；
- 30 份制度 txt 知识库与 Chroma 检索；
- Gradio 单页界面与命令行入口。
