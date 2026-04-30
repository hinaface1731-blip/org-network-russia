"""
graph_builder.py — построение мультиграфа связей между организациями.
Расширенная версия: аффилированные связи, рекурсивный обход учредителей.
"""

import logging
from collections import defaultdict
from typing import Callable, Optional
import networkx as nx

from fetcher import search_org_by_inn, batch_fetch, find_affiliated_companies

logger = logging.getLogger(__name__)


def _okved2(okved: str) -> str:
    return okved.split(".")[0].zfill(2) if okved else ""


def _norm_name(name: str) -> str:
    return " ".join(name.upper().split())


class OrgGraphBuilder:
    """
    Строит граф NetworkX из данных об организациях.
    Граф — MultiGraph: между двумя узлами может быть несколько рёбер.
    """

    def __init__(self, use_affiliated: bool = True, max_depth: int = 2):
        self.G: nx.MultiGraph = nx.MultiGraph()
        self._orgs: dict[str, dict] = {}
        self._use_affiliated = use_affiliated
        self._max_depth = max_depth
        self._visited_affiliated: set[str] = set()

    def add_org(self, org: dict) -> None:
        inn = org["inn"]
        if not inn:
            return
        self._orgs[inn] = org
        self.G.add_node(
            inn,
            label=org.get("short_name") or org.get("name", inn),
            name=org.get("name", ""),
            okved=org.get("okved", ""),
            okved_name=org.get("okved_name", ""),
            status=org.get("status", ""),
            employee_count=org.get("employee_count"),
            capital=org.get("capital"),
            revenue=None,  # Будет заполнено позже
        )

    def add_edge_type(self, inn1: str, inn2: str, edge_type: str, **attrs) -> None:
        if inn1 not in self.G or inn2 not in self.G:
            return
        if inn1 == inn2:
            return
        self.G.add_edge(inn1, inn2, type=edge_type, **attrs)

    def _build_edges_for_pair(self, inn1: str, inn2: str) -> None:
        o1 = self._orgs.get(inn1)
        o2 = self._orgs.get(inn2)
        if not o1 or not o2:
            return

        # --- parent_child ---
        o2_founder_inns = {f["inn"] for f in o2.get("founders", []) if f["inn"]}
        o1_founder_inns = {f["inn"] for f in o1.get("founders", []) if f["inn"]}

        if inn1 in o2_founder_inns:
            share = next((f["share"] for f in o2["founders"] if f["inn"] == inn1), None)
            control = "majority" if (share and share > 50) else "minority"
            self.add_edge_type(inn1, inn2, "parent_child", share=share, control=control)

        if inn2 in o1_founder_inns:
            share = next((f["share"] for f in o1["founders"] if f["inn"] == inn2), None)
            control = "majority" if (share and share > 50) else "minority"
            self.add_edge_type(inn2, inn1, "parent_child", share=share, control=control)

        # --- common_founder ---
        common_founders = o1_founder_inns & o2_founder_inns
        for cf_inn in common_founders:
            self.add_edge_type(inn1, inn2, "common_founder", via=cf_inn)

        # --- common_director ---
        mgr1 = {_norm_name(m["name"]) for m in o1.get("managers", []) if m["name"]}
        mgr2 = {_norm_name(m["name"]) for m in o2.get("managers", []) if m["name"]}
        for mgr in mgr1 & mgr2:
            self.add_edge_type(inn1, inn2, "common_director", via=mgr)

        # --- same_industry (взвешенная) ---
        ok1 = o1.get("okved", "")
        ok2 = o2.get("okved", "")
        if ok1 and ok2:
            if ok1 == ok2:
                self.add_edge_type(inn1, inn2, "same_industry", okved=ok1, weight=1.0)
            elif _okved2(ok1) == _okved2(ok2):
                self.add_edge_type(inn1, inn2, "same_industry", okved=_okved2(ok1), weight=0.5)

    def _load_affiliated(self, inn: str, depth: int = 1) -> None:
        """Рекурсивно загружает аффилированные компании."""
        if depth <= 0 or inn in self._visited_affiliated:
            return
        self._visited_affiliated.add(inn)

        affiliated = find_affiliated_companies(inn)
        for aff in affiliated:
            aff_inn = aff.get("inn", "")
            if aff_inn and aff_inn not in self._orgs:
                self.add_org(aff)
                # Аффилированная связь — особый тип ребра
                self.add_edge_type(inn, aff_inn, "affiliated", 
                                   via="общие учредители/руководители")
                # Рекурсивно углубляемся
                if depth > 1:
                    self._load_affiliated(aff_inn, depth - 1)

    def _load_founders_recursive(self, inn: str, depth: int) -> None:
        """Рекурсивно загружает учредителей-юрлица."""
        if depth <= 0:
            return
        
        org = self._orgs.get(inn)
        if not org:
            return

        for f in org.get("founders", []):
            if f.get("type") == "UL" and f["inn"] and f["inn"] not in self._orgs:
                founder_data = search_org_by_inn(f["inn"])
                if founder_data:
                    self.add_org(founder_data)
                    self._load_founders_recursive(f["inn"], depth - 1)

    def build_edges(self) -> None:
        """Строит рёбра между всеми загруженными организациями."""
        inns = list(self._orgs.keys())
        for i in range(len(inns)):
            for j in range(i + 1, len(inns)):
                self._build_edges_for_pair(inns[i], inns[j])
        logger.info("Graph built: %d nodes, %d edges", 
                    self.G.number_of_nodes(), self.G.number_of_edges())

    def build_full_graph(self, inn_list: list[str], 
                         load_affiliated: bool = True,
                         founder_depth: int = 2) -> nx.MultiGraph:
        """
        Строит полный граф с аффилированными связями и рекурсивным обходом учредителей.
        """
        # Загружаем основные компании
        data = batch_fetch(inn_list)
        for org in data.values():
            self.add_org(org)

        if load_affiliated:
            logger.info("Loading affiliated companies...")
            for inn in inn_list:
                self._load_affiliated(inn, depth=2)

        if founder_depth > 0:
            logger.info("Loading founders recursively (depth=%d)...", founder_depth)
            current_inns = list(self._orgs.keys())
            for inn in current_inns:
                self._load_founders_recursive(inn, founder_depth)

        self.build_edges()
        return self.G


# ---------------------------------------------------------------------------
# Обновлённые фабричные функции
# ---------------------------------------------------------------------------

def build_graph_from_inn_list(inn_list: list[str], 
                              use_affiliated: bool = True,
                              founder_depth: int = 2) -> nx.MultiGraph:
    """Загружает данные по списку ИНН и строит полный граф с аффилированными связями."""
    builder = OrgGraphBuilder(use_affiliated=use_affiliated, max_depth=founder_depth)
    return builder.build_full_graph(inn_list, load_affiliated=use_affiliated, 
                                   founder_depth=founder_depth)


def build_ego_graph(center_inn: str, depth: int = 2) -> nx.MultiGraph:
    """Удобная обёртка для построения ego-графа."""
    builder = OrgGraphBuilder()
    return builder.build_ego_graph(center_inn, depth)