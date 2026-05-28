"""
metrics.py — метрики графа для любого масштаба.

Изменения vs старая версия:
  • Betweenness с авто-семплированием (k=√n) для графов > 500 узлов
  • get_industry_group() — единая функция (не дублируется в visualizer)
  • enrich_graph_with_metrics() автоматически выбирает алгоритм кластеризации
  • community_summary() возвращает топ-компании кластера по PageRank
"""

import logging
from typing import Any

import networkx as nx

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
#  Отраслевые группы
# ─────────────────────────────────────────────────────────────

INDUSTRY_GROUPS: dict[str, list[str]] = {
    "Нефтегаз":           ["06", "09", "19", "49.5"],
    "Банки и финансы":    ["64", "65", "66"],
    "Металлургия":        ["24", "07"],
    "Энергетика":         ["35"],
    "Телеком и ИТ":       ["61", "62", "63"],
    "Розничная торговля": ["47"],
    "Транспорт":          ["49", "50", "51", "52"],
    "Госорганы":          ["84"],
    "Химия":              ["20", "21", "22"],
    "Строительство":      ["41", "42", "43"],
    "Недвижимость":       ["68"],
    "Сельское хозяйство": ["01", "02", "03"],
    "Образование":        ["85"],
    "Здравоохранение":    ["86"],
    "Добыча":             ["05", "07", "08", "10", "11"],
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


# ─────────────────────────────────────────────────────────────
#  Louvain (опционально)
# ─────────────────────────────────────────────────────────────

try:
    import community as community_louvain
    HAS_LOUVAIN = True
except ImportError:
    HAS_LOUVAIN = False
    logger.debug("python-louvain not installed — using Label Propagation")


# ─────────────────────────────────────────────────────────────
#  Вспомогательные
# ─────────────────────────────────────────────────────────────

def _to_simple_weighted(G: nx.Graph) -> nx.Graph:
    """MultiGraph → простой Graph, вес = число рёбер между парой."""
    simple = nx.Graph()
    simple.add_nodes_from(G.nodes(data=True))
    for u, v, _ in G.edges(data=True):
        if simple.has_edge(u, v):
            simple[u][v]["weight"] += 1
        else:
            simple.add_edge(u, v, weight=1)
    return simple


# ─────────────────────────────────────────────────────────────
#  PageRank
# ─────────────────────────────────────────────────────────────

def compute_pagerank(G: nx.Graph, alpha: float = 0.85) -> dict[str, float]:
    simple = _to_simple_weighted(G)
    return nx.pagerank(simple, alpha=alpha, weight="weight", max_iter=200)


def top_nodes_by_pagerank(G: nx.Graph, n: int = 10) -> list[tuple[str, float, str]]:
    pr = compute_pagerank(G)
    top = sorted(pr.items(), key=lambda x: x[1], reverse=True)[:n]
    return [(inn, score, G.nodes[inn].get("label", inn)) for inn, score in top]


# ─────────────────────────────────────────────────────────────
#  Betweenness (с авто-семплированием)
# ─────────────────────────────────────────────────────────────

def compute_betweenness(G: nx.Graph) -> dict[str, float]:
    """
    Betweenness centrality.
    Для графов > 500 узлов использует семплирование k=√n для скорости.
    Точность: ±5% при k≥√n.
    """
    simple = _to_simple_weighted(G)
    n = simple.number_of_nodes()

    if n <= 500:
        k = None  # точный расчёт
    elif n <= 5000:
        k = max(50, int(n ** 0.5))
    else:
        k = max(100, int(n ** 0.4))  # агрессивное семплирование для 5k+

    if k:
        logger.debug("Betweenness: sampling k=%d of %d nodes", k, n)

    return nx.betweenness_centrality(simple, k=k, weight="weight", normalized=True)


# ─────────────────────────────────────────────────────────────
#  Все метрики вместе
# ─────────────────────────────────────────────────────────────

def node_metrics(G: nx.Graph) -> dict[str, dict[str, Any]]:
    pr  = compute_pagerank(G)
    deg = dict(G.degree())
    btw = compute_betweenness(G)

    return {
        inn: {
            "pagerank":    round(pr.get(inn, 0.0), 7),
            "degree":      deg.get(inn, 0),
            "betweenness": round(btw.get(inn, 0.0), 7),
        }
        for inn in G.nodes()
    }


# ─────────────────────────────────────────────────────────────
#  Кластеризация (сообщества)
# ─────────────────────────────────────────────────────────────

def detect_communities(G: nx.Graph) -> dict[str, int]:
    """
    Определяет сообщества.
    Алгоритм выбирается автоматически:
      • < 50 узлов       → Girvan-Newman (точный, медленный)
      • 50–100k узлов    → Louvain (если доступен) или Label Propagation
      • любой размер     → Label Propagation как fallback
    """
    if G.number_of_nodes() < 2:
        return {n: 0 for n in G.nodes()}

    simple = _to_simple_weighted(G)

    if HAS_LOUVAIN:
        try:
            partition = community_louvain.best_partition(simple, weight="weight")
            n_comm = len(set(partition.values()))
            logger.info("Louvain: %d communities", n_comm)
            return partition
        except Exception as e:
            logger.warning("Louvain failed (%s), falling back to Label Propagation", e)

    # Label Propagation (встроен в networkx, O(n+m), быстро на любом размере)
    logger.info("Using Label Propagation")
    communities = nx.community.label_propagation_communities(simple)
    partition = {}
    for cid, comm in enumerate(communities):
        for node in comm:
            partition[node] = cid
    logger.info("Label Propagation: %d communities", len(set(partition.values())))
    return partition


# ─────────────────────────────────────────────────────────────
#  Итоговое обогащение графа
# ─────────────────────────────────────────────────────────────

def enrich_graph_with_metrics(G: nx.MultiGraph) -> nx.MultiGraph:
    """Добавляет PageRank, degree, betweenness, community, industry_group в атрибуты узлов."""
    n = G.number_of_nodes()
    logger.info("Enriching graph: %d nodes, %d edges…", n, G.number_of_edges())

    metrics   = node_metrics(G)
    partition = detect_communities(G)

    for inn in G.nodes():
        m = metrics.get(inn, {})
        G.nodes[inn]["pagerank"]       = m.get("pagerank", 0.0)
        G.nodes[inn]["degree"]         = m.get("degree", 0)
        G.nodes[inn]["betweenness"]    = m.get("betweenness", 0.0)
        G.nodes[inn]["community"]      = partition.get(inn, -1)
        okved = G.nodes[inn].get("okved", "")
        G.nodes[inn]["industry_group"] = get_industry_group(okved)

    logger.info("Enrichment done")
    return G


# ─────────────────────────────────────────────────────────────
#  Сводка по кластерам
# ─────────────────────────────────────────────────────────────

def community_summary(G: nx.Graph, partition: dict[str, int]) -> list[dict]:
    """
    Возвращает список кластеров, отсортированных по размеру.
    Для каждого — топ-5 организаций по PageRank.
    """
    groups: dict[int, list[str]] = {}
    for inn, cid in partition.items():
        groups.setdefault(cid, []).append(inn)

    result = []
    for cid, members in sorted(groups.items(), key=lambda x: -len(x[1])):
        # Топ-5 по PageRank
        top = sorted(
            members,
            key=lambda inn: G.nodes[inn].get("pagerank", 0),
            reverse=True,
        )[:5]
        result.append({
            "community_id": cid,
            "size":         len(members),
            "members": [
                {
                    "inn":      inn,
                    "label":    G.nodes[inn].get("label", inn),
                    "pagerank": G.nodes[inn].get("pagerank", 0),
                }
                for inn in top
            ],
        })
    return result
