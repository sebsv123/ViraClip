"""
Tests for advanced caching functionality.
"""

import pytest
import json
import gzip
from unittest.mock import AsyncMock, MagicMock
from src.caching.advanced_cache import AdvancedCache, cached


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis_mock = AsyncMock()
    return redis_mock


@pytest.fixture
def cache(mock_redis):
    """Create cache with mocked Redis."""
    return AdvancedCache(redis_client=mock_redis)


@pytest.mark.asyncio
async def test_cache_get_miss(cache, mock_redis):
    """Test cache miss returns None."""
    mock_redis.get.return_value = None
    mock_redis.incr = AsyncMock()
    mock_redis.expire = AsyncMock()
    
    result = await cache.get("test_namespace", "test_id")
    
    assert result is None
    mock_redis.get.assert_called_once()


@pytest.mark.asyncio
async def test_cache_get_hit(cache, mock_redis):
    """Test cache hit returns deserialized value."""
    test_data = {"key": "value", "number": 123}
    json_data = json.dumps(test_data)
    mock_redis.get.return_value = json_data.encode('utf-8')
    mock_redis.incr = AsyncMock()
    mock_redis.expire = AsyncMock()
    
    result = await cache.get("test_namespace", "test_id")
    
    assert result == test_data


@pytest.mark.asyncio
async def test_cache_get_compressed(cache, mock_redis):
    """Test cache can decompress gzipped values."""
    test_data = {"key": "value" * 1000}  # Large data
    json_data = json.dumps(test_data)
    compressed = b"GZIP:" + gzip.compress(json_data.encode('utf-8'))
    
    mock_redis.get.return_value = compressed
    mock_redis.incr = AsyncMock()
    mock_redis.expire = AsyncMock()
    
    result = await cache.get("test_namespace", "test_id")
    
    assert result == test_data


@pytest.mark.asyncio
async def test_cache_set(cache, mock_redis):
    """Test setting value in cache."""
    test_data = {"key": "value"}
    mock_redis.setex = AsyncMock()
    
    success = await cache.set("test_namespace", "test_id", test_data, ttl=3600)
    
    assert success is True
    mock_redis.setex.assert_called_once()
    
    # Verify it was serialized to JSON
    call_args = mock_redis.setex.call_args
    assert call_args[0][1] == 3600  # TTL
    # Value should be JSON-encoded
    stored_value = call_args[0][2].decode('utf-8')
    assert json.loads(stored_value) == test_data


@pytest.mark.asyncio
async def test_cache_set_with_compression(cache, mock_redis):
    """Test that large values are automatically compressed."""
    # Create large data that exceeds compression threshold
    test_data = {"key": "x" * 2000}
    mock_redis.setex = AsyncMock()
    
    await cache.set("test_namespace", "test_id", test_data)
    
    # Verify compression was applied
    call_args = mock_redis.setex.call_args
    stored_value = call_args[0][2]
    assert stored_value.startswith(b"GZIP:")


@pytest.mark.asyncio
async def test_cache_delete(cache, mock_redis):
    """Test deleting from cache."""
    mock_redis.delete = AsyncMock()
    
    success = await cache.delete("test_namespace", "test_id")
    
    assert success is True
    mock_redis.delete.assert_called_once()


@pytest.mark.asyncio
async def test_cache_invalidate_pattern(cache, mock_redis):
    """Test invalidating multiple keys by pattern."""
    # Mock scan_iter to return some keys
    async def mock_scan():
        for key in [b"cache:test:1", b"cache:test:2", b"cache:test:3"]:
            yield key
    
    mock_redis.scan_iter = MagicMock(return_value=mock_scan())
    mock_redis.delete = AsyncMock(return_value=3)
    
    deleted = await cache.invalidate_pattern("cache:test:*")
    
    assert deleted == 3
    mock_redis.delete.assert_called_once()


@pytest.mark.asyncio
async def test_cache_ttl_defaults():
    """Test that default TTLs are configured correctly."""
    cache = AdvancedCache()
    
    assert cache.ttls["transcript"] == 86400 * 7  # 7 days
    assert cache.ttls["ai_analysis"] == 86400 * 3  # 3 days
    assert cache.ttls["video_metadata"] == 86400  # 1 day
    assert cache.ttls["user_prefs"] == 3600  # 1 hour


@pytest.mark.asyncio
async def test_cache_get_metrics(cache, mock_redis):
    """Test getting cache metrics."""
    # Mock scan_iter for metrics
    async def mock_scan():
        for key in [
            b"cache_metrics:transcript:hit",
            b"cache_metrics:transcript:miss",
            b"cache_metrics:ai_analysis:hit"
        ]:
            yield key
    
    mock_redis.scan_iter = MagicMock(return_value=mock_scan())
    mock_redis.get = AsyncMock(side_effect=[b"100", b"10", b"50"])
    
    metrics = await cache.get_metrics()
    
    assert "transcript" in metrics
    assert metrics["transcript"]["hits"] == 100
    assert metrics["transcript"]["misses"] == 10
    assert "hit_rate" in metrics["transcript"]


@pytest.mark.asyncio
async def test_cached_decorator():
    """Test @cached decorator caches function results."""
    call_count = 0
    
    @cached("test_namespace", ttl=60)
    async def expensive_function(arg1, arg2):
        nonlocal call_count
        call_count += 1
        return {"result": arg1 + arg2}
    
    # Mock the cache
    from src.caching import advanced_cache
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(return_value=None)  # First call: cache miss
    mock_cache.set = AsyncMock()
    advanced_cache._cache = mock_cache
    
    result1 = await expensive_function(1, 2)
    
    assert result1 == {"result": 3}
    assert call_count == 1
    mock_cache.set.assert_called_once()


@pytest.mark.asyncio
async def test_graceful_degradation_no_redis():
    """Test cache gracefully degrades when Redis unavailable."""
    cache = AdvancedCache(redis_client=None)
    
    # All operations should return safely without errors
    result = await cache.get("test", "id")
    assert result is None
    
    success = await cache.set("test", "id", {"data": "value"})
    assert success is False
    
    success = await cache.delete("test", "id")
    assert success is False
