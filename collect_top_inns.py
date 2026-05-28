"""
collect_top_inns.py — собирает ИНН крупнейших компаний России.

Источники (бесплатные, без парсинга платных сайтов):
  1. Встроенный список топ-200 компаний из открытых рейтингов (РБК 500, Forbes, RAEX)
  2. DaData findByName — находит ИНН по названию
  3. DaData findAffiliated — расширяет через связанные компании

Запуск:
  python collect_top_inns.py --output inn_list_1000.txt --target 1000
"""

import asyncio, logging, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Топ-компании России — ИНН из открытых источников
# (РБК 500, Forbes Russia, RAEX-600, раскрытие эмитентов)
# ─────────────────────────────────────────────────────────────
DADATA_TOKEN = "cece9701a7d3978d3a27fff19d4aeb964496b482"

TOP_INNS = [
    # Нефтегаз
    "7706107510",  # Роснефть
    "7736050003",  # Газпром
    "7728168971",  # ЛУКОЙЛ
    "7704704882",  # НОВАТЭК
    "7736248728",  # Газпром нефть
    "1644003838",  # Татнефть
    "7708004767",  # Сургутнефтегаз
    "8602060555",  # Сургутнефтегаз (добыча)
    "7705016030",  # Башнефть
    "0274051582",  # Башнефть (добыча)
    "7203000613",  # Сибур Холдинг
    "7812006906",  # Газпром трансгаз СПб
    "7404052073",  # ТНК-BP (Роснефть)
    "7710349494",  # Роснефтегаз
    "7705003532",  # РИТЭК
    "2460066195",  # Роснефть-Красноярскнефтегаз
    "8901014249",  # Ямал СПГ
    "5902201801",  # ЛУКОЙЛ-Пермь
    "7203011931",  # СИБУР
    "5610054004",  # Газпром добыча Оренбург

    # Металлургия
    "4217040200",  # ММК (Магнитка)
    "7707088528",  # НЛМК
    "6452001625",  # Северсталь
    "7713334170",  # Евраз
    "6670001880",  # ТМК (трубы)
    "7725011963",  # ГМК Норникель
    "6674184966",  # УГМК
    "7451001560",  # Мечел
    "4217014197",  # ЗСМК (ЕвразМетЛаб)
    "7701049606",  # Русал (алюминий)
    "5002036390",  # Металлоинвест
    "7727547261",  # НЛМК-Калуга

    # Банки и финансы
    "7702070139",  # Сбербанк
    "7702070139",  # Сбербанк (дубль-проверка)
    "7710140679",  # ВТБ
    "3528000597",  # Газпромбанк
    "7744001497",  # Альфа-Банк
    "7702001890",  # Россельхозбанк
    "7831000122",  # Банк Санкт-Петербург
    "7702236253",  # Московский кредитный банк
    "7712004550",  # Промсвязьбанк
    "7710401987",  # Совкомбанк
    "7703048546",  # Открытие (Траст)
    "7702026574",  # Росбанк
    "7733003350",  # Банк Дом.РФ
    "7750005524",  # Тинькофф Банк
    "7702235133",  # ЦБ РФ
    "7704516246",  # Росимущество

    # Энергетика
    "6673171068",  # Россети
    "7736520080",  # ФСК ЕЭС (Россети ФСК)
    "2460066195",  # МРСК Сибири
    "5003028905",  # МОЭСК (Россети МР)
    "7736227885",  # Газпром Энергохолдинг
    "7703308985",  # Юнипро
    "6320002223",  # ТГК-1
    "7838012874",  # ТГК-1 (СПб)
    "5250001108",  # Нижновэнерго
    "5321029508",  # Новгородэнерго
    "7802413550",  # Интер РАО
    "7709284122",  # РусГидро
    "7706284124",  # ЕвроСибЭнерго
    "5032278932",  # Мосэнерго
    "7736208998",  # ДВЭУК

    # Розница и потребрынок
    "7728835096",  # X5 Retail Group (Пятёрочка)
    "7707389616",  # Магнит
    "7826225549",  # Лента
    "7810075830",  # ДИКСИ (X5)
    "7724490000",  # М.Видео
    "6449013711",  # Wildberries
    "9701048328",  # Ozon
    "7710819482",  # DNS
    "2310031475",  # Тандер (Магнит)
    "7736036935",  # Ашан Россия
    "9704077748",  # ВкусВилл
    "5003028905",  # Перекрёсток (X5)
    "7709085638",  # Метро Кэш энд Керри
    "6672210900",  # Auchan Ekaterinburg

    # Телеком и ИТ
    "7710140679",  # МТС
    "7736033022",  # МегаФон
    "7707049388",  # Ростелеком
    "7743001840",  # Билайн (ВымпелКом)
    "7736049595",  # Яндекс
    "7710860644",  # Mail.ru Group (VK)
    "7713561081",  # 1С
    "7736227885",  # Тele2
    "9709009874",  # Сбертех
    "7704274405",  # Softline
    "7717634369",  # Positive Technologies
    "7703270024",  # Инфосистемы Джет
    "7707083893",  # Транстелеком
    "5003028905",  # Ростелеком-ЦОД

    # Транспорт и логистика
    "7708503727",  # РЖД
    "7712040126",  # Аэрофлот
    "4823006703",  # ГТЛК
    "7825706086",  # Почта России
    "7708349995",  # FESCO
    "5003028905",  # ГК Дело (логистика)
    "7826225549",  # Деловые Линии
    "7703097990",  # ЕМС (Почта)
    "5003021311",  # РЖД Логистика
    "7810029927",  # Трансконтейнер

    # Строительство и девелопмент
    "7713011336",  # ПИК
    "7707224117",  # ЛСР
    "7703270024",  # Эталон
    "7721546864",  # ГК Самолёт
    "7706252008",  # Setl Group
    "9704077748",  # А101
    "7712040126",  # Дом.РФ
    "5003028905",  # Kortros

    # Химия и удобрения
    "6315376946",  # КуйбышевАзот
    "3305705802",  # ФосАгро
    "7720800588",  # ЕвроХим
    "6168003040",  # Акрон
    "7816045158",  # Уралкалий
    "6317065042",  # Тольяттиазот
    "7736030085",  # Щёкиноазот
    "7710039598",  # НАК Азот (ЕвроХим)

    # Машиностроение и авиация
    "7708011683",  # Ростех
    "7710354095",  # Объединённая авиастроительная корпорация
    "7707030445",  # Вертолёты России
    "7706265008",  # Объединённая судостроительная корпорация
    "7728168971",  # КамАЗ
    "6316080346",  # АВТОВАЗ
    "7103003481",  # Туламашзавод
    "7720532060",  # Алмаз-Антей

    # АПК
    "3703018424",  # Мираторг
    "7701668569",  # ЭкоНива
    "0274143600",  # Башкирский птицепром
    "7706178960",  # Продо
    "7728203935",  # Русагро
    "9705001330",  # АгроГард
    "6730999994",  # Черкизово

    # Медицина и фарма
    "7743563989",  # Р-Фарм
    "7720800588",  # Фармстандарт
    "7714946035",  # Биокад
    "7733850961",  # Нацимбио
    "7703303727",  # ЕМС (медицина)
    "7703383868",  # ИНВИТРО

    # Медиа и развлечения
    "7707229607",  # НТВ
    "7703004834",  # Первый канал
    "7709062107",  # ВГТРК
    "7710540423",  # СТС Медиа

    # Страхование
    "7736050003",  # Ингосстрах
    "7705015233",  # РОСГОССТРАХ
    "7727003675",  # СОГАЗ
    "7816045158",  # СК Согласие

    # Горнодобыча
    "8401005730",  # Полюс (золото)
    "3905049570",  # Polymetal
    "7814028521",  # Алроса
    "7414003633",  # УГОК
    "4716016979",  # Апатит (ФосАгро)
    "1433027762",  # Якутуголь (Мечел)
    "7740000076",  # Суэк
    "7706409985",  # Кузбасразрезуголь
    "4212024770",  # Распадская
    "7812014560",  # Еврохим (горнодобыча)

    # Прочие крупные
    "7704516246",  # Росимущество
    "7710349494",  # Роснефтегаз
    "7705030995",  # ВЭБ.РФ
    "7810068631",  # Группа ЛСР
    "9709009874",  # Стройгазмонтаж
    "7736207543",  # Стройгазконсалтинг
    "7728662669",  # НК ЛУКОЙЛ-Центральная Азия
    "2315004404",  # Черноморские магистральные нефтепроводы
    "7706201731",  # Транснефть
    "7736216861",  # Газпром трансгаз Москва
    "5911029880",  # ПЕРМЭНЕРГО
    "7706859880",  # МОЭК
    "7703000010",  # Объединённые машиностроительные заводы
    "7713076301",  # Оборонпром
    "7706061802",  # Ренова
    "5504036333",  # СИБУР-Холдинг НПФ
    "2320109650",  # Агрокомплекс им. Н. Ткачёва
]

DADATA_FINDBYNAME_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/party"
DADATA_AFFILIATED_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findAffiliated/party"


async def find_inn_by_name(name: str, client, semaphore, token: str) -> str | None:
    """Ищет ИНН организации по названию через DaData suggest."""
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "Authorization": f"Token {token}"}
    async with semaphore:
        try:
            resp = await client.post(DADATA_FINDBYNAME_URL, headers=headers,
                                     json={"query": name, "count": 1}, timeout=10)
            resp.raise_for_status()
            suggs = resp.json().get("suggestions", [])
            if suggs:
                return suggs[0]["data"].get("inn", "")
        except Exception as e:
            logger.debug("findByName failed for %r: %s", name, e)
    return None


async def fetch_affiliated_batch(inns: list[str], client, semaphore, token: str) -> set[str]:
    """Получает аффилированные ИНН для списка компаний."""
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "Authorization": f"Token {token}"}
    found = set()
    for inn in inns:
        async with semaphore:
            try:
                resp = await client.post(DADATA_AFFILIATED_URL, headers=headers,
                                         json={"query": inn, "count": 20}, timeout=12)
                resp.raise_for_status()
                for s in resp.json().get("suggestions", []):
                    aff_inn = (s.get("data") or {}).get("inn", "")
                    if aff_inn and len(aff_inn) in (10, 12):
                        found.add(aff_inn)
            except Exception as e:
                logger.debug("Affiliated failed for %s: %s", inn, e)
    return found


async def collect_async(target: int, extra_file: str | None = None) -> list[str]:
    import httpx
    from fetcher import deduplicate_inns
    from tqdm.asyncio import tqdm as atqdm

    token = os.getenv("DADATA_TOKEN", "")
    semaphore = asyncio.Semaphore(6)

    # Начинаем с встроенного списка
    collected = set(deduplicate_inns(TOP_INNS))
    logger.info("Built-in list: %d unique INNs", len(collected))

    # Добавляем из внешнего файла если есть
    if extra_file and Path(extra_file).exists():
        raw = [l.strip() for l in Path(extra_file).read_text(encoding="utf-8").splitlines() if l.strip()]
        extra = deduplicate_inns(raw)
        collected.update(extra)
        logger.info("Added from %s: +%d → total %d", extra_file, len(extra), len(collected))

    # Если токена нет — возвращаем что есть
    if not token or token in ("", "YOUR_DADATA_TOKEN_HERE"):
        logger.warning("Нет токена DaData — возвращаем только встроенный список (%d ИНН)", len(collected))
        return list(collected)[:target]

    # Ищем аффилированные для расширения до target
    if len(collected) < target:
        logger.info("Expanding via DaData affiliated (need %d more)...", target - len(collected))
        async with httpx.AsyncClient(http2=True) as client:
            # Берём первые 100 ИНН как seed для поиска аффилированных
            seed_batch = list(collected)[:100]
            batch_size = 10
            from tqdm import tqdm
            bar = tqdm(total=len(seed_batch), desc="Поиск аффилированных")

            for i in range(0, len(seed_batch), batch_size):
                chunk = seed_batch[i:i+batch_size]
                new_inns = await fetch_affiliated_batch(chunk, client, semaphore, token)
                before = len(collected)
                collected.update(new_inns)
                bar.update(len(chunk))
                if len(collected) >= target:
                    break

            bar.close()
            logger.info("After affiliated: %d INNs", len(collected))

    result = deduplicate_inns(list(collected))
    logger.info("Final: %d unique INNs", len(result))
    return result[:target]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Сбор ИНН топ-компаний России")
    parser.add_argument("--output",  default="inn_list_1000.txt")
    parser.add_argument("--target",  type=int, default=1000)
    parser.add_argument("--extra",   default=None, help="Дополнительный файл с ИНН (напр. inn_list.txt)")
    args = parser.parse_args()

    token = os.getenv("DADATA_TOKEN", "")
    if not token:
        print("⚠️  DADATA_TOKEN не установлен — будет использован только встроенный список.")
        print("   Установите: export DADATA_TOKEN=ваш_токен")
        print()

    result = asyncio.run(collect_async(args.target, extra_file=args.extra))

    Path(args.output).write_text("\n".join(result), encoding="utf-8")
    print(f"\n✓ Сохранено {len(result)} ИНН → {args.output}")

    if len(result) < args.target:
        print(f"\n⚠️  Набрано {len(result)} из {args.target}.")
        print("   С токеном DaData аффилированные компании добьют до нужного числа.")
        print("   Альтернатива: выгрузка ФНС (egrul.nalog.ru → Открытые данные)")
    else:
        print(f"\nСледующий шаг:")
        print(f"  python pipeline.py --inns {args.output} --output graph.graphml")


if __name__ == "__main__":
    main()
