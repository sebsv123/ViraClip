"""
Middleware module for ViraClip.

Includes:
- Rate limiting
- Request tracking
- Performance monitoring
"""

from .rate_limiter import (
    RateLimiter,
    get_rate_limiter,
    init_rate_limiter,
    rate_limit,
    get_client_identifier,
)

__all__ = [
    "RateLimiter",
    "get_rate_limiter",
    "init_rate_limiter",
    "rate_limit",
    "get_client_identifier",
]
