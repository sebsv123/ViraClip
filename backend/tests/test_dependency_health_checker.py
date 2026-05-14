"""
Tests for DependencyHealthChecker (Capa 0) and FeatureFlagManager.
"""

import os
import sys
from unittest.mock import patch, MagicMock
import pytest


@pytest.fixture(autouse=True)
def reset_feature_flags():
    """Reset FeatureFlagManager singleton before each test."""
    from src.core.feature_flags import FeatureFlagManager
    FeatureFlagManager.reset()
    yield
    FeatureFlagManager.reset()


class TestFeatureFlagManager:
    """Tests for the FeatureFlagManager singleton."""

    def test_singleton(self):
        from src.core.feature_flags import FeatureFlagManager
        a = FeatureFlagManager()
        b = FeatureFlagManager()
        assert a is b

    def test_default_all_true(self):
        from src.core.feature_flags import FEATURE_FLAGS
        flags = FEATURE_FLAGS.get_all()
        for key, val in flags.items():
            assert val is True, f"{key} should be True by default"

    def test_set_and_get(self):
        from src.core.feature_flags import FEATURE_FLAGS
        FEATURE_FLAGS.set("test_feature", False)
        assert FEATURE_FLAGS.get("test_feature") is False
        assert FEATURE_FLAGS.get("nonexistent", True) is True

    def test_get_all_returns_copy(self):
        from src.core.feature_flags import FEATURE_FLAGS
        flags = FEATURE_FLAGS.get_all()
        flags["test"] = False
        assert FEATURE_FLAGS.get("test", "not_found") == "not_found"

    def test_to_json(self):
        from src.core.feature_flags import FEATURE_FLAGS
        import json
        data = json.loads(FEATURE_FLAGS.to_json())
        assert isinstance(data, dict)


class TestDependencyHealthChecker:
    """Tests for DependencyHealthChecker."""

    def test_happy_path_all_available(self):
        """All dependencies available → all flags True."""
        from src.core.dependency_health_checker import DependencyHealthChecker
        from src.core.feature_flags import FEATURE_FLAGS
        import src.core.dependency_health_checker as _dhc

        _orig = _dhc.CHECKS
        _dhc.CHECKS = [
            ("numpy", lambda: (True, "NumPy 2.2.6"), "audio_spectral_analysis", ""),
            ("torchcodec", lambda: (True, "TorchCodec OK"), "narrative_cut_detection", ""),
            ("mediapipe", lambda: (True, "MediaPipe OK"), "face_tracking_mediapipe", ""),
            ("nvenc", lambda: (True, "NVENC OK"), "gpu_encode", ""),
            ("librosa", lambda: (True, "librosa OK"), "beat_sync_librosa", ""),
            ("ffmpeg", lambda: (True, "ffmpeg 4.4.2"), "ffmpeg", ""),
            ("groq_api_key", lambda: (True, "Groq OK"), "llm_groq", ""),
            ("deepseek_api_key", lambda: (True, "DeepSeek OK"), "llm_deepseek", ""),
        ]
        try:
            checker = DependencyHealthChecker()
            flags = checker.run_checks()
            assert all(flags.values()), "All flags should be True"
        finally:
            _dhc.CHECKS = _orig

    def test_numpy_incompatible(self):
        """NumPy 2.4 → audio_spectral_analysis=False."""
        from src.core.dependency_health_checker import DependencyHealthChecker
        from src.core.feature_flags import FEATURE_FLAGS
        import src.core.dependency_health_checker as _dhc

        _orig = _dhc.CHECKS
        _dhc.CHECKS = [
            ("numpy", lambda: (False, "NumPy 2.4.0"), "audio_spectral_analysis", ""),
            ("torchcodec", lambda: (True, "TorchCodec OK"), "narrative_cut_detection", ""),
            ("mediapipe", lambda: (True, "MediaPipe OK"), "face_tracking_mediapipe", ""),
            ("nvenc", lambda: (True, "NVENC OK"), "gpu_encode", ""),
            ("librosa", lambda: (True, "librosa OK"), "beat_sync_librosa", ""),
            ("ffmpeg", lambda: (True, "ffmpeg 4.4.2"), "ffmpeg", ""),
            ("groq_api_key", lambda: (True, "Groq OK"), "llm_groq", ""),
            ("deepseek_api_key", lambda: (True, "DeepSeek OK"), "llm_deepseek", ""),
        ]
        try:
            checker = DependencyHealthChecker()
            flags = checker.run_checks()
            assert flags["audio_spectral_analysis"] is False
        finally:
            _dhc.CHECKS = _orig

    def test_torchcodec_fails(self):
        """TorchCodec ImportError → narrative_cut_detection=False."""
        from src.core.dependency_health_checker import DependencyHealthChecker
        from src.core.feature_flags import FEATURE_FLAGS
        import src.core.dependency_health_checker as _dhc

        _orig = _dhc.CHECKS
        _dhc.CHECKS = [
            ("numpy", lambda: (True, "NumPy 2.2.6"), "audio_spectral_analysis", ""),
            ("torchcodec", lambda: (False, "TorchCodec fail"), "narrative_cut_detection", ""),
            ("mediapipe", lambda: (True, "MediaPipe OK"), "face_tracking_mediapipe", ""),
            ("nvenc", lambda: (True, "NVENC OK"), "gpu_encode", ""),
            ("librosa", lambda: (True, "librosa OK"), "beat_sync_librosa", ""),
            ("ffmpeg", lambda: (True, "ffmpeg 4.4.2"), "ffmpeg", ""),
            ("groq_api_key", lambda: (True, "Groq OK"), "llm_groq", ""),
            ("deepseek_api_key", lambda: (True, "DeepSeek OK"), "llm_deepseek", ""),
        ]
        try:
            checker = DependencyHealthChecker()
            flags = checker.run_checks()
            assert flags["narrative_cut_detection"] is False
        finally:
            _dhc.CHECKS = _orig

    def test_ffmpeg_ausente_raise_runtimeerror(self):
        """FFmpeg no disponible → RuntimeError fatal."""
        from src.core.dependency_health_checker import DependencyHealthChecker
        import src.core.dependency_health_checker as _dhc

        _orig = _dhc.CHECKS
        _dhc.CHECKS = [
            ("numpy", lambda: (True, "NumPy 2.2.6"), "audio_spectral_analysis", ""),
            ("torchcodec", lambda: (True, "TorchCodec OK"), "narrative_cut_detection", ""),
            ("mediapipe", lambda: (True, "MediaPipe OK"), "face_tracking_mediapipe", ""),
            ("nvenc", lambda: (True, "NVENC OK"), "gpu_encode", ""),
            ("librosa", lambda: (True, "librosa OK"), "beat_sync_librosa", ""),
            ("ffmpeg", lambda: (False, "ffmpeg not found"), "ffmpeg", ""),
            ("groq_api_key", lambda: (True, "Groq OK"), "llm_groq", ""),
            ("deepseek_api_key", lambda: (True, "DeepSeek OK"), "llm_deepseek", ""),
        ]
        try:
            checker = DependencyHealthChecker()
            with pytest.raises(RuntimeError, match="FFmpeg not available"):
                checker.run_checks()
        finally:
            _dhc.CHECKS = _orig

    def test_sin_llm_raise_runtimeerror(self):
        """Sin Groq ni DeepSeek → RuntimeError fatal."""
        from src.core.dependency_health_checker import DependencyHealthChecker
        import src.core.dependency_health_checker as _dhc

        _orig = _dhc.CHECKS
        _dhc.CHECKS = [
            ("numpy", lambda: (True, "NumPy 2.2.6"), "audio_spectral_analysis", ""),
            ("torchcodec", lambda: (True, "TorchCodec OK"), "narrative_cut_detection", ""),
            ("mediapipe", lambda: (True, "MediaPipe OK"), "face_tracking_mediapipe", ""),
            ("nvenc", lambda: (True, "NVENC OK"), "gpu_encode", ""),
            ("librosa", lambda: (True, "librosa OK"), "beat_sync_librosa", ""),
            ("ffmpeg", lambda: (True, "ffmpeg 4.4.2"), "ffmpeg", ""),
            ("groq_api_key", lambda: (False, "Groq no configurada"), "llm_groq", ""),
            ("deepseek_api_key", lambda: (False, "DeepSeek no configurada"), "llm_deepseek", ""),
        ]
        try:
            checker = DependencyHealthChecker()
            with pytest.raises(RuntimeError, match="No LLM configured"):
                checker.run_checks()
        finally:
            _dhc.CHECKS = _orig

    def test_tabla_ascii_en_output(self):
        """El resumen debe contener la tabla ASCII."""
        from src.core.dependency_health_checker import _build_status_table

        results = {
            "numpy": (True, "NumPy 2.2.6"),
            "torchcodec": (False, "TorchCodec no disponible"),
            "ffmpeg": (True, "ffmpeg 4.4.2"),
        }
        table = _build_status_table(results)
        assert "┌" in table
        assert "Status" in table
        assert "✅ ON" in table
        assert "❌ OFF" in table
        assert "└" in table

    def test_recheck_recovers(self):
        """Feature que estaba False → recheck pasa → se recupera."""
        from src.core.dependency_health_checker import DependencyHealthChecker
        from src.core.feature_flags import FEATURE_FLAGS
        import src.core.dependency_health_checker as _dhc

        FEATURE_FLAGS.set("audio_spectral_analysis", False)

        _orig = _dhc.CHECKS
        _dhc.CHECKS = [
            ("numpy", lambda: (True, "NumPy 2.2.6"), "audio_spectral_analysis", ""),
        ]
        try:
            checker = DependencyHealthChecker()
            recovered = checker.recheck(["audio_spectral_analysis"])
            assert "audio_spectral_analysis" in recovered
            assert FEATURE_FLAGS.get("audio_spectral_analysis") is True
        finally:
            _dhc.CHECKS = _orig

    def test_recheck_noop_when_already_true(self):
        """Feature ya True → recheck no hace nada."""
        from src.core.dependency_health_checker import DependencyHealthChecker
        from src.core.feature_flags import FEATURE_FLAGS
        import src.core.dependency_health_checker as _dhc

        FEATURE_FLAGS.set("audio_spectral_analysis", True)

        _orig = _dhc.CHECKS
        _dhc.CHECKS = [
            ("numpy", lambda: (True, "NumPy 2.2.6"), "audio_spectral_analysis", ""),
        ]
        try:
            checker = DependencyHealthChecker()
            recovered = checker.recheck(["audio_spectral_analysis"])
            assert len(recovered) == 0
        finally:
            _dhc.CHECKS = _orig
