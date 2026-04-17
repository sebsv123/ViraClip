"""
Advanced Redis caching layer for expensive operations.

Caches:
- Transcript data (avoid re-transcription)
- AI analysis results (avoid re-running LLM)
- Video metadata (avoid re-downloading)
- User preferences

Features:
- TTL-based expiration
- Cache invalidation patterns
- Compression for large values
- Cache warming
- Hit/miss metrics
"""

import logging
import json
import gzip
from typing import Optional, Any, Callable
from functools import wraps
import hashlib
import redis.asyncio as redis

logger = logging.getLogger(__name__)


class AdvancedCache:
    """
    Advanced caching layer with compression and metrics.
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis = redis_client
        self.compression_threshold = 1024  # Compress values > 1KB
        
        # TTL defaults (seconds)
        self.ttls = {
            "transcript": 86400 * 7,      # 7 days
            "ai_analysis": 86400 * 3,     # 3 days
            "video_metadata": 86400,      # 1 day
            "user_prefs": 3600,           # 1 hour
            "temp": 300,                  # 5 minutes
        }
    
    def _make_key(self, namespace: str, identifier: str) -> str:
        """Generate cache key with namespace."""
        return f"cache:{namespace}:{identifier}"
    
    def _compress_value(self, value: str) -> bytes:
        """Compress large values with gzip."""
        if len(value) < self.compression_threshold:
            return value.encode('utf-8')
        
        compressed = gzip.compress(value.encode('utf-8'))
        logger.debug(f"Compressed {len(value)} → {len(compressed)} bytes")
        return b"GZIP:" + compressed
    
    def _decompress_value(self, value: bytes) -> str:
        """Decompress gzipped values."""
        if value.startswith(b"GZIP:"):
            compressed = value[5:]  # Remove "GZIP:" prefix
            return gzip.decompress(compressed).decode('utf-8')
        return value.decode('utf-8')
    
    async def get(
        self,
        namespace: str,
        identifier: str,
        deserialize: bool = True
    ) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            namespace: Cache namespace (transcript, ai_analysis, etc.)
            identifier: Unique identifier for cached item
            deserialize: If True, parse JSON automatically
            
        Returns:
            Cached value or None if not found
        """
        if self.redis is None:
            return None
        
        key = self._make_key(namespace, identifier)
        
        try:
            value = await self.redis.get(key)
            
            if value is None:
                # Cache miss
                await self._record_metric("miss", namespace)
                return None
            
            # Cache hit
            await self._record_metric("hit", namespace)
            
            # Decompress if needed
            decompressed = self._decompress_value(value)
            
            # Deserialize JSON if requested
            if deserialize:
                return json.loads(decompressed)
            return decompressed
            
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            await self._record_metric("error", namespace)
            return None
    
    async def set(
        self,
        namespace: str,
        identifier: str,
        value: Any,
        ttl: Optional[int] = None,
        serialize: bool = True
    ) -> bool:
        """
        Set value in cache.
        
        Args:
            namespace: Cache namespace
            identifier: Unique identifier
            value: Value to cache (will be JSON serialized if serialize=True)
            ttl: Time to live in seconds (uses default if None)
            serialize: If True, JSON serialize value
            
        Returns:
            True if successful
        """
        if self.redis is None:
            return False
        
        key = self._make_key(namespace, identifier)
        
        try:
            # Serialize to JSON if requested
            if serialize:
                value_str = json.dumps(value, ensure_ascii=False)
            else:
                value_str = str(value)
            
            # Compress large values
            compressed = self._compress_value(value_str)
            
            # Get TTL
            if ttl is None:
                ttl = self.ttls.get(namespace, 3600)
            
            # Store in Redis
            await self.redis.setex(key, ttl, compressed)
            
            logger.debug(f"Cached {namespace}:{identifier} (TTL: {ttl}s)")
            return True
            
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False
    
    async def delete(self, namespace: str, identifier: str) -> bool:
        """Delete item from cache."""
        if self.redis is None:
            return False
        
        key = self._make_key(namespace, identifier)
        
        try:
            await self.redis.delete(key)
            logger.debug(f"Deleted cache key: {namespace}:{identifier}")
            return True
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False
    
    async def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all keys matching pattern.
        
        Args:
            pattern: Redis key pattern (e.g., "cache:transcript:*")
            
        Returns:
            Number of keys deleted
        """
        if self.redis is None:
            return 0
        
        try:
            keys = []
            async for key in self.redis.scan_iter(match=pattern):
                keys.append(key)
            
            if keys:
                deleted = await self.redis.delete(*keys)
                logger.info(f"Invalidated {deleted} keys matching {pattern}")
                return deleted
            return 0
            
        except Exception as e:
            logger.error(f"Cache invalidation error: {e}")
            return 0
    
    async def _record_metric(self, metric_type: str, namespace: str):
        """Record cache hit/miss/error metrics."""
        if self.redis is None:
            return
        
        try:
            metric_key = f"cache_metrics:{namespace}:{metric_type}"
            await self.redis.incr(metric_key)
            await self.redis.expire(metric_key, 86400)  # Keep for 24h
        except Exception:
            pass  # Don't fail on metrics
    
    async def get_metrics(self, namespace: Optional[str] = None) -> dict:
        """
        Get cache metrics.
        
        Args:
            namespace: Specific namespace or None for all
            
        Returns:
            Dict with hit/miss/error counts
        """
        if self.redis is None:
            return {}
        
        try:
            pattern = f"cache_metrics:{namespace or '*'}:*"
            metrics = {}
            
            async for key in self.redis.scan_iter(match=pattern):
                key_str = key.decode('utf-8')
                parts = key_str.split(":")
                ns = parts[1]
                metric_type = parts[2]
                
                count = await self.redis.get(key)
                count = int(count) if count else 0
                
                if ns not in metrics:
                    metrics[ns] = {"hits": 0, "misses": 0, "errors": 0}
                
                if metric_type == "hit":
                    metrics[ns]["hits"] = count
                elif metric_type == "miss":
                    metrics[ns]["misses"] = count
                elif metric_type == "error":
                    metrics[ns]["errors"] = count
            
            # Calculate hit rates
            for ns in metrics:
                total = metrics[ns]["hits"] + metrics[ns]["misses"]
                if total > 0:
                    metrics[ns]["hit_rate"] = round(metrics[ns]["hits"] / total * 100, 2)
                else:
                    metrics[ns]["hit_rate"] = 0.0
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to get cache metrics: {e}")
            return {}


# Global cache instance
_cache: Optional[AdvancedCache] = None


def get_cache() -> AdvancedCache:
    """Get or create global cache instance."""
    global _cache
    if _cache is None:
        _cache = AdvancedCache()
    return _cache


async def init_cache(redis_client: redis.Redis):
    """Initialize cache with Redis client."""
    global _cache
    _cache = AdvancedCache(redis_client=redis_client)
    logger.info("Advanced cache initialized with Redis")


def cached(
    namespace: str,
    ttl: Optional[int] = None,
    key_func: Optional[Callable] = None
):
    """
    Decorator to cache function results.
    
    Usage:
        @cached("ai_analysis", ttl=3600)
        async def analyze_transcript(transcript: str):
            # Expensive operation
            return result
    
    Args:
        namespace: Cache namespace
        ttl: Time to live in seconds
        key_func: Function to generate cache key from args
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache = get_cache()
            
            # Generate cache key
            if key_func:
                identifier = key_func(*args, **kwargs)
            else:
                # Default: hash function name + args
                key_parts = [func.__name__]
                key_parts.extend(str(arg) for arg in args)
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                key_str = ":".join(key_parts)
                identifier = hashlib.sha256(key_str.encode()).hexdigest()[:16]
            
            # Try to get from cache
            cached_result = await cache.get(namespace, identifier)
            if cached_result is not None:
                logger.debug(f"Cache hit: {namespace}:{identifier}")
                return cached_result
            
            # Execute function
            result = await func(*args, **kwargs)
            
            # Cache result
            await cache.set(namespace, identifier, result, ttl=ttl)
            
            return result
        
        return wrapper
    return decorator
