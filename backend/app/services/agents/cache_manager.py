"""Agent 执行结果缓存管理器 — 内存 LRU + TTL 过期。

使用 OrderedDict 实现 LRU 淘汰策略，SHA256 参数哈希作为缓存键。
线程安全：threading.Lock 保护所有读写操作。
可替换为 Redis（扩展 AbstractCacheBackend）。
"""

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Optional


class CacheEntry:
    """缓存条目 — 存储 Agent 执行结果和元数据。"""

    def __init__(self, result: dict, ttl: int = 3600):
        self.result = result
        self.created_at = time.time()
        self.ttl = ttl

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl

    @property
    def age(self) -> float:
        return time.time() - self.created_at


class CacheManager:
    """LRU + TTL 缓存管理器，线程安全。"""

    def __init__(self, ttl: int = 3600, max_entries: int = 1000):
        self._ttl = ttl
        self._max_entries = max_entries
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def _make_key(self, agent_name: str, params: dict) -> str:
        """生成缓存键：agent_name:SHA256(json(params, sort_keys))。"""
        params_str = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
        params_hash = hashlib.sha256(params_str.encode()).hexdigest()
        return f"{agent_name}:{params_hash}"

    def get(self, agent_name: str, params: dict) -> Optional[dict]:
        """获取缓存结果。命中时更新 LRU 访问顺序。"""
        key = self._make_key(agent_name, params)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.is_expired:
                del self._cache[key]
                self._misses += 1
                return None
            # 更新 LRU 顺序（最近访问的移到末尾）
            self._cache.move_to_end(key)
            self._hits += 1
            return {
                **entry.result,
                "_cached": True,
                "_cache_age": round(entry.age, 1),
            }

    def set(self, agent_name: str, params: dict, result: dict) -> None:
        """写入缓存结果。超过 max_entries 时淘汰最久未访问。"""
        key = self._make_key(agent_name, params)
        with self._lock:
            # 如果已存在则先删除（重新插入以更新 LRU 顺序）
            if key in self._cache:
                del self._cache[key]
            # 淘汰最久未访问条目
            while len(self._cache) >= self._max_entries:
                self._cache.popitem(last=False)
            self._cache[key] = CacheEntry(result, ttl=self._ttl)

    def invalidate(self, agent_name: Optional[str] = None) -> int:
        """失效缓存。
        
        Args:
            agent_name: 如指定，仅失效该 Agent 的所有缓存；如 None，失效全部缓存。
        Returns:
            失效的条目数。
        """
        count = 0
        with self._lock:
            if agent_name is None:
                count = len(self._cache)
                self._cache.clear()
            else:
                keys_to_delete = [k for k in self._cache if k.startswith(f"{agent_name}:")]
                for k in keys_to_delete:
                    del self._cache[k]
                count = len(keys_to_delete)
        return count

    def stats(self) -> dict:
        """缓存统计信息。"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = round(self._hits / total, 3) if total > 0 else 0.0
            return {
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
                "entries": len(self._cache),
                "max_entries": self._max_entries,
                "ttl_seconds": self._ttl,
            }


# 模块级单例
cache_manager = CacheManager()
