"""
visualizer.py — генерация интерактивного HTML-графа с цветовыми кластерами.
Группировка по отраслям с гравитацией, как на картах Twitch/Википедии.
"""

import json
import logging
from pathlib import Path
import networkx as nx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константы оформления
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

# Отраслевые группы и их цвета (яркие, для кластеров)
INDUSTRY_CONFIG = {
    "Нефтегаз":          {"color": "#ff6b35", "center": [0.25, 0.35]},
    "Банки и финансы":   {"color": "#e63946", "center": [0.65, 0.25]},
    "Металлургия":       {"color": "#ffb703", "center": [0.15, 0.65]},
    "Энергетика":        {"color": "#f4a261", "center": [0.50, 0.15]},
    "Телеком и ИТ":      {"color": "#457b9d", "center": [0.80, 0.55]},
    "Розничная торговля": {"color": "#2ec4b6", "center": [0.70, 0.80]},
    "Транспорт":         {"color": "#8338ec", "center": [0.35, 0.80]},
    "Госорганы":         {"color": "#6d2b3d", "center": [0.90, 0.15]},
    "Химия":             {"color": "#06d6a0", "center": [0.10, 0.45]},
    "Строительство":     {"color": "#fb8b24", "center": [0.55, 0.70]},
    "Прочее":            {"color": "#8b949e", "center": [0.50, 0.50]},
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

def get_industry_center(okved: str) -> list:
    industry = get_industry_group(okved)
    return INDUSTRY_CONFIG.get(industry, INDUSTRY_CONFIG["Прочее"])["center"]

def _node_size(G: nx.Graph, inn: str) -> float:
    n = G.nodes[inn]
    pr = n.get("pagerank", 0.01)
    revenue = n.get("revenue") or 0
    emp = n.get("employee_count") or 0
    capital = n.get("capital") or 0

    size = 8
    size += pr * 3000
    size += min(revenue / 1e10, 15) if revenue else 0
    size += min(emp / 10000, 10) if emp else 0
    size += min(capital / 5e8, 6) if capital else 0

    return max(10, min(size, 60))

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
        f"ОКВЭД: {n.get('okved','')} {n.get('okved_name','')}<br>"
        f"Статус: {n.get('status','')}<br>"
        f"Уставной капитал: {cap_str}<br>"
        f"Сотрудников: {emp_str}<br>"
        f"PageRank: {n.get('pagerank', 0):.4f}<br>"
        f"Betweenness: {n.get('betweenness', 0):.4f}<br>"
        f"Кластер: {n.get('community', '?')}"
    )

def _edge_width(edge_data: dict) -> float:
    etype = edge_data.get("type", "")
    if etype == "parent_child":
        share = edge_data.get("share") or 0
        return 1.0 + (share / 100) * 6
    elif etype == "common_director":
        return 2.0
    elif etype == "same_industry":
        return 0.5
    return 1.5

# ---------------------------------------------------------------------------
# Основная функция
# ---------------------------------------------------------------------------

def export_to_html_d3(G: nx.MultiGraph, filename: str = "org_network.html") -> str:
    nodes = []
    for inn in G.nodes():
        n = G.nodes[inn]
        industry = get_industry_group(n.get("okved", ""))
        center = get_industry_center(n.get("okved", ""))
        nodes.append({
            "id": inn,
            "label": n.get("label", inn),
            "title": n.get("name", inn),
            "group": n.get("community", 0),
            "industry": industry,
            "industryColor": INDUSTRY_CONFIG[industry]["color"],
            "industryCenter": center,
            "pagerank": n.get("pagerank", 0.01),
            "size": _node_size(G, inn),
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
            "title": EDGE_TITLES.get(etype, etype),
            "color": EDGE_COLORS.get(etype, "#888"),
            "width": _edge_width(data),
            "share": data.get("share"),
            "via": data.get("via", ""),
        })

    graph_json = json.dumps({"nodes": nodes, "links": links}, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Сеть организаций РФ</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ 
    background: #0a0e14; 
    font-family: 'Segoe UI', Arial, sans-serif; 
    color: #c9d1d9; 
    overflow: hidden; 
  }}
  svg {{ width: 100vw; height: 100vh; }}
  
  .cluster-zone {{
    fill-opacity: 0.06;
    stroke-width: 2;
    stroke-opacity: 0.3;
  }}
  
  .cluster-label {{
    font-size: 14px;
    font-weight: bold;
    fill-opacity: 0.5;
    pointer-events: none;
    text-anchor: middle;
  }}
  
  .link {{
    stroke-opacity: 0.5;
    cursor: pointer;
    transition: stroke-opacity 0.3s;
  }}
  .link:hover {{ stroke-opacity: 1; }}
  
  .node circle {{
    stroke: #1a1f2b;
    stroke-width: 2px;
    cursor: pointer;
    transition: stroke-width 0.2s, stroke 0.2s;
    filter: drop-shadow(0 0 4px rgba(0,0,0,0.5));
  }}
  .node circle:hover {{ 
    stroke-width: 3px; 
    stroke: #fff;
    filter: drop-shadow(0 0 8px rgba(255,255,255,0.3));
  }}
  .node text {{
    font-size: 10px;
    fill: #c9d1d9;
    pointer-events: none;
    text-shadow: 0 0 4px rgba(0,0,0,0.9);
    opacity: 0.8;
  }}
  
  #tooltip {{
    position: fixed;
    background: rgba(10,14,20,0.96);
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 12px;
    pointer-events: none;
    max-width: 340px;
    line-height: 1.7;
    display: none;
    box-shadow: 0 8px 32px rgba(0,0,0,0.8);
    z-index: 1000;
  }}
  
  #legend {{
    position: fixed;
    top: 16px;
    right: 16px;
    background: rgba(10,14,20,0.94);
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 14px 18px;
    font-size: 11px;
    z-index: 999;
    max-height: 85vh;
    overflow-y: auto;
    backdrop-filter: blur(10px);
  }}
  
  .legend-title {{
    font-weight: bold;
    margin-bottom: 6px;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
  }}
  
  .legend-item {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 4px 0;
  }}
  
  .legend-dot {{
    width: 12px;
    height: 12px;
    border-radius: 50%;
    flex-shrink: 0;
    border: 1px solid rgba(255,255,255,0.2);
  }}
  
  .legend-line {{
    width: 20px;
    height: 3px;
    border-radius: 2px;
    flex-shrink: 0;
  }}
  
  #search {{
    position: fixed;
    top: 16px;
    left: 16px;
    z-index: 999;
    display: flex;
    gap: 6px;
  }}
  
  #search input {{
    background: rgba(10,14,20,0.94);
    border: 1px solid #30363d;
    border-radius: 6px;
    color: #c9d1d9;
    padding: 8px 12px;
    font-size: 13px;
    width: 220px;
    outline: none;
    backdrop-filter: blur(10px);
  }}
  
  #search input:focus {{ border-color: #58a6ff; }}
  
  #search button {{
    background: #238636;
    border: none;
    border-radius: 6px;
    color: white;
    padding: 8px 14px;
    cursor: pointer;
    font-size: 13px;
    font-weight: bold;
  }}
  
  #search button:hover {{ background: #2ea043; }}
</style>
</head>
<body>
<div id="tooltip"></div>

<div id="search">
  <input type="text" id="searchInput" placeholder="Поиск организации..." onkeyup="if(event.key==='Enter')searchNode()">
  <button onclick="searchNode()">🔍</button>
</div>

<div id="legend">
  <div class="legend-title" style="color:#58a6ff;margin-top:0">🏭 ОТРАСЛЕВЫЕ КЛАСТЕРЫ</div>
  {''.join(f'<div class="legend-item"><div class="legend-dot" style="background:{c["color"]}"></div>{n}</div>' for n,c in INDUSTRY_CONFIG.items() if n != "Прочее")}
  
  <div style="margin:8px 0;border-top:1px solid #30363d"></div>
  <div class="legend-title" style="color:#f4a261">🔗 ТИПЫ СВЯЗЕЙ</div>
  <div class="legend-item"><div class="legend-line" style="background:#e63946"></div>Учредительство</div>
  <div class="legend-item"><div class="legend-line" style="background:#f4a261"></div>Общий учредитель</div>
  <div class="legend-item"><div class="legend-line" style="background:#2a9d8f"></div>Общий руководитель</div>
  <div class="legend-item"><div class="legend-line" style="background:#457b9d"></div>Одна отрасль</div>
  
  <div style="margin-top:10px;font-size:10px;color:#8b949e">
    Размер = значимость<br>
    Ближе = больше связей
  </div>
</div>

<svg id="graph"></svg>

<script>
const graphData = {graph_json};
const W = window.innerWidth;
const H = window.innerHeight;

const svg = d3.select("#graph");
const g = svg.append("g");
const tooltip = document.getElementById("tooltip");

// Отрисовка кластерных зон (полупрозрачные круги)
const clusters = g.append("g").attr("class", "clusters");
const clusterData = {{}};
graphData.nodes.forEach(n => {{
  if (!clusterData[n.industry]) {{
    clusterData[n.industry] = {{
      industry: n.industry,
      color: n.industryColor,
      center: n.industryCenter
    }};
  }}
}});

Object.values(clusterData).forEach(c => {{
  clusters.append("circle")
    .attr("class", "cluster-zone")
    .attr("cx", c.center[0] * W)
    .attr("cy", c.center[1] * H)
    .attr("r", 100)
    .attr("fill", c.color)
    .attr("stroke", c.color);
  
  clusters.append("text")
    .attr("class", "cluster-label")
    .attr("x", c.center[0] * W)
    .attr("y", c.center[1] * H - 110)
    .attr("fill", c.color)
    .text(c.industry);
}});

svg.call(d3.zoom()
  .scaleExtent([0.1, 8])
  .on("zoom", e => g.attr("transform", e.transform)));

const sim = d3.forceSimulation(graphData.nodes)
  .force("link", d3.forceLink(graphData.links).id(d => d.id)
    .distance(d => {{
      if (d.type === 'parent_child') return 80;
      if (d.type === 'common_director') return 60;
      if (d.type === 'same_industry') return 150;
      return 100;
    }})
    .strength(d => {{
      if (d.type === 'parent_child') return 0.7;
      if (d.type === 'common_director') return 0.5;
      return 0.2;
    }}))
  .force("charge", d3.forceManyBody()
    .strength(d => -150 - d.size * 4))
  .force("center", d3.forceCenter(W/2, H/2))
  // Притяжение к центру своего отраслевого кластера
  .force("cluster", alpha => {{
    graphData.nodes.forEach(d => {{
      const center = d.industryCenter;
      const cx = center[0] * W;
      const cy = center[1] * H;
      d.vx += (cx - d.x) * 0.02 * alpha;
      d.vy += (cy - d.y) * 0.02 * alpha;
    }});
  }})
  .force("collision", d3.forceCollide(d => d.size + 8));

const link = g.append("g")
  .selectAll("line")
  .data(graphData.links)
  .join("line")
  .attr("class", "link")
  .attr("stroke", d => d.color)
  .attr("stroke-width", d => d.width)
  .attr("stroke-dasharray", d => d.type === "same_industry" ? "4,4" : "none");

const node = g.append("g")
  .selectAll("g")
  .data(graphData.nodes)
  .join("g")
  .attr("class", "node")
  .call(d3.drag()
    .on("start", (e, d) => {{
      if (!e.active) sim.alphaTarget(0.3).restart();
      d.fx = d.x; d.fy = d.y;
    }})
    .on("drag", (e, d) => {{
      d.fx = e.x; d.fy = e.y;
    }})
    .on("end", (e, d) => {{
      if (!e.active) sim.alphaTarget(0);
      d.fx = null; d.fy = null;
    }}));

node.append("circle")
  .attr("r", d => d.size)
  .attr("fill", d => d.industryColor);

node.append("text")
  .attr("dy", d => d.size + 12)
  .attr("text-anchor", "middle")
  .text(d => d.label.length > 22 ? d.label.substring(0, 20) + '...' : d.label);

node
  .on("mouseover", (e, d) => {{
    tooltip.innerHTML = d.tooltip;
    tooltip.style.display = "block";
    link.attr("stroke-opacity", l =>
      l.source.id === d.id || l.target.id === d.id ? 1 : 0.1
    );
    node.selectAll("circle").attr("opacity", n =>
      n.id === d.id || graphData.links.some(l =>
        (l.source.id === d.id && l.target.id === n.id) ||
        (l.target.id === d.id && l.source.id === n.id)
      ) ? 1 : 0.2
    );
  }})
  .on("mousemove", e => {{
    tooltip.style.left = Math.min(e.clientX + 15, W - 350) + "px";
    tooltip.style.top = Math.min(e.clientY + 15, H - 200) + "px";
  }})
  .on("mouseout", () => {{
    tooltip.style.display = "none";
    link.attr("stroke-opacity", 0.5);
    node.selectAll("circle").attr("opacity", 1);
  }})
  .on("dblclick", (e, d) => {{
    svg.transition().duration(750).call(
      d3.zoom().transform,
      d3.zoomIdentity.translate(W/2, H/2).scale(2.5).translate(-d.x, -d.y)
    );
  }});

link
  .on("mouseover", (e, d) => {{
    tooltip.innerHTML = `<b>${{d.title}}</b>${{d.via ? '<br>Через: ' + d.via : ''}}${{d.share ? '<br>Доля: ' + d.share + '%' : ''}}`;
    tooltip.style.display = "block";
  }})
  .on("mousemove", e => {{
    tooltip.style.left = Math.min(e.clientX + 15, W - 350) + "px";
    tooltip.style.top = Math.min(e.clientY + 15, H - 100) + "px";
  }})
  .on("mouseout", () => {{ tooltip.style.display = "none"; }});

function searchNode() {{
  const query = document.getElementById("searchInput").value.toLowerCase();
  const found = graphData.nodes.find(n => 
    n.label.toLowerCase().includes(query) || 
    n.id.includes(query) ||
    n.title.toLowerCase().includes(query)
  );
  if (found && found.x && found.y) {{
    svg.transition().duration(750).call(
      d3.zoom().transform,
      d3.zoomIdentity.translate(W/2, H/2).scale(3).translate(-found.x, -found.y)
    );
    node.selectAll("circle")
      .attr("stroke", n => n.id === found.id ? "#fff" : "#1a1f2b")
      .attr("stroke-width", n => n.id === found.id ? 4 : 2);
    setTimeout(() => node.selectAll("circle").attr("stroke", "#1a1f2b").attr("stroke-width", 2), 3000);
  }}
}}

sim.on("tick", () => {{
  link
    .attr("x1", d => d.source.x)
    .attr("y1", d => d.source.y)
    .attr("x2", d => d.target.x)
    .attr("y2", d => d.target.y);
  node.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
}});
</script>
</body>
</html>"""

    Path(filename).write_text(html, encoding="utf-8")
    logger.info("D3 graph exported to %s (%d nodes, %d edges)", 
                filename, G.number_of_nodes(), G.number_of_edges())
    return filename