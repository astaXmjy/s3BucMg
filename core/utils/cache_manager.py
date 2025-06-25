# core/utils/cache_manager.py
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class CacheManager:
    def __init__(self, ttl_seconds: int = 300):
        self.cache: Dict[str, Dict] = {}
        self.ttl_seconds = ttl_seconds

    async def get(self, key: str) -> Optional[Any]:
        try:
            if key in self.cache:
                cache_item = self.cache[key]
                if not self._is_expired(cache_item['timestamp']):
                    return cache_item['data']
                else:
                    del self.cache[key]
            return None
        except Exception as e:
            logger.error(f"Cache get error: {str(e)}")
            return None

    async def set(self, key: str, value: Any) -> None:
        try:
            self.cache[key] = {
                'data': value,
                'timestamp': datetime.now()
            }
        except Exception as e:
            logger.error(f"Cache set error: {str(e)}")

    async def delete(self, key: str) -> None:
        try:
            self.cache.pop(key, None)
        except Exception as e:
            logger.error(f"Cache delete error: {str(e)}")

    async def clear(self) -> None:
        try:
            self.cache.clear()
        except Exception as e:
            logger.error(f"Cache clear error: {str(e)}")

    def _is_expired(self, timestamp: datetime) -> bool:
        return (datetime.now() - timestamp).total_seconds() > self.ttl_seconds