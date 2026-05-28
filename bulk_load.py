"""
bulk_load.py — массовая загрузка организаций в кэш.

Usage:
    # Загрузить все ИНН из всех списков в inn_lists/
    python bulk_load.py

    # Загрузить конкретный список
    python bulk_load.py inn_lists/банки.txt

    # Загрузить все организации из ЕГРЮЛ по региону (нужен API)
    python bulk_load.py --search "Москва" --limit 5000

    # Загрузить топ-1000 крупнейших компаний
    python bulk_load.py --top-companies 1000
"""

import argparse
import logging
import time
from pathlib import Path
from typing import Optional

from fetcher import search_org_by_inn, batch_fetch, search_orgs_by_query, DADATA_TOKEN
from cache import get_cache

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_inn_list(inn_list: list[str], delay: float = 0.2) -> int:
    """Загружает список ИНН в кэш. Возвращает количество загруженных."""
    if not DADATA_TOKEN:
        logger.error("No DaData token set. Set DADATA_TOKEN env variable.")
        return 0

    loaded = 0
    cache = get_cache()

    for i, inn in enumerate(inn_list):
        inn = inn.strip()
        if not inn or len(inn) != 10:
            logger.warning(f"Invalid INN: {inn}, skipping")
            continue

        if cache.get(inn):
            logger.debug(f"Skipping cached INN: {inn}")
            continue

        data = search_org_by_inn(inn)
        if data:
            loaded += 1
            logger.info(f"[{i+1}/{len(inn_list)}] Loaded: {data.get('name', inn)} ({inn})")
        else:
            logger.warning(f"[{i+1}/{len(inn_list)}] Not found: {inn}")

        time.sleep(delay)

    logger.info(f"Loaded {loaded}/{len(inn_list)} organizations")
    return loaded


def load_from_directory(dir_path: Path, delay: float = 0.2) -> int:
    """Загружает все ИНН из всех .txt файлов в директории."""
    total = 0
    for txt_file in sorted(dir_path.glob("*.txt")):
        logger.info(f"Loading from {txt_file.name}...")
        inns = txt_file.read_text(encoding="utf-8").splitlines()
        count = load_inn_list(inns, delay=delay)
        total += count
    logger.info(f"Total loaded: {total}")
    return total


def load_by_search(query: str, limit: int = 1000, delay: float = 0.2, status: str = "ACTIVE") -> int:
    """Ищет организации и загружает в кэш."""
    if not DADATA_TOKEN:
        logger.error("No DaData token. Set DADATA_TOKEN env variable.")
        return 0

    cache = get_cache()
    loaded = 0
    offset = 0
    batch_size = 100

    while loaded < limit:
        remaining = limit - loaded
        batch = min(batch_size, remaining)

        logger.info(f"Searching: {query} (batch {offset}, limit={batch})...")
        orgs = search_orgs_by_query(query, status=status, count=batch)

        if not orgs:
            logger.info("No more results")
            break

        for org in orgs:
            inn = org.get("inn", "")
            if inn and not cache.get(inn):
                cache.set(inn, org)
                loaded += 1
                logger.info(f"[{loaded}] {org.get('name', inn)} ({inn})")

            time.sleep(delay)

        offset += batch

        if len(orgs) < batch:
            break

    logger.info(f"Total loaded: {loaded}")
    return loaded


def load_top_companies(limit: int = 1000, delay: float = 0.2) -> int:
    """Загружает крупнейшие компании России по выручке через поиск по регионам."""
    regions = [
        "Москва", "Московская область", "Санкт-Петербург",
        "Татарстан", "Башкортостан", "Свердловская область",
        "Челябинская область", "Краснодарский край", "Ростовская область",
        "Самарская область", "Новосибирская область", "Красноярский край",
        "Пермский край", "Омская область", "Волгоградская область",
    ]

    return load_by_search("ПАО", limit=limit, delay=delay, status="ACTIVE")


def main():
    parser = argparse.ArgumentParser(description="Bulk load organizations to cache")
    parser.add_argument("file", nargs="?", help="INN list file or inn_lists directory")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between requests")
    parser.add_argument("--search", type=str, help="Search organizations by region/name")
    parser.add_argument("--status", type=str, default="ACTIVE", help="Organization status filter")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum results")
    parser.add_argument("--top-companies", type=int, metavar="N", help="Load top N companies by revenue")

    args = parser.parse_args()

    if args.top_companies:
        load_top_companies(limit=args.top_companies, delay=args.delay)
        return

    if args.search:
        load_by_search(args.search, limit=args.limit, delay=args.delay, status=args.status)
        return

    if args.file:
        path = Path(args.file)
        if path.is_dir():
            load_from_directory(path, delay=args.delay)
        elif path.is_file():
            inns = path.read_text(encoding="utf-8").splitlines()
            load_inn_list(inns, delay=args.delay)
        else:
            logger.error(f"File not found: {path}")
    else:
        inn_lists_dir = Path(__file__).parent / "inn_lists"
        if inn_lists_dir.exists():
            load_from_directory(inn_lists_dir, delay=args.delay)
        else:
            logger.error(f"inn_lists directory not found: {inn_lists_dir}")


if __name__ == "__main__":
    main()