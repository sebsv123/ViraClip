"""
Rate Limiting Middleware using Redis.

Implements token bucket algorithm for API rate limiting with:
- Per-user rate limits
- Per-IP rate limits for anonymous requests
- Different limits for different endpoint groups
- Graceful degradation if Redis unavailable
"""

import logging
import time
from typing import Optional, Tuple
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
import redis.asyncio as redis

from ..config import get_config

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Token bucket rate limiter using Redis.
    
    Limits are defined as: {requests} per {window_seconds}
    
    Example:
        - API calls: 100 requests per 60 seconds
        - Video uploads: 5 requests per 3600 seconds (1 hour)
        - Admin endpoints: 1000 requests per 60 seconds
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis = redis_client
        self.config = get_config()
        
        # Rate limit definitions (requests per window_seconds)
        self.limits = {
            "api_general": (100, 60),        # 100 req/min for general API
            "video_upload": (5, 3600),       # 5 uploads/hour
            "task_create": (10, 300),        # 10 tasks per 5 min
            "admin": (1000, 60),             # 1000 req/min for admins
            "auth": (20, 300),               # 20 auth attempts per 5 min
        }
    
    async def check_rate_limit(
        self,
        identifier: str,
        limit_type: str = "api_general"
    ) -> Tuple[bool, Optional[dict]]:
        """
        Check if request is within rate limit.
        
        Args:
            identifier: User ID, IP address, or other unique identifier
            limit_type: Type of limit to apply (from self.limits)
            
        Returns:
            (allowed, headers)
            - allowed: True if request should be allowed
            - headers: Dict with rate limit headers (X-RateLimit-*)
        """
        if self.redis is None:
            # Graceful degradation: allow all if Redis unavailable
            logger.warning("Redis unavailable, rate limiting disabled")
            return True, None
        
        if limit_type not in self.limits:
            logger.warning(f"Unknown limit type: {limit_type}, using api_general")
            limit_type = "api_general"
        
        max_requests, window_seconds = self.limits[limit_type]
        
        # Redis key for this identifier + limit type
        key = f"ratelimit:{limit_type}:{identifier}"
        
        try:
            current_time = int(time.time())
            window_start = current_time - window_seconds
            
            # Use Redis sorted set to track requests in time window
            pipe = self.redis.pipeline()
            
            # Remove old requests outside window
            pipe.zremrangebyscore(key, 0, window_start)
            
            # Count requests in current window
            pipe.zcard(key)
            
            # Add current request
            pipe.zadd(key, {str(current_time): current_time})
            
            # Set expiration on key
            pipe.expire(key, window_seconds)
            
            results = await pipe.execute()
            request_count = results[1]
            
            # Check if limit exceeded
            allowed = request_count < max_requests
            remaining = max(0, max_requests - request_count - 1)
            
            # Rate limit headers
            headers = {
                "X-RateLimit-Limit": str(max_requests),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(current_time + window_seconds),
            }
            
            if not allowed:
                retry_after = window_seconds
                headers["Retry-After"] = str(retry_after)
                logger.warning(
                    f"Rate limit exceeded for {identifier} ({limit_type}): "
                    f"{request_count}/{max_requests} requests"
                )
            
            return allowed, headers
            
        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")
            # Graceful degradation: allow on error
            return True, None
    
    async def reset_limit(self, identifier: str, limit_type: str = "api_general"):
        """Reset rate limit for an identifier (admin utility)."""
        if self.redis is None:
            return
        
        key = f"ratelimit:{limit_type}:{identifier}"
        try:
            await self.redis.delete(key)
            logger.info(f"Rate limit reset for {identifier} ({limit_type})")
        except Exception as e:
            logger.error(f"Failed to reset rate limit: {e}")


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        # Will be initialized with Redis client in startup
        _rate_limiter = RateLimiter()
    return _rate_limiter


async def init_rate_limiter(redis_client: redis.Redis):
    """Initialize rate limiter with Redis client."""
    global _rate_limiter
    _rate_limiter = RateLimiter(redis_client=redis_client)
    logger.info("Rate limiter initialized with Redis")


def get_client_identifier(request: Request) -> str:
    """
    Get unique identifier for rate limiting.
    
    Priority:
    1. User ID (if authenticated)
    2. IP address (for anonymous)
    """
    # Check if user is authenticated (you'll need to adjust based on your auth)
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    
    # Fallback to IP address
    # Try to get real IP from X-Forwarded-For (if behind proxy)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take first IP in chain
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"
    
    return f"ip:{ip}"


async def rate_limit_middleware(
    request: Request,
    call_next,
    limit_type: str = "api_general"
):
    """
    Middleware to apply rate limiting to requests.
    
    Usage in route:
        @app.get("/api/endpoint")
        async def endpoint(request: Request):
            await rate_limit_middleware(request, None, "api_general")
            ...
    """
    limiter = get_rate_limiter()
    identifier = get_client_identifier(request)
    
    allowed, headers = await limiter.check_rate_limit(identifier, limit_type)
    
    if not allowed:
        # Return 429 Too Many Requests
        content = {
            "error": "rate_limit_exceeded",
            "message": f"Rate limit exceeded. Please try again later.",
        }
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=content,
            headers=headers or {}
        )
    
    # Proceed with request
    response = await call_next(request)
    
    # Add rate limit headers to response
    if headers:
        for key, value in headers.items():
            response.headers[key] = value
    
    return response


def rate_limit(limit_type: str = "api_general"):
    """
    Decorator for FastAPI endpoints to apply rate limiting.
    
    Usage:
        @app.post("/tasks/create")
        @rate_limit("task_create")
        async def create_task(...):
            ...
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Extract request from kwargs
            request = kwargs.get("request")
            if not request:
                # Try to find Request in args
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            
            if not request:
                logger.warning("No request found for rate limiting")
                return await func(*args, **kwargs)
            
            # Check rate limit
            limiter = get_rate_limiter()
            identifier = get_client_identifier(request)
            allowed, headers = await limiter.check_rate_limit(identifier, limit_type)
            
            if not allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                    headers=headers or {}
                )
            
            # Proceed with function
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator
