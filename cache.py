import json, logging, os, queue, sqlite3, threading, time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
CACHE_TTL = int(os.getenv("CACHE_TTL_DAYS","30")) * 86400
POSTGRES_DSN = os.getenv("POSTGRES_DSN","")
DB_PATH = Path(os.getenv("CACHE_DB_PATH", str(Path(__file__).parent / "dadata_cache.db")))
_POOL_SIZE = int(os.getenv("CACHE_POOL_SIZE","8"))

class _SQLitePool:
    def __init__(self, path, size=8):
        self._path = str(path)
        self._pool = queue.Queue(maxsize=size)
        for _ in range(size):
            self._pool.put(self._make())
    def _make(self):
        c = sqlite3.connect(self._path, check_same_thread=False, timeout=30)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA cache_size=-32768")
        c.execute("PRAGMA temp_store=MEMORY")
        c.row_factory = sqlite3.Row
        return c
    @contextmanager
    def get(self):
        c = self._pool.get(timeout=10)
        try: yield c
        except:
            try: c.close()
            except: pass
            c = self._make()
            raise
        finally: self._pool.put(c)

class SQLiteCache:
    def __init__(self, db_path=DB_PATH, ttl=CACHE_TTL):
        self.db_path = db_path; self.ttl = ttl
        self._init(); self._pool = _SQLitePool(db_path, _POOL_SIZE)
    def _init(self):
        c = sqlite3.connect(str(self.db_path))
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE IF NOT EXISTS dadata_cache(inn TEXT PRIMARY KEY, data TEXT NOT NULL, created_at REAL NOT NULL)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ca ON dadata_cache(created_at)")
        c.commit(); c.close()
    def get(self, inn):
        with self._pool.get() as c:
            row = c.execute("SELECT data,created_at FROM dadata_cache WHERE inn=?",(inn,)).fetchone()
        if not row: return None
        if time.time()-row["created_at"] >= self.ttl: self.delete(inn); return None
        return json.loads(row["data"])
    def set(self, inn, data):
        with self._pool.get() as c:
            c.execute("INSERT OR REPLACE INTO dadata_cache(inn,data,created_at)VALUES(?,?,?)",(inn,json.dumps(data,ensure_ascii=False),time.time()))
            c.commit()
    def mget(self, inns):
        if not inns: return {}
        ph = ",".join("?"*len(inns)); now = time.time()
        with self._pool.get() as c:
            rows = c.execute(f"SELECT inn,data,created_at FROM dadata_cache WHERE inn IN({ph})",inns).fetchall()
        result = {i:None for i in inns}; expired=[]
        for r in rows:
            if now-r["created_at"]<self.ttl: result[r["inn"]]=json.loads(r["data"])
            else: expired.append(r["inn"])
        if expired: self.mdelete(expired)
        return result
    def mset(self, records):
        if not records: return
        now=time.time(); rows=[(i,json.dumps(d,ensure_ascii=False),now) for i,d in records.items()]
        with self._pool.get() as c:
            c.executemany("INSERT OR REPLACE INTO dadata_cache(inn,data,created_at)VALUES(?,?,?)",rows); c.commit()
    def delete(self, inn):
        with self._pool.get() as c: c.execute("DELETE FROM dadata_cache WHERE inn=?",(inn,)); c.commit()
    def mdelete(self, inns):
        if not inns: return
        ph=",".join("?"*len(inns))
        with self._pool.get() as c: c.execute(f"DELETE FROM dadata_cache WHERE inn IN({ph})",inns); c.commit()
    def clear_expired(self):
        with self._pool.get() as c:
            cur=c.execute("DELETE FROM dadata_cache WHERE created_at<?",(time.time()-self.ttl,)); c.commit(); return cur.rowcount
    def stats(self):
        with self._pool.get() as c:
            total=c.execute("SELECT COUNT(*) FROM dadata_cache").fetchone()[0]
            size=c.execute("SELECT COALESCE(SUM(LENGTH(data)),0) FROM dadata_cache").fetchone()[0]
            row=c.execute("SELECT MIN(created_at),MAX(created_at) FROM dadata_cache").fetchone()
        return {"backend":"sqlite","total_entries":total,"size_bytes":size,"size_mb":round(size/1048576,2),
                "oldest_entry":time.strftime("%Y-%m-%d",time.localtime(row[0])) if row[0] else None,
                "newest_entry":time.strftime("%Y-%m-%d",time.localtime(row[1])) if row[1] else None,
                "db_path":str(self.db_path),"ttl_days":self.ttl//86400,"pool_size":_POOL_SIZE}

_cache_instance=None; _lock=threading.Lock()
def get_cache():
    global _cache_instance
    if _cache_instance: return _cache_instance
    with _lock:
        if _cache_instance: return _cache_instance
        _cache_instance = SQLiteCache()
    return _cache_instance
