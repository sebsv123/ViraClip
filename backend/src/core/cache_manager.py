"""
Smart Cache Manager with Redis backend
Provides intelligent caching with TTL, versioning, and distributed support.
"""

import json
import hashlib
import logging
from typing import Any, Dict, Optional, Union
from pathlib import Path
from datetime import datetime, timedelta

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class SmartCacheManager:
    """
    Intelligent caching system with Redis backend and local fallback.
    Supports versioning, TTL, and cache invalidation strategies.
    """
    
    # Cache versions for invalidation on algorithm updates
    CACHE_VERSIONS = {
        "transcript": "v2.1",
        "ai_analysis": "v3.0",
        "hook_analysis": "v1.0",
        "niche_analysis": "v1.0",
        "virality_score": "v2.0",
    }
    
    # Default TTL in seconds
    DEFAULT_TTL = {
        "transcript": 86400 * 7,      # 7 days
        "ai_analysis": 86400 * 3,   # 3 days
        "hook_analysis": 86400 * 1, # 1 day
        "niche_analysis": 86400 * 7, # 7 days (stable)
        "virality_score": 86400 * 1, # 1 day
    }
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._local_cache: Dict[str, Any] = {}
        self._local_timestamps: Dict[str, datetime] = {}
        self._hit_count = 0
        self._miss_count = 0
    
    def _generate_key(self, cache_type: str, identifier: str) -> str:
        """Generate cache key with versioning."""
        version = self.CACHE_VERSIONS.get(cache_type, "v1")
        hash_input = f"{cache_type}:{version}:{identifier}"
        key_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
        return f"viraclip:{cache_type}:{key_hash}"
    
    def _generate_file_hash(self, file_path: Path) -> str:
        """Generate hash from first 1MB of file."""
        try:
            with open(file_path, "rb") as f:
                chunk = f.read(1_048_576)
            return hashlib.sha256(chunk).hexdigest()
        except Exception as e:
            logger.warning(f"Failed to hash file {file_path}: {e}")
            return str(file_path.stat().st_mtime) if file_path.exists() else ""
    
    async def get(
        self, 
        cache_type: str, 
        identifier: Union[str, Path],
        check_local: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached data with fallback strategy:
        1. Try Redis (distributed)
        2. Try local memory cache
        3. Try disk cache
        """
        if isinstance(identifier, Path):
            identifier = self._generate_file_hash(identifier)
        
        cache_key = self._generate_key(cache_type, identifier)
        
        # Try Redis first
        if self.redis and REDIS_AVAILABLE:
            try:
                data = await self.redis.get(cache_key)
                if data:
                    self._hit_count += 1
                    logger.debug(f"Redis cache hit: {cache_type}")
                    return json.loads(data)
            except Exception as e:
                logger.debug(f"Redis get failed: {e}")
        
        # Try local cache
        if check_local and cache_key in self._local_cache:
            cached_time = self._local_timestamps.get(cache_key)
            ttl = self.DEFAULT_TTL.get(cache_type, 3600)
            
            if cached_time and (datetime.now() - cached_time).seconds < ttl:
                self._hit_count += 1
                logger.debug(f"Local cache hit: {cache_type}")
                return self._local_cache[cache_key]
            else:
                # Expired - remove
                del self._local_cache[cache_key]
                del self._local_timestamps[cache_key]
        
        self._miss_count += 1
        return None
    
    async def set(
        self,
        cache_type: str,
        identifier: Union[str, Path],
        data: Dict[str, Any],
        custom_ttl: Optional[int] = None,
    ) -> bool:
        """
        Set cached data in all available cache layers.
        """
        if isinstance(identifier, Path):
            identifier = self._generate_file_hash(identifier)
        
        cache_key = self._generate_key(cache_type, identifier)
        ttl = custom_ttl or self.DEFAULT_TTL.get(cache_type, 3600)
        
        # Add metadata
        enriched_data = {
            "data": data,
            "_meta": {
                "cached_at": datetime.now().isoformat(),
                "version": self.CACHE_VERSIONS.get(cache_type, "v1"),
                "ttl": ttl,
            }
        }
        
        success = False
        
        # Store in Redis
        if self.redis and REDIS_AVAILABLE:
            try:
                await self.redis.setex(
                    cache_key, 
                    ttl, 
                    json.dumps(enriched_data)
                )
                success = True
                logger.debug(f"Redis cache set: {cache_type} (TTL: {ttl}s)")
            except Exception as e:
                logger.debug(f"Redis set failed: {e}")
        
        # Store in local cache
        self._local_cache[cache_key] = enriched_data
        self._local_timestamps[cache_key] = datetime.now()
        
        return success
    
    async def invalidate(
        self, 
        cache_type: Optional[str] = None,
        identifier: Optional[Union[str, Path]] = None
    ) -> int:
        """
        Invalidate cache entries.
        If cache_type is None, invalidate all.
        If identifier is None, invalidate all of that type.
        """
        invalidated = 0
        
        if cache_type is None:
            # Invalidate all
            pattern = "viraclip:*"
        elif identifier is None:
            # Invalidate all of specific type
            pattern = f"viraclip:{cache_type}:*"
        else:
            # Invalidate specific entry
            if isinstance(identifier, Path):
                identifier = self._generate_file_hash(identifier)
            cache_key = self._generate_key(cache_type, identifier)
            pattern = cache_key
        
        # Clear from Redis
        if self.redis and REDIS_AVAILABLE:
            try:
                if "*" in pattern:
                    # Use scan and delete
                    keys = []
                    async for key in self.redis.scan_iter(match=pattern):
                        keys.append(key)
                    if keys:
                        await self.redis.delete(*keys)
                        invalidated = len(keys)
                else:
                    await self.redis.delete(pattern)
                    invalidated = 1
            except Exception as e:
                logger.warning(f"Redis invalidation failed: {e}")
        
        # Clear from local cache
        keys_to_remove = [
            k for k in self._local_cache.keys()
            if pattern.replace("*", "") in k or k == pattern
        ]
        for key in keys_to_remove:
            del self._local_cache[key]
            if key in self._local_timestamps:
                del self._local_timestamps[key]
        
        logger.info(f"Invalidated {invalidated} cache entries (pattern: {pattern})")
        return invalidated
    
    async def invalidate_by_version(self, min_version: str) -> int:
        """
        Invalidate all caches older than specified version.
        Useful when updating AI models or algorithms.
        """
        invalidated = 0
        
        for cache_type, current_version in self.CACHE_VERSIONS.items():
            if current_version < min_version:
                count = await self.invalidate(cache_type)
                invalidated += count
                logger.info(f"Invalidated {cache_type} cache (version {current_version} < {min_version})")
        
        return invalidated
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics."""
        total = self._hit_count + self._miss_count
        hit_rate = self._hit_count / total if total > 0 else 0
        
        return {
            "hits": self._hit_count,
            "misses": self._miss_count,
            "hit_rate": hit_rate,
            "local_entries": len(self._local_cache),
            "versions": self.CACHE_VERSIONS,
            "redis_connected": self.redis is not None and REDIS_AVAILABLE,
        }
    
    def reset_stats(self):
        """Reset statistics counters."""
        self._hit_count = 0
        self._miss_count = 0


# Global instance
_cache_manager: Optional[SmartCacheManager] = None


def get_cache_manager(redis_client=None) -> SmartCacheManager:
    """Get or create global cache manager instance."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = SmartCacheManager(redis_client)
    return _cache_manager


async def cache_transcript_smart(
    video_path: Path,
    transcript_data: Dict[str, Any],
    redis_client=None
) -> bool:
    """Cache transcript with smart manager."""
    cache = get_cache_manager(redis_client)
    return await cache.set("transcript", video_path, transcript_data)


async def get_cached_transcript_smart(
    video_path: Path,
    redis_client=None
) -> Optional[Dict[str, Any]]:
    """Get cached transcript with smart manager."""
    cache = get_cache_manager(redis_client)
    result = await cache.get("transcript", video_path)
    return result["data"] if result else None


async def cache_ai_analysis_smart(
    video_hash: str,
    analysis_data: Dict[str, Any],
    redis_client=None
) -> bool:
    """Cache AI analysis results."""
    cache = get_cache_manager(redis_client)
    return await cache.set("ai_analysis", video_hash, analysis_data)


async def get_cached_ai_analysis_smart(
    video_hash: str,
    redis_client=None
) -> Optional[Dict[str, Any]]:
    """Get cached AI analysis."""
    cache = get_cache_manager(redis_client)
    result = await cache.get("ai_analysis", video_hash)
    return result["data"] if result else None
