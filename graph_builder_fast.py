"""
graph_builder_fast.py — быстрый построитель графа с индексами.
Использует O(n*m) вместо O(n²) для поиска общих руководителей.
"""

import logging
from collections import defaultdict
import networkx as nx

from fetcher import search_org_by_inn, batch_fetch
from cache import get_cache

logger = logging.getLogger(__name__)


def _okved2(okved: str) -> str:
    return okved.split(".")[0].zfill(2) if okved else ""


def _norm_name(name: str) -> str:
    return " ".join(name.upper().split())


class FastGraphBuilder:
    """Быстрый построитель графа с индексами для массовой загрузки."""
    
    def __init__(self):
        self.G: nx.MultiGraph = nx.MultiGraph()
        self._orgs: dict[str, dict] = {}
        self._director_index: dict[str, list[str]] = defaultdict(list)
        self._okved_index: dict[str, list[str]] = defaultdict(list)
        self._founder_index: dict[str, list[str]] = defaultdict(list)
    
    def add_org(self, org: dict) -> None:
        inn = org.get("inn", "")
        if not inn or inn in self._orgs:
            return
        
        self._orgs[inn] = org
        
        # Узел графа
        self.G.add_node(
            inn,
            label=org.get("short_name") or org.get("name", inn),
            name=org.get("name", ""),
            okved=org.get("okved", ""),
            okved_name=org.get("okved_name", ""),
            status=org.get("status", ""),
            employee_count=org.get("employee_count"),
            capital=org.get("capital"),
        )
        
        # Индекс руководителей
        for mgr in org.get("managers", []):
            name = _norm_name(mgr.get("name", ""))
            if name:
                self._director_index[name].append(inn)
        
        # Индекс ОКВЭД
        okved = _okved2(org.get("okved", ""))
        if okved and okved != "00":
            self._okved_index[okved].append(inn)
        
        # Индекс учредителей
        for f in org.get("founders", []):
            f_inn = f.get("inn", "")
            if f_inn:
                self._founder_index[f_inn].append(inn)
    
    def build_edges_fast(self) -> int:
        """Быстрое построение рёбер через индексы. Возвращает количество рёбер."""
        edge_count = 0
        
        # 1. Общие руководители (common_director)
        logger.info("Building common_director edges...")
        for name, inns in self._director_index.items():
            if len(inns) > 1:
                for i in range(len(inns)):
                    for j in range(i + 1, len(inns)):
                        if inns[i] != inns[j]:
                            self.G.add_edge(inns[i], inns[j], 
                                          type="common_director", via=name)
                            edge_count += 1
        logger.info("common_director: %d edges", edge_count)
        
        # 2. Общие учредители (common_founder)
        logger.info("Building common_founder edges...")
        founder_edges = 0
        for f_inn, inns in self._founder_index.items():
            if len(inns) > 1:
                for i in range(len(inns)):
                    for j in range(i + 1, len(inns)):
                        if inns[i] != inns[j]:
                            self.G.add_edge(inns[i], inns[j],
                                          type="common_founder", via=f_inn)
                            founder_edges += 1
        edge_count += founder_edges
        logger.info("common_founder: %d edges", founder_edges)
        
        # 3. Одна отрасль (same_industry)
        logger.info("Building same_industry edges...")
        industry_edges = 0
        for okved, inns in self._okved_index.items():
            if len(inns) > 1:
                # Для больших групп ограничиваем связи (топ-50 по группе)
                if len(inns) > 50:
                    inns = inns[:50]
                for i in range(len(inns)):
                    for j in range(i + 1, len(inns)):
                        if inns[i] != inns[j]:
                            self.G.add_edge(inns[i], inns[j],
                                          type="same_industry", okved=okved)
                            industry_edges += 1
        edge_count += industry_edges
        logger.info("same_industry: %d edges", industry_edges)
        
        # 4. Учредительство (parent_child)
        logger.info("Building parent_child edges...")
        parent_edges = 0
        for inn, org in self._orgs.items():
            for f in org.get("founders", []):
                f_inn = f.get("inn", "")
                if f_inn and f_inn in self._orgs:
                    share = f.get("share")
                    self.G.add_edge(f_inn, inn, type="parent_child", share=share)
                    parent_edges += 1
        edge_count += parent_edges
        logger.info("parent_child: %d edges", parent_edges)
        
        logger.info("Total edges built: %d", edge_count)
        return edge_count


def build_graph_fast(inn_list: list[str]) -> nx.MultiGraph:
    """Загружает список ИНН и строит граф с индексами."""
    builder = FastGraphBuilder()
    
    # Загружаем организации
    logger.info("Loading %d organizations...", len(inn_list))
    data = batch_fetch(inn_list)
    
    for inn, org in data.items():
        builder.add_org(org)
    
    logger.info("Loaded %d organizations", len(builder._orgs))
    
    # Строим рёбра
    edge_count = builder.build_edges_fast()
    
    logger.info("Graph: %d nodes, %d edges", 
                builder.G.number_of_nodes(), builder.G.number_of_edges())
    
    return builder.G