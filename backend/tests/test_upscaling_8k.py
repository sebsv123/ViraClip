"""
Phase 9.3 — 8K Upscaling Service Tests
======================================
Test the 8K/Hollywood-quality upscaling service with mocked GPU operations.

Run with: docker-compose exec backend .venv/bin/python -m pytest tests/test_upscaling_8k.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# Ensure imports work in Docker context
if "/app/src" not in sys.path:
    sys.path.insert(0, "/app/src")


class TestUpscale8KService:
    """Test the 8K upscaling service."""

    @pytest.fixture
    def mock_8k_service(self):
        """Create an Upscale8KService with mocked GPU."""
        from services.upscaling_8k_service import Upscale8KService
        svc = Upscale8KService()
        return svc

    @pytest.mark.asyncio
    async def test_8k_service_initialization(self, mock_8k_service):
        """Test service initializes correctly."""
        assert mock_8k_service.model == "realesrgan"
        assert mock_8k_service.out_dir.exists()

    @pytest.mark.asyncio
    async def test_upscale_8k_direct_mode_fallback(self, mock_8k_service, tmp_path):
        """Test 8K upscaling falls back to FFmpeg when GPU unavailable."""
        # Create dummy input file
        input_file = tmp_path / "test_1080p.mp4"
        input_file.touch()

        with patch.object(mock_8k_service, 'is_available', return_value=False):
            with patch.object(mock_8k_service, '_ffmpeg_scale', new_callable=AsyncMock) as mock_scale:
                result = await mock_8k_service.upscale_8k(
                    str(input_file),
                    mode="direct"
                )

        assert result["mode"] == "ffmpeg_fallback"
        assert result["output_resolution"] == "7680x4320"
        assert "processing_time_sec" in result
        mock_scale.assert_called_once()

    @pytest.mark.asyncio
    async def test_upscale_8k_gpu_unavailable_uses_lanczos(self, mock_8k_service, tmp_path):
        """Test that GPU unavailability triggers lanczos fallback."""
        input_file = tmp_path / "test.mp4"
        input_file.touch()

        with patch.object(mock_8k_service, 'is_available', return_value=False):
            with patch.object(mock_8k_service, '_probe_resolution', return_value=(1920, 1080)):
                with patch.object(mock_8k_service, '_ffmpeg_scale', new_callable=AsyncMock) as mock_ffmpeg:
                    result = await mock_8k_service.upscale_8k(
                        str(input_file),
                        mode="direct"
                    )

        # Verify FFmpeg was called with 8K dimensions
        mock_ffmpeg.assert_called_once()
        call_args = mock_ffmpeg.call_args
        assert call_args[0][2] == 7680  # width
        assert call_args[0][3] == 4320  # height

    @pytest.mark.asyncio
    async def test_upscale_4k_success(self, mock_8k_service, tmp_path):
        """Test 4K upscaling produces correct output."""
        input_file = tmp_path / "test_1080p.mp4"
        input_file.touch()

        with patch.object(mock_8k_service, 'is_available', return_value=False):
            with patch.object(mock_8k_service, '_probe_resolution', return_value=(1920, 1080)):
                with patch.object(mock_8k_service, '_ffmpeg_scale', new_callable=AsyncMock):
                    result = await mock_8k_service.upscale_4k(str(input_file))

        assert result["original_resolution"] == "1920x1080"
        assert "output_path" in result
        assert "processing_time_sec" in result

    @pytest.mark.asyncio
    async def test_upscale_8k_invalid_source_too_large(self, mock_8k_service, tmp_path):
        """Test that source larger than 8K raises error."""
        input_file = tmp_path / "test_16k.mp4"
        input_file.touch()

        with patch.object(mock_8k_service, '_probe_resolution', return_value=(15360, 8640)):
            with pytest.raises(ValueError, match="larger than 8K"):
                await mock_8k_service.upscale_8k(str(input_file))

    @pytest.mark.asyncio
    async def test_upscale_8k_invalid_mode(self, mock_8k_service, tmp_path):
        """Test that invalid mode raises error."""
        input_file = tmp_path / "test.mp4"
        input_file.touch()

        with patch.object(mock_8k_service, 'is_available', return_value=True):
            with patch.object(mock_8k_service, '_probe_resolution', return_value=(1920, 1080)):
                with pytest.raises(ValueError, match="Unknown mode"):
                    await mock_8k_service.upscale_8k(str(input_file), mode="invalid")

    def test_estimate_quality_direct_mode(self, mock_8k_service):
        """Test PSNR estimation for direct mode."""
        psnr = mock_8k_service._estimate_quality(1920, 1080, "direct")
        assert 25 <= psnr <= 35  # Typical ESRGAN range

    def test_estimate_quality_dual_mode(self, mock_8k_service):
        """Test PSNR estimation for dual mode (should be higher)."""
        direct_psnr = mock_8k_service._estimate_quality(1920, 1080, "direct")
        dual_psnr = mock_8k_service._estimate_quality(1920, 1080, "dual")
        assert dual_psnr > direct_psnr  # Dual should be better

    def test_estimate_quality_4k_source(self, mock_8k_service):
        """Test PSNR estimation for 4K source (should be higher)."""
        psnr_1080p = mock_8k_service._estimate_quality(1920, 1080, "direct")
        psnr_4k = mock_8k_service._estimate_quality(3840, 2160, "direct")
        assert psnr_4k > psnr_1080p  # 4K source should produce better results

    def test_get_8k_info(self, mock_8k_service):
        """Test 8K capability info returns correct structure."""
        with patch('torch.cuda.is_available', return_value=True):
            with patch('torch.cuda.get_device_properties') as mock_props:
                mock_props.return_value.total_memory = 12 * 1024**3  # 12GB
                info = mock_8k_service.get_8k_info()

        assert "8k_supported" in info
        assert "vram_gb" in info
        assert "recommended_mode" in info
        assert info["target_resolution"] == "7680x4320"

    def test_get_8k_info_low_vram(self, mock_8k_service):
        """Test 8K info with low VRAM (<8GB)."""
        with patch('torch.cuda.is_available', return_value=True):
            with patch('torch.cuda.get_device_properties') as mock_props:
                mock_props.return_value.total_memory = 6 * 1024**3  # 6GB
                info = mock_8k_service.get_8k_info()

        assert info["8k_supported"] is False

    def test_get_8k_info_high_vram(self, mock_8k_service):
        """Test 8K info with high VRAM (>=12GB)."""
        with patch('torch.cuda.is_available', return_value=True):
            with patch('torch.cuda.get_device_properties') as mock_props:
                mock_props.return_value.total_memory = 16 * 1024**3  # 16GB
                info = mock_8k_service.get_8k_info()

        assert info["8k_supported"] is True
        assert info["recommended_mode"] == "dual"

    @pytest.mark.asyncio
    async def test_apply_denoise_success(self, mock_8k_service, tmp_path):
        """Test denoising pre-processing."""
        input_file = tmp_path / "test.mp4"
        input_file.touch()

        with patch('asyncio.create_subprocess_exec') as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_exec.return_value = mock_proc

            result = await mock_8k_service._apply_denoise(input_file)

        mock_exec.assert_called_once()
        # Check afftdn filter is in the command
        call_args = mock_exec.call_args[0]
        assert any("afftdn" in str(arg) for arg in call_args)

    @pytest.mark.asyncio
    async def test_apply_denoise_failure_uses_original(self, mock_8k_service, tmp_path):
        """Test denoising failure falls back to original."""
        input_file = tmp_path / "test.mp4"
        input_file.touch()

        with patch('asyncio.create_subprocess_exec') as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 1  # Failure
            mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))
            mock_exec.return_value = mock_proc

            result = await mock_8k_service._apply_denoise(input_file)

        assert result == input_file  # Returns original on failure


class TestResolutionConstants:
    """Test the 8K resolution constants."""

    def test_8k_resolution_values(self):
        """Verify 8K resolution constants are correct."""
        from services.upscaling_8k_service import K8_WIDTH, K8_HEIGHT, K4_WIDTH, K4_HEIGHT

        assert K8_WIDTH == 7680
        assert K8_HEIGHT == 4320
        assert K4_WIDTH == 3840
        assert K4_HEIGHT == 2160

        # Verify aspect ratio is 16:9
        assert K8_WIDTH / K8_HEIGHT == 16 / 9
        assert K4_WIDTH / K4_HEIGHT == 16 / 9


class Test8KModes:
    """Test different 8K upscaling modes."""

    @pytest.mark.asyncio
    async def test_direct_mode_calls_4x_upscale(self):
        """Test direct mode uses 4× model."""
        from services.upscaling_8k_service import Upscale8KService
        svc = Upscale8KService()

        with patch.object(svc, '_upscale_sync') as mock_sync:
            mock_sync.return_value = "7680x4320"
            with patch.object(svc, 'is_available', return_value=True):
                with patch.object(svc, '_probe_resolution', return_value=(1920, 1080)):
                    await svc.upscale_8k("/tmp/test.mp4", mode="direct")

        mock_sync.assert_called_once()
        # Check it was called with scale=4 (realesrgan model)
        # Arguments: (src, dest, model_name, scale)
        call_args = mock_sync.call_args[0]
        assert call_args[2] == "realesrgan"  # 4× model name
        assert call_args[3] == 4  # scale factor


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
