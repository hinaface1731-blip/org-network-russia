"""
fetcher.py — загрузка данных об организациях из DaData API и резервных источников.

DaData API: https://dadata.ru/api/find-party/
Регистрация: https://dadata.ru/ → «Войти» → бесплатно 10 000 запросов/день.
"""

import os
import time
import logging
from typing import Optional
import httpx
from cache import get_cache

logger = logging.getLogger(__name__)

DADATA_TOKEN = os.getenv("DADATA_TOKEN", "")
DADATA_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Authorization": f"Token {DADATA_TOKEN}",
}


def search_org_by_inn(inn: str) -> Optional[dict]:
    """
    Запрашивает DaData по ИНН и возвращает нормализованный словарь.
    Использует SQLite-кэш для ускорения повторных запросов.
    """
    # Проверяем кэш
    cache = get_cache()
    cached = cache.get(inn)
    if cached:
        return cached

    # Проверяем синтетическую базу
    if DADATA_TOKEN in ("YOUR_DADATA_TOKEN_HERE", ""):
        logger.warning("DaData token not set — using synthetic stub for INN=%s", inn)
        result = _synthetic_stub(inn)
        if result:
            cache.set(inn, result)
        return result

    payload = {"query": inn, "count": 1}

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(DADATA_URL, headers=HEADERS, json=payload)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error("DaData HTTP error %s for INN=%s", e.response.status_code, inn)
        # Пробуем синтетику как fallback
        result = _synthetic_stub(inn)
        if result:
            cache.set(inn, result)
        return result
    except httpx.RequestError as e:
        logger.error("DaData request failed for INN=%s: %s", inn, e)
        result = _synthetic_stub(inn)
        if result:
            cache.set(inn, result)
        return result

    suggestions = resp.json().get("suggestions", [])
    if not suggestions:
        logger.warning("No suggestions from DaData for INN=%s", inn)
        result = _synthetic_stub(inn)
        if result:
            cache.set(inn, result)
        return result

    raw = suggestions[0]["data"]
    result = _parse_dadata(inn, raw)
    
    # Сохраняем в кэш
    if result:
        cache.set(inn, result)
    
    return result


def _parse_dadata(inn: str, d: dict) -> dict:
    """Извлекает нужные поля из сырого ответа DaData."""
    founders = []
    for f in (d.get("founders") or []):
        ftype = "FL" if f.get("ogrn") is None else "UL"
        founders.append({
            "inn": f.get("inn") or f.get("ogrn", ""),
            "name": f.get("name", {}).get("full_with_opf") or f.get("fio", {}).get("source", ""),
            "type": ftype,
            "share": f.get("share", {}).get("percent"),
        })

    managers = []
    for m in (d.get("managers") or []):
        managers.append({
            "inn": m.get("inn", ""),
            "name": m.get("fio", {}).get("source", ""),
            "post": m.get("post", ""),
        })

    okved_raw = d.get("okved") or ""
    okved_name = ""
    if d.get("okveds"):
        primary = next((o for o in d["okveds"] if o.get("main")), d["okveds"][0])
        okved_raw = primary.get("code", okved_raw)
        okved_name = primary.get("name", "")

    return {
        "inn": inn,
        "kpp": d.get("kpp", ""),
        "name": (d.get("name") or {}).get("full_with_opf", ""),
        "short_name": (d.get("name") or {}).get("short_with_opf", ""),
        "ogrn": d.get("ogrn", ""),
        "status": (d.get("state") or {}).get("status", "UNKNOWN"),
        "okved": okved_raw,
        "okved_name": okved_name,
        "address": (d.get("address") or {}).get("unrestricted_value", ""),
        "founders": founders,
        "managers": managers,
        "capital": (d.get("finance") or {}).get("ustavnyy_kapital"),
        "employee_count": d.get("employee_count"),
    }


# ---------------------------------------------------------------------------
# Синтетические данные — для демо без API-ключа
# ---------------------------------------------------------------------------

_SYNTHETIC_DB: dict[str, dict] = {
    "7736050003": {
        "inn": "7736050003",
        "kpp": "997250001",
        "name": 'ПАО "ГАЗПРОМ"',
        "short_name": "ПАО ГАЗПРОМ",
        "ogrn": "1027700070518",
        "status": "ACTIVE",
        "okved": "49.50",
        "okved_name": "Транспортирование по трубопроводам",
        "address": "117997, г. Москва, ул. Наметкина, д. 16",
        "founders": [
            {"inn": "7710349494", "name": "АО «РОСНЕФТЕГАЗ»", "type": "UL", "share": 10.97},
            {"inn": "7736216786", "name": "ООО «НОВАТЭК-ГАЗПРОМ»", "type": "UL", "share": 0.5},
        ],
        "managers": [
            {"inn": "", "name": "Миллер Алексей Борисович", "post": "Председатель Правления"},
        ],
        "capital": 118367564500.0,
        "employee_count": 476000,
    },
    "7710349494": {
        "inn": "7710349494",
        "kpp": "771001001",
        "name": 'АО "РОСНЕФТЕГАЗ"',
        "short_name": "АО РОСНЕФТЕГАЗ",
        "ogrn": "1047796341395",
        "status": "ACTIVE",
        "okved": "64.20",
        "okved_name": "Деятельность холдинговых компаний",
        "address": "119180, г. Москва, пер. 1-й Голутвинский, д. 6",
        "founders": [
            {"inn": "7704516246", "name": "РОСИМУЩЕСТВО", "type": "UL", "share": 100.0},
        ],
        "managers": [
            {"inn": "", "name": "Сечин Игорь Иванович", "post": "Председатель Совета директоров"},
        ],
        "capital": 3630000000.0,
        "employee_count": 120,
    },
    "7706107510": {
        "inn": "7706107510",
        "kpp": "997250001",
        "name": 'ПАО "НК "РОСНЕФТЬ"',
        "short_name": "ПАО НК РОСНЕФТЬ",
        "ogrn": "1027700043502",
        "status": "ACTIVE",
        "okved": "06.10",
        "okved_name": "Добыча сырой нефти",
        "address": "115035, г. Москва, Софийская наб., д. 26/1",
        "founders": [
            {"inn": "7710349494", "name": "АО «РОСНЕФТЕГАЗ»", "type": "UL", "share": 40.4},
            {"inn": "7704516246", "name": "РОСИМУЩЕСТВО", "type": "UL", "share": 11.3},
        ],
        "managers": [
            {"inn": "", "name": "Сечин Игорь Иванович", "post": "Главный исполнительный директор"},
        ],
        "capital": 105981778000.0,
        "employee_count": 330000,
    },
    "7702070139": {
        "inn": "7702070139",
        "kpp": "770201001",
        "name": 'ПАО "СБЕРБАНК России"',
        "short_name": "ПАО СБЕРБАНК",
        "ogrn": "1027700132195",
        "status": "ACTIVE",
        "okved": "64.19",
        "okved_name": "Денежное посредничество прочее",
        "address": "117312, г. Москва, ул. Вавилова, д. 19",
        "founders": [
            {"inn": "7702235133", "name": "БАНК РОССИИ (ЦБ РФ)", "type": "UL", "share": 50.0},
        ],
        "managers": [
            {"inn": "", "name": "Греф Герман Оскарович", "post": "Президент, Председатель Правления"},
        ],
        "capital": 67760844000.0,
        "employee_count": 270000,
    },
    "7704704882": {
        "inn": "7704704882",
        "kpp": "770401001",
        "name": 'ПАО "НОВАТЭК"',
        "short_name": "ПАО НОВАТЭК",
        "ogrn": "1028900785904",
        "status": "ACTIVE",
        "okved": "06.20",
        "okved_name": "Добыча природного газа",
        "address": "629008, ЯНАО, г. Новый Уренгой",
        "founders": [
            {"inn": "9909378434", "name": "NOVATEK EQUITY (CYPRUS) LIMITED", "type": "UL", "share": 25.5},
        ],
        "managers": [
            {"inn": "", "name": "Михельсон Леонид Викторович", "post": "Председатель Правления"},
        ],
        "capital": 30400000.0,
        "employee_count": 12000,
    },
    "7704516246": {
        "inn": "7704516246",
        "kpp": "770401001",
        "name": 'ФЕДЕРАЛЬНОЕ АГЕНТСТВО ПО УПРАВЛЕНИЮ ГОСУДАРСТВЕННЫМ ИМУЩЕСТВОМ',
        "short_name": "РОСИМУЩЕСТВО",
        "ogrn": "1087746829994",
        "status": "ACTIVE",
        "okved": "84.11",
        "okved_name": "Государственное управление общего характера",
        "address": "109012, г. Москва, Никольский пер., д. 9",
        "founders": [],
        "managers": [
            {"inn": "", "name": "Верхний Вадим Александрович", "post": "Руководитель"},
        ],
        "capital": None,
        "employee_count": 3000,
    },
    "7736248728": {
        "inn": "7736248728",
        "kpp": "773601001",
        "name": 'ПАО "ГАЗПРОМ НЕФТЬ"',
        "short_name": "ПАО ГАЗПРОМ НЕФТЬ",
        "ogrn": "1025501701686",
        "status": "ACTIVE",
        "okved": "06.10",
        "okved_name": "Добыча сырой нефти",
        "address": "190000, г. Санкт-Петербург, пл. Победы, д. 2",
        "founders": [
            {"inn": "7736050003", "name": 'ПАО "ГАЗПРОМ"', "type": "UL", "share": 95.7},
        ],
        "managers": [
            {"inn": "", "name": "Дюков Александр Валерьевич", "post": "Председатель Правления"},
        ],
        "capital": 7586500000.0,
        "employee_count": 72000,
    },
    "7728168971": {
        "inn": "7728168971",
        "kpp": "997250001",
        "name": 'ПАО "ЛУКОЙЛ"',
        "short_name": "ПАО ЛУКОЙЛ",
        "ogrn": "1027700035769",
        "status": "ACTIVE",
        "okved": "06.10",
        "okved_name": "Добыча сырой нефти",
        "address": "101000, г. Москва, Сретенский б-р, д. 11",
        "founders": [],
        "managers": [
            {"inn": "", "name": "Алекперов Вагит Юсуфович", "post": "Президент"},
        ],
        "capital": 21264000.0,
        "employee_count": 100000,
    },
    "7702235133": {
        "inn": "7702235133",
        "kpp": "770201001",
        "name": 'ЦЕНТРАЛЬНЫЙ БАНК РОССИЙСКОЙ ФЕДЕРАЦИИ',
        "short_name": "ЦБ РФ / БАНК России",
        "ogrn": "1037700013020",
        "status": "ACTIVE",
        "okved": "64.11",
        "okved_name": "Деятельность Центрального банка",
        "address": "107016, г. Москва, ул. Неглинная, д. 12",
        "founders": [],
        "managers": [
            {"inn": "", "name": "Набиуллина Эльвира Сахипзадовна", "post": "Председатель"},
        ],
        "capital": None,
        "employee_count": 48000,
    },
    "7736227885": {
        "inn": "7736227885",
        "kpp": "773601001",
        "name": 'ПАО "ГАЗПРОМ ЭНЕРГОХОЛДИНГ"',
        "short_name": "ПАО ГАЗПРОМ ЭНЕРГОХОЛДИНГ",
        "ogrn": "1027739841370",
        "status": "ACTIVE",
        "okved": "35.11",
        "okved_name": "Производство электроэнергии",
        "address": "117420, г. Москва, ул. Наметкина, д. 16",
        "founders": [
            {"inn": "7736050003", "name": 'ПАО "ГАЗПРОМ"', "type": "UL", "share": 100.0},
        ],
        "managers": [
            {"inn": "", "name": "Митрофанов Денис Владимирович", "post": "Председатель Правления"},
        ],
        "capital": 10000000.0,
        "employee_count": 500,
    },
}


def _synthetic_stub(inn: str) -> Optional[dict]:
    """Возвращает синтетические данные для демо."""
    if inn in _SYNTHETIC_DB:
        return _SYNTHETIC_DB[inn]
    # Генерируем минимальную заглушку для неизвестных ИНН
    logger.info("Generating minimal stub for unknown INN=%s", inn)
    return {
        "inn": inn,
        "kpp": "",
        "name": f"Организация ИНН {inn}",
        "short_name": f"ORG-{inn}",
        "ogrn": "",
        "status": "UNKNOWN",
        "okved": "00.00",
        "okved_name": "Не определено",
        "address": "",
        "founders": [],
        "managers": [],
        "capital": None,
        "employee_count": None,
    }

# ---------------------------------------------------------------------------
# Аффилированные компании через DaData
# ---------------------------------------------------------------------------

DADATA_AFFILIATED_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findAffiliated/party"

def find_affiliated_companies(inn: str, depth: int = 1) -> list[dict]:
    """
    Находит компании, аффилированные с данной, через общих учредителей и руководителей.
    Возвращает список словарей, как в search_org_by_inn.
    """
    if DADATA_TOKEN in ("YOUR_DADATA_TOKEN_HERE", ""):
        logger.warning("No DaData token — skipping affiliated search")
        return []

    affiliated = []
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                DADATA_AFFILIATED_URL,
                headers=HEADERS,
                json={"query": inn, "count": 50}
            )
            resp.raise_for_status()
            suggestions = resp.json().get("suggestions", [])
            
            for s in suggestions:
                data = s.get("data", {})
                aff_inn = data.get("inn", "")
                if aff_inn and aff_inn != inn:
                    affiliated.append(_parse_dadata(aff_inn, data))
                    
    except Exception as e:
        logger.error("Affiliated search failed for INN=%s: %s", inn, e)
    
    logger.info("Found %d affiliated companies for INN=%s", len(affiliated), inn)
    return affiliated

def batch_fetch(inns: list[str], delay: float = 0.3) -> dict[str, dict]:
    """
    Загружает несколько организаций. delay — пауза между запросами (сек),
    чтобы не превысить rate limit DaData (10 000/сут, ~7/сек).
    """
    result = {}
    for inn in inns:
        data = search_org_by_inn(inn)
        if data:
            result[inn] = data
        time.sleep(delay)
    return result
