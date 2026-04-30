"""
visualizer.py — генерация интерактивного HTML-графа через D3.js.
Улучшенная версия: размер узлов от метрик, отраслевые цвета, легенда.
"""

import json
import logging
from pathlib import Path
from typing import Optional
import networkx as nx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константы оформления
# ---------------------------------------------------------------------------

EDGE_COLORS = {
    "parent_child":    "#e63946",   # красный
    "common_founder":  "#f4a261",   # оранжевый
    "common_director": "#2a9d8f",   # бирюзовый
    "same_industry":   "#457b9d",   # синий
    "affiliated":      "#e9c46a",   # жёлтый
}

EDGE_TITLES = {
    "parent_child":    "Учредительство",
    "common_founder":  "Общий учредитель",
    "common_director": "Общий руководитель",
    "same_industry":   "Одна отрасль",
    "affiliated":      "Аффилированность",
}

# Цвета отраслевых групп
INDUSTRY_COLORS = {
    "Нефтегаз":          "#e63946",
    "Банки и финансы":   "#2a9d8f",
    "Металлургия":       "#e9c46a",
    "Энергетика":        "#f4a261",
    "Телеком и ИТ":      "#457b9d",
    "Розничная торговля": "#a8dadc",
    "Транспорт":         "#264653",
    "Госорганы":         "#6d2b3d",
    "Химия":             "#90be6d",
    "Строительство":     "#577590",
    "Прочее":            "#8b949e",
}

# Отраслевые группы по префиксам ОКВЭД
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
    """Определяет отраслевую группу по коду ОКВЭД."""
    if not okved:
        return "Прочее"
    for group, prefixes in INDUSTRY_GROUPS.items():
        for prefix in prefixes:
            if okved.startswith(prefix):
                return group
    return "Прочее"


def _node_size(G: nx.Graph, inn: str) -> float:
    """
    Размер узла зависит от:
    - PageRank (вес в сети)
    - Выручка
    - Число сотрудников
    - Уставной капитал
    """
    n = G.nodes[inn]
    pr = n.get("pagerank", 0.01)
    revenue = n.get("revenue") or 0
    emp = n.get("employee_count") or 0
    capital = n.get("capital") or 0

    size = 6  # базовый размер
    size += pr * 2500          # PageRank
    size += min(revenue / 5e10, 12) if revenue else 0   # выручка (до +12px)
    size += min(emp / 10000, 8) if emp else 0           # сотрудники (до +8px)
    size += min(capital / 5e8, 6) if capital else 0     # капитал (до +6px)

    return max(8, min(size, 55))


def _node_color(G: nx.Graph, inn: str) -> str:
    """Цвет узла по отраслевой группе."""
    okved = G.nodes[inn].get("okved", "")
    industry = get_industry_group(okved)
    return INDUSTRY_COLORS.get(industry, INDUSTRY_COLORS["Прочее"])


def _node_title(G: nx.Graph, inn: str) -> str:
    """HTML-подсказка при наведении."""
    n = G.nodes[inn]
    capital = n.get("capital")
    cap_str = f"{capital:,.0f} ₽" if capital else "н/д"
    emp = n.get("employee_count")
    emp_str = f"{emp:,}" if emp else "н/д"
    revenue = n.get("revenue")
    rev_str = f"{revenue:,.0f} ₽" if revenue else "н/д"
    industry = get_industry_group(n.get("okved", ""))

    return (
        f"<b>{n.get('name', inn)}</b><br>"
        f"ИНН: {inn}<br>"
        f"Отрасль: {industry}<br>"
        f"ОКВЭД: {n.get('okved','')} {n.get('okved_name','')}<br>"
        f"Статус: {n.get('status','')}<br>"
        f"Выручка: {rev_str}<br>"
        f"Уставной капитал: {cap_str}<br>"
        f"Сотрудников: {emp_str}<br>"
        f"PageRank: {n.get('pagerank', 0):.4f}<br>"
        f"Betweenness: {n.get('betweenness', 0):.4f}<br>"
        f"Кластер: {n.get('community', '?')}"
    )


def _edge_width(edge_data: dict) -> float:
    """Толщина ребра зависит от типа связи и силы."""
    etype = edge_data.get("type", "")
    if etype == "parent_child":
        share = edge_data.get("share") or 0
        return 1.0 + (share / 50) * 4  # чем больше доля, тем толще
    elif etype == "affiliated":
        return 2.5  # аффилированные связи пожирнее
    elif etype == "same_industry":
        weight = edge_data.get("weight", 0.5)
        return 0.5 + weight * 2
    return 1.5


# ---------------------------------------------------------------------------
# Основная функция экспорта в HTML (D3.js)
# ---------------------------------------------------------------------------

def export_to_html_d3(G: nx.MultiGraph, filename: str = "org_network_d3.html") -> str:
    """
    Экспорт через D3.js с улучшенной визуализацией.
    Генерирует самодостаточный HTML.
    """
    nodes = []
    for inn in G.nodes():
        n = G.nodes[inn]
        nodes.append({
            "id": inn,
            "label": n.get("label", inn),
            "title": n.get("name", inn),
            "group": n.get("community", 0),
            "industry": get_industry_group(n.get("okved", "")),
            "pagerank": n.get("pagerank", 0.01),
            "revenue": n.get("revenue") or 0,
            "employee_count": n.get("employee_count") or 0,
            "capital": n.get("capital") or 0,
            "size": _node_size(G, inn),
            "color": _node_color(G, inn),
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
            "control": data.get("control", ""),
        })

    graph_json = json.dumps({"nodes": nodes, "links": links}, ensure_ascii=False)
    edge_colors_js = json.dumps(EDGE_COLORS)

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Сеть организаций РФ</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0d1117; font-family: 'Segoe UI', Arial, sans-serif; color: #c9d1d9; overflow: hidden; }}
  svg {{ width: 100vw; height: 100vh; }}
  
  .link {{
    stroke-opacity: 0.7;
    cursor: pointer;
    transition: stroke-opacity 0.2s;
  }}
  .link:hover {{ stroke-opacity: 1; }}
  
  .node circle {{
    stroke: #30363d;
    stroke-width: 2px;
    cursor: pointer;
    transition: stroke-width 0.2s;
  }}
  .node circle:hover {{ stroke-width: 3px; stroke: #58a6ff; }}
  .node text {{
    font-size: 11px;
    fill: #c9d1d9;
    pointer-events: none;
    text-shadow: 0 0 3px rgba(0,0,0,0.8);
  }}
  
  #tooltip {{
    position: fixed;
    background: rgba(13,17,23,0.96);
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 12px;
    pointer-events: none;
    max-width: 340px;
    line-height: 1.7;
    display: none;
    box-shadow: 0 8px 32px rgba(0,0,0,0.7);
    z-index: 1000;
  }}
  
  #legend {{
    position: fixed;
    top: 16px;
    right: 16px;
    background: rgba(13,17,23,0.93);
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 14px 18px;
    font-size: 12px;
    z-index: 999;
    max-height: 80vh;
    overflow-y: auto;
  }}
  
  .legend-section {{
    margin-bottom: 12px;
  }}
  
  .legend-section:last-child {{
    margin-bottom: 0;
  }}
  
  .legend-title {{
    font-weight: bold;
    margin-bottom: 6px;
    font-size: 13px;
  }}
  
  .legend-item {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 3px 0;
  }}
  
  .legend-line {{
    width: 24px;
    height: 3px;
    border-radius: 2px;
    flex-shrink: 0;
  }}
  
  .legend-dot {{
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
    border: 1px solid #30363d;
  }}
  
  #search {{
    position: fixed;
    top: 16px;
    left: 16px;
    z-index: 999;
    background: rgba(13,17,23,0.93);
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 8px;
    display: flex;
    gap: 6px;
  }}
  
  #search input {{
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 4px;
    color: #c9d1d9;
    padding: 6px 10px;
    font-size: 12px;
    width: 200px;
    outline: none;
  }}
  
  #search input:focus {{
    border-color: #58a6ff;
  }}
  
  #search button {{
    background: #238636;
    border: none;
    border-radius: 4px;
    color: white;
    padding: 6px 12px;
    cursor: pointer;
    font-size: 12px;
    font-weight: bold;
  }}
  
  #search button:hover {{
    background: #2ea043;
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
  <div class="legend-section">
    <div class="legend-title" style="color:#58a6ff">🔗 ТИПЫ СВЯЗЕЙ</div>
    <div class="legend-item"><div class="legend-line" style="background:#e63946"></div>Учредительство</div>
    <div class="legend-item"><div class="legend-line" style="background:#f4a261"></div>Общий учредитель</div>
    <div class="legend-item"><div class="legend-line" style="background:#2a9d8f"></div>Общий руководитель</div>
    <div class="legend-item"><div class="legend-line" style="background:#457b9d"></div>Одна отрасль</div>
    <div class="legend-item"><div class="legend-line" style="background:#e9c46a"></div>Аффилированность</div>
  </div>
  <div class="legend-section">
    <div class="legend-title" style="color:#f4a261">🏭 ОТРАСЛИ</div>
    <div class="legend-item"><div class="legend-dot" style="background:#e63946"></div>Нефтегаз</div>
    <div class="legend-item"><div class="legend-dot" style="background:#2a9d8f"></div>Банки и финансы</div>
    <div class="legend-item"><div class="legend-dot" style="background:#e9c46a"></div>Металлургия</div>
    <div class="legend-item"><div class="legend-dot" style="background:#f4a261"></div>Энергетика</div>
    <div class="legend-item"><div class="legend-dot" style="background:#457b9d"></div>Телеком и ИТ</div>
    <div class="legend-item"><div class="legend-dot" style="background:#a8dadc"></div>Розничная торговля</div>
    <div class="legend-item"><div class="legend-dot" style="background:#264653"></div>Транспорт</div>
    <div class="legend-item"><div class="legend-dot" style="background:#6d2b3d"></div>Госорганы</div>
    <div class="legend-item"><div class="legend-dot" style="background:#90be6d"></div>Химия</div>
    <div class="legend-item"><div class="legend-dot" style="background:#577590"></div>Строительство</div>
  </div>
  <div style="margin-top:10px;font-size:10px;color:#8b949e">
    Размер кружка = значимость<br>
    (PageRank + выручка + сотрудники)
  </div>
</div>

<svg id="graph"></svg>

<script>
const graphData = {graph_json};
const EDGE_COLORS = {edge_colors_js};

const svg = d3.select("#graph");
const W = window.innerWidth;
const H = window.innerHeight;
const g = svg.append("g");
const tooltip = document.getElementById("tooltip");

// Zoom
svg.call(d3.zoom()
  .scaleExtent([0.1, 10])
  .on("zoom", e => g.attr("transform", e.transform)));

// Симуляция с более сильными связями
const sim = d3.forceSimulation(graphData.nodes)
  .force("link", d3.forceLink(graphData.links).id(d => d.id)
    .distance(d => {{
      if (d.type === 'parent_child') return 120;
      if (d.type === 'affiliated') return 100;
      if (d.type === 'same_industry') return 200;
      return 160;
    }})
    .strength(d => {{
      if (d.type === 'parent_child' && d.share > 50) return 0.8;
      if (d.type === 'affiliated') return 0.6;
      return 0.3;
    }}))
  .force("charge", d3.forceManyBody()
    .strength(d => -200 - d.size * 5))
  .force("center", d3.forceCenter(W/2, H/2))
  .force("collision", d3.forceCollide(d => d.size + 5));

// Рёбра
const link = g.append("g")
  .selectAll("line")
  .data(graphData.links)
  .join("line")
  .attr("class", "link")
  .attr("stroke", d => d.color)
  .attr("stroke-width", d => d.width)
  .attr("stroke-dasharray", d => d.type === "same_industry" ? "5,5" : "none");

// Узлы
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

// Круги узлов
node.append("circle")
  .attr("r", d => d.size)
  .attr("fill", d => d.color);

// Подписи
node.append("text")
  .attr("dy", d => d.size + 12)
  .attr("text-anchor", "middle")
  .text(d => d.label.length > 25 ? d.label.substring(0, 23) + '...' : d.label);

// Всплывающие подсказки
node
  .on("mouseover", (e, d) => {{
    tooltip.innerHTML = d.tooltip;
    tooltip.style.display = "block";
  }})
  .on("mousemove", e => {{
    tooltip.style.left = Math.min(e.clientX + 15, W - 350) + "px";
    tooltip.style.top = Math.min(e.clientY + 15, H - 200) + "px";
  }})
  .on("mouseout", () => {{
    tooltip.style.display = "none";
  }})
  .on("dblclick", (e, d) => {{
    // Двойной клик — подсветка всех связей узла
    link.attr("stroke-opacity", l =>
      l.source.id === d.id || l.target.id === d.id ? 1 : 0.15
    );
    node.selectAll("circle")
      .attr("opacity", n => n.id === d.id || 
        graphData.links.some(l => 
          (l.source.id === d.id && l.target.id === n.id) ||
          (l.target.id === d.id && l.source.id === n.id)
        ) ? 1 : 0.3);
    setTimeout(() => {{
      link.attr("stroke-opacity", 0.7);
      node.selectAll("circle").attr("opacity", 1);
    }}, 2000);
  }});

// Поиск узла
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
      d3.zoomIdentity
        .translate(W/2, H/2)
        .scale(2)
        .translate(-found.x, -found.y)
    );
    // Подсветка
    node.selectAll("circle")
      .attr("stroke", n => n.id === found.id ? "#58a6ff" : "#30363d")
      .attr("stroke-width", n => n.id === found.id ? 4 : 2);
    setTimeout(() => {{
      node.selectAll("circle")
        .attr("stroke", "#30363d")
        .attr("stroke-width", 2);
    }}, 3000);
  }}
}}

// Легенда для рёбер
link.on("mouseover", (e, d) => {{
  tooltip.innerHTML = `<b>${{d.title}}</b>${{d.via ? '<br>Через: ' + d.via : ''}}${{d.share ? '<br>Доля: ' + d.share + '%' : ''}}${{d.control === 'majority' ? '<br>Контроль: мажоритарный (>50%)' : ''}}`;
  tooltip.style.display = "block";
}})
.on("mousemove", e => {{
  tooltip.style.left = Math.min(e.clientX + 15, W - 350) + "px";
  tooltip.style.top = Math.min(e.clientY + 15, H - 100) + "px";
}})
.on("mouseout", () => {{
  tooltip.style.display = "none";
}});

// Анимация
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