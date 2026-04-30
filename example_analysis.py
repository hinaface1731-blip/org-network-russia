"""
example_analysis.py — демонстрационный анализ сети Газпрома.

Запуск:
    python example_analysis.py

Не требует API-ключа: использует синтетическую базу.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import logging
logging.basicConfig(level=logging.WARNING)  # Меньше шума

from fetcher import _SYNTHETIC_DB
from graph_builder import build_graph_from_inn_list, build_ego_graph
from metrics import (
    enrich_graph_with_metrics,
    top_nodes_by_pagerank,
    community_summary,
    node_metrics,
)
from visualizer import export_to_html_d3

SEPARATOR = "─" * 60


def print_section(title: str):
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)


# ---------------------------------------------------------------------------
# 1. Построение ego-графа вокруг Газпрома
# ---------------------------------------------------------------------------

GAZPROM_INN = "7736050003"

print_section("1. EGO-ГРАФ ГАЗПРОМА (глубина 2)")

G = build_ego_graph(GAZPROM_INN, depth=2)
G = enrich_graph_with_metrics(G)

print(f"Узлов в графе:   {G.number_of_nodes()}")
print(f"Рёбер в графе:   {G.number_of_edges()}")

edge_types: dict[str, int] = {}
for _, _, d in G.edges(data=True):
    t = d.get("type", "unknown")
    edge_types[t] = edge_types.get(t, 0) + 1

print("\nРаспределение рёбер по типу:")
for t, cnt in sorted(edge_types.items(), key=lambda x: -x[1]):
    labels = {
        "parent_child":    "Учредительство     ",
        "common_founder":  "Общий учредитель   ",
        "common_director": "Общий руководитель ",
        "same_industry":   "Одна отрасль       ",
    }
    print(f"  {labels.get(t, t)}: {cnt}")


# ---------------------------------------------------------------------------
# 2. Полный граф из 9 синтетических организаций
# ---------------------------------------------------------------------------

print_section("2. ПОЛНЫЙ ГРАФ (9 синтетических организаций)")

ALL_INNS = list(_SYNTHETIC_DB.keys())
G_full = build_graph_from_inn_list(ALL_INNS)
G_full = enrich_graph_with_metrics(G_full)

print(f"Организаций: {G_full.number_of_nodes()}")
print(f"Связей:      {G_full.number_of_edges()}")

import networkx as nx
print(f"Плотность:   {nx.density(G_full):.3f}")
print(f"Связность:   {'Да' if nx.is_connected(G_full) else 'Нет'}")


# ---------------------------------------------------------------------------
# 3. Топ-5 организаций по PageRank
# ---------------------------------------------------------------------------

print_section("3. ТОП-5 ЦЕНТРАЛЬНЫХ ОРГАНИЗАЦИЙ (PageRank)")

top5 = top_nodes_by_pagerank(G_full, n=5)
for rank, (inn, score, label) in enumerate(top5, 1):
    node = G_full.nodes[inn]
    deg = node.get("degree", 0)
    btw = node.get("betweenness", 0)
    print(f"\n  #{rank}. {label}")
    print(f"       ИНН:         {inn}")
    print(f"       PageRank:    {score:.5f}")
    print(f"       Степень:     {deg}")
    print(f"       Betweenness: {btw:.5f}")
    print(f"       ОКВЭД:       {node.get('okved','')} — {node.get('okved_name','')}")
    print(f"       Кластер:     {node.get('community', '?')}")


# ---------------------------------------------------------------------------
# 4. Кластеры (сообщества)
# ---------------------------------------------------------------------------

print_section("4. КЛАСТЕРЫ СВЯЗАННЫХ ОРГАНИЗАЦИЙ (Louvain / Label Propagation)")

partition = nx.get_node_attributes(G_full, "community")
clusters = community_summary(G_full, partition)

for c in clusters:
    print(f"\n  Кластер {c['community_id']} ({c['size']} орг.):")
    for m in c["members"]:
        print(f"    • {m['label']} (ИНН {m['inn']})")


# ---------------------------------------------------------------------------
# 5. Детальные связи Газпрома
# ---------------------------------------------------------------------------

print_section("5. ПРЯМЫЕ СВЯЗИ ГАЗПРОМА")

EDGE_LABELS = {
    "parent_child":    "→ учредительство",
    "common_founder":  "↔ общий учредитель",
    "common_director": "↔ общий директор",
    "same_industry":   "~ одна отрасль",
}

for u, v, data in G_full.edges(data=True):
    if GAZPROM_INN in (u, v):
        other = v if u == GAZPROM_INN else u
        label_other = G_full.nodes[other].get("label", other)
        etype = data.get("type", "?")
        via = data.get("via", "")
        via_str = f" (через: {via})" if via else ""
        print(f"  {G_full.nodes[GAZPROM_INN]['label']} {EDGE_LABELS.get(etype, etype)} {label_other}{via_str}")


# ---------------------------------------------------------------------------
# 6. Экспорт HTML
# ---------------------------------------------------------------------------

print_section("6. ЭКСПОРТ ГРАФОВ В HTML")

# Ego-граф Газпрома
ego_file = export_to_html_d3(G, "gazprom_ego_graph.html")
print(f"  Ego-граф Газпрома → {ego_file}")

# Полный граф
full_file = export_to_html_d3(G_full, "full_network.html")
print(f"  Полный граф       → {full_file}")

print(f"\n  ✓ Откройте файлы в браузере для интерактивного просмотра")


# ---------------------------------------------------------------------------
# 7. Сводная таблица метрик
# ---------------------------------------------------------------------------

print_section("7. СВОДНАЯ ТАБЛИЦА МЕТРИК")

metrics = node_metrics(G_full)
rows = []
for inn, m in metrics.items():
    label = G_full.nodes[inn].get("label", inn)
    rows.append((label, inn, m["pagerank"], m["degree"], m["betweenness"]))

rows.sort(key=lambda x: -x[2])

print(f"  {'Организация':<30} {'ИНН':<14} {'PageRank':>10} {'Степень':>8} {'Btw':>10}")
print(f"  {'─'*30} {'─'*14} {'─'*10} {'─'*8} {'─'*10}")
for label, inn, pr, deg, btw in rows:
    short = label[:28] + ".." if len(label) > 30 else label
    print(f"  {short:<30} {inn:<14} {pr:>10.5f} {deg:>8} {btw:>10.5f}")

print(f"\n{'─'*60}")
print("  Готово. Файлы для открытия в браузере:")
print(f"    • gazprom_ego_graph.html")
print(f"    • full_network.html")
print(f"  Для веб-интерфейса: streamlit run app.py")
print(f"{'─'*60}\n")
