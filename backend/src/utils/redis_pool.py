"""
Redis Connection Pool Manager

Centralizes Redis connection pooling for optimal performance.
Avoids creating new connections per operation.
"""
from __future__ import annotations

import logging
from typing import Optional

from redis.asyncio import Redis, ConnectionPool

from ..config import get_config

logger = logging.getLogger(__name__)

# Global connection pool
_connection_pool: Optional[ConnectionPool] = None
_redis_client: Optional[Redis] = None


def get_connection_pool() -> ConnectionPool:
    """Get or create the global Redis connection pool.
    
    Returns:
        ConnectionPool: Shared connection pool for all Redis operations
    """
    global _connection_pool
    
    if _connection_pool is None:
        config = get_config()
        _connection_pool = ConnectionPool(
            host=config.redis_host,
            port=config.redis_port,
            password=config.redis_password,
            db=0,
            max_connections=50,  # Pool size for high concurrency
            socket_keepalive=True,
            socket_keepalive_options={},
            health_check_interval=30,  # Check health every 30s
            decode_responses=True,  # Ensure string responses
        )
        logger.info("[RedisPool] Created connection pool (max=50)")
    
    return _connection_pool


async def get_redis_client() -> Redis:
    """Get a Redis client from the connection pool.
    
    Returns:
        Redis: Client using shared connection pool
    """
    global _redis_client
    
    if _redis_client is None:
        pool = get_connection_pool()
        _redis_client = Redis(connection_pool=pool)
        logger.debug("[RedisPool] Created Redis client from pool")
    
    return _redis_client


async def close_redis_pool() -> None:
    """Close the connection pool (for cleanup/shutdown).
    """
    global _connection_pool, _redis_client
    
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
        logger.info("[RedisPool] Redis client closed")
    
    if _connection_pool:
        await _connection_pool.disconnect()
        _connection_pool = None
        logger.info("[RedisPool] Connection pool disconnected")


# Convenience function for health checks
async def check_redis_health() -> dict:
    """Check Redis connection health.
    
    Returns:
        dict: Health status with connected, pool_size, available_connections
    """
    try:
        redis = await get_redis_client()
        await redis.ping()
        
        pool = get_connection_pool()
        return {
            "connected": True,
            "pool_size": pool.max_connections,
            "available": len(pool._available_connections) if hasattr(pool, '_available_connections') else None,
        }
    except Exception as e:
        logger.error(f"[RedisPool] Health check failed: {e}")
        return {
            "connected": False,
            "error": str(e),
        }
