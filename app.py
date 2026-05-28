"""
app.py — Streamlit-интерфейс для анализа сети организаций.

Запуск:
    streamlit run app.py

Новое vs старая версия:
  • Pipeline-режим: загружает inn_list.txt целиком через batch_fetch_async
  • Sigma.js (WebGL) — держит 10k–100k узлов в браузере
  • Прогресс загрузки прямо в интерфейсе
  • Экспорт в GraphML / GEXF для Gephi
  • Кэш-статистика с PostgreSQL поддержкой
"""

import asyncio
import os
import sys
import logging
import tempfile
from pathlib import Path

import streamlit as st
import networkx as nx
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from fetcher import _SYNTHETIC_DB, deduplicate_inns
from graph_builder import OrgGraphBuilder, build_graph_from_inn_list, build_ego_graph
from metrics import enrich_graph_with_metrics, top_nodes_by_pagerank, community_summary
from visualizer import export_to_html_sigma, graph_to_json
from cache import get_cache
from pipeline import pipeline_run, load_inn_list

logging.basicConfig(level=logging.WARNING)

# ─────────────────────────────────────────────────────────────
#  Конфигурация
# ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Сеть организаций РФ",
    page_icon="🕸",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  .main { background: #0d1117; }
  h1, h2, h3 { color: #58a6ff !important; }
  .stMetric label { color: #8b949e !important; }
  code { background: #161b22; }
  .stButton>button {
    background: #238636; border: none; color: white;
    border-radius: 6px; font-weight: 600;
  }
  .stButton>button:hover { background: #2ea043; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
#  Боковая панель
# ─────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚙️ Параметры")

    mode = st.radio(
        "Режим",
        ["Демо (синтетика)", "Ego-граф (ИНН)", "Список ИНН", "Файл inn_list.txt"],
        index=0,
    )

    depth = st.slider("Глубина связей", 1, 3, 2)

    show_edge_types = st.multiselect(
        "Типы рёбер",
        ["parent_child", "common_founder", "common_director", "same_industry"],
        default=["parent_child", "common_founder", "common_director", "same_industry"],
    )

    st.markdown("---")
    st.markdown("**🔑 API**")
    api_key = st.text_input("DADATA_TOKEN", value=os.getenv("DADATA_TOKEN", ""), type="password")
    if api_key:
        os.environ["DADATA_TOKEN"] = api_key
        # Обновляем токен в fetcher
        import fetcher as _f
        _f.DADATA_TOKEN = api_key
        st.success("Токен установлен ✓")

    pg_dsn = st.text_input(
        "POSTGRES_DSN (опц.)",
        value=os.getenv("POSTGRES_DSN", ""),
        placeholder="postgresql://user:pass@host/db",
        type="password",
    )
    if pg_dsn:
        os.environ["POSTGRES_DSN"] = pg_dsn

    st.markdown("---")
    st.markdown("**🗄 Кэш**")
    cache = get_cache()
    stats = cache.stats()
    col1, col2 = st.columns(2)
    col1.metric("Записей", f"{stats['total_entries']:,}")
    col2.metric("Размер", f"{stats['size_mb']} МБ")
    st.caption(f"Бэкенд: **{stats['backend']}** · TTL: {stats['ttl_days']} д.")

    if st.button("🧹 Очистить устаревшее"):
        n = cache.clear_expired()
        st.success(f"Удалено {n} записей")
        st.rerun()

    st.markdown("---")
    st.markdown("**📤 Экспорт графа**")
    export_fmt = st.selectbox("Формат", ["GraphML", "GEXF", "JSON"])

# ─────────────────────────────────────────────────────────────
#  Заголовок
# ─────────────────────────────────────────────────────────────

st.markdown("# 🕸 Карта связей организаций РФ")
st.markdown("Учредительство · Общие директора · Отраслевая принадлежность")

# ─────────────────────────────────────────────────────────────
#  Ввод и загрузка
# ─────────────────────────────────────────────────────────────

G: nx.MultiGraph | None = None

if mode == "Демо (синтетика)":
    if st.button("🚀 Загрузить демо (9 компаний)", type="primary"):
        with st.spinner("Строю граф…"):
            G = build_graph_from_inn_list(list(_SYNTHETIC_DB.keys()))
            G = enrich_graph_with_metrics(G)
            st.session_state["G"] = G
            st.session_state["G_name"] = "demo"

elif mode == "Ego-граф (ИНН)":
    inn_input = st.text_input("ИНН", value="7736050003", placeholder="7736050003 — Газпром")
    if st.button("🔍 Построить ego-граф", type="primary"):
        with st.spinner(f"Загружаю данные для ИНН {inn_input}…"):
            G = build_ego_graph(inn_input.strip(), depth=depth)
            G = enrich_graph_with_metrics(G)
            st.session_state["G"] = G
            st.session_state["G_name"] = f"ego_{inn_input.strip()}"

elif mode == "Список ИНН":
    inns_text = st.text_area(
        "ИНН (по одному на строку)",
        value="\n".join(list(_SYNTHETIC_DB.keys())),
        height=160,
    )
    if st.button("🔍 Построить граф", type="primary"):
        raw = [x.strip() for x in inns_text.splitlines() if x.strip()]
        inns = deduplicate_inns(raw)
        st.info(f"Уникальных ИНН: **{len(inns)}** (из {len(raw)} введённых)")

        progress = st.progress(0, text="Загружаю организации…")

        with st.spinner("Параллельная загрузка из DaData…"):
            from fetcher import batch_fetch_async
            orgs = asyncio.run(batch_fetch_async(inns, show_progress=False))
            progress.progress(50, text="Строю граф…")
            G = build_graph_from_inn_list(inns, orgs_dict=orgs)
            progress.progress(80, text="Вычисляю метрики…")
            G = enrich_graph_with_metrics(G)
            progress.progress(100, text="Готово!")

        st.session_state["G"] = G
        st.session_state["G_name"] = "custom"

elif mode == "Файл inn_list.txt":
    uploaded = st.file_uploader("Загрузи файл с ИНН", type=["txt", "csv"])
    use_local = st.checkbox("Использовать локальный inn_list.txt", value=True)

    inns_file: list[str] = []

    if uploaded:
        content = uploaded.read().decode("utf-8")
        raw = [x.strip() for x in content.splitlines() if x.strip()]
        inns_file = deduplicate_inns(raw)
        st.success(f"Файл загружен: **{len(inns_file)}** уникальных ИНН")
    elif use_local and Path("inn_list.txt").exists():
        inns_file = load_inn_list("inn_list.txt")
        st.info(f"inn_list.txt: **{len(inns_file)}** уникальных ИНН")

    chunk_size = st.slider("Размер чанка (запросов за раз)", 100, 1000, 500, step=100)

    if inns_file and st.button("🚀 Запустить pipeline", type="primary"):
        st.markdown(f"**Начинаю загрузку {len(inns_file):,} организаций…**")
        st.caption(
            f"Скорость: ~{6 * 60:.0f} орг/мин (DaData rate limit)  ·  "
            f"Расчётное время: ~{len(inns_file)/360:.0f} мин"
        )

        prog_bar = st.progress(0)
        status   = st.empty()

        with st.spinner("Pipeline запущен…"):
            # Запускаем pipeline
            G = pipeline_run(
                inns_file,
                output=None,
                cache_only=False,
                chunk_size=chunk_size,
            )
            prog_bar.progress(100)
            status.success("✅ Pipeline завершён!")

        if G:
            G = enrich_graph_with_metrics(G) if not nx.get_node_attributes(G, "pagerank") else G
            st.session_state["G"] = G
            st.session_state["G_name"] = "pipeline"

# Восстановить граф из session_state
if G is None and "G" in st.session_state:
    G = st.session_state["G"]

# ─────────────────────────────────────────────────────────────
#  Отображение результатов
# ─────────────────────────────────────────────────────────────

if G is not None and G.number_of_nodes() > 0:

    # Фильтрация рёбер
    G_vis = G.copy()
    remove = [
        (u, v, k) for u, v, k, d in G_vis.edges(data=True, keys=True)
        if d.get("type") not in show_edge_types
    ]
    G_vis.remove_edges_from(remove)

    # ── Метрики ──
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Организации",   f"{G_vis.number_of_nodes():,}")
    c2.metric("Связи",         f"{G_vis.number_of_edges():,}")
    c3.metric("Плотность",     f"{nx.density(G_vis):.4f}" if G_vis.number_of_nodes() > 1 else "—")
    n_comm = len(set(nx.get_node_attributes(G_vis, "community").values()))
    c4.metric("Кластеров",     n_comm)
    is_conn = nx.is_connected(G_vis) if G_vis.number_of_nodes() < 50000 else "—"
    c5.metric("Связный?",      "Да" if is_conn is True else ("Нет" if is_conn is False else "—"))

    # Предупреждение для больших графов
    if G_vis.number_of_nodes() > 50000:
        st.warning(
            f"⚠️ Граф содержит {G_vis.number_of_nodes():,} узлов. "
            "Рендеринг может занять несколько секунд. "
            "Sigma.js (WebGL) справляется до ~100k узлов."
        )

    st.markdown("---")
    col_graph, col_info = st.columns([3, 1])

    with col_graph:
        st.markdown("### 🗺 Интерактивная карта (Sigma.js / WebGL)")

        n_nodes = G_vis.number_of_nodes()
        render_limit = st.slider(
            "Макс. узлов для рендера",
            min_value=100,
            max_value=min(100000, n_nodes),
            value=min(20000, n_nodes),
            step=1000,
            help="Ограничь число узлов если браузер тормозит",
        )

        # Если узлов больше лимита — берём топ по PageRank
        G_render = G_vis
        if n_nodes > render_limit:
            st.info(f"Показаны топ-{render_limit:,} организаций по PageRank из {n_nodes:,}")
            pr = nx.get_node_attributes(G_vis, "pagerank")
            top_nodes = sorted(pr, key=pr.get, reverse=True)[:render_limit]
            G_render = G_vis.subgraph(top_nodes).copy()

        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
            tmp = f.name

        export_to_html_sigma(G_render, tmp)
        html = Path(tmp).read_text(encoding="utf-8")
        Path(tmp).unlink(missing_ok=True)

        st.components.v1.html(html, height=640, scrolling=False)

        # Скачать HTML
        st.download_button(
            "⬇️ Скачать HTML-карту",
            data=html,
            file_name=f"org_network_{st.session_state.get('G_name','graph')}.html",
            mime="text/html",
        )

        # Экспорт графа
        if st.button(f"📥 Экспорт в {export_fmt}"):
            with tempfile.NamedTemporaryFile(suffix=f".{export_fmt.lower()}", delete=False) as f:
                exp_path = f.name
            if export_fmt == "GraphML":
                nx.write_graphml(G_vis, exp_path)
            elif export_fmt == "GEXF":
                nx.write_gexf(G_vis, exp_path)
            else:
                import json
                Path(exp_path).write_text(
                    json.dumps(graph_to_json(G_vis), ensure_ascii=False), encoding="utf-8"
                )
            data = Path(exp_path).read_bytes()
            Path(exp_path).unlink(missing_ok=True)
            st.download_button(
                f"⬇️ Скачать {export_fmt}",
                data=data,
                file_name=f"org_network.{export_fmt.lower()}",
            )

    with col_info:
        st.markdown("### 🏆 Топ-10 по PageRank")
        for rank, (inn, score, label) in enumerate(top_nodes_by_pagerank(G_vis, 10), 1):
            n_data = G_vis.nodes[inn]
            deg = n_data.get("degree", 0)
            st.markdown(
                f"**{rank}.** {label}  \n"
                f"<small style='color:#8b949e'>ИНН {inn} · PR={score:.5f} · {deg} связей</small>",
                unsafe_allow_html=True,
            )

        st.markdown("### 🔵 Кластеры")
        partition = nx.get_node_attributes(G_vis, "community")
        summary = community_summary(G_vis, partition)
        for c in summary[:8]:
            with st.expander(f"Кластер #{c['community_id']} ({c['size']} орг.)"):
                for m in c["members"]:
                    st.markdown(f"• **{m['label']}** `PR={m['pagerank']:.5f}`")

    # ── Таблица организаций ──
    st.markdown("---")
    st.markdown("### 📋 Организации")
    rows = []
    for inn in G_vis.nodes():
        n_data = G_vis.nodes[inn]
        rows.append({
            "ИНН":         inn,
            "Название":    n_data.get("label", inn),
            "Отрасль":     n_data.get("industry_group", "—"),
            "ОКВЭД":       n_data.get("okved", ""),
            "Статус":      n_data.get("status", ""),
            "Сотрудников": n_data.get("employee_count"),
            "PageRank":    f"{n_data.get('pagerank', 0):.6f}",
            "Степень":     n_data.get("degree", 0),
            "Кластер":     n_data.get("community", "?"),
        })
    df = pd.DataFrame(rows).sort_values("PageRank", ascending=False)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # ── Таблица рёбер ──
    st.markdown("### 🔗 Связи")
    ICONS = {"parent_child":"🔴","common_founder":"🟠","common_director":"🟢","same_industry":"🔵"}
    edge_rows = []
    for u, v, data in G_vis.edges(data=True):
        etype = data.get("type","?")
        edge_rows.append({
            "Тип":     f"{ICONS.get(etype,'⚪')} {etype}",
            "Орг. 1":  G_vis.nodes[u].get("label", u),
            "Орг. 2":  G_vis.nodes[v].get("label", v),
            "Доля %":  data.get("share"),
            "Через":   data.get("via",""),
        })
    if edge_rows:
        st.dataframe(pd.DataFrame(edge_rows), use_container_width=True, hide_index=True)

else:
    st.info("👆 Выберите режим и нажмите «Построить граф»")

st.markdown("---")
st.markdown(
    "<small>Данные: DaData API (ЕГРЮЛ) · Граф: NetworkX · "
    "Визуализация: Sigma.js (WebGL) · Кэш: SQLite WAL / PostgreSQL</small>",
    unsafe_allow_html=True,
)
