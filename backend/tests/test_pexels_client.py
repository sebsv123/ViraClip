"""
Unit tests for PexelsClient (backend/src/services/pexels_client.py).

Tests cover:
- search_videos with valid results
- Empty results when no API key
- Joker terms fallback
- Retry on timeout
- 401 auth error (no retry)
- Video filtering (HD quality, dimensions, duration)
- search_videos_batch with multiple queries
- Graceful degradation on network errors
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List

from src.services.pexels_client import (
    PexelsClient,
    PexelsVideo,
    JOKER_TERMS,
    DURATION_BUFFER_SECONDS,
    RETRY_TIMES,
    ORIENTATION_DIMENSIONS,
    get_pexels_client,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def client():
    """PexelsClient with a fake API key."""
    return PexelsClient(api_key="test-key-123")


@pytest.fixture()
def mock_session():
    """Create a mock httpx.AsyncClient session."""
    session = AsyncMock()
    session.get = AsyncMock()
    session.aclose = AsyncMock()
    return session


def _make_raw_video(
    vid_id: int,
    duration: float = 10.0,
    width: int = 576,
    height: int = 1024,
    quality: str = "hd",
    file_type: str = "video/mp4",
) -> dict:
    """Helper to build a raw Pexels API video dict."""
    return {
        "id": vid_id,
        "duration": duration,
        "video_files": [
            {
                "id": vid_id * 100,
                "width": width,
                "height": height,
                "quality": quality,
                "file_type": file_type,
                "link": f"https://pexels.com/video/{vid_id}.mp4",
            }
        ],
    }


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestPexelsClientInit:
    """Client initialization and singleton."""

    def test_init_with_key(self):
        c = PexelsClient(api_key="abc")
        assert c.api_key == "abc"

    def test_init_without_key(self):
        c = PexelsClient()
        assert c.api_key is None

    def test_singleton(self):
        c1 = get_pexels_client("key-1")
        c2 = get_pexels_client("key-2")
        assert c1 is c2  # same instance
        # Cleanup: reset singleton for other tests
        import src.services.pexels_client as pc
        pc._pexels_client = None


class TestSearchVideosNoApiKey:
    """When no API key is configured, return empty list."""

    @pytest.mark.asyncio
    async def test_no_key_returns_empty(self):
        c = PexelsClient()  # no key
        result = await c.search_videos(query="test")
        assert result == []


class TestSearchVideosSuccess:
    """Happy path: API returns valid videos."""

    @pytest.mark.asyncio
    async def test_basic_search(self, client, mock_session):
        raw_videos = [
            _make_raw_video(1, duration=10.0, width=576, height=1024),
            _make_raw_video(2, duration=8.0, width=576, height=1024),
            _make_raw_video(3, duration=15.0, width=576, height=1024),
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = {"videos": raw_videos}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        with patch.object(client, "_get_session", return_value=mock_session):
            results = await client.search_videos(
                query="nature",
                min_duration=3.0,
                orientation="portrait",
            )

        assert len(results) > 0
        assert all(isinstance(v, PexelsVideo) for v in results)
        assert all(v.width == 576 and v.height == 1024 for v in results)
        assert all(v.duration >= 3.0 for v in results)

    @pytest.mark.asyncio
    async def test_search_landscape(self, client, mock_session):
        """Landscape orientation should match 1024x576."""
        raw_videos = [
            _make_raw_video(1, duration=10.0, width=1024, height=576),
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = {"videos": raw_videos}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        with patch.object(client, "_get_session", return_value=mock_session):
            results = await client.search_videos(
                query="landscape",
                min_duration=3.0,
                orientation="landscape",
            )

        assert len(results) == 1
        assert results[0].width == 1024
        assert results[0].height == 576

    @pytest.mark.asyncio
    async def test_search_square(self, client, mock_session):
        """Square orientation should match 640x640."""
        raw_videos = [
            _make_raw_video(1, duration=10.0, width=640, height=640),
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = {"videos": raw_videos}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        with patch.object(client, "_get_session", return_value=mock_session):
            results = await client.search_videos(
                query="square",
                min_duration=3.0,
                orientation="square",
            )

        assert len(results) == 1
        assert results[0].width == 640
        assert results[0].height == 640


class TestSearchVideosFiltering:
    """Video filtering logic."""

    @pytest.mark.asyncio
    async def test_duration_filter(self, client, mock_session):
        """Videos shorter than min_duration + buffer should be excluded."""
        raw_videos = [
            _make_raw_video(1, duration=2.0, width=576, height=1024),  # too short
            _make_raw_video(2, duration=7.0, width=576, height=1024),  # >= 3+3=6 ✓
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = {"videos": raw_videos}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        with patch.object(client, "_get_session", return_value=mock_session):
            results = await client.search_videos(
                query="test",
                min_duration=3.0,
                orientation="portrait",
            )

        assert len(results) == 1
        assert results[0].id == 2

    @pytest.mark.asyncio
    async def test_exclude_ids(self, client, mock_session):
        """Excluded IDs should not appear in results."""
        raw_videos = [
            _make_raw_video(1, duration=10.0, width=576, height=1024),
            _make_raw_video(2, duration=10.0, width=576, height=1024),
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = {"videos": raw_videos}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        with patch.object(client, "_get_session", return_value=mock_session):
            results = await client.search_videos(
                query="test",
                min_duration=3.0,
                exclude_ids=[1],
                orientation="portrait",
            )

        assert len(results) == 1
        assert results[0].id == 2

    @pytest.mark.asyncio
    async def test_non_hd_quality_excluded(self, client, mock_session):
        """Non-HD quality videos should be excluded."""
        raw_videos = [
            _make_raw_video(1, duration=10.0, width=576, height=1024, quality="hd"),
            _make_raw_video(2, duration=10.0, width=576, height=1024, quality="low"),
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = {"videos": raw_videos}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        with patch.object(client, "_get_session", return_value=mock_session):
            results = await client.search_videos(
                query="test",
                min_duration=3.0,
                orientation="portrait",
            )

        assert len(results) == 1
        assert results[0].id == 1

    @pytest.mark.asyncio
    async def test_non_mp4_excluded(self, client, mock_session):
        """Non-MP4 files should be excluded."""
        raw_videos = [
            _make_raw_video(1, duration=10.0, width=576, height=1024, file_type="video/mp4"),
            _make_raw_video(2, duration=10.0, width=576, height=1024, file_type="video/webm"),
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = {"videos": raw_videos}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        with patch.object(client, "_get_session", return_value=mock_session):
            results = await client.search_videos(
                query="test",
                min_duration=3.0,
                orientation="portrait",
            )

        assert len(results) == 1
        assert results[0].id == 1

    @pytest.mark.asyncio
    async def test_wrong_dimensions_excluded(self, client, mock_session):
        """Videos with wrong dimensions for orientation should be excluded."""
        raw_videos = [
            _make_raw_video(1, duration=10.0, width=1920, height=1080),  # wrong dims
            _make_raw_video(2, duration=10.0, width=576, height=1024),   # correct
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = {"videos": raw_videos}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        with patch.object(client, "_get_session", return_value=mock_session):
            results = await client.search_videos(
                query="test",
                min_duration=3.0,
                orientation="portrait",
            )

        assert len(results) == 1
        assert results[0].id == 2


class TestSearchVideosErrors:
    """Error handling and graceful degradation."""

    @pytest.mark.asyncio
    async def test_401_auth_error_no_retry(self, client, mock_session):
        """401 should return empty immediately, no retry."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = __import__("httpx").HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=MagicMock(status_code=401)
        )
        mock_session.get.return_value = mock_response

        with patch.object(client, "_get_session", return_value=mock_session):
            results = await client.search_videos(
                query="test",
                min_duration=3.0,
                orientation="portrait",
            )

        assert results == []
        # Should only have been called once (no retry on 401)
        assert mock_session.get.call_count == 1

    @pytest.mark.asyncio
    async def test_timeout_retry_then_success(self, client, mock_session):
        """Timeout should retry, and succeed on retry."""
        mock_response_success = MagicMock()
        mock_response_success.json.return_value = {
            "videos": [_make_raw_video(1, duration=10.0, width=576, height=1024)]
        }
        mock_response_success.raise_for_status = MagicMock()

        # First call times out, second succeeds
        mock_session.get.side_effect = [
            __import__("httpx").TimeoutException("Timeout"),
            mock_response_success,
        ]

        with patch.object(client, "_get_session", return_value=mock_session):
            results = await client.search_videos(
                query="test",
                min_duration=3.0,
                orientation="portrait",
            )

        assert len(results) == 1
        assert results[0].id == 1
        assert mock_session.get.call_count == 2

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self, client, mock_session):
        """After exhausting retries, return empty list."""
        mock_session.get.side_effect = __import__("httpx").TimeoutException("Timeout")

        with patch.object(client, "_get_session", return_value=mock_session):
            results = await client.search_videos(
                query="test",
                min_duration=3.0,
                orientation="portrait",
            )

        assert results == []
        # Should have retried RETRY_TIMES times
        assert mock_session.get.call_count == RETRY_TIMES

    @pytest.mark.asyncio
    async def test_network_error_graceful(self, client, mock_session):
        """Generic network error should be caught gracefully."""
        mock_session.get.side_effect = RuntimeError("Connection refused")

        with patch.object(client, "_get_session", return_value=mock_session):
            results = await client.search_videos(
                query="test",
                min_duration=3.0,
                orientation="portrait",
            )

        assert results == []


class TestJokerTermsFallback:
    """Joker terms fallback when primary query returns nothing."""

    @pytest.mark.asyncio
    async def test_joker_terms_used_when_primary_fails(self, client, mock_session):
        """When primary query returns nothing, joker terms should be tried."""
        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            # First call (primary query) returns empty
            if call_count == 1:
                resp.json.return_value = {"videos": []}
            else:
                # Subsequent calls (joker terms) return a video
                resp.json.return_value = {
                    "videos": [_make_raw_video(call_count, duration=10.0, width=576, height=1024)]
                }
            return resp

        mock_session.get = mock_get

        with patch.object(client, "_get_session", return_value=mock_session):
            results = await client.search_videos(
                query="obscure_topic",
                min_duration=3.0,
                orientation="portrait",
            )

        assert len(results) > 0
        # Should have tried at least 2 terms (primary + at least one joker)
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_all_terms_fail_returns_empty(self, client, mock_session):
        """When all terms (primary + joker) fail, return empty."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"videos": []}
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response

        with patch.object(client, "_get_session", return_value=mock_session):
            results = await client.search_videos(
                query="nothing",
                min_duration=3.0,
                orientation="portrait",
            )

        assert results == []


class TestSearchVideosBatch:
    """Batch search across multiple queries."""

    @pytest.mark.asyncio
    async def test_batch_multiple_queries(self, client, mock_session):
        """search_videos_batch should collect unique results from multiple queries."""
        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            # Return different videos for each query
            resp.json.return_value = {
                "videos": [
                    _make_raw_video(call_count * 10 + i, duration=10.0, width=576, height=1024)
                    for i in range(1, 4)
                ]
            }
            return resp

        mock_session.get = mock_get

        with patch.object(client, "_get_session", return_value=mock_session):
            results = await client.search_videos_batch(
                queries=["nature", "ocean", "space"],
                min_duration=3.0,
                orientation="portrait",
                max_per_query=2,
            )

        # Should have unique results, max 2 per query
        assert len(results) > 0
        assert len(results) <= 6  # 3 queries * max_per_query=2
        ids = [v.id for v in results]
        assert len(ids) == len(set(ids))  # all unique

    @pytest.mark.asyncio
    async def test_batch_deduplication(self, client, mock_session):
        """Same video ID from different queries should be deduplicated."""
        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            # Both queries return the same video ID
            resp.json.return_value = {
                "videos": [_make_raw_video(42, duration=10.0, width=576, height=1024)]
            }
            return resp

        mock_session.get = mock_get

        with patch.object(client, "_get_session", return_value=mock_session):
            results = await client.search_videos_batch(
                queries=["nature", "ocean"],
                min_duration=3.0,
                orientation="portrait",
                max_per_query=2,
            )

        assert len(results) == 1
        assert results[0].id == 42


class TestPexelsVideoDataclass:
    """PexelsVideo dataclass."""

    def test_dataclass_creation(self):
        v = PexelsVideo(id=1, url="https://example.com/v.mp4", width=576, height=1024, duration=10.0)
        assert v.id == 1
        assert v.url == "https://example.com/v.mp4"
        assert v.width == 576
        assert v.height == 1024
        assert v.duration == 10.0

    def test_dataclass_repr(self):
        v = PexelsVideo(id=1, url="https://example.com/v.mp4", width=576, height=1024, duration=10.0)
        r = repr(v)
        assert "PexelsVideo" in r
        assert "id=1" in r


class TestClientCleanup:
    """Client session cleanup."""

    @pytest.mark.asyncio
    async def test_close(self, client, mock_session):
        with patch.object(client, "_get_session", return_value=mock_session):
            session = await client._get_session()
            assert session is not None
            await client.close()
            assert client._session is None
            mock_session.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_no_session(self, client):
        """Closing when no session exists should not error."""
        await client.close()  # should not raise
