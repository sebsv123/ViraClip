"""
Cache Manager — Performance Optimization
=========================================
Sistema de caché centralizado para reducir llamadas costosas.

Features:
- Redis cache con TTL configurable
- In-memory LRU cache como fallback
- Decoradores para funciones async
- Cache invalidation por patrón
"""

import os
import logging
import asyncio
import hashlib
import json
from typing import Any, Optional, Callable, Dict
from functools import wraps
from datetime import timedelta

logger = logging.getLogger(__name__)

# In-memory LRU cache fallback
_memory_cache: Dict[str, tuple[Any, float]] = {}
_max_memory_cache_size = 1000

# Redis client (lazy loaded)
_redis_client = None


async def get_redis_client():
    """Get or create Redis client."""
    global _redis_client
    
    if _redis_client is None:
        try:
            import redis.asyncio as redis
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            _redis_client = await redis.from_url(redis_url, decode_responses=True)
            logger.info("[cache] Redis client initialized")
        except Exception as e:
            logger.warning(f"[cache] Redis unavailable: {e}")
            _redis_client = False  # Mark as unavailable
    
    return _redis_client if _redis_client else None


def cache_key(*args, **kwargs) -> str:
    """Generate cache key from function arguments."""
    key_parts = [str(arg) for arg in args]
    key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
    key_str = ":".join(key_parts)
    
    # Hash long keys
    if len(key_str) > 200:
        return hashlib.md5(key_str.encode()).hexdigest()
    
    return key_str


def redis_cache(
    ttl: int = 3600,
    prefix: str = "viraclip",
    serialize: bool = True
):
    """
    Decorator for Redis caching with automatic fallback to memory.
    
    Args:
        ttl: Time to live in seconds (default 1 hour)
        prefix: Cache key prefix
        serialize: Whether to JSON serialize/deserialize
    
    Example:
        @redis_cache(ttl=300, prefix="trends")
        async def get_trending_hashtags(platform: str):
            # Expensive API call
            return ["trending1", "trending2"]
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate cache key
            func_key = f"{prefix}:{func.__name__}:{cache_key(*args, **kwargs)}"
            
            # Try Redis first
            redis = await get_redis_client()
            if redis:
                try:
                    cached = await redis.get(func_key)
                    if cached:
                        logger.debug(f"[cache] HIT Redis: {func_key}")
                        return json.loads(cached) if serialize else cached
                except Exception as e:
                    logger.warning(f"[cache] Redis get failed: {e}")
            
            # Try memory cache
            if func_key in _memory_cache:
                cached_value, expiry = _memory_cache[func_key]
                if asyncio.get_event_loop().time() < expiry:
                    logger.debug(f"[cache] HIT Memory: {func_key}")
                    return cached_value
                else:
                    del _memory_cache[func_key]
            
            # Cache miss - execute function
            logger.debug(f"[cache] MISS: {func_key}")
            result = await func(*args, **kwargs)
            
            # Store in Redis
            if redis:
                try:
                    cached_data = json.dumps(result) if serialize else result
                    await redis.setex(func_key, ttl, cached_data)
                except Exception as e:
                    logger.warning(f"[cache] Redis set failed: {e}")
            
            # Store in memory cache
            expiry_time = asyncio.get_event_loop().time() + ttl
            _memory_cache[func_key] = (result, expiry_time)
            
            # LRU eviction if too large
            if len(_memory_cache) > _max_memory_cache_size:
                oldest_key = min(_memory_cache.keys(), key=lambda k: _memory_cache[k][1])
                del _memory_cache[oldest_key]
            
            return result
        
        return wrapper
    return decorator


async def invalidate_cache(pattern: str = "*"):
    """
    Invalidate cache entries matching pattern.
    
    Args:
        pattern: Redis key pattern (e.g., "trends:*", "feedback:*")
    """
    redis = await get_redis_client()
    if redis:
        try:
            keys = await redis.keys(pattern)
            if keys:
                await redis.delete(*keys)
                logger.info(f"[cache] Invalidated {len(keys)} keys matching '{pattern}'")
        except Exception as e:
            logger.warning(f"[cache] Invalidation failed: {e}")
    
    # Clear memory cache matching pattern
    matching_keys = [k for k in _memory_cache.keys() if pattern.replace("*", "") in k]
    for key in matching_keys:
        del _memory_cache[key]
    
    if matching_keys:
        logger.info(f"[cache] Cleared {len(matching_keys)} memory cache entries")


async def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics."""
    stats = {
        "memory_cache_size": len(_memory_cache),
        "memory_cache_max": _max_memory_cache_size
    }
    
    redis = await get_redis_client()
    if redis:
        try:
            info = await redis.info("stats")
            stats["redis_keys"] = info.get("db0", {}).get("keys", 0)
            stats["redis_hits"] = info.get("keyspace_hits", 0)
            stats["redis_misses"] = info.get("keyspace_misses", 0)
            
            hit_rate = 0
            if stats["redis_hits"] + stats["redis_misses"] > 0:
                hit_rate = stats["redis_hits"] / (stats["redis_hits"] + stats["redis_misses"]) * 100
            
            stats["redis_hit_rate"] = f"{hit_rate:.1f}%"
        except Exception as e:
            logger.warning(f"[cache] Stats failed: {e}")
            stats["redis_available"] = False
    
    return stats


# Singleton for lazy-loaded models
_model_cache: Dict[str, Any] = {}


def get_cached_model(
    model_name: str,
    loader_func: Callable,
    *args,
    **kwargs
) -> Any:
    """
    Lazy load and cache ML models.
    
    Args:
        model_name: Unique model identifier
        loader_func: Function to load model if not cached
        *args, **kwargs: Arguments to loader_func
    
    Example:
        def load_whisper():
            from faster_whisper import WhisperModel
            return WhisperModel("large-v3")
        
        model = get_cached_model("whisper-large-v3", load_whisper)
    """
    if model_name not in _model_cache:
        logger.info(f"[cache] Loading model: {model_name}")
        _model_cache[model_name] = loader_func(*args, **kwargs)
    
    return _model_cache[model_name]


def clear_model_cache(model_name: Optional[str] = None):
    """Clear cached models."""
    if model_name:
        if model_name in _model_cache:
            del _model_cache[model_name]
            logger.info(f"[cache] Cleared model: {model_name}")
    else:
        _model_cache.clear()
        logger.info(f"[cache] Cleared all models")
