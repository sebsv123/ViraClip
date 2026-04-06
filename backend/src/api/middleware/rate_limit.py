"""
Rate Limiting Middleware for GPU Endpoints
==========================================

Provides per-user rate limiting for GPU-intensive endpoints.
Uses Redis as the backing store for distributed rate limiting.

Configuration (via environment variables):
    RATE_LIMIT_T2V_PER_MINUTE=10
    RATE_LIMIT_TTS_PER_MINUTE=20
    RATE_LIMIT_UPSCALE_PER_MINUTE=5
    RATE_LIMIT_8K_PER_MINUTE=3
    RATE_LIMIT_LORA_PER_HOUR=1

Usage:
    from api.middleware.rate_limit import rate_limit_gpu
    
    @router.post("/gpu/broll/generate")
    @rate_limit_gpu(endpoint_type="t2v")
    async def generate_broll(...)
"""
from __future__ import annotations

import functools
import logging
import os
from typing import Any, Callable, Optional

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute

logger = logging.getLogger(__name__)

# Default rate limits (can be overridden via env vars)
DEFAULT_LIMITS = {
    "t2v": {"requests": int(os.environ.get("RATE_LIMIT_T2V_PER_MINUTE", "10")), "window": 60},
    "tts": {"requests": int(os.environ.get("RATE_LIMIT_TTS_PER_MINUTE", "20")), "window": 60},
    "upscale": {"requests": int(os.environ.get("RATE_LIMIT_UPSCALE_PER_MINUTE", "5")), "window": 60},
    "upscale_8k": {"requests": int(os.environ.get("RATE_LIMIT_8K_PER_MINUTE", "3")), "window": 60},
    "lora": {"requests": int(os.environ.get("RATE_LIMIT_LORA_PER_HOUR", "1")), "window": 3600},
    # Task creation: 20 tasks/hour by default (override via RATE_LIMIT_TASKS_PER_HOUR)
    "tasks": {"requests": int(os.environ.get("RATE_LIMIT_TASKS_PER_HOUR", "20")), "window": 3600},
    # Video ingestion via yt-dlp: 10/hour (bandwidth-heavy)
    "ingest": {"requests": int(os.environ.get("RATE_LIMIT_INGEST_PER_HOUR", "10")), "window": 3600},
    # Autopilot full pipeline: 5/hour (very compute-heavy)
    "autopilot": {"requests": int(os.environ.get("RATE_LIMIT_AUTOPILOT_PER_HOUR", "5")), "window": 3600},
}


class RateLimitExceeded(HTTPException):
    """Custom exception for rate limit violations."""
    def __init__(self, retry_after: int, current_usage: int, limit: int):
        super().__init__(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "retry_after_seconds": retry_after,
                "current_usage": current_usage,
                "limit": limit,
            },
            headers={"Retry-After": str(retry_after)},
        )


async def check_rate_limit(
    user_id: str,
    endpoint_type: str,
    redis_client=None
) -> tuple[bool, int, int]:
    """
    Check if user has exceeded rate limit.
    
    Returns:
        (allowed, current_count, retry_after)
    """
    import time
    
    # Get limit config
    config = DEFAULT_LIMITS.get(endpoint_type, {"requests": 10, "window": 60})
    limit = config["requests"]
    window = config["window"]
    
    # Build Redis key
    key = f"rate_limit:{endpoint_type}:{user_id}"
    
    try:
        if redis_client is None:
            # Fallback: use in-memory dict (not distributed, but works for single instance)
            from ...workers.job_queue import JobQueue
            redis_client = await JobQueue.get_pool()
        
        # Use Redis for atomic increment and expiry
        current = await redis_client.incr(key)
        
        if current == 1:
            # First request, set expiry
            await redis_client.expire(key, window)
        
        if current > limit:
            # Get TTL for retry-after header
            ttl = await redis_client.ttl(key)
            return False, current, max(ttl, 1)
        
        return True, current, 0
        
    except Exception as e:
        logger.warning(f"Rate limiting error (allowing request): {e}")
        # Fail open - allow request if rate limiting is broken
        return True, 0, 0


def rate_limit_gpu(endpoint_type: str):
    """
    Decorator for GPU endpoint rate limiting.
    
    Args:
        endpoint_type: One of "t2v", "tts", "upscale", "upscale_8k", "lora"
    
    Usage:
        @router.post("/gpu/broll/generate")
        @rate_limit_gpu("t2v")
        async def generate_broll(request: Request, ...)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract request from args/kwargs
            request: Optional[Request] = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            
            if request is None:
                request = kwargs.get("request")
            
            if request is None:
                logger.warning("Rate limit: No request object found")
                return await func(*args, **kwargs)
            
            # Get user ID from header
            user_id = request.headers.get("x-viraclip-user-id") or request.headers.get("user_id")
            if not user_id:
                # Try to get from query param or use IP as fallback
                user_id = request.query_params.get("user_id") or request.client.host
            
            # Check rate limit
            allowed, current, retry_after = await check_rate_limit(
                user_id, endpoint_type
            )
            
            if not allowed:
                config = DEFAULT_LIMITS.get(endpoint_type, {"requests": 10, "window": 60})
                raise RateLimitExceeded(
                    retry_after=retry_after,
                    current_usage=current,
                    limit=config["requests"]
                )
            
            # Add rate limit info to response headers (will be set by middleware)
            request.state.rate_limit_info = {
                "endpoint_type": endpoint_type,
                "current_usage": current,
                "limit": config["requests"],
            }
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


class RateLimitHeadersMiddleware:
    """Middleware to add rate limit headers to responses."""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        
        async def wrapped_send(message):
            if message["type"] == "http.response.start":
                # Add rate limit headers if available in scope extensions
                rate_info = scope.get("rate_limit_info")
                if rate_info:
                    headers = list(message.get("headers", []))
                    headers.append((b"X-RateLimit-Limit", str(rate_info["limit"]).encode()))
                    headers.append((b"X-RateLimit-Remaining", str(max(0, rate_info["limit"] - rate_info["current_usage"])).encode()))
                    headers.append((b"X-RateLimit-Endpoint", rate_info["endpoint_type"].encode()))
                    message["headers"] = headers
            
            await send(message)
        
        return await self.app(scope, receive, wrapped_send)


# Convenience function for common patterns
async def get_rate_limit_status(user_id: str) -> dict:
    """Get current rate limit status for all GPU endpoints."""
    status = {}
    
    for endpoint_type, config in DEFAULT_LIMITS.items():
        key = f"rate_limit:{endpoint_type}:{user_id}"
        try:
            from ...workers.job_queue import JobQueue
            redis_client = await JobQueue.get_pool()
            current = int(await redis_client.get(key) or 0)
            ttl = await redis_client.ttl(key)
            
            status[endpoint_type] = {
                "limit": config["requests"],
                "current_usage": current,
                "remaining": max(0, config["requests"] - current),
                "window_seconds": config["window"],
                "reset_in_seconds": max(0, ttl),
            }
        except Exception as e:
            status[endpoint_type] = {"error": str(e)}
    
    return status


async def task_rate_limit_dependency(request: Request) -> None:
    """
    FastAPI dependency: enforces per-user task-creation rate limit.

    Add to a route with:  Depends(task_rate_limit_dependency)

    Limit defaults to 20 tasks/hour; override via RATE_LIMIT_TASKS_PER_HOUR env var.
    Fails **open** if Redis is unavailable so a Redis outage never blocks submissions.
    """
    user_id = (
        request.headers.get("x-viraclip-user-id")
        or request.headers.get("user_id")
        or request.query_params.get("user_id")
        or (request.client.host if request.client else "anonymous")
    )

    allowed, current, retry_after = await check_rate_limit(user_id, "tasks")
    if not allowed:
        config = DEFAULT_LIMITS["tasks"]
        raise RateLimitExceeded(
            retry_after=retry_after,
            current_usage=current,
            limit=config["requests"],
        )


async def ingest_rate_limit_dependency(request: Request) -> None:
    """FastAPI dependency: 10 yt-dlp ingestions per hour per user."""
    user_id = (
        request.headers.get("x-viraclip-user-id")
        or request.headers.get("user_id")
        or request.query_params.get("user_id")
        or (request.client.host if request.client else "anonymous")
    )
    allowed, current, retry_after = await check_rate_limit(user_id, "ingest")
    if not allowed:
        config = DEFAULT_LIMITS["ingest"]
        raise RateLimitExceeded(
            retry_after=retry_after,
            current_usage=current,
            limit=config["requests"],
        )


async def autopilot_rate_limit_dependency(request: Request) -> None:
    """FastAPI dependency: 5 autopilot runs per hour per user."""
    user_id = (
        request.headers.get("x-viraclip-user-id")
        or request.headers.get("user_id")
        or request.query_params.get("user_id")
        or (request.client.host if request.client else "anonymous")
    )
    allowed, current, retry_after = await check_rate_limit(user_id, "autopilot")
    if not allowed:
        config = DEFAULT_LIMITS["autopilot"]
        raise RateLimitExceeded(
            retry_after=retry_after,
            current_usage=current,
            limit=config["requests"],
        )


__all__ = [
    "rate_limit_gpu",
    "check_rate_limit",
    "task_rate_limit_dependency",
    "ingest_rate_limit_dependency",
    "autopilot_rate_limit_dependency",
    "RateLimitExceeded",
    "RateLimitHeadersMiddleware",
    "get_rate_limit_status",
    "DEFAULT_LIMITS",
]
