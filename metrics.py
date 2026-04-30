"""
metrics.py — метрики графа: PageRank, степень, кластеры Louvain.

Зависимость: python-louvain (community)
    pip install python-louvain
"""

import logging
from typing import Any
import networkx as nx

INDUSTRY_GROUPS = {
    "Нефтегаз": ["06", "09", "19", "49.5"],
    "Банки и финансы": ["64", "65", "66"],
    "Металлургия": ["24", "07"],
    "Энергетика": ["35"],
    "Телеком и ИТ": ["61", "62", "63"],
    "Розничная торговля": ["47"],
    "Транспорт": ["49", "50", "51", "52"],
    "Госорганы": ["84"],
    "Недвижимость": ["68"],
    "Строительство": ["41", "42", "43"],
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

logger = logging.getLogger(__name__)

try:
    import community as community_louvain  # python-louvain
    HAS_LOUVAIN = True
except ImportError:
    HAS_LOUVAIN = False
    logger.warning(
        "python-louvain not installed. Community detection disabled. "
        "Install: pip install python-louvain"
    )


# ---------------------------------------------------------------------------
# PageRank
# ---------------------------------------------------------------------------

def compute_pagerank(G: nx.Graph, alpha: float = 0.85) -> dict[str, float]:
    """
    Вычисляет PageRank для всех узлов.
    Для MultiGraph конвертируем в простой граф с весами.
    """
    simple = _to_simple_weighted(G)
    pr = nx.pagerank(simple, alpha=alpha, weight="weight")
    return pr


def top_nodes_by_pagerank(
    G: nx.Graph, n: int = 10
) -> list[tuple[str, float, str]]:
    """
    Возвращает топ-N узлов по PageRank.
    Каждый элемент: (inn, pagerank_score, label).
    """
    pr = compute_pagerank(G)
    sorted_pr = sorted(pr.items(), key=lambda x: x[1], reverse=True)[:n]
    return [
        (inn, score, G.nodes[inn].get("label", inn))
        for inn, score in sorted_pr
    ]


# ---------------------------------------------------------------------------
# Другие метрики
# ---------------------------------------------------------------------------

def compute_degree_centrality(G: nx.Graph) -> dict[str, float]:
    return nx.degree_centrality(G)


def compute_betweenness(G: nx.Graph, k: int = None) -> dict[str, float]:
    """
    Betweenness centrality.
    k — число сэмплируемых путей (None = точный расчёт, медленно на больших сетях).
    """
    simple = _to_simple_weighted(G)
    return nx.betweenness_centrality(simple, k=k, weight="weight", normalized=True)


def node_metrics(G: nx.Graph) -> dict[str, dict[str, Any]]:
    """
    Считает PageRank, степень и betweenness для каждого узла.
    Результат: {inn: {"pagerank": float, "degree": int, "betweenness": float}}
    """
    pr = compute_pagerank(G)
    deg = dict(G.degree())
    # betweenness с k=min(50, n) для ускорения на больших графах
    k = min(50, G.number_of_nodes()) if G.number_of_nodes() > 10 else None
    btw = compute_betweenness(G, k=k)

    result = {}
    for inn in G.nodes():
        result[inn] = {
            "pagerank": round(pr.get(inn, 0.0), 6),
            "degree": deg.get(inn, 0),
            "betweenness": round(btw.get(inn, 0.0), 6),
        }
    return result


# ---------------------------------------------------------------------------
# Обнаружение сообществ (кластеров)
# ---------------------------------------------------------------------------

def detect_communities(G: nx.Graph) -> dict[str, int]:
    """
    Возвращает словарь {inn: community_id}.
    Использует алгоритм Louvain если доступен, иначе — Girvan-Newman (медленно)
    или Label Propagation (быстро).
    """
    if G.number_of_nodes() < 2:
        return {n: 0 for n in G.nodes()}

    simple = _to_simple_weighted(G)

    if HAS_LOUVAIN:
        partition = community_louvain.best_partition(simple, weight="weight")
        logger.info(
            "Louvain: %d communities detected", len(set(partition.values()))
        )
        return partition

    # Fallback: Label Propagation (встроен в networkx, O(n))
    logger.info("Using Label Propagation (Louvain unavailable)")
    communities = nx.community.label_propagation_communities(simple)
    partition = {}
    for cid, comm in enumerate(communities):
        for node in comm:
            partition[node] = cid
    return partition


def community_summary(
    G: nx.Graph, partition: dict[str, int]
) -> list[dict]:
    """
    Возвращает список кластеров с их составом:
    [{"community_id": int, "size": int, "members": [{"inn": ..., "label": ...}]}]
    """
    groups: dict[int, list] = {}
    for inn, cid in partition.items():
        groups.setdefault(cid, []).append(inn)

    result = []
    for cid, members in sorted(groups.items(), key=lambda x: -len(x[1])):
        result.append({
            "community_id": cid,
            "size": len(members),
            "members": [
                {"inn": inn, "label": G.nodes[inn].get("label", inn)}
                for inn in members
            ],
        })
    return result


# ---------------------------------------------------------------------------
# Вспомогательные
# ---------------------------------------------------------------------------

def _to_simple_weighted(G: nx.Graph) -> nx.Graph:
    """
    Конвертирует (Multi)Graph в простой Graph с весом = число рёбер между узлами.
    """
    simple = nx.Graph()
    simple.add_nodes_from(G.nodes(data=True))
    for u, v, _ in G.edges(data=True):
        if simple.has_edge(u, v):
            simple[u][v]["weight"] += 1
        else:
            simple.add_edge(u, v, weight=1)
    return simple


def enrich_graph_with_metrics(G: nx.MultiGraph) -> nx.MultiGraph:
    """
    Добавляет метрики прямо в атрибуты узлов графа (для визуализации).
    """
    metrics = node_metrics(G)
    partition = detect_communities(G)

    for inn in G.nodes():
        m = metrics.get(inn, {})
        G.nodes[inn]["pagerank"] = m.get("pagerank", 0.0)
        G.nodes[inn]["degree"] = m.get("degree", 0)
        G.nodes[inn]["betweenness"] = m.get("betweenness", 0.0)
        G.nodes[inn]["community"] = partition.get(inn, -1)

    for inn in G.nodes():
        okved = G.nodes[inn].get("okved", "")
        G.nodes[inn]["industry_group"] = get_industry_group(okved)

    return G
