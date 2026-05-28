"""
graph_builder.py — построение мультиграфа связей.

Изменения vs старая версия:
  • Инкрементальная сборка: add_org() → build_edges() — не хранит всё в памяти сразу
  • Батч-вариант build_edges_batch() для 10k+ узлов (чанки по окведу)
  • Нормализация ФИО директоров/учредителей перед сравнением
  • Дедупликация рёбер через множество seen-ключей
  • build_graph_from_inn_list() принимает уже загруженный dict орг (из pipeline)
"""

import logging
import unicodedata
from typing import Callable, Optional

import networkx as nx

from fetcher import search_org_by_inn, batch_fetch

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  Утилиты
# ─────────────────────────────────────────────────────────────

def _okved2(okved: str) -> str:
    """Двузначный префикс ОКВЭД: '06.10' → '06'."""
    return okved.split(".")[0].zfill(2) if okved else ""


def _norm_name(name: str) -> str:
    """
    Нормализация ФИО/названия для сравнения:
    убираем акценты, лишние пробелы, приводим к верхнему регистру.
    """
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(ascii_str.upper().split())


# ─────────────────────────────────────────────────────────────
#  Основной строитель
# ─────────────────────────────────────────────────────────────

class OrgGraphBuilder:
    """
    Строит nx.MultiGraph из словарей организаций.

    Использование:
        builder = OrgGraphBuilder()
        for org in orgs.values():
            builder.add_org(org)
        builder.build_edges()
        G = builder.G
    """

    def __init__(self, max_depth: int = 2):
        self.G: nx.MultiGraph = nx.MultiGraph()
        self._orgs:        dict[str, dict] = {}
        self._max_depth    = max_depth
        self._loaded_inns: set[str] = set()
        self._edge_seen:   set[tuple] = set()

    # ── добавление узла ──────────────────────────────────────

    def add_org(self, org: dict) -> None:
        inn = org.get("inn", "").strip()
        if not inn or inn in self._orgs:
            return
        self._orgs[inn] = org
        self._loaded_inns.add(inn)

        label = org.get("short_name") or org.get("name", inn)
        # Обрезаем слишком длинные метки для читаемости на графе
        if len(label) > 40:
            label = label[:38] + "…"

        self.G.add_node(
            inn,
            label       = label,
            name        = org.get("name", ""),
            okved       = org.get("okved", ""),
            okved_name  = org.get("okved_name", ""),
            status      = org.get("status", ""),
            employee_count = org.get("employee_count"),
            capital     = org.get("capital"),
            address     = org.get("address", ""),
        )

    # ── добавление ребра (дедупликация встроена) ─────────────

    def _add_edge(self, inn1: str, inn2: str, edge_type: str, **attrs) -> bool:
        if inn1 not in self.G or inn2 not in self.G or inn1 == inn2:
            return False

        # Ключ дедупликации: (sorted пара, тип, опционально via)
        via = attrs.get("via", "")
        key = (tuple(sorted([inn1, inn2])), edge_type, via)
        if key in self._edge_seen:
            return False
        self._edge_seen.add(key)

        self.G.add_edge(inn1, inn2, type=edge_type, **attrs)
        return True

    # ── построение рёбер для пары ────────────────────────────

    def _build_pair(self, inn1: str, inn2: str) -> None:
        o1 = self._orgs.get(inn1)
        o2 = self._orgs.get(inn2)
        if not o1 or not o2:
            return

        # Множества ИНН учредителей
        f1_inns = {f["inn"] for f in o1.get("founders", []) if f.get("inn")}
        f2_inns = {f["inn"] for f in o2.get("founders", []) if f.get("inn")}

        # parent_child: o1 — учредитель o2
        if inn1 in f2_inns:
            share = next((f.get("share") for f in o2["founders"] if f.get("inn") == inn1), None)
            self._add_edge(inn1, inn2, "parent_child", share=share)

        # parent_child: o2 — учредитель o1
        if inn2 in f1_inns:
            share = next((f.get("share") for f in o1["founders"] if f.get("inn") == inn2), None)
            self._add_edge(inn2, inn1, "parent_child", share=share)

        # common_founder (юрлица)
        for cf_inn in f1_inns & f2_inns:
            self._add_edge(inn1, inn2, "common_founder", via=cf_inn)

        # common_founder (физлица по ФИО)
        f1_names = {
            _norm_name(f["name"])
            for f in o1.get("founders", [])
            if f.get("name") and f.get("type") in ("FL", "PHYSICAL")
        }
        f2_names = {
            _norm_name(f["name"])
            for f in o2.get("founders", [])
            if f.get("name") and f.get("type") in ("FL", "PHYSICAL")
        }
        for nm in f1_names & f2_names:
            self._add_edge(inn1, inn2, "common_founder", via=nm, physical=True)

        # common_director (по нормализованному ФИО)
        mgr1 = {_norm_name(m["name"]) for m in o1.get("managers", []) if m.get("name")}
        mgr2 = {_norm_name(m["name"]) for m in o2.get("managers", []) if m.get("name")}
        for mgr in mgr1 & mgr2:
            self._add_edge(inn1, inn2, "common_director", via=mgr)

        # same_industry
        ok1, ok2 = o1.get("okved", ""), o2.get("okved", "")
        if ok1 and ok2:
            if ok1 == ok2:
                self._add_edge(inn1, inn2, "same_industry", okved=ok1, weight=1.0)
            elif _okved2(ok1) == _okved2(ok2):
                self._add_edge(inn1, inn2, "same_industry", okved=_okved2(ok1), weight=0.5)

    # ── полный перебор O(n²) — для небольших графов ──────────

    def build_edges(self) -> None:
        inns = list(self._orgs.keys())
        n = len(inns)
        logger.info("Building edges for %d nodes (O(n²) = %d pairs)…", n, n*(n-1)//2)
        for i in range(n):
            for j in range(i + 1, n):
                self._build_pair(inns[i], inns[j])
        logger.info(
            "Edges built: %d nodes, %d edges",
            self.G.number_of_nodes(), self.G.number_of_edges()
        )

    # ── оптимизированный вариант для 5k+ узлов ───────────────

    def build_edges_smart(self) -> None:
        """
        Для больших графов (5k+ узлов) строит рёбра умнее:
          • parent_child и common_founder: через индекс учредителей O(n)
          • common_director: через индекс директоров O(n)
          • same_industry: только внутри одного ОКВЭД-2 (избегает O(n²) по всей сети)
        """
        inns = list(self._orgs.keys())
        n = len(inns)
        logger.info("Smart edge build for %d nodes…", n)

        # Индекс: inn_учредителя → список дочерних inn
        founder_to_children: dict[str, list[str]] = {}
        # Индекс: inn_учредителя → {inn_компании: share}
        founder_children_share: dict[str, dict[str, float]] = {}
        # Индекс: нормализованное_ФИО → список inn
        director_to_companies: dict[str, list[str]] = {}
        # Индекс: окведΩ2 → список inn
        okved2_to_companies: dict[str, list[str]] = {}

        for inn, org in self._orgs.items():
            # Учредители
            for f in org.get("founders", []):
                finn = f.get("inn", "")
                if finn:
                    founder_to_children.setdefault(finn, []).append(inn)
                    founder_children_share.setdefault(finn, {})[inn] = f.get("share")

            # Директора
            for m in org.get("managers", []):
                nm = _norm_name(m.get("name", ""))
                if nm:
                    director_to_companies.setdefault(nm, []).append(inn)

            # ОКВЭД
            ok = org.get("okved", "")
            if ok:
                okved2_to_companies.setdefault(_okved2(ok), []).append(inn)
                okved2_to_companies.setdefault(ok, []).append(inn)  # полный код тоже

        # 1. parent_child
        for finn, children in founder_to_children.items():
            if finn in self.G:  # учредитель есть в графе
                for child in children:
                    share = founder_children_share.get(finn, {}).get(child)
                    self._add_edge(finn, child, "parent_child", share=share)

        # 2. common_founder (юрлицо учреждает ≥2 компаний из нашего графа)
        for finn, children in founder_to_children.items():
            in_graph = [c for c in children if c in self.G]
            for i in range(len(in_graph)):
                for j in range(i + 1, len(in_graph)):
                    self._add_edge(in_graph[i], in_graph[j], "common_founder", via=finn)

        # 3. common_director
        for nm, companies in director_to_companies.items():
            in_graph = [c for c in companies if c in self.G]
            for i in range(len(in_graph)):
                for j in range(i + 1, len(in_graph)):
                    self._add_edge(in_graph[i], in_graph[j], "common_director", via=nm)

        # 4. same_industry (только внутри группы ОКВЭД-2, не все со всеми)
        MAX_SAME_INDUSTRY = 200   # не строим рёбра если группа слишком большая (спам)
        for ok, companies in okved2_to_companies.items():
            if len(ok) > 3:       # полный код — строим full match
                weight = 1.0
            else:                 # двузначный — partial match
                weight = 0.5
            in_graph = [c for c in companies if c in self.G]
            if len(in_graph) > MAX_SAME_INDUSTRY:
                logger.debug("Skipping same_industry for ОКВЭД %s: %d companies (too many)", ok, len(in_graph))
                continue
            for i in range(len(in_graph)):
                for j in range(i + 1, len(in_graph)):
                    self._add_edge(in_graph[i], in_graph[j], "same_industry",
                                   okved=ok, weight=weight)

        logger.info(
            "Smart edges done: %d nodes, %d edges",
            self.G.number_of_nodes(), self.G.number_of_edges()
        )

    # ── рекурсивная загрузка (ego-граф) ──────────────────────

    def load_recursive(self, inn: str, depth: int) -> None:
        if depth <= 0 or inn in self._loaded_inns:
            return
        org = search_org_by_inn(inn)
        if not org:
            logger.warning("Not found: %s", inn)
            return
        self.add_org(org)
        for founder in org.get("founders", []):
            finn = founder.get("inn", "")
            ftype = founder.get("type", "")
            if ftype in ("UL", "LEGAL") and finn and finn != inn:
                self.load_recursive(finn, depth - 1)

    def build_ego_graph(self, center_inn: str, depth: int = 2) -> nx.MultiGraph:
        self.load_recursive(center_inn, depth)
        n = self.G.number_of_nodes()
        if n > 5000:
            self.build_edges_smart()
        else:
            self.build_edges()
        return self.G

    def build_full_graph(
        self,
        inn_list: list[str],
        orgs_dict: Optional[dict[str, dict]] = None,
        founder_depth: int = 1,
    ) -> nx.MultiGraph:
        """
        Args:
            inn_list:     список ИНН
            orgs_dict:    уже загруженные данные (из pipeline.batch_fetch_async).
                          Если None — загружает сам через batch_fetch.
            founder_depth: глубина рекурсии по учредителям (0 = только входной список)
        """
        if orgs_dict is not None:
            for org in orgs_dict.values():
                self.add_org(org)
        else:
            orgs_data = batch_fetch(inn_list)
            for org in orgs_data.values():
                self.add_org(org)

        n = self.G.number_of_nodes()
        if n > 5000:
            self.build_edges_smart()
        else:
            self.build_edges()
        return self.G


# ─────────────────────────────────────────────────────────────
#  Функции-обёртки (совместимость)
# ─────────────────────────────────────────────────────────────

def build_graph_from_inn_list(
    inn_list: list[str],
    orgs_dict: Optional[dict[str, dict]] = None,
    founder_depth: int = 1,
) -> nx.MultiGraph:
    """
    Строит граф из списка ИНН.

    Args:
        inn_list:     список ИНН
        orgs_dict:    если уже загружены данные (из pipeline) — передай сюда,
                      тогда повторной загрузки не будет
        founder_depth: глубина рекурсии учредителей (рекомендуем 1 для больших списков)
    """
    builder = OrgGraphBuilder(max_depth=founder_depth)
    return builder.build_full_graph(inn_list, orgs_dict=orgs_dict, founder_depth=founder_depth)


def build_ego_graph(center_inn: str, depth: int = 2) -> nx.MultiGraph:
    builder = OrgGraphBuilder(max_depth=depth)
    return builder.build_ego_graph(center_inn, depth)
