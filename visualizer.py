"""
visualizer.py — генерация интерактивного HTML-графа с Canvas-рендерингом.
Оптимизирован для 5000+ узлов. Цветовые кластеры по отраслям.
"""

import json
import logging
from pathlib import Path
import networkx as nx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

EDGE_COLORS = {
    "parent_child":    "#e63946",
    "common_founder":  "#f4a261",
    "common_director": "#2a9d8f",
    "same_industry":   "#457b9d",
    "affiliated":      "#e9c46a",
}

EDGE_TITLES = {
    "parent_child":    "Учредительство",
    "common_founder":  "Общий учредитель",
    "common_director": "Общий руководитель",
    "same_industry":   "Одна отрасль",
    "affiliated":      "Аффилированность",
}

INDUSTRY_CONFIG = {
    "Нефтегаз":          {"color": "#ff6b35"},
    "Банки и финансы":   {"color": "#e63946"},
    "Металлургия":       {"color": "#ffb703"},
    "Энергетика":        {"color": "#f4a261"},
    "Телеком и ИТ":      {"color": "#457b9d"},
    "Розничная торговля": {"color": "#2ec4b6"},
    "Транспорт":         {"color": "#8338ec"},
    "Госорганы":         {"color": "#6d2b3d"},
    "Химия":             {"color": "#06d6a0"},
    "Строительство":     {"color": "#fb8b24"},
    "Машиностроение":    {"color": "#9b5de5"},
    "Фармацевтика":      {"color": "#00bbf9"},
    "Сельское хозяйство":{"color": "#38b000"},
    "Прочее":            {"color": "#8b949e"},
}

INDUSTRY_GROUPS = {
    "Нефтегаз":          ["06", "09", "19", "49.5"],
    "Банки и финансы":   ["64", "65", "66"],
    "Металлургия":       ["24", "07"],
    "Энергетика":        ["35"],
    "Телеком и ИТ":      ["61", "62", "63"],
    "Розничная торговля": ["47"],
    "Транспорт":         ["49", "50", "51", "52"],
    "Госорганы":         ["84"],
    "Химия":             ["20", "21", "22"],
    "Строительство":     ["41", "42", "43"],
    "Машиностроение":    ["28", "29", "30"],
    "Фармацевтика":      ["21.2"],
    "Сельское хозяйство":["01", "02", "03"],
}


def get_industry_group(okved: str) -> str:
    if not okved:
        return "Прочее"
    for group, prefixes in INDUSTRY_GROUPS.items():
        for prefix in prefixes:
            if okved.startswith(prefix):
                return group
    return "Прочее"


def get_industry_color(okved: str) -> str:
    industry = get_industry_group(okved)
    return INDUSTRY_CONFIG.get(industry, INDUSTRY_CONFIG["Прочее"])["color"]


def _node_size(G: nx.Graph, inn: str) -> float:
    n = G.nodes[inn]
    pr = n.get("pagerank", 0.01)
    emp = n.get("employee_count") or 0
    capital = n.get("capital") or 0

    size = 3
    size += pr * 1500
    size += min(emp / 10000, 6) if emp else 0
    size += min(capital / 5e8, 4) if capital else 0

    return max(2.5, min(size, 30))


def _node_title(G: nx.Graph, inn: str) -> str:
    n = G.nodes[inn]
    capital = n.get("capital")
    cap_str = f"{capital:,.0f} ₽" if capital else "н/д"
    emp = n.get("employee_count")
    emp_str = f"{emp:,}" if emp else "н/д"
    industry = get_industry_group(n.get("okved", ""))

    return (
        f"<b>{n.get('name', inn)}</b><br>"
        f"ИНН: {inn}<br>"
        f"Отрасль: {industry}<br>"
        f"ОКВЭД: {n.get('okved','')}<br>"
        f"Статус: {n.get('status','')}<br>"
        f"Сотрудников: {emp_str}<br>"
        f"Капитал: {cap_str}<br>"
        f"PageRank: {n.get('pagerank', 0):.4f}<br>"
        f"Кластер: {n.get('community', '?')}"
    )


def export_to_html_d3(G: nx.MultiGraph, filename: str = "org_network.html") -> str:
    """Canvas-рендеринг для больших графов (5000+ узлов)."""
    
    nodes = []
    for inn in G.nodes():
        n = G.nodes[inn]
        nodes.append({
            "id": inn,
            "label": n.get("label", inn)[:30],
            "title": n.get("name", inn),
            "industry": get_industry_group(n.get("okved", "")),
            "color": get_industry_color(n.get("okved", "")),
            "size": _node_size(G, inn),
            "pagerank": n.get("pagerank", 0.01),
            "tooltip": _node_title(G, inn),
        })

    links = []
    seen = set()
    for u, v, data in G.edges(data=True):
        etype = data.get("type", "")
        key = (tuple(sorted([u, v])), etype)
        if key in seen:
            continue
        seen.add(key)
        links.append({
            "source": u,
            "target": v,
            "type": etype,
            "color": EDGE_COLORS.get(etype, "#888"),
            "title": EDGE_TITLES.get(etype, etype),
            "via": data.get("via", ""),
            "share": data.get("share"),
        })

    graph_json = json.dumps({"nodes": nodes, "links": links}, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Сеть организаций РФ</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#0a0e14; overflow:hidden; font-family:Segoe UI,Arial,sans-serif; }}
canvas {{ display:block; }}
#tooltip {{
  position:fixed; background:rgba(10,14,20,0.96); border:1px solid #30363d;
  border-radius:8px; padding:12px 16px; font-size:12px; pointer-events:none;
  max-width:340px; line-height:1.7; display:none; z-index:1000;
  box-shadow:0 8px 32px rgba(0,0,0,0.8); color:#c9d1d9;
}}
#legend {{
  position:fixed; top:16px; right:16px; background:rgba(10,14,20,0.94);
  border:1px solid #30363d; border-radius:10px; padding:14px 18px;
  font-size:11px; z-index:999; max-height:85vh; overflow-y:auto;
  backdrop-filter:blur(10px); color:#c9d1d9;
}}
.legend-title {{ font-weight:bold; margin-bottom:6px; font-size:12px; text-transform:uppercase; letter-spacing:1px; }}
.legend-item {{ display:flex; align-items:center; gap:8px; margin:3px 0; }}
.legend-dot {{ width:10px; height:10px; border-radius:50%; flex-shrink:0; border:1px solid rgba(255,255,255,0.2); }}
.legend-line {{ width:20px; height:3px; border-radius:2px; flex-shrink:0; }}
#search {{
  position:fixed; top:16px; left:16px; z-index:999; display:flex; gap:6px;
}}
#search input {{
  background:rgba(10,14,20,0.94); border:1px solid #30363d; border-radius:6px;
  color:#c9d1d9; padding:8px 12px; font-size:13px; width:220px; outline:none;
  backdrop-filter:blur(10px);
}}
#search input:focus {{ border-color:#58a6ff; }}
#search button {{
  background:#238636; border:none; border-radius:6px; color:#fff;
  padding:8px 14px; cursor:pointer; font-size:13px; font-weight:bold;
}}
#search button:hover {{ background:#2ea043; }}
#stats {{
  position:fixed; bottom:16px; left:16px; background:rgba(10,14,20,0.94);
  border:1px solid #30363d; border-radius:8px; padding:8px 14px;
  font-size:11px; color:#8b949e; z-index:999;
}}
</style>
</head>
<body>
<div id="tooltip"></div>

<div id="search">
  <input type="text" id="searchInput" placeholder="Поиск организации..." onkeyup="if(event.key==='Enter')searchNode()">
  <button onclick="searchNode()">🔍</button>
</div>

<div id="legend">
  <div class="legend-title" style="color:#58a6ff">🏭 ОТРАСЛИ</div>
  {''.join(f'<div class="legend-item"><div class="legend-dot" style="background:{c["color"]}"></div>{n}</div>' for n,c in INDUSTRY_CONFIG.items() if n != "Прочее")}
  <div style="margin:8px 0;border-top:1px solid #30363d"></div>
  <div class="legend-title" style="color:#f4a261">🔗 СВЯЗИ</div>
  <div class="legend-item"><div class="legend-line" style="background:#e63946"></div>Учредительство</div>
  <div class="legend-item"><div class="legend-line" style="background:#f4a261"></div>Общий учредитель</div>
  <div class="legend-item"><div class="legend-line" style="background:#2a9d8f"></div>Общий руководитель</div>
  <div class="legend-item"><div class="legend-line" style="background:#457b9d"></div>Одна отрасль</div>
</div>

<div id="stats">
  Узлов: <b>{len(nodes)}</b> | Связей: <b>{len(links)}</b> | 
  FPS: <span id="fps">—</span>
</div>

<canvas id="canvas"></canvas>

<script>
const graphData = {graph_json};
const W = window.innerWidth;
const H = window.innerHeight;

const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
canvas.width = W * devicePixelRatio;
canvas.height = H * devicePixelRatio;
canvas.style.width = W + "px";
canvas.style.height = H + "px";
ctx.scale(devicePixelRatio, devicePixelRatio);

const tooltip = document.getElementById("tooltip");

// Индексы для быстрого поиска
const nodeMap = new Map(graphData.nodes.map(n => [n.id, n]));
const nodeIndex = new Map(graphData.nodes.map((n, i) => [n.id, i]));

// Transform
let transform = d3.zoomIdentity;

// FPS
let frames = 0, lastTime = performance.now();

// Симуляция
const sim = d3.forceSimulation(graphData.nodes)
  .force("link", d3.forceLink(graphData.links).id(d => d.id)
    .distance(d => d.type === 'common_director' ? 40 : 80)
    .strength(d => d.type === 'common_director' ? 0.5 : 0.2))
  .force("charge", d3.forceManyBody().strength(d => -30 - d.size * 3))
  .force("center", d3.forceCenter(W/2, H/2))
  .force("collision", d3.forceCollide(d => d.size + 2))
  .alphaDecay(0.02);

// Canvas отрисовка
function draw() {{
  ctx.save();
  ctx.clearRect(0, 0, W, H);
  ctx.translate(transform.x, transform.y);
  ctx.scale(transform.k, transform.k);

  // Рёбра
  graphData.links.forEach(l => {{
    const s = l.source, t = l.target;
    if (!s.x || !t.x) return;
    ctx.beginPath();
    ctx.moveTo(s.x, s.y);
    ctx.lineTo(t.x, t.y);
    ctx.strokeStyle = l.color;
    ctx.lineWidth = l.type === 'common_director' ? 1.5 / transform.k : 0.5 / transform.k;
    ctx.globalAlpha = l.type === 'same_industry' ? 0.15 : 0.4;
    ctx.stroke();
  }});

  // Узлы
  graphData.nodes.forEach(n => {{
    if (!n.x) return;
    const r = Math.max(2, n.size / Math.sqrt(transform.k));
    
    // Тень
    ctx.beginPath();
    ctx.arc(n.x, n.y, r + 1, 0, 2*Math.PI);
    ctx.fillStyle = 'rgba(0,0,0,0.3)';
    ctx.fill();

    // Круг
    ctx.beginPath();
    ctx.arc(n.x, n.y, r, 0, 2*Math.PI);
    ctx.fillStyle = n.color;
    ctx.globalAlpha = 0.9;
    ctx.fill();
    ctx.strokeStyle = '#1a1f2b';
    ctx.lineWidth = 1 / transform.k;
    ctx.stroke();
    ctx.globalAlpha = 1;

    // Подпись (только при достаточном зуме)
    if (transform.k > 0.5 && r > 4) {{
      ctx.fillStyle = '#c9d1d9';
      ctx.font = `${{Math.max(8, 10/transform.k)}}px Segoe UI`;
      ctx.textAlign = 'center';
      ctx.fillText(n.label.length > 20 ? n.label.slice(0,18)+'..' : n.label, n.x, n.y + r + 12/transform.k);
    }}
  }});

  ctx.restore();

  // FPS
  frames++;
  const now = performance.now();
  if (now - lastTime >= 1000) {{
    document.getElementById("fps").textContent = frames;
    frames = 0;
    lastTime = now;
  }}
}}

sim.on("tick", draw);

// Zoom
const zoom = d3.zoom()
  .scaleExtent([0.05, 10])
  .on("zoom", e => {{
    transform = e.transform;
    draw();
  }});

d3.select(canvas).call(zoom)
  .on("dblclick.zoom", null);

// Поиск
function searchNode() {{
  const q = document.getElementById("searchInput").value.toLowerCase();
  const found = graphData.nodes.find(n => n.label.toLowerCase().includes(q) || n.id.includes(q));
  if (found && found.x) {{
    const scale = 4;
    transform = d3.zoomIdentity
      .translate(W/2, H/2)
      .scale(scale)
      .translate(-found.x, -found.y);
    draw();
  }}
}}

// Hover
let hoveredNode = null;
canvas.addEventListener("mousemove", e => {{
  const mx = (e.clientX - transform.x) / transform.k;
  const my = (e.clientY - transform.y) / transform.k;
  
  hoveredNode = null;
  for (const n of graphData.nodes) {{
    if (!n.x) continue;
    const r = Math.max(2, n.size / Math.sqrt(transform.k));
    const dx = n.x - mx, dy = n.y - my;
    if (dx*dx + dy*dy < r*r) {{
      hoveredNode = n;
      canvas.style.cursor = 'pointer';
      tooltip.innerHTML = n.tooltip;
      tooltip.style.display = 'block';
      tooltip.style.left = Math.min(e.clientX + 15, W - 350) + "px";
      tooltip.style.top = Math.min(e.clientY + 15, H - 200) + "px";
      return;
    }}
  }}
  canvas.style.cursor = 'grab';
  tooltip.style.display = 'none';
}});

canvas.addEventListener("click", e => {{
  if (hoveredNode) {{
    const scale = 4;
    transform = d3.zoomIdentity
      .translate(W/2, H/2)
      .scale(scale)
      .translate(-hoveredNode.x, -hoveredNode.y);
    draw();
  }}
}});

// Ресайз
window.addEventListener("resize", () => {{
  const W2 = window.innerWidth, H2 = window.innerHeight;
  canvas.width = W2 * devicePixelRatio;
  canvas.height = H2 * devicePixelRatio;
  canvas.style.width = W2 + "px";
  canvas.style.height = H2 + "px";
  ctx.scale(devicePixelRatio, devicePixelRatio);
  draw();
}});

// Клавиши
window.addEventListener("keydown", e => {{
  if (e.key === 'r' || e.key === 'R') {{
    transform = d3.zoomIdentity.translate(W/2, H/2).scale(1);
    draw();
  }}
  if (e.key === 'f' || e.key === 'F') {{
    document.getElementById("searchInput").focus();
  }}
}});
</script>
</body>
</html>"""

    Path(filename).write_text(html, encoding="utf-8")
    logger.info("Canvas graph exported to %s (%d nodes, %d edges)", 
                filename, G.number_of_nodes(), G.number_of_edges())
    return filename