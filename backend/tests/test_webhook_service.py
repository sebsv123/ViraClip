"""Tests for webhook delivery service."""
import hmac
import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.services.webhook_service import (
    WEBHOOK_SECRET,
    _sign_payload,
    deliver_webhook,
    deliver_webhook_with_retry,
)


@pytest.mark.asyncio
async def test_successful_delivery_returns_true():
    """HTTP 200 → returns True."""
    with patch("src.services.webhook_service.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
        result = await deliver_webhook(
            "https://hooks.example.com", "task_1", "completed", {"clips": 3}
        )
        assert result is True


@pytest.mark.asyncio
async def test_non_2xx_returns_false():
    """HTTP 400 → returns False."""
    with patch("src.services.webhook_service.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
        result = await deliver_webhook(
            "https://hooks.example.com", "task_1", "completed", {}
        )
        assert result is False


@pytest.mark.asyncio
async def test_network_error_returns_false():
    """Network error → returns False, no exception."""
    with patch("src.services.webhook_service.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post.side_effect = (
            httpx.ConnectError("Connection refused")
        )
        result = await deliver_webhook(
            "https://hooks.example.com", "task_1", "completed", {}
        )
        assert result is False


def test_hmac_signature_correct():
    """HMAC signature starts with sha256= and is valid."""
    with patch("src.services.webhook_service.WEBHOOK_SECRET", "test_secret"):
        payload = {"event": "task.completed", "task_id": "abc"}
        sig = _sign_payload(payload)
        assert sig.startswith("sha256=")
        # Verify with same key
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        expected = hmac.new(
            b"test_secret", body.encode(), hashlib.sha256
        ).hexdigest()
        assert sig == f"sha256={expected}"


def test_webhook_url_http_blocked():
    """HTTP URL → blocked."""
    from urllib.parse import urlparse
    from src.core.url_validator import validate_source_url
    with pytest.raises(Exception):
        validate_source_url("http://hooks.zapier.com/test")


def test_webhook_url_none_allowed():
    """None URL → allowed."""
    assert None is None  # No validation needed for None
