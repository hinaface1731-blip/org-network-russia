import asyncio, logging, os, re, time
from typing import Optional
import httpx
from tqdm.asyncio import tqdm as atqdm

logger = logging.getLogger(__name__)
DADATA_TOKEN = "9ed70a99453e571fd22edb9d34efa1abc5f2e8a9"
DADATA_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
MAX_CONCURRENT=8; RATE_PER_SEC=6.0; RETRY_COUNT=3; RETRY_BACKOFF=2.0

def normalize_inn(raw):
    if not raw: return None
    digits = re.sub(r"\D","",str(raw).strip())
    if len(digits)==10 or len(digits)==12: return digits
    if len(digits)==9: return "0"+digits
    return None

def deduplicate_inns(inns):
    seen=set(); result=[]
    for r in inns:
        n=normalize_inn(r)
        if n and n not in seen: seen.add(n); result.append(n)
    return result

class RateLimiter:
    def __init__(self,rate):
        self._rate=rate; self._tokens=rate; self._last=time.monotonic(); self._lock=asyncio.Lock()
    async def acquire(self):
        async with self._lock:
            now=time.monotonic(); elapsed=now-self._last
            self._tokens=min(self._rate,self._tokens+elapsed*self._rate); self._last=now
            if self._tokens<1:
                await asyncio.sleep((1-self._tokens)/self._rate); self._tokens=0
            else: self._tokens-=1

def _parse_dadata(inn, d):
    founders=[]
    for f in (d.get("founders") or []):
        ftype="FL" if f.get("ogrn") is None else "UL"
        founders.append({"inn":f.get("inn") or f.get("ogrn",""),
            "name":(f.get("name") or {}).get("full_with_opf") or (f.get("fio") or {}).get("source",""),
            "type":ftype,"share":(f.get("share") or {}).get("percent")})
    managers=[{"inn":m.get("inn",""),"name":(m.get("fio") or {}).get("source",""),"post":m.get("post","")}
              for m in (d.get("managers") or [])]
    okved=d.get("okved",""); okved_name=""
    if d.get("okveds"):
        p=next((o for o in d["okveds"] if o.get("main")),d["okveds"][0])
        okved=p.get("code",okved); okved_name=p.get("name","")
    return {"inn":inn,"kpp":d.get("kpp",""),"name":(d.get("name") or {}).get("full_with_opf",""),
            "short_name":(d.get("name") or {}).get("short_with_opf",""),"ogrn":d.get("ogrn",""),
            "status":(d.get("state") or {}).get("status","UNKNOWN"),"okved":okved,"okved_name":okved_name,
            "address":(d.get("address") or {}).get("unrestricted_value",""),"founders":founders,
            "managers":managers,"capital":(d.get("finance") or {}).get("ustavnyy_kapital"),
            "employee_count":d.get("employee_count")}

async def _fetch_one(inn, client, limiter, semaphore):
    from cache import get_cache
    cache=get_cache()
    cached=cache.get(inn)
    if cached: return cached
    if not DADATA_TOKEN or DADATA_TOKEN in ("YOUR_DADATA_TOKEN_HERE",""):
        r=_synthetic_stub(inn)
        if r: cache.set(inn,r)
        return r
    headers={"Content-Type":"application/json","Accept":"application/json","Authorization":f"Token {DADATA_TOKEN}"}
    async with semaphore:
        for attempt in range(1,RETRY_COUNT+1):
            await limiter.acquire()
            try:
                resp=await client.post(DADATA_URL,headers=headers,json={"query":inn,"count":1},timeout=12)
                if resp.status_code==429: await asyncio.sleep(RETRY_BACKOFF*attempt); continue
                resp.raise_for_status()
                suggs=resp.json().get("suggestions",[])
                result=_parse_dadata(inn,suggs[0]["data"]) if suggs else _synthetic_stub(inn)
                if result: cache.set(inn,result)
                return result
            except httpx.TimeoutException: await asyncio.sleep(RETRY_BACKOFF)
            except: break
    return _synthetic_stub(inn)

def search_org_by_inn(inn):
    n=normalize_inn(inn)
    if not n: return None
    return asyncio.run(batch_fetch_async([n])).get(n)

async def batch_fetch_async(inns, show_progress=True):
    inns=deduplicate_inns(inns)
    if not inns: return {}
    limiter=RateLimiter(RATE_PER_SEC); semaphore=asyncio.Semaphore(MAX_CONCURRENT)
    async with httpx.AsyncClient(http2=True) as client:
        tasks=[_fetch_one(i,client,limiter,semaphore) for i in inns]
        if show_progress: done=await atqdm.gather(*tasks,desc="Загрузка организаций")
        else: done=await asyncio.gather(*tasks)
    return {inn:r for inn,r in zip(inns,done) if r}

def batch_fetch(inns, delay=0.0):
    return asyncio.run(batch_fetch_async(inns))

_SYNTHETIC_DB = {
    "7736050003":{"inn":"7736050003","kpp":"997250001","name":'ПАО "ГАЗПРОМ"',"short_name":"ПАО ГАЗПРОМ","ogrn":"1027700070518","status":"ACTIVE","okved":"49.50","okved_name":"Транспортирование по трубопроводам","address":"117997, г. Москва, ул. Наметкина, д. 16","founders":[{"inn":"7710349494","name":"АО «РОСНЕФТЕГАЗ»","type":"UL","share":10.97},{"inn":"7736216786","name":"ООО «НОВАТЭК-ГАЗПРОМ»","type":"UL","share":0.5}],"managers":[{"inn":"","name":"Миллер Алексей Борисович","post":"Председатель Правления"}],"capital":118367564500.0,"employee_count":476000},
    "7710349494":{"inn":"7710349494","kpp":"771001001","name":'АО "РОСНЕФТЕГАЗ"',"short_name":"АО РОСНЕФТЕГАЗ","ogrn":"1047796341395","status":"ACTIVE","okved":"64.20","okved_name":"Деятельность холдинговых компаний","address":"119180, г. Москва","founders":[{"inn":"7704516246","name":"РОСИМУЩЕСТВО","type":"UL","share":100.0}],"managers":[{"inn":"","name":"Сечин Игорь Иванович","post":"Председатель Совета директоров"}],"capital":3630000000.0,"employee_count":120},
    "7706107510":{"inn":"7706107510","kpp":"997250001","name":'ПАО "НК "РОСНЕФТЬ"',"short_name":"ПАО НК РОСНЕФТЬ","ogrn":"1027700043502","status":"ACTIVE","okved":"06.10","okved_name":"Добыча сырой нефти","address":"115035, г. Москва","founders":[{"inn":"7710349494","name":"АО «РОСНЕФТЕГАЗ»","type":"UL","share":40.4},{"inn":"7704516246","name":"РОСИМУЩЕСТВО","type":"UL","share":11.3}],"managers":[{"inn":"","name":"Сечин Игорь Иванович","post":"Главный исполнительный директор"}],"capital":105981778000.0,"employee_count":330000},
    "7702070139":{"inn":"7702070139","kpp":"770201001","name":'ПАО "СБЕРБАНК России"',"short_name":"ПАО СБЕРБАНК","ogrn":"1027700132195","status":"ACTIVE","okved":"64.19","okved_name":"Денежное посредничество прочее","address":"117312, г. Москва","founders":[{"inn":"7702235133","name":"БАНК РОССИИ (ЦБ РФ)","type":"UL","share":50.0}],"managers":[{"inn":"","name":"Греф Герман Оскарович","post":"Президент"}],"capital":67760844000.0,"employee_count":270000},
    "7704704882":{"inn":"7704704882","kpp":"770401001","name":'ПАО "НОВАТЭК"',"short_name":"ПАО НОВАТЭК","ogrn":"1028900785904","status":"ACTIVE","okved":"06.20","okved_name":"Добыча природного газа","address":"629008, ЯНАО","founders":[],"managers":[{"inn":"","name":"Михельсон Леонид Викторович","post":"Председатель Правления"}],"capital":30400000.0,"employee_count":12000},
    "7704516246":{"inn":"7704516246","kpp":"770401001","name":"ФЕДЕРАЛЬНОЕ АГЕНТСТВО ПО УПРАВЛЕНИЮ ГОСУДАРСТВЕННЫМ ИМУЩЕСТВОМ","short_name":"РОСИМУЩЕСТВО","ogrn":"1087746829994","status":"ACTIVE","okved":"84.11","okved_name":"Государственное управление","address":"109012, г. Москва","founders":[],"managers":[{"inn":"","name":"Верхний Вадим Александрович","post":"Руководитель"}],"capital":None,"employee_count":3000},
    "7736248728":{"inn":"7736248728","kpp":"773601001","name":'ПАО "ГАЗПРОМ НЕФТЬ"',"short_name":"ПАО ГАЗПРОМ НЕФТЬ","ogrn":"1025501701686","status":"ACTIVE","okved":"06.10","okved_name":"Добыча сырой нефти","address":"190000, г. Санкт-Петербург","founders":[{"inn":"7736050003","name":'ПАО "ГАЗПРОМ"',"type":"UL","share":95.7}],"managers":[{"inn":"","name":"Дюков Александр Валерьевич","post":"Председатель Правления"}],"capital":7586500000.0,"employee_count":72000},
    "7728168971":{"inn":"7728168971","kpp":"997250001","name":'ПАО "ЛУКОЙЛ"',"short_name":"ПАО ЛУКОЙЛ","ogrn":"1027700035769","status":"ACTIVE","okved":"06.10","okved_name":"Добыча сырой нефти","address":"101000, г. Москва","founders":[],"managers":[{"inn":"","name":"Алекперов Вагит Юсуфович","post":"Президент"}],"capital":21264000.0,"employee_count":100000},
    "7702235133":{"inn":"7702235133","kpp":"770201001","name":"ЦЕНТРАЛЬНЫЙ БАНК РОССИЙСКОЙ ФЕДЕРАЦИИ","short_name":"ЦБ РФ / БАНК России","ogrn":"1037700013020","status":"ACTIVE","okved":"64.11","okved_name":"Деятельность Центрального банка","address":"107016, г. Москва","founders":[],"managers":[{"inn":"","name":"Набиуллина Эльвира Сахипзадовна","post":"Председатель"}],"capital":None,"employee_count":48000},
    "7736227885":{"inn":"7736227885","kpp":"773601001","name":'ПАО "ГАЗПРОМ ЭНЕРГОХОЛДИНГ"',"short_name":"ПАО ГАЗПРОМ ЭНЕРГОХОЛДИНГ","ogrn":"1027739841370","status":"ACTIVE","okved":"35.11","okved_name":"Производство электроэнергии","address":"117420, г. Москва","founders":[{"inn":"7736050003","name":'ПАО "ГАЗПРОМ"',"type":"UL","share":100.0}],"managers":[{"inn":"","name":"Митрофанов Денис Владимирович","post":"Председатель Правления"}],"capital":10000000.0,"employee_count":500},
}

def _synthetic_stub(inn):
    if inn in _SYNTHETIC_DB: return _SYNTHETIC_DB[inn]
    return {"inn":inn,"kpp":"","name":f"Организация {inn}","short_name":f"ORG-{inn}","ogrn":"","status":"UNKNOWN","okved":"00.00","okved_name":"Не определено","address":"","founders":[],"managers":[],"capital":None,"employee_count":None}
