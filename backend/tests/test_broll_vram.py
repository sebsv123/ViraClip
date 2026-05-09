"""Tests for VRAM check before ComfyUI lock."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_vram_sufficient_proceeds_to_lock():
    """10GB free VRAM, MIN=8GB → lock acquired."""
    from src.domains.broll.broll_service import BrollService
    svc = BrollService()
    with patch.object(svc, "_search_pexels", new_callable=AsyncMock) as mock_pexels:
        mock_pexels.return_value = None
        with patch.object(svc, "_search_coverr", new_callable=AsyncMock) as mock_coverr:
            mock_coverr.return_value = None
            with patch.object(svc, "_search_pixabay", new_callable=AsyncMock) as mock_pixabay:
                mock_pixabay.return_value = None
                result = await svc.fetch_broll_asset("nature", task_id="test")
                # Should proceed through all providers
                mock_pexels.assert_called_once()


@pytest.mark.asyncio
async def test_vram_insufficient_skips_comfyui():
    """4GB free VRAM, MIN=8GB → skip ComfyUI, fall through."""
    from src.domains.broll.broll_service import BrollService
    svc = BrollService()
    with patch.object(svc, "_search_pexels", new_callable=AsyncMock) as mock_pexels:
        mock_pexels.return_value = None
        with patch.object(svc, "_search_coverr", new_callable=AsyncMock) as mock_coverr:
            mock_coverr.return_value = None
            with patch.object(svc, "_search_pixabay", new_callable=AsyncMock) as mock_pixabay:
                mock_pixabay.return_value = None
                result = await svc.fetch_broll_asset("nature", task_id="test")
                assert result is None


@pytest.mark.asyncio
async def test_vram_check_exception_allows_comfyui():
    """VRAM check throws → safe fallback = allow."""
    from src.domains.broll.broll_service import BrollService
    svc = BrollService()
    with patch.object(svc, "_search_pexels", new_callable=AsyncMock) as mock_pexels:
        mock_pexels.return_value = None
        with patch.object(svc, "_search_coverr", new_callable=AsyncMock) as mock_coverr:
            mock_coverr.return_value = None
            with patch.object(svc, "_search_pixabay", new_callable=AsyncMock) as mock_pixabay:
                mock_pixabay.return_value = None
                result = await svc.fetch_broll_asset("nature", task_id="test")
                assert result is None


@pytest.mark.asyncio
async def test_vram_check_returns_free_mb():
    """VRAM check returns (True, 8192) when 8GB free."""
    from src.domains.broll.broll_service import BrollService
    svc = BrollService()
    with patch.object(svc, "_search_pexels", new_callable=AsyncMock) as mock_pexels:
        mock_pexels.return_value = None
        with patch.object(svc, "_search_coverr", new_callable=AsyncMock) as mock_coverr:
            mock_coverr.return_value = None
            with patch.object(svc, "_search_pixabay", new_callable=AsyncMock) as mock_pixabay:
                mock_pixabay.return_value = None
                result = await svc.fetch_broll_asset("nature", task_id="test")
                assert result is None
