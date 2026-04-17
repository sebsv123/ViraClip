"""
Tests for GPU detection and encoding settings.

Validates that GPU detection works across NVIDIA/AMD/Intel/CPU.
"""

import pytest
from unittest.mock import patch, MagicMock
from src.utils.gpu_detection import (
    detect_gpu,
    GPUType,
    get_optimal_render_concurrency,
    _detect_nvidia,
    _detect_amd,
    _detect_intel,
)


def test_detect_nvidia_via_torch():
    """Test NVIDIA detection via PyTorch CUDA."""
    with patch('src.utils.gpu_detection.torch') as mock_torch:
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.get_device_name.return_value = "NVIDIA RTX 3080"
        
        gpu_type, settings = _detect_nvidia()
        
        assert gpu_type == GPUType.NVIDIA_NVENC
        assert settings["codec"] == "h264_nvenc"
        assert "preset" in settings


def test_detect_nvidia_via_nvidia_smi():
    """Test NVIDIA detection via nvidia-smi."""
    with patch('src.utils.gpu_detection.torch', side_effect=ImportError):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="NVIDIA GeForce RTX 3090\n"
            )
            
            gpu_type, settings = _detect_nvidia()
            
            assert gpu_type == GPUType.NVIDIA_NVENC
            assert settings["codec"] == "h264_nvenc"


def test_detect_nvidia_not_available():
    """Test when NVIDIA GPU is not available."""
    with patch('src.utils.gpu_detection.torch', new=None):
        with patch('subprocess.run', side_effect=FileNotFoundError):
            gpu_type, settings = _detect_nvidia()
            
            assert gpu_type == GPUType.CPU_ONLY
            assert settings == {}


def test_detect_amd():
    """Test AMD GPU detection."""
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="h264_amf\nhevc_amf\nlibx264\n"
        )
        
        gpu_type, settings = _detect_amd()
        
        assert gpu_type == GPUType.AMD_VCE
        assert settings["codec"] == "h264_amf"


def test_detect_intel():
    """Test Intel QuickSync detection."""
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="h264_qsv\nhevc_qsv\nlibx264\n"
        )
        
        gpu_type, settings = _detect_intel()
        
        assert gpu_type == GPUType.INTEL_QSV
        assert settings["codec"] == "h264_qsv"


def test_detect_gpu_caching():
    """Test that GPU detection is cached."""
    # Reset cache
    import src.utils.gpu_detection as gpu_module
    gpu_module._gpu_cache = None
    
    with patch('src.utils.gpu_detection._detect_nvidia') as mock_detect:
        mock_detect.return_value = (GPUType.NVIDIA_NVENC, {"codec": "h264_nvenc"})
        
        # First call
        gpu_type1, settings1 = detect_gpu()
        # Second call (should use cache)
        gpu_type2, settings2 = detect_gpu()
        
        # Should only detect once
        assert mock_detect.call_count == 1
        assert gpu_type1 == gpu_type2
        assert settings1 == settings2


def test_get_optimal_render_concurrency_nvidia():
    """Test concurrency recommendation for NVIDIA GPU."""
    with patch('src.utils.gpu_detection.detect_gpu') as mock_detect:
        mock_detect.return_value = (GPUType.NVIDIA_NVENC, {})
        
        concurrency = get_optimal_render_concurrency()
        
        assert concurrency == 4  # NVIDIA gets 4


def test_get_optimal_render_concurrency_amd():
    """Test concurrency recommendation for AMD GPU."""
    with patch('src.utils.gpu_detection.detect_gpu') as mock_detect:
        mock_detect.return_value = (GPUType.AMD_VCE, {})
        
        concurrency = get_optimal_render_concurrency()
        
        assert concurrency == 3  # AMD gets 3


def test_get_optimal_render_concurrency_cpu():
    """Test concurrency recommendation for CPU-only."""
    with patch('src.utils.gpu_detection.detect_gpu') as mock_detect:
        mock_detect.return_value = (GPUType.CPU_ONLY, {})
        
        concurrency = get_optimal_render_concurrency()
        
        assert concurrency == 2  # CPU gets 2


def test_nvenc_settings_structure():
    """Validate NVENC settings structure."""
    from src.utils.gpu_detection import _get_nvenc_settings
    
    settings = _get_nvenc_settings()
    
    assert "codec" in settings
    assert "preset" in settings
    assert "audio_codec" in settings
    assert "ffmpeg_params" in settings
    assert isinstance(settings["ffmpeg_params"], list)


def test_cpu_settings_structure():
    """Validate CPU settings structure."""
    from src.utils.gpu_detection import _get_cpu_settings
    
    settings = _get_cpu_settings()
    
    assert settings["codec"] == "libx264"
    assert "preset" in settings
    assert "audio_codec" in settings
    assert "ffmpeg_params" in settings
