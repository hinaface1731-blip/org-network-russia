"""
cache.py — SQLite-кэш для ответов DaData API.
Ускоряет повторные запросы и экономит лимит API.
"""

import sqlite3
import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "dadata_cache.db"
CACHE_TTL = 86400 * 30  # 30 дней


class DadataCache:
    """SQLite-кэш для ответов DaData API."""
    
    def __init__(self, db_path: Path = None, ttl: int = None):
        self.db_path = db_path or DB_PATH
        self.ttl = ttl or CACHE_TTL
        self._init_db()
    
    def _init_db(self):
        """Создаёт таблицу, если её нет."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dadata_cache (
                    inn TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_created_at 
                ON dadata_cache(created_at)
            """)
            conn.commit()
    
    def get(self, inn: str) -> Optional[dict]:
        """Получает данные из кэша, если они свежие."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT data, created_at FROM dadata_cache WHERE inn = ?",
                (inn,)
            )
            row = cursor.fetchone()
            
            if row:
                data_json, created_at = row
                age = time.time() - created_at
                
                if age < self.ttl:
                    logger.info("Cache HIT for INN=%s (age=%.0f days)", inn, age / 86400)
                    return json.loads(data_json)
                else:
                    logger.info("Cache EXPIRED for INN=%s (age=%.0f days)", inn, age / 86400)
                    self.delete(inn)
            
            logger.info("Cache MISS for INN=%s", inn)
            return None
    
    def set(self, inn: str, data: dict):
        """Сохраняет данные в кэш."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO dadata_cache (inn, data, created_at) VALUES (?, ?, ?)",
                (inn, json.dumps(data, ensure_ascii=False), time.time())
            )
            conn.commit()
        logger.info("Cached INN=%s", inn)
    
    def delete(self, inn: str):
        """Удаляет запись из кэша."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM dadata_cache WHERE inn = ?", (inn,))
            conn.commit()
    
    def clear_expired(self) -> int:
        """Удаляет все просроченные записи. Возвращает количество удалённых."""
        cutoff = time.time() - self.ttl
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM dadata_cache WHERE created_at < ?",
                (cutoff,)
            )
            conn.commit()
            deleted = cursor.rowcount
            if deleted:
                logger.info("Cleared %d expired cache entries", deleted)
            return deleted
    
    def stats(self) -> dict:
        """Возвращает статистику кэша."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM dadata_cache").fetchone()[0]
            size = conn.execute(
                "SELECT SUM(LENGTH(data)) FROM dadata_cache"
            ).fetchone()[0] or 0
            
            if total > 0:
                newest = conn.execute(
                    "SELECT MAX(created_at) FROM dadata_cache"
                ).fetchone()[0]
                oldest = conn.execute(
                    "SELECT MIN(created_at) FROM dadata_cache"
                ).fetchone()[0]
            else:
                newest = oldest = 0
            
            return {
                "total_entries": total,
                "size_bytes": size,
                "size_mb": round(size / 1024 / 1024, 2),
                "newest_entry": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(newest)) if newest else None,
                "oldest_entry": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(oldest)) if oldest else None,
                "db_path": str(self.db_path),
                "ttl_days": self.ttl // 86400,
            }


# Глобальный экземпляр кэша
_cache = DadataCache()


def get_cache() -> DadataCache:
    """Возвращает глобальный экземпляр кэша."""
    return _cache