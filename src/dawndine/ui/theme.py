"""Gradio 主题、CSS 与前端脚本常量。"""

from __future__ import annotations

import gradio as gr

__all__ = [
    "_CSS",
    "_THEME",
    "_BOOT_JS",
    "_THEME_SYNC_JS",
    "_THEME_CHANGE_JS",
    "_CLOSE_SETTINGS_JS",
    "_WIKI_SCROLL_JS",
    "_TABLE_DATATYPE",
    "_MAINTENANCE_DATATYPE",
]

_CSS = """
:root {
  --dd-bg: #f2f7f6;
  --dd-bg-2: #e8f2ef;
  --dd-surface: #ffffff;
  --dd-soft: #f5faf8;
  --dd-ink: #18332c;
  --dd-muted: #657b75;
  --dd-line: #dce9e5;
  --dd-teal: #0f766e;
  --dd-teal-dark: #0b5c56;
  --dd-cyan: #0891b2;
  --dd-mint: #dff3ec;
  --dd-amber: #b7791f;
  --dd-shadow: 0 12px 32px rgba(24, 51, 44, 0.07);
  --dd-sidebar-bg: rgba(255, 255, 255, 0.94);
  --dd-page-bg: rgba(255, 255, 255, 0.92);
  --dd-panel-shadow: 0 5px 16px rgba(24, 51, 44, 0.04);
  --dd-status-bg: #eef8f4;
  --dd-status-line: #d7ede5;
  --dd-status-ink: #245847;
  --dd-chat-bg: #fbfdfc;
  --dd-quick-bg: #f3faf7;
  --dd-quick-line: #d5ebe3;
  --dd-quick-ink: #286b57;
  --dd-live-bg: #eaf8f3;
  --dd-live-line: #c9e9dd;
  --dd-live-ink: #1f6f58;
  --dd-footer-ink: #6c807a;
  --dd-footer-strong: #2d5c4d;
  --dd-thread-ink: #5f756e;
  --dd-side-footer-ink: #80928c;
  --dd-build-note-ink: #2a7a63;
}
html.dark, :root.dark {
  --dd-bg: #0a1210;
  --dd-bg-2: #0f1b18;
  --dd-surface: #12221e;
  --dd-soft: #162924;
  --dd-ink: #e4f2ed;
  --dd-muted: #9db6ae;
  --dd-line: #23403a;
  --dd-teal: #2dd4bf;
  --dd-teal-dark: #7ff0dd;
  --dd-cyan: #22d3ee;
  --dd-mint: #14332b;
  --dd-amber: #e8bd6a;
  --dd-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
  --dd-sidebar-bg: rgba(18, 34, 30, 0.94);
  --dd-page-bg: rgba(18, 34, 30, 0.9);
  --dd-panel-shadow: 0 5px 18px rgba(0, 0, 0, 0.35);
  --dd-status-bg: #10251f;
  --dd-status-line: #1f4237;
  --dd-status-ink: #b9ead9;
  --dd-chat-bg: #0e1c19;
  --dd-quick-bg: #12241f;
  --dd-quick-line: #22443a;
  --dd-quick-ink: #9ed9c8;
  --dd-live-bg: #123027;
  --dd-live-line: #1f4a3c;
  --dd-live-ink: #9be6cf;
  --dd-footer-ink: #8ba49d;
  --dd-footer-strong: #c7e8dd;
  --dd-thread-ink: #9db6ae;
  --dd-side-footer-ink: #7d958e;
  --dd-build-note-ink: #7fd7bf;
}
html { color-scheme: light; }
html.dark { color-scheme: dark; }
body.dark { color-scheme: dark; background: var(--dd-bg) !important; }
/* Gradio 原生页脚里的“屏幕工作室 / 语言 / 显示主题”入口不再展示 */
footer .settings, footer .record, footer .divider { display: none !important; }
.gradio-container {
  width: 100% !important;
  max-width: 1500px !important;
  margin: 0 auto !important;
  padding: 18px 22px 30px var(--dd-pad-left, 310px) !important;
  background:
    radial-gradient(circle at 8% 0%, rgba(8, 145, 178, 0.09), transparent 30%),
    radial-gradient(circle at 96% 2%, rgba(15, 118, 110, 0.08), transparent 28%),
    var(--dd-bg);
}
#dd-sidebar {
  left: max(12px, calc((100vw - 1500px) / 2 + 2px)) !important;
  top: 12px !important;
  width: 286px !important;
  height: calc(100vh - 24px) !important;
  max-height: calc(100vh - 24px) !important;
  overflow: hidden !important;
  /* 滚动交给内层 .sidebar-content，并隐藏其滚动条 */
  scrollbar-width: none;
  -ms-overflow-style: none;
  overscroll-behavior: contain;
  transform: translateX(0) !important;
  background: var(--dd-sidebar-bg) !important;
  border: 1px solid var(--dd-line) !important;
  border-radius: 22px !important;
  padding: 0 !important;
  box-shadow: var(--dd-shadow) !important;
  min-width: 286px !important;
  align-self: flex-start;
}
#dd-sidebar::-webkit-scrollbar {
  width: 0 !important;
  height: 0 !important;
  display: none !important;
}
/* 侧栏内容：纵向弹性布局，底部留白与顶部一致 */
#dd-sidebar .sidebar-content {
  display: flex !important;
  flex-direction: column !important;
  flex: 1 1 auto !important;
  height: 100% !important;
  box-sizing: border-box;
  min-height: 0;
  padding: 0 !important;
  overflow: hidden !important;
  scrollbar-width: none;
  -ms-overflow-style: none;
  overscroll-behavior: contain;
}
#dd-sidebar .sidebar-content > .column {
  display: flex !important;
  flex-direction: column !important;
  flex: 1 1 auto !important;
  height: 100% !important;
  box-sizing: border-box;
  gap: 12px !important;
  min-height: 0;
  padding: 18px 14px !important;
  overflow-y: auto !important;
  scrollbar-width: none;
  -ms-overflow-style: none;
  overscroll-behavior: contain;
}
/* Gradio 会把 Radio 与 thread_id 包进同一个 form：让该 form 吃掉剩余高度，
   使 thread_id、说明与免责声明整体贴近侧栏底部 */
#dd-sidebar .sidebar-content > .column > .form {
  display: flex !important;
  flex-direction: column !important;
  flex-wrap: nowrap !important;
  flex: 1 1 auto !important;
  gap: 12px !important;
  min-height: 0;
  /* form 只是 Gradio 的分组壳：去掉它的灰底与边框，避免拉伸后出现空灰块 */
  background: transparent !important;
  border: 0 !important;
  border-radius: 0 !important;
  box-shadow: none !important;
  overflow: visible !important;
}
#dd-sidebar .sidebar-content::-webkit-scrollbar,
#dd-sidebar .sidebar-content > .column::-webkit-scrollbar {
  width: 0 !important;
  height: 0 !important;
  display: none !important;
}
#dd-sidebar .sidebar-content > * { min-width: 0; }
/* 当前会话信息组（thread_id + 说明 + 免责声明）贴近侧栏底部，
   底部留白与顶部 18px 对齐 */
#dd-sidebar .dd-thread { margin-top: auto !important; }
#dd-sidebar .toggle-button { display: none !important; }
.toggle-button { display: none !important; }
.dd-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 2px 2px 12px;
  border-bottom: 1px solid var(--dd-line);
  margin-bottom: 0;
}
.dd-logo {
  width: 36px;
  height: 36px;
  border-radius: 11px;
  display: grid;
  place-items: center;
  color: #fff;
  font-weight: 900;
  font-size: 13px;
  letter-spacing: -0.06em;
  background: linear-gradient(135deg, var(--dd-teal), var(--dd-cyan));
  box-shadow: 0 8px 18px rgba(15, 118, 110, 0.24);
}
.dd-brand-name {
  font-size: 14px;
  font-weight: 850;
  color: var(--dd-ink);
  line-height: 1.3;
  white-space: normal;
}
.dd-brand-sub {
  margin-top: 2px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--dd-muted);
}
#dd-nav { margin-top: 0; }
#dd-nav .wrap {
  display: flex !important;
  flex-direction: column !important;
  gap: 10px !important;
}
#dd-nav label {
  display: flex !important;
  align-items: center !important;
  width: 100% !important;
  min-height: 48px;
  border: 1px solid transparent !important;
  border-radius: 14px !important;
  padding: 12px 14px !important;
  background: transparent !important;
  color: var(--dd-ink) !important;
  font-size: 14px !important;
  line-height: 1.35 !important;
  font-weight: 650 !important;
  white-space: normal !important;
  cursor: pointer;
}
#dd-nav label > span {
  font-size: 14px !important;
  line-height: 1.35 !important;
}
#dd-nav label:hover { background: var(--dd-soft) !important; }
#dd-nav label:has(input:checked) {
  background: var(--dd-mint) !important;
  border-color: rgba(15, 118, 110, 0.18) !important;
  color: var(--dd-teal-dark) !important;
}
#dd-nav input { accent-color: var(--dd-teal); margin-right: 4px; }
.dd-side-note {
  margin-top: 0;
  padding: 11px;
  border-radius: 14px;
  background: var(--dd-soft);
  border: 1px solid var(--dd-line);
  color: var(--dd-muted);
  font-size: 11px;
  line-height: 1.6;
}
.dd-side-footer {
  margin-top: 10px;
  color: var(--dd-side-footer-ink);
  font-size: 10px;
  line-height: 1.5;
}
#dd-sidebar .dd-thread label span,
#dd-sidebar .dd-thread label {
  color: var(--dd-muted) !important;
  font-size: 10.5px !important;
}
#dd-sidebar .dd-thread textarea {
  font-family: "Cascadia Code", Consolas, monospace;
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--dd-thread-ink);
  /* 侧栏窄，短 id 也要完整显示：允许换行，不再省略截断 */
  white-space: normal !important;
  overflow: visible !important;
  text-overflow: clip !important;
}
.dd-topbar {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  row-gap: 8px;
  gap: 16px;
  align-items: flex-start;
  padding: 6px 4px 16px;
}
.dd-topbar > div:first-child { min-width: 0; }
.dd-title {
  margin: 5px 0 3px !important;
  color: var(--dd-ink) !important;
  font-size: clamp(25px, 3vw, 34px) !important;
  line-height: 1.18 !important;
  font-weight: 850 !important;
  letter-spacing: -0.02em;
}
.dd-subtitle {
  margin: 0 !important;
  color: var(--dd-muted) !important;
  font-size: 13px !important;
  line-height: 1.6 !important;
  white-space: normal !important;
}
.dd-build-note {
  margin: 6px 0 0 !important;
  color: var(--dd-build-note-ink) !important;
  font-size: 11px !important;
  line-height: 1.5 !important;
}
.dd-live {
  flex: none;
  margin-top: 8px;
  border-radius: 999px;
  padding: 7px 11px;
  background: var(--dd-live-bg);
  border: 1px solid var(--dd-live-line);
  color: var(--dd-live-ink);
  font-size: 11px;
  font-weight: 700;
  white-space: normal;
  text-align: center;
}
.dd-page {
  border: 1px solid var(--dd-line) !important;
  border-radius: 22px !important;
  background: var(--dd-page-bg) !important;
  box-shadow: var(--dd-shadow) !important;
  padding: 18px !important;
}
.dd-panel {
  border: 1px solid var(--dd-line) !important;
  border-radius: 18px !important;
  background: var(--dd-surface) !important;
  padding: 14px !important;
  box-shadow: var(--dd-panel-shadow) !important;
}
/* 图片水印：主操作区大卡片按钮与分步弹窗容器 */
.dd-wm-actions {
  gap: 14px !important;
  flex-wrap: wrap !important;
}
.dd-wm-card {
  position: relative;
  min-height: 112px !important;
  border-radius: 16px !important;
  border: 1px solid var(--dd-line) !important;
  background: var(--dd-surface) !important;
  color: var(--dd-ink) !important;
  font-size: 15px !important;
  font-weight: 800 !important;
  letter-spacing: 0.01em;
  box-shadow: var(--dd-panel-shadow) !important;
  overflow: hidden;
  transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease !important;
}
/* 卡片内真正的按钮铺满整张卡片（含外壳留白），避免只有左侧窄条可点 */
.dd-wm-card > button,
.dd-wm-card > .wrap,
.dd-wm-card > .block > button {
  position: absolute !important;
  inset: 0 !important;
  width: 100% !important;
  height: 100% !important;
  min-height: 100% !important;
  margin: 0 !important;
  padding: 16px 18px !important;
  border: none !important;
  border-radius: 16px !important;
  background: transparent !important;
  box-shadow: none !important;
  color: var(--dd-ink) !important;
  font-size: 15px !important;
  font-weight: 800 !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  text-align: center !important;
  cursor: pointer !important;
}
.dd-wm-card:hover {
  transform: translateY(-2px);
  border-color: var(--dd-teal) !important;
  box-shadow: 0 14px 30px rgba(15, 118, 110, 0.18) !important;
}
.dd-wm-card:active { transform: translateY(0); }
.dd-wm-modal {
  border: 1px solid var(--dd-line) !important;
  border-radius: 18px !important;
  background: var(--dd-soft) !important;
  padding: 14px 16px 16px !important;
  box-shadow: var(--dd-panel-shadow) !important;
  margin-top: 4px !important;
}
.dd-wm-close {
  margin-top: 10px !important;
}
/* 知识库：图谱 iframe 与空状态 */
#dd-kg { padding: 0 !important; }
.dd-kg-frame {
  width: 100% !important;
  height: 780px !important;
  border: 1px solid var(--dd-line) !important;
  border-radius: 16px !important;
  background: var(--dd-surface) !important;
  box-shadow: var(--dd-panel-shadow) !important;
}
.dd-kg-empty {
  padding: 32px 20px !important;
  text-align: center;
  color: var(--dd-muted) !important;
  border: 1px dashed var(--dd-line) !important;
  border-radius: 16px !important;
  background: var(--dd-soft) !important;
  line-height: 1.9;
}
.dd-card-title {
  margin: 0 0 10px !important;
  color: var(--dd-ink) !important;
  font-size: 14px !important;
  font-weight: 800 !important;
  line-height: 1.5 !important;
  white-space: normal !important;
}
.dd-card-title + p { color: var(--dd-muted) !important; }
/* 我的日程 / 后勤维修：与图片水印一致的分模块卡片（列表置顶，其余功能各自成块） */
.dd-sch-module,
.dd-maint-module {
  border: 1px solid var(--dd-line) !important;
  border-radius: 18px !important;
  background: var(--dd-surface) !important;
  padding: 14px 16px 16px !important;
  box-shadow: var(--dd-panel-shadow) !important;
  margin: 0 0 14px !important;
}
.dd-sch-module > .dd-card-title,
.dd-sch-module > .dd-sch-title,
.dd-maint-module > .dd-card-title,
.dd-maint-module > .dd-maint-title {
  margin: 0 0 6px !important;
  color: var(--dd-ink) !important;
  font-size: 14px !important;
  font-weight: 800 !important;
  line-height: 1.5 !important;
}
.dd-sch-module > .dd-hint,
.dd-maint-module > .dd-hint { margin: 0 0 10px !important; }
.dd-sch-module .dd-status,
.dd-sch-module .dd-key-status,
.dd-maint-module .dd-status,
.dd-maint-module .dd-key-status { margin: 6px 0 0 !important; }
.dd-sch-module .dd-table-toolbar,
.dd-maint-module .dd-table-toolbar { margin-bottom: 6px !important; }
/* 日程列表工具条：标题、视图切换、刷新按钮同排居中，去掉多余标签占位 */
.dd-table-toolbar {
  align-items: center !important;
  justify-content: space-between !important;
  flex-wrap: wrap !important;
  gap: 10px 14px !important;
  margin-bottom: 8px !important;
}
.dd-table-toolbar .dd-card-title {
  margin: 0 !important;
  flex: 0 1 auto;
}
.dd-table-toolbar .dd-view-radio {
  min-width: 0 !important;
}
.dd-table-toolbar .dd-view-radio .wrap {
  gap: 6px 10px !important;
}
/* 我的日程 / 后勤维修：可勾选删除列表（点击整行 / 按住拖动框选） */
#dd-sched-select .wrap,
#dd-maint-select .wrap {
  display: flex !important;
  flex-direction: column !important;
  flex-wrap: nowrap !important;
  max-height: 320px;
  overflow-y: auto;
  gap: 6px !important;
  padding: 2px !important;
}
#dd-sched-select label,
#dd-maint-select label {
  display: flex !important;
  align-items: flex-start !important;
  width: 100% !important;
  margin: 0 !important;
  padding: 8px 10px !important;
  border: 1px solid var(--dd-line) !important;
  border-radius: 10px !important;
  background: var(--dd-soft) !important;
  color: var(--dd-ink) !important;
  font-size: 13px !important;
  line-height: 1.5 !important;
  cursor: pointer;
  user-select: none;
}
#dd-sched-select label:hover,
#dd-maint-select label:hover { border-color: var(--dd-teal) !important; }
#dd-sched-select label:has(input:checked),
#dd-maint-select label:has(input:checked) {
  border-color: var(--dd-teal) !important;
  background: var(--dd-mint) !important;
}
#dd-sched-select input[type="checkbox"],
#dd-maint-select input[type="checkbox"] {
  accent-color: var(--dd-teal);
  margin: 3px 8px 0 0;
  flex: 0 0 auto;
}
#dd-sched-select label span,
#dd-maint-select label span {
  white-space: normal !important;
  overflow-wrap: anywhere;
}
.dd-sched-tools {
  gap: 8px !important;
  flex-wrap: wrap !important;
  margin-bottom: 8px !important;
}
.dd-sched-tools > button {
  flex: 0 0 auto !important;
  min-width: 108px !important;
}
/* 待删除清单：勾选结果实时列出，超长自动滚动 */
.dd-delete-box {
  margin: 10px 0 2px !important;
  padding: 10px 12px !important;
  border: 1px dashed var(--dd-teal) !important;
  border-radius: 12px !important;
  background: var(--dd-soft) !important;
  max-height: 190px;
  overflow-y: auto;
  font-size: 12.5px !important;
  line-height: 1.7 !important;
}
.dd-delete-box p { margin: 0 0 4px !important; }
.dd-delete-box strong { color: var(--dd-ink); }
.dd-status {
  min-height: 38px;
  border-radius: 12px;
  padding: 8px 12px;
  background: var(--dd-status-bg);
  border: 1px solid var(--dd-status-line);
  color: var(--dd-status-ink);
  font-size: 13px;
}
.dd-status p { margin: 0 !important; }
#dd-chatbot {
  border: 1px solid var(--dd-line) !important;
  border-radius: 16px !important;
  background: var(--dd-chat-bg) !important;
  overflow: hidden;
}
#dd-chatbot .message { font-size: 14px; line-height: 1.65; }
#dd-chatbot .message, #dd-chatbot .prose, #dd-chatbot .prose p {
  overflow-wrap: anywhere;
  word-break: break-word;
}
#dd-message textarea { border-radius: 12px !important; font-size: 14px !important; }
#dd-send { min-width: 84px; border-radius: 12px !important; font-weight: 750 !important; }
.dd-quick-row { gap: 6px !important; flex-wrap: wrap !important; }
.dd-quick-row button {
  border-radius: 999px !important;
  min-height: 30px !important;
  font-size: 11px !important;
  padding: 2px 11px !important;
  background: var(--dd-quick-bg) !important;
  border: 1px solid var(--dd-quick-line) !important;
  color: var(--dd-quick-ink) !important;
}
/* Gradio 原生页脚：构建信息与“设置”并排居中，中间留出间距 */
footer {
  position: relative !important;
  align-items: center !important;
  justify-content: center !important;
  gap: 28px !important;
}
.dd-system-entry {
  position: static !important;
  margin: 0;
  padding: 0 2px;
  border: none;
  background: transparent;
  color: var(--dd-footer-ink);
  font-family: inherit;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
}
.dd-system-entry:hover {
  color: var(--dd-accent);
  text-decoration: underline;
}
/* 设置弹窗：默认隐藏，点“设置”后在页面中央单开小窗 */
#dd-settings-modal { display: none !important; }
#dd-settings-modal.dd-open {
  display: flex !important;
  position: fixed !important;
  inset: 0;
  z-index: 10000;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(8, 20, 16, 0.55);
}
#dd-settings-modal .dd-modal-panel {
  flex: 0 0 auto !important;
  width: min(780px, 94vw);
  max-height: 84vh;
  overflow-y: auto;
  padding: 22px 26px 24px;
  border-radius: 16px;
  border: 1px solid var(--dd-line);
  background: var(--dd-bg-2);
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.28);
}
/* 设置弹窗排版：标题与说明各占整行，避免加粗文字被半栏挤压、截断 */
#dd-settings-modal h3,
#dd-settings-modal h4,
#dd-settings-modal .dd-settings-title {
  margin: 18px 0 8px !important;
  padding: 0 !important;
  font-size: 15px !important;
  line-height: 1.55 !important;
  font-weight: 800 !important;
  color: var(--dd-ink) !important;
  white-space: normal !important;
  overflow: visible !important;
  text-overflow: clip !important;
  letter-spacing: 0.01em;
}
#dd-settings-modal .dd-modal-head h3 { margin: 0 !important; font-size: 19px !important; }
#dd-settings-modal .dd-settings-actions {
  gap: 10px !important;
  flex-wrap: wrap !important;
  margin: 2px 0 6px !important;
}
#dd-settings-modal .dd-settings-actions > button {
  flex: 0 0 auto !important;
  min-width: 130px !important;
}
/* 设置弹窗：每个独立功能一个卡片框；内容变长时把下方卡片整体下推，避免文字重叠 */
#dd-settings-modal .dd-settings-block {
  display: block !important;
  border: 1px solid var(--dd-line) !important;
  border-radius: 14px !important;
  background: var(--dd-surface) !important;
  padding: 12px 14px 14px !important;
  margin: 0 0 12px !important;
  overflow: visible !important;
  height: auto !important;
  min-height: 0 !important;
}
#dd-settings-modal .dd-settings-block:last-child { margin-bottom: 0 !important; }
/* 弹窗面板是纵向 flex：卡片禁止压缩，内容再长也只会把面板撑出滚动条，不会挤压别的卡片 */
#dd-settings-modal .dd-modal-panel > * { flex: 0 0 auto !important; }
#dd-settings-modal .dd-settings-block > .dd-settings-title {
  margin: 0 0 8px !important;
  font-size: 14px !important;
}
/* 卡片内部的 Gradio 容器按内容高度顺序排列：内容变高时卡片整体变高，并把下方卡片下推 */
#dd-settings-modal .dd-settings-block .styler {
  display: block !important;
  height: auto !important;
  min-height: 0 !important;
  max-height: none !important;
  overflow: visible !important;
  background: transparent !important;
  border-color: transparent !important;
  border-radius: 0 !important;
}
#dd-settings-modal .dd-settings-block .styler > .block {
  display: block !important;
  flex: 0 0 auto !important;
  height: auto !important;
  min-height: 0 !important;
  max-height: none !important;
  overflow: visible !important;
}
/* 卡片内部纯文字块（标题 / 说明）不再叠第二层灰底，卡片本身就是唯一的“框” */
#dd-settings-modal .dd-settings-block .block:has(.prose),
#dd-settings-modal .dd-settings-block .block:has(.html-container) {
  background: transparent !important;
  border-color: transparent !important;
  box-shadow: none !important;
}
#dd-settings-modal .dd-settings-block .dd-key-status,
#dd-settings-modal .dd-settings-block .dd-hint,
#dd-settings-modal .dd-settings-block .prose {
  margin: 6px 0 0 !important;
  padding: 0 !important;
  max-height: none !important;
  overflow: visible !important;
  white-space: normal !important;
  word-break: break-word;
  overflow-wrap: anywhere;
}
#dd-settings-modal .dd-settings-block .prose p,
#dd-settings-modal .dd-settings-block .prose li {
  margin: 0 0 4px !important;
  line-height: 1.7 !important;
}
#dd-settings-modal .dd-modal-head {
  align-items: center !important;
  justify-content: space-between !important;
  margin-bottom: 8px !important;
}
#dd-settings-modal .dd-modal-close {
  min-width: 34px !important;
  max-width: 34px !important;
  padding: 2px 0 !important;
}
body.dd-modal-open { overflow: hidden !important; }
.dd-key-status {
  min-height: 0 !important;
  margin: 2px 0 10px !important;
  padding: 0 !important;
  color: var(--dd-muted);
  font-size: 12.5px;
  line-height: 1.75;
  white-space: normal !important;
  overflow: visible !important;
  word-break: break-word;
  overflow-wrap: anywhere;
}
.dd-key-status p,
.dd-key-status li {
  margin: 0 0 4px !important;
  line-height: 1.75 !important;
  font-size: 12.5px !important;
}
.dd-key-status code { font-size: 12px !important; }
.dd-hint {
  color: var(--dd-muted);
  font-size: 12px;
  line-height: 1.7;
}
.dd-hint p, .dd-hint strong { line-height: 1.7 !important; }
#dd-output-path textarea,
#dd-export-path textarea {
  font-family: "Cascadia Code", Consolas, monospace;
  font-size: 11px;
  white-space: pre-wrap !important;
  overflow-wrap: anywhere !important;
  word-break: break-all !important;
}
.dd-footer {
  margin-top: 18px;
  padding-top: 12px;
  border-top: 1px solid var(--dd-line);
  color: var(--dd-footer-ink);
  font-size: 11px;
  line-height: 1.6;
  text-align: center;
}
.dd-footer strong { color: var(--dd-footer-strong); }
/* 全局排版兜底：标题、说明、按钮文字一律允许换行，避免被窄容器截断 */
.gradio-container .prose p,
.gradio-container .prose li,
.gradio-container .prose td,
.gradio-container .prose th,
.gradio-container .dd-page p,
.gradio-container .dd-page li,
.gradio-container label span,
.gradio-container button span {
  max-width: 100%;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.gradio-container .dd-page .prose { max-width: 100%; }
@media (max-width: 900px) {
  html, body { max-width: 100%; overflow-x: hidden; }
  .gradio-container {
    width: 100vw !important;
    max-width: 100vw !important;
    overflow-x: hidden;
  }
  #dd-sidebar { display: none !important; }
  .dd-mobile-nav { display: block !important; margin-bottom: 10px; }
  .dd-key-row { flex-direction: column !important; align-items: stretch !important; }
  .dd-key-row > * { width: 100% !important; }
  .dd-topbar { flex-direction: column; gap: 4px; }
  .dd-page, .dd-panel, .dd-settings { min-width: 0 !important; max-width: 100% !important; }
  .dd-page { padding: 12px !important; }
  .dd-sch-module,
  .dd-maint-module { padding: 12px !important; border-radius: 14px !important; }
  .dd-wm-actions { flex-direction: column !important; }
  .dd-wm-card { min-height: 84px !important; width: 100% !important; }
  .dd-wm-card > button,
  .dd-wm-card > .wrap,
  .dd-wm-card > .block > button { padding: 12px 14px !important; }
  .dd-kg-frame { height: 520px !important; }
  .dd-system-entry {
    margin-left: 0;
  }
  footer { gap: 18px !important; }
  #dd-settings-modal { padding: 12px; }
  #dd-settings-modal .dd-modal-panel {
    width: 100% !important;
    max-height: 88vh;
    padding: 14px 14px;
  }
  .dd-main, .dd-main * { min-width: 0 !important; }
}
.dd-mobile-nav { display: none; }
"""

_THEME = gr.themes.Soft(
    primary_hue="teal",
    secondary_hue="cyan",
    neutral_hue="slate",
    font=["Inter", "Microsoft YaHei", "sans-serif"],
)

_BOOT_JS = """
() => {
  const applyResponsive = () => {
    const mobile = window.innerWidth <= 900;
    document.documentElement.style.setProperty('--dd-pad-left', mobile ? '10px' : '310px');
  };
  applyResponsive();
  window.addEventListener('resize', applyResponsive);

  // ---- 主题：浅色 / 深色 / 跟随系统，记住在本浏览器 ----
  const THEME_KEY = 'dd-theme';
  const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  const readStored = () => {
    try {
      const raw = localStorage.getItem(THEME_KEY);
      return raw === 'dark' || raw === 'auto' ? raw : 'light';
    } catch (error) {
      return 'light';
    }
  };
  const resolve = (mode) => {
    if (mode === 'dark') return 'dark';
    if (mode === 'auto') return media && media.matches ? 'dark' : 'light';
    return 'light';
  };
  let current = resolve('light');
  const paint = () => {
    [document.documentElement, document.body].forEach((el) => {
      if (!el) return;
      el.classList.toggle('dark', current === 'dark');
      el.style.colorScheme = current;
    });
  };
  window.ddGetTheme = readStored;
  window.ddSetTheme = (mode) => {
    const safe = ['light', 'dark', 'auto'].includes(mode) ? mode : 'light';
    current = resolve(safe);
    paint();
    try {
      localStorage.setItem(THEME_KEY, safe);
    } catch (error) {
      /* 隐私模式禁用 localStorage 时忽略 */
    }
    return current;
  };
  window.ddSetTheme(readStored());
  if (media) {
    const onSystemTheme = () => {
      const stored = readStored();
      window.ddSetTheme(stored === 'auto' ? 'auto' : stored);
    };
    if (media.addEventListener) media.addEventListener('change', onSystemTheme);
    else if (media.addListener) media.addListener(onSystemTheme);
  }
  // Gradio 初始化时可能改写 dark 类，启动阶段强制保持用户选择的主题。
  const observer = new MutationObserver(paint);
  [document.documentElement, document.body].forEach((el) => {
    if (el) observer.observe(el, { attributes: true, attributeFilter: ['class'] });
  });
  setTimeout(() => observer.disconnect(), 3000);

  // 不让浏览器密码管理器把上一位使用者的 Key 自动填回输入框。
  let keyTouched = false;
  document.addEventListener('input', (event) => {
    if (event.target && event.target.type === 'password') {
      keyTouched = true;
    }
  }, true);
  const scrubKeyInputs = () => {
    document.querySelectorAll('input[type="password"]').forEach((el) => {
      el.setAttribute('autocomplete', 'new-password');
      if (!keyTouched && el.value) {
        el.value = '';
      }
    });
  };
  scrubKeyInputs();
  setTimeout(scrubKeyInputs, 600);
  setTimeout(scrubKeyInputs, 1500);

  // ---- 设置：Gradio 页脚右侧的“设置”入口 + 页面中央弹窗 ----
  const settingsModal = () => document.querySelector('#dd-settings-modal');
  window.ddOpenSettings = () => {
    const modal = settingsModal();
    if (!modal) return;
    modal.classList.add('dd-open');
    document.body.classList.add('dd-modal-open');
  };
  window.ddCloseSettings = () => {
    const modal = settingsModal();
    if (modal) modal.classList.remove('dd-open');
    document.body.classList.remove('dd-modal-open');
  };
  const mountSystemEntry = () => {
    const footer = document.querySelector('footer');
    if (!footer) return false;
    if (footer.querySelector('.dd-system-entry')) return true;
    const entry = document.createElement('button');
    entry.type = 'button';
    entry.className = 'dd-system-entry';
    entry.textContent = '设置';
    entry.setAttribute('aria-label', '打开设置');
    entry.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      window.ddOpenSettings();
    });
    footer.appendChild(entry);
    return true;
  };
  mountSystemEntry();
  const entryTimer = setInterval(() => {
    if (mountSystemEntry()) clearInterval(entryTimer);
  }, 500);
  setTimeout(() => clearInterval(entryTimer), 15000);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') window.ddCloseSettings();
  });
  document.addEventListener('click', (event) => {
    const modal = settingsModal();
    if (modal && modal.classList.contains('dd-open') && event.target === modal) {
      window.ddCloseSettings();
    }
  });

  // ---- 图片水印大卡片：点击卡片任意位置都等同点击卡片里的按钮 ----
  document.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const card = target.closest('.dd-wm-card');
    if (!card || card.tagName === 'BUTTON') return;
    const inner = card.querySelector('button');
    if (!inner || inner === target || inner.contains(target)) return;
    event.preventDefault();
    event.stopPropagation();
    inner.click();
  }, true);

  // ---- 我的日程 / 后勤维修：点击整行勾选，按住鼠标拖动可框选多条 ----
  if (!window.ddScheduleDragReady) {
    window.ddScheduleDragReady = true;
    const GROUPISH = '#dd-sched-select, #dd-maint-select';
    const LABELS = '#dd-sched-select label, #dd-maint-select label';
    let painting = false;
    let targetState = true;
    let visited = new WeakSet();
    let scrollBox = null;
    let suppressClick = false;

    const labelOf = (node) => (node && node.closest ? node.closest(LABELS) : null);
    const inputOf = (label) => (label ? label.querySelector('input[type="checkbox"]') : null);
    const setChecked = (input, state) => {
      if (input && !input.disabled && input.checked !== state) input.click();
    };
    const findScrollBox = (label) => {
      const group = label && label.closest ? label.closest(GROUPISH) : null;
      if (!group) return null;
      const wrap = group.querySelector('.wrap');
      return wrap && wrap.scrollHeight > wrap.clientHeight + 4 ? wrap : null;
    };
    const autoScroll = (event) => {
      if (!scrollBox) return;
      const rect = scrollBox.getBoundingClientRect();
      if (event.clientY < rect.top + 26) scrollBox.scrollTop -= 16;
      else if (event.clientY > rect.bottom - 26) scrollBox.scrollTop += 16;
    };
    const paintLabel = (label) => {
      if (!label || visited.has(label)) return;
      visited.add(label);
      setChecked(inputOf(label), targetState);
    };

    document.addEventListener('mousedown', (event) => {
      const label = labelOf(event.target);
      if (!label) return;
      const input = inputOf(label);
      if (!input || input.disabled) return;
      painting = true;
      targetState = !input.checked;
      visited = new WeakSet();
      visited.add(label);
      scrollBox = findScrollBox(label);
      suppressClick = true;
      // 起始行立即切换：整行（含文字、空白处）都可以点击勾选
      setChecked(input, targetState);
      if (event.target !== input) {
        event.preventDefault();
        input.focus({ preventScroll: true });
      }
    }, true);

    document.addEventListener('mousemove', (event) => {
      if (!painting) return;
      autoScroll(event);
      const hit = document.elementFromPoint(event.clientX, event.clientY);
      paintLabel(labelOf(hit));
      event.preventDefault();
    }, { capture: true, passive: false });

    const endPaint = () => {
      if (!painting) return;
      painting = false;
      scrollBox = null;
      visited = new WeakSet();
      // 等这一轮 click 派发完再恢复，避免起始行被原生 click 二次切换
      setTimeout(() => { suppressClick = false; }, 0);
    };
    document.addEventListener('mouseup', endPaint, true);
    document.addEventListener('mouseleave', endPaint, true);

    document.addEventListener('click', (event) => {
      if (!suppressClick) return;
      const label = labelOf(event.target);
      if (!label) return;
      // setChecked 触发的合成 click 必须放行，否则 Gradio 收不到 change
      if (event.target && event.target.closest('input[type="checkbox"]')) return;
      event.preventDefault();
      event.stopPropagation();
    }, true);
  }
}
"""

_THEME_SYNC_JS = """
() => {
  const stored = window.ddGetTheme ? window.ddGetTheme() : 'light';
  if (stored === 'dark') return ['深色'];
  if (stored === 'auto') return ['跟随系统'];
  return ['浅色'];
}
"""

_THEME_CHANGE_JS = """
(value) => {
  const mapping = {'浅色': 'light', '深色': 'dark', '跟随系统': 'auto'};
  if (window.ddSetTheme) window.ddSetTheme(mapping[value] || 'light');
}
"""

_CLOSE_SETTINGS_JS = """
() => {
  if (window.ddCloseSettings) window.ddCloseSettings();
}
"""

# 切换 Wiki 分类后，表格回到该分类的第一条（滚动条置顶）；关键字与分类原样回传给后端。
_WIKI_SCROLL_JS = """
(keyword, category) => {
  const resetWikiTableScroll = () => {
    const root = document.querySelector('#dd-wiki-table');
    if (!root) return;
    root.scrollTop = 0;
    root.querySelectorAll('*').forEach((el) => {
      if (el && typeof el.scrollTop === 'number' && el.scrollTop !== 0) el.scrollTop = 0;
    });
    const wrap = root.querySelector('.table-wrap');
    if (wrap) wrap.scrollTop = 0;
  };
  resetWikiTableScroll();
  [180, 360, 700, 1200].forEach((delay) => setTimeout(resetWikiTableScroll, delay));
  return [keyword, category];
}
"""

_TABLE_DATATYPE = ["number", "str", "str", "str", "str", "str"]
_MAINTENANCE_DATATYPE = ["number", "str", "str", "str", "str", "str", "str"]
