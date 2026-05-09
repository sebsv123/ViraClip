"""Tests for signed share links."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from src.services.clip_share_link_service import (
    _generate_token,
    _verify_token,
    create_share_link,
    revoke_share_link,
)


def test_generate_and_verify_token():
    """Generated token verifies correctly."""
    expires = datetime.utcnow() + timedelta(hours=48)
    token = _generate_token("clip_123", expires)
    payload = _verify_token(token)
    assert payload is not None
    assert payload["clip_id"] == "clip_123"


def test_expired_token_returns_none():
    """Expired token → None."""
    expires = datetime.utcnow() - timedelta(hours=1)
    token = _generate_token("clip_123", expires)
    payload = _verify_token(token)
    assert payload is None


def test_tampered_token_returns_none():
    """Tampered token → None."""
    expires = datetime.utcnow() + timedelta(hours=48)
    token = _generate_token("clip_123", expires)
    tampered = token[:-5] + "XXXXX"
    payload = _verify_token(tampered)
    assert payload is None


@pytest.mark.asyncio
async def test_create_share_link_saves_to_redis():
    """create_share_link calls redis.setex with TTL."""
    redis = AsyncMock()
    redis.setex.return_value = True
    result = await create_share_link("clip_1", "user_1", redis, expiry_hours=48)
    assert "url" in result
    assert "token" in result
    assert result["expires_in_hours"] == 48
    redis.setex.assert_called_once()
    # Verify TTL is positive
    args, kwargs = redis.setex.call_args
    assert args[1] > 0  # TTL > 0


@pytest.mark.asyncio
async def test_revoke_share_link_deletes_redis_key():
    """revoke_share_link returns True when key deleted."""
    redis = AsyncMock()
    redis.delete.return_value = 1
    result = await revoke_share_link("clip_1", "token_abc", redis)
    assert result is True


@pytest.mark.asyncio
async def test_revoke_nonexistent_returns_false():
    """revoke_share_link returns False when key not found."""
    redis = AsyncMock()
    redis.delete.return_value = 0
    result = await revoke_share_link("clip_1", "nonexistent", redis)
    assert result is False
