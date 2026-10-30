"""后勤 Wiki 知识图谱构建。

本文件职责：
- 读取 data/knowledge/wiki.json，把“分类—实体—关联实体”构建为无向图；
- 使用 pyvis 渲染可拖拽、可缩放的交互式 HTML，默认输出 data/kg.html；
- 节点按分类着色：食安/食堂绿色系、维修蓝色系、设备紫色系；
- networkx 与 pyvis 采用延迟导入，缺少依赖时给出明确的安装提示。

依赖：networkx、pyvis（uv add networkx pyvis）、dawndine.knowledge.wiki、dawndine.config。
被调用：app.py（知识图谱页）、维护脚本、tests。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from dawndine.config import KG_HTML_FILE
from dawndine.knowledge.wiki import load_wiki, wiki_path

logger = logging.getLogger(__name__)

__all__ = ["KnowledgeGraphError", "build_knowledge_graph"]

CATEGORY_STYLES: dict[str, dict[str, str]] = {
    "食安法规与标准": {"bg": "#1b5e20", "light": "#a5d6a7", "border": "#0f3d14"},
    "食堂日常操作": {"bg": "#2e7d32", "light": "#c8e6c9", "border": "#1b5e20"},
    "维修响应与规范": {"bg": "#0d47a1", "light": "#bbdefb", "border": "#08306b"},
    "设备与空间信息": {"bg": "#4a148c", "light": "#e1bee7", "border": "#320b5e"},
}
_FALLBACK_STYLE = {"bg": "#455a64", "light": "#cfd8dc", "border": "#263238"}
_VIRTUAL_STYLE = {"bg": "#90a4ae", "light": "#eceff1", "border": "#607d8b"}

DEPENDENCY_HINT = "缺少依赖 networkx / pyvis，请先执行：uv add networkx pyvis"


class KnowledgeGraphError(RuntimeError):
    """知识图谱构建失败（数据为空、依赖缺失或渲染异常）。"""


def _require_graph_libs() -> tuple[Any, Any]:
    """延迟导入 networkx 与 pyvis；缺失时抛出可操作的错误。"""

    try:
        import networkx as nx
    except ImportError as exc:  # pragma: no cover - 取决于运行环境
        raise KnowledgeGraphError(DEPENDENCY_HINT) from exc
    try:
        from pyvis.network import Network
    except ImportError as exc:  # pragma: no cover - 取决于运行环境
        raise KnowledgeGraphError(DEPENDENCY_HINT) from exc
    return nx, Network


def _category_style(category: str) -> dict[str, str]:
    """返回分类配色，未知分类使用中性灰。"""

    return CATEGORY_STYLES.get(category, _FALLBACK_STYLE)


_DETAIL_KEYS: tuple[str, ...] = ("id", "title", "content", "category")


def _build_graph(entries: list[dict[str, Any]]) -> Any:
    """用 networkx 构建分类—实体—关联实体图。"""

    nx, _ = _require_graph_libs()
    graph = nx.Graph()
    entity_entries: dict[str, list[dict[str, Any]]] = {}

    for entry in entries:
        category = entry["category"]
        entity = entry["entity"]
        category_id = f"category::{category}"
        entity_id = f"entity::{entity}"

        graph.add_node(category_id, kind="category", label=category, category=category)
        if not graph.has_node(entity_id):
            graph.add_node(entity_id, kind="entity", label=entity, category=category)
        else:
            # 该实体可能先由其他条目的 relations 建立为虚拟节点，本条目出现时升级为正式实体。
            attrs = graph.nodes[entity_id]
            attrs["kind"] = "entity"
            attrs["label"] = entity
            attrs["category"] = category
            attrs["virtual"] = False
        entity_entries.setdefault(entity, []).append(entry)
        graph.add_edge(category_id, entity_id, kind="包含")

        for relation in entry["relations"]:
            relation = relation.strip()
            if not relation or relation == entity:
                continue
            relation_id = f"entity::{relation}"
            if not graph.has_node(relation_id):
                graph.add_node(
                    relation_id,
                    kind="entity",
                    label=relation,
                    category=category,
                    virtual=True,
                )
            graph.add_edge(entity_id, relation_id, kind="关联")

    for entity, items in entity_entries.items():
        node_id = f"entity::{entity}"
        # 悬停信息交给页面内注入的自定义小框（见 _inject_hover_tooltip），
        # 不再写入 pyvis 原生 title，避免浏览器原生提示与自定义提示重复出现。
        graph.nodes[node_id]["details"] = [
            {key: item[key] for key in _DETAIL_KEYS} for item in items
        ]
        graph.nodes[node_id]["categories"] = list(dict.fromkeys(i["category"] for i in items))
        graph.nodes[node_id]["entries"] = len(items)

    return graph


def _tooltip_payload(graph: Any) -> dict[str, dict[str, Any]]:
    """整理每个节点的悬停信息，供前端自定义小框展示。"""

    payload: dict[str, dict[str, Any]] = {}
    for node_id, attrs in graph.nodes(data=True):
        if attrs.get("kind") == "category":
            payload[node_id] = {
                "kind": "category",
                "label": attrs.get("label", node_id),
                "count": graph.degree(node_id),
            }
            continue
        entries = attrs.get("details") or []
        payload[node_id] = {
            "kind": "entity",
            "label": attrs.get("label", node_id),
            "categories": list(attrs.get("categories") or []),
            "entries": list(entries),
        }
    return payload


def _render_html(graph: Any, output_path: Path) -> None:
    """用 pyvis 把 networkx 图渲染为可拖拽缩放的 HTML。"""

    _, Network = _require_graph_libs()
    net = Network(
        height="760px",
        width="100%",
        bgcolor="#f7fbf9",
        # font_color 保持 False：pyvis 一旦设置全局字体色，会覆盖每个节点的 font 配置
        # （分类节点的白色粗体标题、实体节点的字号都会丢失）。
        font_color=False,
        directed=False,
        notebook=False,
        cdn_resources="in_line",
    )

    for node_id, attrs in graph.nodes(data=True):
        kind = attrs.get("kind")
        if kind == "category":
            style = _category_style(attrs.get("category", ""))
            net.add_node(
                node_id,
                label=attrs.get("label", node_id),
                shape="box",
                size=34,
                borderWidth=2,
                color={
                    "background": style["bg"],
                    "border": style["border"],
                    "highlight": {"background": style["bg"], "border": style["border"]},
                },
                font={"size": 18, "color": "#ffffff", "face": "Microsoft YaHei"},
                margin=12,
            )
            continue

        virtual = bool(attrs.get("virtual"))
        style = _VIRTUAL_STYLE if virtual else _category_style(attrs.get("category", ""))
        degree = graph.degree(node_id)
        net.add_node(
            node_id,
            label=attrs.get("label", node_id),
            shape="dot",
            size=14 + min(degree * 2, 18),
            borderWidth=2,
            color={
                "background": style["light"],
                "border": style["border"],
                "highlight": {"background": style["bg"], "border": style["border"]},
            },
            font={"size": 13, "color": "#18332c", "face": "Microsoft YaHei"},
        )

    for source, target, attrs in graph.edges(data=True):
        containment = attrs.get("kind") == "包含"
        net.add_edge(
            source,
            target,
            title="包含" if containment else "关联",
            color="#b7cfc6" if containment else "#7ea9d6",
            width=2.0 if containment else 1.2,
            dashes=not containment,
        )

    options = {
        "interaction": {
            "hover": True,
            "dragNodes": True,
            "dragView": True,
            "zoomView": True,
            "navigationButtons": True,
            "keyboard": True,
            "multiselect": True,
        },
        "physics": {
            "enabled": True,
            "barnesHut": {
                "gravitationalConstant": -12000,
                "centralGravity": 0.32,
                "springLength": 140,
                "springConstant": 0.04,
                # 基础阻尼稍大：布局收敛后残速快速衰减，不做无限期模拟。
                "damping": 0.12,
                "avoidOverlap": 0.2,
            },
            "stabilization": {"enabled": True, "iterations": 220, "fit": True},
            # 页面脚本会在稳定后/拖动结束后逐级加大阻尼（见 _TOOLTIP_SCRIPT）。
            "minVelocity": 0.8,
            "maxVelocity": 12,
            "timestep": 0.3,
            "adaptiveTimestep": True,
        },
        "nodes": {"borderWidth": 2},
        "edges": {"smooth": {"type": "continuous", "roundness": 0.2}, "selectionWidth": 1.6},
        "layout": {"improvedLayout": True},
    }
    net.set_options(json.dumps(options, ensure_ascii=False))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        net.write_html(str(output_path), notebook=False, open_browser=False)
    except TypeError:  # 兼容旧版 pyvis 的 write_html 签名
        net.write_html(str(output_path))
    except Exception as exc:  # 兜底：直接写 generate_html 结果
        generator = getattr(net, "generate_html", None)
        if generator is None:
            raise KnowledgeGraphError(f"知识图谱渲染失败：{exc}") from exc
        output_path.write_text(generator(), encoding="utf-8")


_TOOLTIP_STYLE = """
<style type="text/css">
#dd-kg-tooltip {
  position: fixed;
  display: none;
  z-index: 1000;
  max-width: 340px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid #b7cfc6;
  background: rgba(255, 255, 255, 0.98);
  color: #18332c;
  font-family: "Microsoft YaHei", Inter, sans-serif;
  font-size: 12px;
  line-height: 1.6;
  box-shadow: 0 12px 32px rgba(24, 51, 44, 0.18);
  pointer-events: none;
  white-space: normal;
  overflow-wrap: anywhere;
}
#dd-kg-tooltip .dd-kg-tip-title {
  margin-bottom: 2px;
  font-size: 13.5px;
  font-weight: 800;
}
#dd-kg-tooltip .dd-kg-tip-meta {
  margin-bottom: 4px;
  color: #657b75;
  font-size: 11.5px;
}
#dd-kg-tooltip .dd-kg-tip-item { margin-top: 5px; }
#dd-kg-tooltip .dd-kg-tip-id {
  display: inline-block;
  margin-right: 6px;
  padding: 0 5px;
  border-radius: 6px;
  background: #dff3ec;
  color: #0f766e;
  font-size: 11px;
  font-weight: 700;
}
#dd-kg-tooltip .dd-kg-tip-entry { font-weight: 700; }
#dd-kg-tooltip .dd-kg-tip-text {
  margin-top: 1px;
  color: #3f5751;
  font-size: 11.5px;
}
</style>
"""

_TOOLTIP_SCRIPT = """
<div id="dd-kg-tooltip" role="tooltip" aria-hidden="true"></div>
<script type="text/javascript">
(function () {
  // 悬停小框：鼠标停在节点上显示该条知识，离开节点即隐藏（不依赖 pyvis 原生 title）。
  const DATA = __PAYLOAD__;
  const container = document.getElementById('mynetwork');
  const box = document.getElementById('dd-kg-tooltip');
  if (!container || !box) return;

  const ESCAPE = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (value) => String(value === null || value === undefined ? '' : value)
    .replace(/[&<>"']/g, (ch) => ESCAPE[ch]);
  const clip = (value, limit) => {
    const text = String(value || '');
    return text.length > limit ? text.slice(0, limit) + '…' : text;
  };

  const hide = () => {
    box.style.display = 'none';
    box.setAttribute('aria-hidden', 'true');
  };

  const show = (pointer) => {
    const rect = container.getBoundingClientRect();
    box.style.display = 'block';
    box.setAttribute('aria-hidden', 'false');
    const width = box.offsetWidth;
    const height = box.offsetHeight;
    const px = pointer && isFinite(pointer.x) ? pointer.x : rect.width / 2;
    const py = pointer && isFinite(pointer.y) ? pointer.y : rect.height / 2;
    let left = rect.left + px + 16;
    let top = rect.top + py + 16;
    if (left + width > window.innerWidth - 8) left = Math.max(8, rect.left + px - width - 16);
    if (top + height > window.innerHeight - 8) top = Math.max(8, window.innerHeight - height - 8);
    box.style.left = Math.round(left) + 'px';
    box.style.top = Math.round(top) + 'px';
  };

  const renderCategory = (info) =>
    '<div class="dd-kg-tip-title">' + esc(info.label) + '</div>' +
    '<div class="dd-kg-tip-meta">分类节点 · ' + esc(info.count || 0) + ' 个实体</div>';

  const renderEntity = (info) => {
    const entries = Array.isArray(info.entries) ? info.entries : [];
    const tags = (info.categories || []).join(' / ');
    const parts = ['<div class="dd-kg-tip-title">' + esc(info.label) + '</div>'];
    parts.push(
      '<div class="dd-kg-tip-meta">' + (tags ? esc(tags) : '关联概念') +
      ' · ' + entries.length + ' 条知识</div>'
    );
    if (!entries.length) {
      parts.push('<div class="dd-kg-tip-text">暂无收录的知识条目。</div>');
      return parts.join('');
    }
    entries.slice(0, 3).forEach((entry) => {
      parts.push(
        '<div class="dd-kg-tip-item">' +
          '<span class="dd-kg-tip-id">' + esc(entry.id) + '</span>' +
          '<span class="dd-kg-tip-entry">' + esc(entry.title) + '</span>' +
          '<div class="dd-kg-tip-text">' + esc(clip(entry.content, 92)) + '</div>' +
        '</div>'
      );
    });
    if (entries.length > 3) {
      parts.push('<div class="dd-kg-tip-meta">另有 ' + (entries.length - 3) + ' 条未展开</div>');
    }
    return parts.join('');
  };

  // 物理档位：保留小球之间的碰撞，靠阻尼逐级加大来衰减弹动。
  // damping 越大，碰撞后保留的速度越少 → 每一轮弹动的幅度与次数递减，直至静止。
  const PHYSICS = {
    settle:   { damping: 0.72, minVelocity: 0.8, maxVelocity: 6,  timestep: 0.25 },
    interact: { damping: 0.24, minVelocity: 0,   maxVelocity: 12, timestep: 0.3 },
    decay1:   { damping: 0.45, minVelocity: 0.6, maxVelocity: 9,  timestep: 0.28 },
    decay2:   { damping: 0.66, minVelocity: 0.7, maxVelocity: 7,  timestep: 0.24 },
    decay3:   { damping: 0.85, minVelocity: 0.9, maxVelocity: 4,  timestep: 0.2 },
  };

  const applyPhysics = (network, level) => {
    const cfg = PHYSICS[level];
    if (!cfg) return;
    try {
      network.setOptions({
        physics: {
          enabled: true,
          // 改档位时关闭重新稳定化，避免拖动中重跑 220 次布局迭代造成卡顿。
          stabilization: { enabled: false },
          barnesHut: {
            gravitationalConstant: -12000,
            centralGravity: 0.32,
            springLength: 140,
            springConstant: 0.04,
            damping: cfg.damping,
            avoidOverlap: 0.2,
          },
          minVelocity: cfg.minVelocity,
          maxVelocity: cfg.maxVelocity,
          timestep: cfg.timestep,
          adaptiveTimestep: true,
        },
      });
      if (typeof network.startSimulation === 'function') network.startSimulation();
    } catch (error) { /* 旧版 vis 不支持 setOptions 时保持原状 */ }
  };

  const bind = (network) => {
    if (!network || typeof network.on !== 'function') return false;
    let timers = [];
    const clearTimers = () => {
      timers.forEach((timer) => clearTimeout(timer));
      timers = [];
    };
    const decayAt = (delay, level) => {
      timers.push(setTimeout(() => applyPhysics(network, level), delay));
    };
    network.on('hoverNode', (params) => {
      const info = params && params.node ? DATA[params.node] : null;
      if (!info) { hide(); return; }
      box.innerHTML = info.kind === 'category' ? renderCategory(info) : renderEntity(info);
      show(params.pointer && params.pointer.DOM);
    });
    network.on('blurNode', hide);
    network.on('dragStart', () => {
      // 拖动时恢复碰撞：相邻小球会被推动，阻尼保持较轻以保证手感。
      hide();
      clearTimers();
      applyPhysics(network, 'interact');
    });
    network.on('dragEnd', () => {
      hide();
      clearTimers();
      // 松手后阻尼逐级加重：碰撞后的弹动一次比一次轻，不会一直抽搐。
      decayAt(400, 'decay1');
      decayAt(900, 'decay2');
      decayAt(1500, 'decay3');
      decayAt(2400, 'settle');
      // 兜底：阻尼足够大时模拟基本已停，这里再显式收尾，杜绝持续抖动。
      timers.push(setTimeout(() => {
        if (typeof network.stopSimulation === 'function') network.stopSimulation();
      }, 3200));
    });
    network.on('zoom', hide);
    network.on('click', hide);
    network.on('selectNode', hide);
    network.once('stabilizationIterationsDone', () => {
      clearTimers();
      applyPhysics(network, 'settle');
    });
    network.once('stabilized', () => applyPhysics(network, 'settle'));
    if (typeof network.on === 'function') {
      network.on('destroy', clearTimers);
    }
    return true;
  };

  const resolveNetwork = () => {
    if (window.network) return window.network;
    try {
      if (typeof network !== 'undefined' && network) return network;
    } catch (error) { /* 变量尚未声明时忽略 */ }
    return null;
  };

  let attempts = 0;
  const ready = () => {
    const network = resolveNetwork();
    if (network && bind(network)) return;
    attempts += 1;
    if (attempts < 40) setTimeout(ready, 150);
  };
  ready();

  container.addEventListener('mouseleave', hide);
  window.addEventListener('scroll', hide, true);
  window.addEventListener('resize', hide);
  hide();
})();
</script>
"""


def _inject_hover_tooltip(output_path: Path, payload: dict[str, dict[str, Any]]) -> None:
    """把悬停小框的样式、容器与脚本注入 pyvis 生成的 HTML。"""

    if not payload:
        return
    try:
        html_text = output_path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - 取决于文件系统
        raise KnowledgeGraphError(f"知识图谱文件读取失败：{exc}") from exc
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    block = _TOOLTIP_STYLE + _TOOLTIP_SCRIPT.replace("__PAYLOAD__", data_json)
    if "</body>" in html_text:
        html_text = html_text.replace("</body>", f"{block}</body>", 1)
    else:  # pragma: no cover - 正常 pyvis 输出一定带 body
        html_text += block
    output_path.write_text(html_text, encoding="utf-8")


def build_knowledge_graph(
    source_path: Path | str | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """读取 Wiki 并生成 data/kg.html，返回节点/边统计。

    Args:
        source_path: 可选，Wiki JSON 路径；默认 data/knowledge/wiki.json。
        output_path: 可选，HTML 输出路径；默认 data/kg.html。

    Raises:
        KnowledgeGraphError: 数据为空、依赖缺失或渲染失败。
    """

    entries = load_wiki(Path(source_path) if source_path is not None else wiki_path())
    if not entries:
        raise KnowledgeGraphError(
            "未找到可用的 Wiki 知识，请先准备 data/knowledge/wiki.json（JSON 数组）。"
        )

    graph = _build_graph(entries)
    target = Path(output_path) if output_path is not None else KG_HTML_FILE
    _render_html(graph, target)
    _inject_hover_tooltip(target, _tooltip_payload(graph))

    categories = sum(1 for _, attrs in graph.nodes(data=True) if attrs.get("kind") == "category")
    entities = sum(
        1
        for _, attrs in graph.nodes(data=True)
        if attrs.get("kind") == "entity" and not attrs.get("virtual")
    )
    relation_edges = sum(1 for _, _, attrs in graph.edges(data=True) if attrs.get("kind") == "关联")
    stats = {
        "entries": len(entries),
        "categories": categories,
        "entities": entities,
        "relations": relation_edges,
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "output_path": str(target),
    }
    logger.info(
        "知识图谱生成完成：%s 条 Wiki，%s 节点，%s 边，输出 %s",
        stats["entries"],
        stats["nodes"],
        stats["edges"],
        target,
    )
    return stats
