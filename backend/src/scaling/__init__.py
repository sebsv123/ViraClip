"""
Scaling utilities for ViraClip.

Includes Redis connection management for horizontal scaling.
"""

from .redis_manager import (
    RedisManager,
    get_redis_manager,
    get_redis_client,
)

__all__ = [
    "RedisManager",
    "get_redis_manager",
    "get_redis_client",
]
