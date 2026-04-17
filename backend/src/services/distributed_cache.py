"""
Advanced Distributed Cache Optimization
Multi-layer caching with Redis cluster, local cache, and smart invalidation.
"""

import logging
import pickle
import hashlib
from typing import Dict, Any, List, Optional, Callable, Set
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
import asyncio

logger = logging.getLogger(__name__)


class CacheLevel(Enum):
    """Cache hierarchy levels."""
    L1_MEMORY = "l1_memory"      # In-process memory
    L2_LOCAL = "l2_local"        # Local disk/Redis single
    L3_DISTRIBUTED = "l3_distributed"  # Redis cluster


class CachePriority(Enum):
    """Cache priority levels."""
    LOW = "low"           # Short TTL, first to evict
    NORMAL = "normal"     # Standard TTL
    HIGH = "high"         # Longer TTL, important data
    CRITICAL = "critical"  # Longest TTL, rarely evicted


@dataclass
class CacheEntry:
    """Cache entry metadata."""
    key: str
    value: Any
    level: CacheLevel
    priority: CachePriority
    created_at: datetime
    expires_at: datetime
    access_count: int
    last_accessed: datetime
    size_bytes: int
    tags: Set[str]


@dataclass
class CacheStats:
    """Cache performance statistics."""
    hits: int
    misses: int
    evictions: int
    total_size_bytes: int
    entry_count: int
    hit_rate: float
    avg_access_time_ms: float


class DistributedCacheManager:
    """
    Multi-layer distributed cache manager with intelligent optimization.
    """
    
    # Priority TTLs in seconds
    PRIORITY_TTLS = {
        CachePriority.LOW: 300,        # 5 minutes
        CachePriority.NORMAL: 3600,    # 1 hour
        CachePriority.HIGH: 86400,     # 1 day
        CachePriority.CRITICAL: 604800  # 1 week
    }
    
    def __init__(self, redis_client=None, max_memory_size: int = 100 * 1024 * 1024):
        self.redis = redis_client
        self.max_memory_size = max_memory_size
        
        # L1: In-memory cache
        self._l1_cache: Dict[str, CacheEntry] = {}
        self._l1_size = 0
        
        # L2: Local disk cache path
        self._l2_path = "/app/cache/l2"
        
        # Statistics
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "access_times": []
        }
        
        # Tag index for invalidation
        self._tag_index: Dict[str, Set[str]] = {}
        
        # Background tasks
        self._cleanup_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start cache manager background tasks."""
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        logger.info("Distributed cache manager started")
    
    async def stop(self):
        """Stop cache manager."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
        logger.info("Distributed cache manager stopped")
    
    async def get(
        self,
        key: str,
        default: Any = None,
        tags: Optional[Set[str]] = None
    ) -> Any:
        """
        Get value from cache (L1 -> L2 -> L3).
        
        Implements multi-layer cache lookup with automatic promotion.
        """
        start_time = datetime.now()
        
        # Try L1 (memory)
        if key in self._l1_cache:
            entry = self._l1_cache[key]
            if not self._is_expired(entry):
                entry.access_count += 1
                entry.last_accessed = datetime.now()
                self._stats["hits"] += 1
                self._record_access_time(start_time)
                return entry.value
            else:
                # Evict expired entry
                self._evict_from_l1(key)
        
        # Try L2 (local/Redis single)
        if self.redis:
            try:
                value = await self.redis.get(f"l2:{key}")
                if value:
                    # Promote to L1
                    await self._promote_to_l1(key, pickle.loads(value), tags)
                    self._stats["hits"] += 1
                    self._record_access_time(start_time)
                    return pickle.loads(value)
            except Exception as e:
                logger.warning(f"L2 cache read failed: {e}")
        
        self._stats["misses"] += 1
        self._record_access_time(start_time)
        return default
    
    async def set(
        self,
        key: str,
        value: Any,
        priority: CachePriority = CachePriority.NORMAL,
        tags: Optional[Set[str]] = None,
        ttl: Optional[int] = None,
        level: CacheLevel = CacheLevel.L1_MEMORY
    ) -> bool:
        """
        Set value in cache with intelligent level selection.
        
        Args:
            key: Cache key
            value: Value to cache
            priority: Cache priority (determines TTL)
            tags: Tags for grouped invalidation
            ttl: Custom TTL (overrides priority)
            level: Target cache level
        """
        try:
            # Calculate size
            value_bytes = pickle.dumps(value)
            size = len(value_bytes)
            
            # Calculate expiration
            ttl_seconds = ttl or self.PRIORITY_TTLS[priority]
            expires_at = datetime.now() + timedelta(seconds=ttl_seconds)
            
            entry = CacheEntry(
                key=key,
                value=value,
                level=level,
                priority=priority,
                created_at=datetime.now(),
                expires_at=expires_at,
                access_count=0,
                last_accessed=datetime.now(),
                size_bytes=size,
                tags=tags or set()
            )
            
            # Store in appropriate level
            if level == CacheLevel.L1_MEMORY:
                # Check if we need to evict
                await self._ensure_l1_space(size)
                
                self._l1_cache[key] = entry
                self._l1_size += size
                
                # Also store in L2 for persistence
                if self.redis:
                    await self.redis.setex(
                        f"l2:{key}",
                        ttl_seconds,
                        value_bytes
                    )
            
            elif level == CacheLevel.L2_LOCAL and self.redis:
                await self.redis.setex(
                    f"l2:{key}",
                    ttl_seconds,
                    value_bytes
                )
            
            # Index by tags
            if tags:
                for tag in tags:
                    if tag not in self._tag_index:
                        self._tag_index[tag] = set()
                    self._tag_index[tag].add(key)
            
            return True
            
        except Exception as e:
            logger.error(f"Cache set failed: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key from all cache levels."""
        success = True
        
        # Delete from L1
        if key in self._l1_cache:
            self._evict_from_l1(key)
        
        # Delete from L2
        if self.redis:
            try:
                await self.redis.delete(f"l2:{key}")
            except Exception as e:
                logger.warning(f"L2 delete failed: {e}")
                success = False
        
        # Remove from tag index
        for tag_keys in self._tag_index.values():
            tag_keys.discard(key)
        
        return success
    
    async def invalidate_by_tag(self, tag: str) -> int:
        """Invalidate all cache entries with given tag."""
        if tag not in self._tag_index:
            return 0
        
        keys_to_invalidate = list(self._tag_index[tag])
        count = 0
        
        for key in keys_to_invalidate:
            if await self.delete(key):
                count += 1
        
        # Clear tag index
        del self._tag_index[tag]
        
        logger.info(f"Invalidated {count} entries with tag '{tag}'")
        return count
    
    async def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate cache entries matching pattern."""
        count = 0
        
        # L1 pattern matching
        matching_keys = [
            key for key in self._l1_cache.keys()
            if self._key_matches_pattern(key, pattern)
        ]
        
        for key in matching_keys:
            if await self.delete(key):
                count += 1
        
        # L2 pattern matching (if Redis supports it)
        if self.redis:
            try:
                # Scan and delete matching keys
                cursor = 0
                while True:
                    cursor, keys = await self.redis.scan(
                        cursor,
                        match=f"l2:{pattern}"
                    )
                    for key in keys:
                        await self.redis.delete(key)
                        count += 1
                    
                    if cursor == 0:
                        break
            except Exception as e:
                logger.warning(f"Pattern invalidation in L2 failed: {e}")
        
        return count
    
    async def _ensure_l1_space(self, required_bytes: int) -> None:
        """Ensure L1 cache has enough space, evict if necessary."""
        while self._l1_size + required_bytes > self.max_memory_size:
            # Find best entry to evict (lowest priority, oldest, least accessed)
            victim = self._find_eviction_victim()
            if victim:
                self._evict_from_l1(victim)
            else:
                break
    
    def _find_eviction_victim(self) -> Optional[str]:
        """Find best candidate for eviction using multi-factor scoring."""
        if not self._l1_cache:
            return None
        
        best_score = float('inf')
        victim = None
        now = datetime.now()
        
        for key, entry in self._l1_cache.items():
            # Calculate eviction score (lower = better candidate)
            # Factors: priority, age, access frequency, size
            priority_weight = {
                CachePriority.LOW: 0,
                CachePriority.NORMAL: 1,
                CachePriority.HIGH: 2,
                CachePriority.CRITICAL: 3
            }.get(entry.priority, 0)
            
            age_hours = (now - entry.created_at).total_seconds() / 3600
            access_rate = entry.access_count / max(age_hours, 1)
            
            score = (
                priority_weight * 10 +
                age_hours * 2 -
                access_rate * 5 +
                (entry.size_bytes / (1024 * 1024))  # Size in MB
            )
            
            if score < best_score:
                best_score = score
                victim = key
        
        return victim
    
    def _evict_from_l1(self, key: str) -> None:
        """Evict entry from L1 cache."""
        if key in self._l1_cache:
            entry = self._l1_cache[key]
            self._l1_size -= entry.size_bytes
            del self._l1_cache[key]
            self._stats["evictions"] += 1
    
    async def _promote_to_l1(self, key: str, value: Any, tags: Optional[Set[str]]) -> None:
        """Promote value from lower cache to L1."""
        try:
            value_bytes = pickle.dumps(value)
            size = len(value_bytes)
            
            await self._ensure_l1_space(size)
            
            entry = CacheEntry(
                key=key,
                value=value,
                level=CacheLevel.L1_MEMORY,
                priority=CachePriority.NORMAL,
                created_at=datetime.now(),
                expires_at=datetime.now() + timedelta(seconds=3600),
                access_count=1,
                last_accessed=datetime.now(),
                size_bytes=size,
                tags=tags or set()
            )
            
            self._l1_cache[key] = entry
            self._l1_size += size
            
        except Exception as e:
            logger.warning(f"Promotion to L1 failed: {e}")
    
    def _is_expired(self, entry: CacheEntry) -> bool:
        """Check if cache entry is expired."""
        return datetime.now() > entry.expires_at
    
    def _key_matches_pattern(self, key: str, pattern: str) -> bool:
        """Check if key matches wildcard pattern."""
        import fnmatch
        return fnmatch.fnmatch(key, pattern)
    
    def _record_access_time(self, start_time: datetime) -> None:
        """Record cache access time for statistics."""
        access_time = (datetime.now() - start_time).total_seconds() * 1000
        self._stats["access_times"].append(access_time)
        
        # Keep only last 1000 measurements
        if len(self._stats["access_times"]) > 1000:
            self._stats["access_times"] = self._stats["access_times"][-1000:]
    
    async def _periodic_cleanup(self) -> None:
        """Periodic cleanup of expired entries."""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes
                
                # Clean L1 expired entries
                expired_keys = [
                    key for key, entry in self._l1_cache.items()
                    if self._is_expired(entry)
                ]
                
                for key in expired_keys:
                    self._evict_from_l1(key)
                
                if expired_keys:
                    logger.debug(f"Cleaned {len(expired_keys)} expired L1 entries")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
    
    def get_stats(self) -> CacheStats:
        """Get cache performance statistics."""
        total_accesses = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total_accesses if total_accesses > 0 else 0
        
        avg_access_time = (
            sum(self._stats["access_times"]) / len(self._stats["access_times"])
            if self._stats["access_times"] else 0
        )
        
        return CacheStats(
            hits=self._stats["hits"],
            misses=self._stats["misses"],
            evictions=self._stats["evictions"],
            total_size_bytes=self._l1_size,
            entry_count=len(self._l1_cache),
            hit_rate=hit_rate,
            avg_access_time_ms=avg_access_time
        )
    
    async def warm_cache(
        self,
        keys_and_values: List[tuple],
        priority: CachePriority = CachePriority.NORMAL
    ) -> int:
        """Pre-populate cache with multiple entries."""
        count = 0
        for key, value in keys_and_values:
            if await self.set(key, value, priority=priority):
                count += 1
        return count
    
    def cached(
        self,
        ttl: int = 3600,
        priority: CachePriority = CachePriority.NORMAL,
        tags: Optional[List[str]] = None,
        key_func: Optional[Callable] = None
    ):
        """Decorator for caching function results."""
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Generate cache key
                if key_func:
                    cache_key = key_func(*args, **kwargs)
                else:
                    # Default: hash of function name and arguments
                    key_data = f"{func.__name__}:{str(args)}:{str(kwargs)}"
                    cache_key = hashlib.md5(key_data.encode()).hexdigest()
                
                # Try cache first
                result = await self.get(cache_key)
                if result is not None:
                    return result
                
                # Execute function
                result = await func(*args, **kwargs)
                
                # Store in cache
                await self.set(
                    cache_key,
                    result,
                    priority=priority,
                    tags=set(tags) if tags else None,
                    ttl=ttl
                )
                
                return result
            
            return wrapper
        return decorator


# Global instance
_cache_manager: Optional[DistributedCacheManager] = None


def get_cache_manager() -> DistributedCacheManager:
    """Get global cache manager instance."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = DistributedCacheManager()
    return _cache_manager


# Convenience functions
async def cache_get(key: str, default: Any = None) -> Any:
    """Get value from cache."""
    return await get_cache_manager().get(key, default)


async def cache_set(
    key: str,
    value: Any,
    ttl: int = 3600,
    priority: str = "normal"
) -> bool:
    """Set value in cache."""
    prio = CachePriority(priority) if priority in [p.value for p in CachePriority] else CachePriority.NORMAL
    return await get_cache_manager().set(key, value, priority=prio, ttl=ttl)


async def cache_invalidate_tag(tag: str) -> int:
    """Invalidate cache entries by tag."""
    return await get_cache_manager().invalidate_by_tag(tag)
