"""
graph_builder.py — построение мультиграфа связей между организациями.
Версия для бесплатного API DaData.
"""

import logging
from typing import Callable, Optional
import networkx as nx

from fetcher import search_org_by_inn, batch_fetch

logger = logging.getLogger(__name__)


def _okved2(okved: str) -> str:
    return okved.split(".")[0].zfill(2) if okved else ""


def _norm_name(name: str) -> str:
    return " ".join(name.upper().split())


class OrgGraphBuilder:
    def __init__(self, max_depth: int = 2):
        self.G: nx.MultiGraph = nx.MultiGraph()
        self._orgs: dict[str, dict] = {}
        self._max_depth = max_depth
        self._loaded_inns: set[str] = set()

    def add_org(self, org: dict) -> None:
        inn = org.get("inn", "")
        if not inn:
            return
        if inn in self._orgs:
            return
        self._orgs[inn] = org
        self._loaded_inns.add(inn)
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

        # parent_child
        o2_founder_inns = {f["inn"] for f in o2.get("founders", []) if f.get("inn")}
        o1_founder_inns = {f["inn"] for f in o1.get("founders", []) if f.get("inn")}

        if inn1 in o2_founder_inns:
            share = next((f["share"] for f in o2["founders"] if f.get("inn") == inn1), None)
            self.add_edge_type(inn1, inn2, "parent_child", share=share)

        if inn2 in o1_founder_inns:
            share = next((f["share"] for f in o1["founders"] if f.get("inn") == inn2), None)
            self.add_edge_type(inn2, inn1, "parent_child", share=share)

        # common_founder
        common_founders = o1_founder_inns & o2_founder_inns
        for cf_inn in common_founders:
            self.add_edge_type(inn1, inn2, "common_founder", via=cf_inn)
        
        # Общие учредители-физлица по ФИО
        f1_names = {_norm_name(f["name"]) for f in o1.get("founders", []) if f.get("name") and f.get("type") == "PHYSICAL"}
        f2_names = {_norm_name(f["name"]) for f in o2.get("founders", []) if f.get("name") and f.get("type") == "PHYSICAL"}
        for name in f1_names & f2_names:
            self.add_edge_type(inn1, inn2, "common_founder", via=name, physical=True)

        # common_director
        mgr1 = {_norm_name(m["name"]) for m in o1.get("managers", []) if m.get("name")}
        mgr2 = {_norm_name(m["name"]) for m in o2.get("managers", []) if m.get("name")}
        for mgr in mgr1 & mgr2:
            self.add_edge_type(inn1, inn2, "common_director", via=mgr)

        # same_industry
        ok1 = o1.get("okved", "")
        ok2 = o2.get("okved", "")
        if ok1 and ok2:
            if ok1 == ok2:
                self.add_edge_type(inn1, inn2, "same_industry", okved=ok1, weight=1.0)
            elif _okved2(ok1) == _okved2(ok2):
                self.add_edge_type(inn1, inn2, "same_industry", okved=_okved2(ok1), weight=0.5)

    def load_recursive(self, inn: str, depth: int) -> None:
        """Рекурсивно загружает организацию и её учредителей-юрлиц."""
        if depth <= 0 or inn in self._loaded_inns:
            return
        
        logger.info("Loading INN=%s (depth=%d)", inn, depth)
        org = search_org_by_inn(inn)
        if not org:
            logger.warning("Not found: %s", inn)
            return
        
        self.add_org(org)

        # Загружаем учредителей-юрлиц
        for founder in org.get("founders", []):
            founder_inn = founder.get("inn", "")
            founder_type = founder.get("type", "UNKNOWN")
            
            if founder_type == "LEGAL" and founder_inn and founder_inn != inn:
                self.load_recursive(founder_inn, depth - 1)

    def build_edges(self) -> None:
        inns = list(self._orgs.keys())
        for i in range(len(inns)):
            for j in range(i + 1, len(inns)):
                self._build_edges_for_pair(inns[i], inns[j])
        logger.info("Graph built: %d nodes, %d edges", 
                    self.G.number_of_nodes(), self.G.number_of_edges())

    def build_ego_graph(self, center_inn: str, depth: int = 2) -> nx.MultiGraph:
        self.load_recursive(center_inn, depth)
        self.build_edges()
        return self.G

    def build_full_graph(self, inn_list: list[str], founder_depth: int = 2) -> nx.MultiGraph:
        for inn in inn_list:
            self.load_recursive(inn, founder_depth)
        self.build_edges()
        return self.G


def build_graph_from_inn_list(inn_list: list[str], founder_depth: int = 2) -> nx.MultiGraph:
    builder = OrgGraphBuilder(max_depth=founder_depth)
    return builder.build_full_graph(inn_list, founder_depth=founder_depth)


def build_ego_graph(center_inn: str, depth: int = 2) -> nx.MultiGraph:
    builder = OrgGraphBuilder(max_depth=depth)
    return builder.build_ego_graph(center_inn, depth)