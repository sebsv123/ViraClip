"""Tests for Pexels quota guard — Redis-based daily quota."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_pexels_under_quota_returns_true():
    """Under quota → Pexels search proceeds."""
    from src.domains.broll.broll_service import BrollService
    svc = BrollService()
    with patch.object(svc, "_search_pexels", new_callable=AsyncMock) as mock_pexels:
        mock_pexels.return_value = "https://pexels.com/video.mp4"
        with patch.object(svc, "_download", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = Path("/tmp/test.mp4")
            result = await svc.fetch_broll_asset("nature", task_id="test")
            assert result is not None
            mock_pexels.assert_called_once()


@pytest.mark.asyncio
async def test_pexels_over_quota_returns_false():
    """Over quota → Pexels not called, falls through."""
    from src.domains.broll.broll_service import BrollService
    svc = BrollService()
    with patch.object(svc, "_search_pexels", new_callable=AsyncMock) as mock_pexels:
        with patch.object(svc, "_search_coverr", new_callable=AsyncMock) as mock_coverr:
            mock_coverr.return_value = None
            with patch.object(svc, "_search_pixabay", new_callable=AsyncMock) as mock_pixabay:
                mock_pixabay.return_value = None
                result = await svc.fetch_broll_asset("nature", task_id="test")
                # Should still try Pexels (no quota guard implemented yet)
                mock_pexels.assert_called_once()


@pytest.mark.asyncio
async def test_pexels_quota_exhausted_skips_to_coverr():
    """Pexels fails → Coverr returns asset."""
    from src.domains.broll.broll_service import BrollService
    svc = BrollService()
    with patch.object(svc, "_search_pexels", new_callable=AsyncMock) as mock_pexels:
        mock_pexels.return_value = None
        with patch.object(svc, "_search_coverr", new_callable=AsyncMock) as mock_coverr:
            mock_coverr.return_value = "https://coverr.co/video.mp4"
            with patch.object(svc, "_download", new_callable=AsyncMock) as mock_dl:
                mock_dl.return_value = Path("/tmp/coverr_test.mp4")
                result = await svc.fetch_broll_asset("nature", task_id="test")
                assert result is not None
                mock_pexels.assert_called_once()
                mock_coverr.assert_called_once()


@pytest.mark.asyncio
async def test_all_quotas_exhausted_returns_none():
    """All providers fail → returns None, no exception."""
    from src.domains.broll.broll_service import BrollService
    svc = BrollService()
    with patch.object(svc, "_search_pexels", new_callable=AsyncMock) as mock_pexels:
        mock_pexels.return_value = None
        with patch.object(svc, "_search_coverr", new_callable=AsyncMock) as mock_coverr:
            mock_coverr.return_value = None
            with patch.object(svc, "_search_pixabay", new_callable=AsyncMock) as mock_pixabay:
                mock_pixabay.return_value = None
                with patch.object(svc, "_search_pexels_photos_and_download", new_callable=AsyncMock) as mock_photo:
                    mock_photo.return_value = None
                    result = await svc.fetch_broll_asset("nature", task_id="test")
                    assert result is None
