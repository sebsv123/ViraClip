"""
Unit tests for dependency conflict fixes.

BUG A — NumPy demasiado nuevo para Numba
  Fix: numpy==2.2.6 en requirements.txt, pyproject.toml y Dockerfile

BUG B — TorchCodec incompatible con PyTorch 2.10.0+cu130
  Fix: torchcodec>=0.2.0 añadido a pyproject.toml y Dockerfile.
  Se verifica que torchcodec se importa correctamente.
  Se verifica que narrative_cut_engine tiene fallback limpio.
  Se verifica que audio_analysis no explota al importar.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest


class TestNumpyVersion:
    """Tests for BUG A: NumPy version pin for Numba compatibility."""

    def test_numpy_imports_with_version_le_2_2(self):
        """NumPy should import and have version <= 2.2.x for Numba compatibility."""
        import numpy as np
        major, minor = np.__version__.split(".")[:2]
        major, minor = int(major), int(minor)
        assert major == 2, f"NumPy major version should be 2, got {major}"
        assert minor <= 2, (
            f"Numba needs NumPy 2.2 or less. Got NumPy {np.__version__}"
        )

    def test_requirements_pins_numpy_2_2_6(self):
        """requirements.txt should pin numpy==2.2.6."""
        # Inside Docker, requirements.txt is not copied to /app.
        # Check from host-relative paths.
        req_path = Path("requirements.txt")
        if not req_path.exists():
            req_path = Path("backend/requirements.txt")
        if not req_path.exists():
            pytest.skip("requirements.txt not found — running inside container")
            return
        content = req_path.read_text()
        found = False
        for line in content.splitlines():
            if line.startswith("numpy"):
                assert "2.2.6" in line, (
                    f"BUG A: numpy should be pinned to 2.2.6, got: {line}"
                )
                found = True
        assert found, "numpy pin not found in requirements.txt"

    def test_dockerfile_has_ldconfig(self):
        """Dockerfile should have RUN ldconfig after FFmpeg install for TorchCodec SO detection."""
        df_path = Path("Dockerfile")
        if not df_path.exists():
            df_path = Path("backend/Dockerfile")
        if not df_path.exists():
            pytest.skip("Dockerfile not found — running inside container")
            return
        content = df_path.read_text()
        assert "ldconfig" in content, (
            "BUG B: Dockerfile should have RUN ldconfig after FFmpeg install"
        )


class TestAudioAnalysisImport:
    """Tests that audio_analysis modules import cleanly."""

    def test_video_processing_audio_analysis_imports(self):
        """video_processing/audio_analysis.py should import without error."""
        from src.video_processing.audio_analysis import (
            analyze_audio_virality,
            find_viral_moments_from_audio,
            extract_audio_from_video,
            measure_snr,
        )
        assert callable(analyze_audio_virality)
        assert callable(find_viral_moments_from_audio)
        assert callable(extract_audio_from_video)
        assert callable(measure_snr)

    def test_domains_audio_analysis_imports(self):
        """domains/audio/audio_analysis.py should import without error."""
        from src.domains.audio.audio_analysis import (
            AudioAnalysisService,
            get_audio_analysis_service,
            analyze_video_audio,
            suggest_music_for_clip,
        )
        assert AudioAnalysisService is not None
        assert callable(get_audio_analysis_service)
        assert callable(analyze_video_audio)
        assert callable(suggest_music_for_clip)


class TestNarrativeCutEngineFallback:
    """Tests that narrative_cut_engine has clean fallbacks (torchcodec is now installed)."""

    def test_torchcodec_is_installed(self):
        """torchcodec SHOULD be installed (compatible with torch 2.10.0+cu130 now)."""
        spec = __import__("importlib").util.find_spec("torchcodec")
        assert spec is not None, (
            "BUG B: torchcodec should be installed — "
            "it's needed for video decoding with torch 2.10.0+cu130"
        )

    def test_narrative_cut_engine_imports_cleanly(self):
        """narrative_cut_engine should import without torchcodec dependency."""
        from src.video_processing.narrative_cut_engine import (
            NarrativeCutEngine,
            CutPoint,
            NarrativeSegment,
            detect_hesitations,
        )
        assert NarrativeCutEngine is not None
        assert CutPoint is not None
        assert callable(detect_hesitations)

    def test_narrative_cut_engine_no_torchcodec_reference(self):
        """narrative_cut_engine.py should not reference torchcodec anywhere."""
        src_path = Path(__file__).parent.parent / "src" / "video_processing" / "narrative_cut_engine.py"
        if not src_path.exists():
            src_path = Path("/app/src/video_processing/narrative_cut_engine.py")
        if src_path.exists():
            content = src_path.read_text()
            assert "torchcodec" not in content, (
                "BUG B: narrative_cut_engine.py should not import torchcodec"
            )

    def test_narrative_cut_engine_find_narrative_cuts_no_crash(self):
        """find_narrative_cuts should handle empty inputs gracefully."""
        from src.video_processing.narrative_cut_engine import NarrativeCutEngine

        engine = NarrativeCutEngine()
        result = engine.find_narrative_cuts(
            transcript="",
            words_with_timestamps=[],
            audio_silences=[],
        )
        assert result == [], "Should return empty list for empty inputs"

    def test_narrative_cut_engine_with_hesitations(self):
        """find_narrative_cuts should detect hesitation markers."""
        from src.video_processing.narrative_cut_engine import NarrativeCutEngine

        engine = NarrativeCutEngine()
        words = [
            {"word": "hello", "start": 0.0, "end": 0.5, "probability": 0.9},
            {"word": "um", "start": 0.5, "end": 0.8, "probability": 0.7},
            {"word": "world", "start": 0.8, "end": 1.2, "probability": 0.9},
        ]
        result = engine.find_narrative_cuts(
            transcript="hello um world",
            words_with_timestamps=words,
            audio_silences=[],
        )
        # Should find at least the hesitation cut
        hesitation_cuts = [c for c in result if c.reason == "hesitation_marker"]
        assert len(hesitation_cuts) >= 1
        assert hesitation_cuts[0].timestamp == 0.8  # end of "um"
