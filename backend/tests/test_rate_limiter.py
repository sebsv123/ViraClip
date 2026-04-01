"""
Tests for rate limiting functionality.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from src.middleware.rate_limiter import RateLimiter, get_client_identifier
from fastapi import Request


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis_mock = AsyncMock()
    redis_mock.pipeline.return_value = redis_mock
    redis_mock.zremrangebyscore.return_value = redis_mock
    redis_mock.zcard.return_value = redis_mock
    redis_mock.zadd.return_value = redis_mock
    redis_mock.expire.return_value = redis_mock
    redis_mock.execute.return_value = [None, 0, None, None]  # request_count = 0
    return redis_mock


@pytest.fixture
def rate_limiter(mock_redis):
    """Create rate limiter with mocked Redis."""
    return RateLimiter(redis_client=mock_redis)


@pytest.mark.asyncio
async def test_rate_limit_allows_first_request(rate_limiter, mock_redis):
    """Test that first request is always allowed."""
    mock_redis.execute.return_value = [None, 0, None, None]
    
    allowed, headers = await rate_limiter.check_rate_limit("user123", "api_general")
    
    assert allowed is True
    assert headers is not None
    assert "X-RateLimit-Limit" in headers
    assert headers["X-RateLimit-Limit"] == "100"  # api_general limit


@pytest.mark.asyncio
async def test_rate_limit_blocks_when_exceeded(rate_limiter, mock_redis):
    """Test that requests are blocked when limit exceeded."""
    # Simulate 100 requests already made (at limit)
    mock_redis.execute.return_value = [None, 100, None, None]
    
    allowed, headers = await rate_limiter.check_rate_limit("user123", "api_general")
    
    assert allowed is False
    assert headers is not None
    assert "Retry-After" in headers


@pytest.mark.asyncio
async def test_rate_limit_headers_accurate(rate_limiter, mock_redis):
    """Test that rate limit headers show correct remaining count."""
    # 50 requests made out of 100
    mock_redis.execute.return_value = [None, 50, None, None]
    
    allowed, headers = await rate_limiter.check_rate_limit("user123", "api_general")
    
    assert allowed is True
    assert int(headers["X-RateLimit-Remaining"]) == 49  # 100 - 50 - 1


@pytest.mark.asyncio
async def test_different_limit_types():
    """Test that different limit types have different thresholds."""
    limiter = RateLimiter()
    
    # Check limits are configured correctly
    assert limiter.limits["api_general"] == (100, 60)
    assert limiter.limits["video_upload"] == (5, 3600)
    assert limiter.limits["task_create"] == (10, 300)
    assert limiter.limits["admin"] == (1000, 60)


@pytest.mark.asyncio
async def test_graceful_degradation_no_redis():
    """Test that rate limiter allows all when Redis unavailable."""
    limiter = RateLimiter(redis_client=None)
    
    allowed, headers = await limiter.check_rate_limit("user123", "api_general")
    
    assert allowed is True  # Should allow when Redis down
    assert headers is None


@pytest.mark.asyncio
async def test_reset_limit(rate_limiter, mock_redis):
    """Test resetting rate limit for a user."""
    mock_redis.delete = AsyncMock()
    
    await rate_limiter.reset_limit("user123", "api_general")
    
    mock_redis.delete.assert_called_once()


def test_get_client_identifier_authenticated():
    """Test identifier extraction for authenticated users."""
    request = MagicMock(spec=Request)
    request.state.user_id = "user123"
    request.client = None
    
    identifier = get_client_identifier(request)
    
    assert identifier == "user:user123"


def test_get_client_identifier_anonymous():
    """Test identifier extraction for anonymous users (IP-based)."""
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    request.state.user_id = None
    request.client = MagicMock()
    request.client.host = "192.168.1.1"
    request.headers = {}
    
    identifier = get_client_identifier(request)
    
    assert identifier == "ip:192.168.1.1"


def test_get_client_identifier_with_proxy():
    """Test identifier extraction behind proxy (X-Forwarded-For)."""
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    request.state.user_id = None
    request.headers = {"X-Forwarded-For": "203.0.113.1, 192.168.1.1"}
    
    identifier = get_client_identifier(request)
    
    # Should use first IP in X-Forwarded-For chain
    assert identifier == "ip:203.0.113.1"


@pytest.mark.asyncio
async def test_rate_limit_unknown_type_fallback(rate_limiter, mock_redis):
    """Test that unknown limit types fall back to api_general."""
    mock_redis.execute.return_value = [None, 0, None, None]
    
    allowed, headers = await rate_limiter.check_rate_limit("user123", "unknown_type")
    
    assert allowed is True
    assert headers["X-RateLimit-Limit"] == "100"  # Falls back to api_general


@pytest.mark.asyncio
async def test_rate_limit_concurrent_requests(rate_limiter, mock_redis):
    """Test rate limiter with concurrent requests."""
    # Simulate varying request counts
    counts = [10, 20, 30, 40, 50]
    
    async def check_limit(count):
        mock_redis.execute.return_value = [None, count, None, None]
        return await rate_limiter.check_rate_limit("user123", "api_general")
    
    results = await asyncio.gather(*[check_limit(c) for c in counts])
    
    # All should be allowed (under 100 limit)
    assert all(allowed for allowed, _ in results)
