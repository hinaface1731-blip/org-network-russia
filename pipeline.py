"""
pipeline.py — оркестратор массовой загрузки организаций.

Использование из командной строки:
  # Прямой режим (до ~50k ИНН)
  python pipeline.py --inns inn_list.txt --output graph.graphml

  # Только загрузить в кэш
  python pipeline.py --inns inn_list.txt --cache-only

  # Очередь RQ (50k+ ИНН, нужен Redis)
  python pipeline.py --inns inn_list.txt --rq --redis-url redis://localhost:6379/0
"""
import argparse, asyncio, logging, time
from pathlib import Path
import networkx as nx
from tqdm import tqdm

logger = logging.getLogger(__name__)

def load_inn_list(path):
    from fetcher import deduplicate_inns
    raw = [l.strip() for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    return deduplicate_inns(raw)

async def _fetch_all(inns, chunk_size=500):
    from fetcher import batch_fetch_async
    from cache import get_cache
    cache = get_cache()
    results = {}
    cached = cache.mget(inns)
    to_fetch = [i for i,v in cached.items() if v is None]
    results.update({i:v for i,v in cached.items() if v is not None})
    logger.info("Cache: %d hits, %d misses", len(results), len(to_fetch))
    if not to_fetch: return results
    bar = tqdm(total=len(to_fetch), desc="Загрузка из DaData", unit="орг")
    for i in range(0, len(to_fetch), chunk_size):
        chunk = to_fetch[i:i+chunk_size]
        r = await batch_fetch_async(chunk, show_progress=False)
        results.update(r); cache.mset(r); bar.update(len(chunk))
    bar.close()
    return results

def pipeline_run(inns, output=None, cache_only=False, chunk_size=500):
    from fetcher import deduplicate_inns
    from graph_builder import build_graph_from_inn_list
    from metrics import enrich_graph_with_metrics
    from visualizer import graph_to_json
    inns = deduplicate_inns(inns)
    logger.info("Pipeline: %d INNs", len(inns))
    t0 = time.time()
    orgs = asyncio.run(_fetch_all(inns, chunk_size=chunk_size))
    logger.info("Fetched %d orgs in %.1fs", len(orgs), time.time()-t0)
    if cache_only: return None
    G = build_graph_from_inn_list(list(orgs.keys()), orgs_dict=orgs)
    G = enrich_graph_with_metrics(G)
    if output:
        p = Path(output)
        if p.suffix == ".graphml": nx.write_graphml(G, str(p))
        elif p.suffix == ".gexf":  nx.write_gexf(G, str(p))
        elif p.suffix == ".json":
            import json
            p.write_text(json.dumps(graph_to_json(G), ensure_ascii=False), encoding="utf-8")
        logger.info("Saved → %s", p)
    logger.info("Pipeline done in %.1fs: %d nodes, %d edges", time.time()-t0, G.number_of_nodes(), G.number_of_edges())
    return G

def _cli():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description="Массовая загрузка организаций")
    p.add_argument("--inns", required=True)
    p.add_argument("--output", default=None)
    p.add_argument("--cache-only", action="store_true")
    p.add_argument("--chunk-size", type=int, default=500)
    p.add_argument("--rq", action="store_true")
    p.add_argument("--redis-url", default="redis://localhost:6379/0")
    args = p.parse_args()
    inns = load_inn_list(args.inns)
    print(f"Загружено {len(inns)} уникальных ИНН из {args.inns}")
    G = pipeline_run(inns, output=args.output, cache_only=args.cache_only, chunk_size=args.chunk_size)
    if G: print(f"Граф: {G.number_of_nodes()} узлов, {G.number_of_edges()} рёбер")

if __name__ == "__main__":
    _cli()
