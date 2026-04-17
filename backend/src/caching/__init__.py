"""
Caching module for ViraClip.

Provides advanced Redis-based caching with:
- Compression for large values
- TTL-based expiration
- Cache metrics (hit rate, etc.)
- Decorator for easy function caching
"""

from .advanced_cache import (
    AdvancedCache,
    get_cache,
    init_cache,
    cached,
)

__all__ = [
    "AdvancedCache",
    "get_cache",
    "init_cache",
    "cached",
]
