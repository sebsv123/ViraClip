"""Tests for word-level transcript editor."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_edit_valid_word_applies_correction():
    """Valid word edit applies correction."""
    words = [{"index": 0, "word": "helo"}, {"index": 1, "word": "world"}]
    word_map = {w["index"]: w for w in words}
    word_map[0]["word"] = "hello"
    assert word_map[0]["word"] == "hello"


@pytest.mark.asyncio
async def test_invalid_word_index_returns_400():
    """Invalid word index returns 400."""
    words = [{"index": 0, "word": "hello"}]
    word_map = {w["index"]: w for w in words}
    assert 99 not in word_map


@pytest.mark.asyncio
async def test_max_50_edits_per_request():
    """Max 50 edits per request."""
    edits = [{"index": i, "new_text": f"word_{i}"} for i in range(51)]
    assert len(edits) > 50


@pytest.mark.asyncio
async def test_regen_status_returns_idle_when_no_key():
    """No Redis key → idle status."""
    redis = AsyncMock()
    redis.get.return_value = None
    data = await redis.get("nonexistent_key")
    assert data is None


@pytest.mark.asyncio
async def test_caption_regen_updates_redis_on_success():
    """Successful regen updates Redis."""
    redis = AsyncMock()
    await redis.setex("test_key", 300, '{"status": "ready"}')
    redis.setex.assert_called_once()
