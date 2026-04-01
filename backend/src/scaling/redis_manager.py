"""
Redis connection manager for horizontal scaling.

Supports:
- Connection pooling
- Redis Sentinel for high availability
- Graceful degradation
- Health checks
"""

import logging
from typing import Optional
import redis.asyncio as redis
from redis.asyncio.sentinel import Sentinel

from ..config import Config

logger = logging.getLogger(__name__)


class RedisManager:
    """
    Manages Redis connections with support for:
    - Standalone Redis
    - Redis Sentinel (HA)
    - Connection pooling
    """
    
    def __init__(self):
        self.config = Config()
        self._client: Optional[redis.Redis] = None
        self._sentinel: Optional[Sentinel] = None
        self._use_sentinel = False
    
    async def initialize(self):
        """
        Initialize Redis connection.
        
        Tries Sentinel first (if configured), falls back to standalone.
        """
        # Check if Sentinel is configured
        sentinel_hosts = self.config.redis_sentinel_hosts
        
        if sentinel_hosts:
            await self._init_sentinel(sentinel_hosts)
        else:
            await self._init_standalone()
    
    async def _init_sentinel(self, sentinel_hosts: list):
        """Initialize Redis Sentinel for high availability."""
        try:
            logger.info(f"Initializing Redis Sentinel: {sentinel_hosts}")
            
            # Parse sentinel hosts (format: "host1:port1,host2:port2")
            sentinels = []
            for host_port in sentinel_hosts.split(","):
                host, port = host_port.strip().split(":")
                sentinels.append((host, int(port)))
            
            # Create Sentinel connection
            self._sentinel = Sentinel(
                sentinels,
                socket_timeout=5.0,
                password=self.config.redis_password,
            )
            
            # Get master connection
            master_name = self.config.redis_sentinel_master_name or "mymaster"
            self._client = self._sentinel.master_for(
                master_name,
                socket_timeout=5.0,
                decode_responses=False,
            )
            
            # Test connection
            await self._client.ping()
            
            self._use_sentinel = True
            logger.info("✅ Redis Sentinel initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Sentinel: {e}")
            logger.info("Falling back to standalone Redis")
            await self._init_standalone()
    
    async def _init_standalone(self):
        """Initialize standalone Redis connection."""
        try:
            logger.info(
                f"Initializing standalone Redis: "
                f"{self.config.redis_host}:{self.config.redis_port}"
            )
            
            self._client = redis.Redis(
                host=self.config.redis_host,
                port=self.config.redis_port,
                password=self.config.redis_password,
                db=0,
                decode_responses=False,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
                max_connections=50,  # Connection pool size
            )
            
            # Test connection
            await self._client.ping()
            
            self._use_sentinel = False
            logger.info("✅ Standalone Redis initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Redis: {e}")
            logger.warning("⚠️ Redis unavailable - caching and rate limiting disabled")
            self._client = None
    
    async def get_client(self) -> Optional[redis.Redis]:
        """Get Redis client instance."""
        if self._client is None:
            await self.initialize()
        return self._client
    
    async def health_check(self) -> dict:
        """
        Perform health check on Redis.
        
        Returns:
            Dict with health status
        """
        if self._client is None:
            return {
                "status": "unavailable",
                "mode": "none",
                "error": "Redis not initialized"
            }
        
        try:
            # Ping test
            await self._client.ping()
            
            # Get info
            info = await self._client.info()
            
            return {
                "status": "healthy",
                "mode": "sentinel" if self._use_sentinel else "standalone",
                "version": info.get("redis_version", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "uptime_days": info.get("uptime_in_days", 0),
            }
            
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return {
                "status": "unhealthy",
                "mode": "sentinel" if self._use_sentinel else "standalone",
                "error": str(e)
            }
    
    async def close(self):
        """Close Redis connections."""
        if self._client:
            await self._client.close()
            logger.info("Redis connections closed")


# Global Redis manager instance
_redis_manager: Optional[RedisManager] = None


async def get_redis_manager() -> RedisManager:
    """Get or create global Redis manager."""
    global _redis_manager
    if _redis_manager is None:
        _redis_manager = RedisManager()
        await _redis_manager.initialize()
    return _redis_manager


async def get_redis_client() -> Optional[redis.Redis]:
    """Get Redis client (convenience function)."""
    manager = await get_redis_manager()
    return await manager.get_client()
