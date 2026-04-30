"""
app.py — Streamlit-интерфейс для интерактивного анализа сети организаций.

Запуск:
    streamlit run app.py
"""

import os
import sys
import logging
import tempfile
from pathlib import Path

import streamlit as st
import networkx as nx
import pandas as pd

# Добавляем текущую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from fetcher import search_org_by_inn, _SYNTHETIC_DB
from graph_builder import OrgGraphBuilder, build_graph_from_inn_list
from metrics import enrich_graph_with_metrics, top_nodes_by_pagerank, community_summary
from visualizer import export_to_html_d3

logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Конфигурация страницы
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Сеть организаций РФ",
    page_icon="🕸",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
  .main { background: #0d1117; }
  h1 { color: #58a6ff !important; font-family: monospace; }
  .metric-card {
    background: #161b22; border: 1px solid #30363d;
    border-radius: 8px; padding: 12px 16px; margin: 4px 0;
  }
  .edge-badge {
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 11px; font-weight: bold; margin: 2px;
  }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Боковая панель — настройки
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## ⚙️ Параметры")

    mode = st.radio(
        "Режим построения графа",
        ["Ego-граф (по ИНН)", "Список ИНН", "Демо (синтетика)"],
        index=2,
    )

    depth = st.slider("Глубина связей", 1, 3, 2)

    show_edge_types = st.multiselect(
        "Типы рёбер",
        ["parent_child", "common_founder", "common_director", "same_industry"],
        default=["parent_child", "common_founder", "common_director", "same_industry"],
    )

    st.markdown("---")
    st.markdown("**Фильтр по отраслям**")
    
    # Получаем список отраслей из графа (если он загружен)
    available_industries = []
    if "G" in st.session_state:
        industries = set(nx.get_node_attributes(st.session_state["G"], "industry_group").values())
        available_industries = sorted(industries)
    
    selected_industries = st.multiselect(
        "Отрасли",
        available_industries,
        default=available_industries if available_industries else [],
    )

    st.markdown("---")
    st.markdown("**API-ключ DaData**")
    api_key = st.text_input(
        "DADATA_TOKEN", value=os.getenv("DADATA_TOKEN", ""), type="password"
    )
    if api_key:
        os.environ["DADATA_TOKEN"] = api_key
        st.success("Токен установлен")

    st.markdown("---")
    st.markdown("""
**Синтетическая база:** 9 организаций:
- ПАО Газпром
- АО Роснефтегаз  
- ПАО НК Роснефть
- ПАО Сбербанк
- ПАО Новатэк
- Росимущество
- ПАО Газпром Нефть
- ПАО ЛУКОЙЛ
- ЦБ РФ
""")

# ---------------------------------------------------------------------------
# Основная панель
# ---------------------------------------------------------------------------

st.markdown("# 🕸 Карта связей организаций РФ")
st.markdown(
    "Анализ структурных связей: учредительство, общие директора, отраслевая принадлежность."
)

# ---------------------------------------------------------------------------
# Ввод данных
# ---------------------------------------------------------------------------

G: nx.MultiGraph | None = None

if mode == "Ego-граф (по ИНН)":
    inn_input = st.text_input(
        "ИНН организации",
        value="7736050003",
        placeholder="например, 7736050003 (Газпром)",
    )
    if st.button("🔍 Построить граф", type="primary"):
        with st.spinner("Загружаю данные…"):
            builder = OrgGraphBuilder()
            G = builder.build_ego_graph(inn_input.strip(), depth=depth)
            G = enrich_graph_with_metrics(G)
            st.session_state["G"] = G

elif mode == "Список ИНН":
    inns_text = st.text_area(
        "ИНН (по одному на строку)",
        value="\n".join(list(_SYNTHETIC_DB.keys())),
        height=200,
    )
    if st.button("🔍 Построить граф", type="primary"):
        inns = [x.strip() for x in inns_text.splitlines() if x.strip()]
        with st.spinner(f"Загружаю {len(inns)} организаций…"):
            G = build_graph_from_inn_list(inns)
            G = enrich_graph_with_metrics(G)
            st.session_state["G"] = G

else:  # Демо
    if st.button("🚀 Загрузить демо-данные", type="primary"):
        with st.spinner("Строю демо-граф…"):
            G = build_graph_from_inn_list(list(_SYNTHETIC_DB.keys()))
            G = enrich_graph_with_metrics(G)
            st.session_state["G"] = G

# Восстановить граф из session_state
if G is None and "G" in st.session_state:
    G = st.session_state["G"]

# ---------------------------------------------------------------------------
# Отображение результатов
# ---------------------------------------------------------------------------

if G is not None and G.number_of_nodes() > 0:

    # Фильтрация рёбер по типу
    filtered_edges = [
        (u, v, d) for u, v, d in G.edges(data=True)
        if d.get("type") in show_edge_types
    ]
    G_filtered = G.copy()
    edges_to_remove = [
        (u, v, k) for u, v, k, d in G.edges(data=True, keys=True)
        if d.get("type") not in show_edge_types
    ]
    G_filtered.remove_edges_from(edges_to_remove)

    # --- Метрики ---
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Узлы (организации)", G_filtered.number_of_nodes())
    col2.metric("Рёбра (связи)", G_filtered.number_of_edges())
    col3.metric(
        "Плотность",
        f"{nx.density(G_filtered):.3f}" if G_filtered.number_of_nodes() > 1 else "—",
    )
    n_comm = len(set(nx.get_node_attributes(G_filtered, "community").values()))
    col4.metric("Кластеров", n_comm)

    st.markdown("---")

    # --- Две колонки: граф + таблицы ---
    col_graph, col_stats = st.columns([3, 1])

    with col_graph:
        st.markdown("### 🗺 Интерактивная карта")

        # Генерируем HTML
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
            tmp_path = f.name

        export_to_html_d3(G_filtered, tmp_path)
        html_content = Path(tmp_path).read_text(encoding="utf-8")
        os.unlink(tmp_path)

        st.components.v1.html(html_content, height=600, scrolling=False)

        # Кнопка скачать
        st.download_button(
            "⬇️ Скачать HTML-карту",
            data=html_content,
            file_name="org_network.html",
            mime="text/html",
        )

    with col_stats:
        st.markdown("### 🏆 Топ по PageRank")
        top = top_nodes_by_pagerank(G_filtered, n=7)
        for rank, (inn, score, label) in enumerate(top, 1):
            st.markdown(
                f"**{rank}.** {label}  \n"
                f"<small>ИНН {inn} · PR={score:.4f}</small>",
                unsafe_allow_html=True,
            )

        st.markdown("### 🔵 Кластеры")
        partition = nx.get_node_attributes(G_filtered, "community")
        summary = community_summary(G_filtered, partition)
        for c in summary[:6]:
            with st.expander(
                f"Кластер {c['community_id']} ({c['size']} орг.)"
            ):
                for m in c["members"]:
                    st.markdown(f"• {m['label']}")

    # --- Таблица организаций ---
    st.markdown("---")
    st.markdown("### 📋 Данные организаций")

    rows = []
    for inn in G_filtered.nodes():
        n = G_filtered.nodes[inn]
        rows.append({
            "ИНН": inn,
            "Название": n.get("label", inn),
            "ОКВЭД": n.get("okved", ""),
            "Отрасль": n.get("okved_name", ""),
            "Статус": n.get("status", ""),
            "Сотрудники": n.get("employee_count"),
            "PageRank": f"{n.get('pagerank', 0):.5f}",
            "Степень": n.get("degree", 0),
            "Кластер": n.get("community", "?"),
        })

    df = pd.DataFrame(rows).sort_values("PageRank", ascending=False)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # --- Список рёбер ---
    st.markdown("### 🔗 Связи")
    edge_rows = []
    edge_color_map = {
        "parent_child": "🔴",
        "common_founder": "🟠",
        "common_director": "🟢",
        "same_industry": "🔵",
    }
    for u, v, data in G_filtered.edges(data=True):
        etype = data.get("type", "?")
        edge_rows.append({
            "Тип": f"{edge_color_map.get(etype, '⚪')} {etype}",
            "Орг. 1": G_filtered.nodes[u].get("label", u),
            "Орг. 2": G_filtered.nodes[v].get("label", v),
            "Доп. инфо": data.get("via", data.get("okved", "")),
        })

    if edge_rows:
        st.dataframe(pd.DataFrame(edge_rows), use_container_width=True, hide_index=True)

    # Фильтрация по отраслям
    if selected_industries:
        nodes_to_remove = [
            inn for inn in G.nodes()
            if G.nodes[inn].get("industry_group", "Прочее") not in selected_industries
        ]
        G.remove_nodes_from(nodes_to_remove)

else:
    st.info("👆 Выберите режим и нажмите «Построить граф»")

# ---------------------------------------------------------------------------
# Футер
# ---------------------------------------------------------------------------

st.markdown("---")
st.markdown(
    "<small>Данные: DaData API (ЕГРЮЛ) · Граф: NetworkX · "
    "Визуализация: D3.js · "
    "[Зарегистрировать API-ключ DaData](https://dadata.ru/)</small>",
    unsafe_allow_html=True,
)
