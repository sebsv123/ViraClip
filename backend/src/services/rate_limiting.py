"""
Rate Limiting and API Protection Module
Advanced rate limiting with Redis backend and DDoS protection.
"""

import time
import hashlib
import logging
from typing import Dict, Any, Optional, Callable
from functools import wraps
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class RateLimitTier(Enum):
    """Rate limit tiers for different user types."""
    FREE = "free"
    BASIC = "basic"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    requests_per_minute: int
    requests_per_hour: int
    requests_per_day: int
    burst_limit: int
    cooldown_seconds: int


class RateLimiter:
    """
    Redis-backed rate limiter with sliding window algorithm.
    """
    
    # Default rate limits by tier
    DEFAULT_LIMITS = {
        RateLimitTier.FREE: RateLimitConfig(
            requests_per_minute=10,
            requests_per_hour=100,
            requests_per_day=500,
            burst_limit=5,
            cooldown_seconds=60
        ),
        RateLimitTier.BASIC: RateLimitConfig(
            requests_per_minute=30,
            requests_per_hour=300,
            requests_per_day=2000,
            burst_limit=10,
            cooldown_seconds=30
        ),
        RateLimitTier.PREMIUM: RateLimitConfig(
            requests_per_minute=100,
            requests_per_hour=1000,
            requests_per_day=10000,
            burst_limit=20,
            cooldown_seconds=10
        ),
        RateLimitTier.ENTERPRISE: RateLimitConfig(
            requests_per_minute=300,
            requests_per_hour=3000,
            requests_per_day=50000,
            burst_limit=50,
            cooldown_seconds=0
        )
    }
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._local_cache: Dict[str, Dict[str, Any]] = {}
    
    def _get_key(self, identifier: str, window: str) -> str:
        """Generate Redis key for rate limit counter."""
        return f"ratelimit:{identifier}:{window}"
    
    async def is_allowed(
        self,
        identifier: str,
        tier: RateLimitTier = RateLimitTier.FREE
    ) -> tuple[bool, Dict[str, Any]]:
        """
        Check if request is allowed under rate limits.
        
        Returns:
            (allowed, headers) - headers contain limit info for response
        """
        config = self.DEFAULT_LIMITS[tier]
        now = time.time()
        
        # Check all time windows
        windows = [
            ("minute", 60, config.requests_per_minute),
            ("hour", 3600, config.requests_per_hour),
            ("day", 86400, config.requests_per_day)
        ]
        
        # Use local cache if no Redis
        if not self.redis:
            return self._check_local_cache(identifier, windows, now)
        
        # Check Redis-backed limits
        pipe = self.redis.pipeline()
        
        for window_name, window_sec, limit in windows:
            key = self._get_key(identifier, window_name)
            window_start = now - (now % window_sec)
            pipe.zcount(key, window_start, now)
        
        results = await pipe.execute()
        
        # Check if any limit exceeded
        for i, (window_name, window_sec, limit) in enumerate(windows):
            count = results[i]
            
            if count >= limit:
                # Rate limit exceeded
                headers = {
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Window": window_name,
                    "Retry-After": str(window_sec - int(now % window_sec))
                }
                return False, headers
        
        # All checks passed - record request
        for window_name, window_sec, _ in windows:
            key = self._get_key(identifier, window_name)
            window_start = now - (now % window_sec)
            await self.redis.zadd(key, {str(now): now})
            await self.redis.expire(key, window_sec)
        
        # Return success headers
        headers = {
            "X-RateLimit-Limit": str(config.requests_per_minute),
            "X-RateLimit-Remaining": str(config.requests_per_minute - results[0] - 1)
        }
        
        return True, headers
    
    def _check_local_cache(
        self,
        identifier: str,
        windows: list,
        now: float
    ) -> tuple[bool, Dict[str, Any]]:
        """Fallback to local cache if Redis unavailable."""
        key = f"local:{identifier}"
        
        if key not in self._local_cache:
            self._local_cache[key] = {"requests": []}
        
        cache = self._local_cache[key]
        
        # Clean old requests
        for window_name, window_sec, limit in windows:
            cutoff = now - window_sec
            cache["requests"] = [r for r in cache["requests"] if r["time"] > cutoff]
            
            count = len([r for r in cache["requests"] if r["time"] > now - window_sec])
            
            if count >= limit:
                return False, {
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": str(window_sec)
                }
        
        # Record request
        cache["requests"].append({"time": now})
        
        return True, {
            "X-RateLimit-Limit": "10",
            "X-RateLimit-Remaining": "9"
        }
    
    async def get_current_usage(self, identifier: str) -> Dict[str, int]:
        """Get current rate limit usage."""
        if not self.redis:
            return {"minute": 0, "hour": 0, "day": 0}
        
        now = time.time()
        windows = [("minute", 60), ("hour", 3600), ("day", 86400)]
        
        pipe = self.redis.pipeline()
        for window_name, window_sec in windows:
            key = self._get_key(identifier, window_name)
            window_start = now - (now % window_sec)
            pipe.zcount(key, window_start, now)
        
        results = await pipe.execute()
        
        return {
            "minute": results[0],
            "hour": results[1],
            "day": results[2]
        }


class DDoSProtection:
    """
    DDoS protection with request fingerprinting and blocking.
    """
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.block_threshold = 100  # requests in 1 minute to trigger block
        self.block_duration = 3600  # 1 hour block
    
    def _fingerprint_request(
        self,
        ip: str,
        user_agent: str,
        path: str
    ) -> str:
        """Create fingerprint for request pattern detection."""
        data = f"{ip}:{user_agent}:{path}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    async def check_request(
        self,
        ip: str,
        user_agent: str,
        path: str
    ) -> tuple[bool, Optional[str]]:
        """
        Check if request should be allowed.
        
        Returns:
            (allowed, block_reason)
        """
        # Check if IP is blocked
        if await self._is_blocked(ip):
            return False, "IP temporarily blocked due to suspicious activity"
        
        # Check request pattern
        fingerprint = self._fingerprint_request(ip, user_agent, path)
        
        if self.redis:
            key = f"ddos:fingerprint:{fingerprint}"
            count = await self.redis.incr(key)
            
            if count == 1:
                await self.redis.expire(key, 60)
            
            if count > self.block_threshold:
                await self._block_ip(ip, "Suspicious request pattern detected")
                return False, "Request pattern flagged as suspicious"
        
        return True, None
    
    async def _is_blocked(self, ip: str) -> bool:
        """Check if IP is blocked."""
        if not self.redis:
            return False
        
        key = f"ddos:blocked:{ip}"
        return await self.redis.exists(key)
    
    async def _block_ip(self, ip: str, reason: str) -> None:
        """Block an IP address."""
        if not self.redis:
            return
        
        key = f"ddos:blocked:{ip}"
        await self.redis.setex(key, self.block_duration, reason)
        logger.warning(f"Blocked IP {ip}: {reason}")


class APIProtection:
    """
    Combined API protection with rate limiting and DDoS protection.
    """
    
    def __init__(self, redis_client=None):
        self.rate_limiter = RateLimiter(redis_client)
        self.ddos_protection = DDoSProtection(redis_client)
    
    async def protect_request(
        self,
        request_data: Dict[str, Any]
    ) -> tuple[bool, Dict[str, Any], Optional[str]]:
        """
        Apply all protection checks to a request.
        
        Args:
            request_data: Dict with ip, user_agent, path, user_id, tier
        
        Returns:
            (allowed, headers, error_message)
        """
        ip = request_data.get("ip", "unknown")
        user_agent = request_data.get("user_agent", "")
        path = request_data.get("path", "/")
        user_id = request_data.get("user_id")
        tier = request_data.get("tier", RateLimitTier.FREE)
        
        # DDoS check first
        allowed, reason = await self.ddos_protection.check_request(ip, user_agent, path)
        if not allowed:
            return False, {}, reason
        
        # Rate limiting
        identifier = user_id or ip
        allowed, headers = await self.rate_limiter.is_allowed(identifier, tier)
        
        if not allowed:
            return False, headers, "Rate limit exceeded"
        
        return True, headers, None


# Decorators for easy integration
def rate_limited(
    tier_func: Optional[Callable] = None,
    skip_for: Optional[list] = None
):
    """Decorator to add rate limiting to endpoints."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Get request info from FastAPI context
            from fastapi import Request
            
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            
            if not request:
                return await func(*args, **kwargs)
            
            # Check if path should skip rate limiting
            if skip_for and request.url.path in skip_for:
                return await func(*args, **kwargs)
            
            # Get user tier
            tier = RateLimitTier.FREE
            if tier_func:
                tier = await tier_func(request)
            
            # Build request data
            request_data = {
                "ip": request.client.host if request.client else "unknown",
                "user_agent": request.headers.get("user-agent", ""),
                "path": request.url.path,
                "user_id": getattr(request.state, "user_id", None),
                "tier": tier
            }
            
            # Apply protection
            protection = APIProtection()  # Use global instance
            allowed, headers, error = await protection.protect_request(request_data)
            
            if not allowed:
                from fastapi import HTTPException
                raise HTTPException(status_code=429, detail=error, headers=headers)
            
            # Call original function
            response = await func(*args, **kwargs)
            
            # Add rate limit headers to response
            if hasattr(response, "headers"):
                response.headers.update(headers)
            
            return response
        
        return wrapper
    return decorator


# Global protection instance
_protection: Optional[APIProtection] = None


def get_api_protection() -> APIProtection:
    """Get global API protection instance."""
    global _protection
    if _protection is None:
        _protection = APIProtection()
    return _protection


def get_rate_limiter() -> RateLimiter:
    """Get global rate limiter."""
    return get_api_protection().rate_limiter
