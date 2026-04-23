"""
Test BackgroundCompositeService - Modos A, B, C
Updated: 2026-04-23
"""
import pytest
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Set env vars before any imports
os.environ["BACKGROUND_COMPOSITE_ENABLED"] = "true"
os.environ["SAM2_ENABLED"] = "true"
os.environ["SAM2_MIN_VIRAL_SCORE"] = "7.5"
os.environ["SAM2_MIN_DURATION"] = "12.0"


@pytest.fixture(autouse=True)
def mock_scene_analyzer():
    """Mock scene analyzer with different modes."""
    with patch("src.services.background_composite_service.scene_analyzer") as mock:
        yield mock


@pytest.fixture(autouse=True)
def mock_person_segmentation():
    """Mock person segmentation service."""
    with patch("src.services.background_composite_service.person_segmentation_service") as mock:
        mock.extract_person = AsyncMock(return_value="/tmp/person.webm")
        yield mock


@pytest.fixture(autouse=True)
def mock_composite_engine():
    """Mock composite engine."""
    with patch("src.services.background_composite_service.composite_engine") as mock:
        mock.composite = AsyncMock(return_value="/tmp/composite.mp4")
        yield mock


@pytest.fixture(autouse=True)
def mock_comfyui_integration():
    """Mock comfyui integration for LTX background."""
    with patch("src.services.background_composite_service.comfyui_integration") as mock:
        mock.process_with_comfyui = AsyncMock(return_value="/tmp/background.mp4")
        yield mock


class TestBackgroundCompositeService:
    """Test suite for BackgroundCompositeService."""

    @pytest.fixture(autouse=True)
    def setup_service(self):
        """Setup service instance for tests."""
        from src.services.background_composite_service import BackgroundCompositeService
        self.service = BackgroundCompositeService()

    @pytest.mark.asyncio
    async def test_mode_c_when_feature_disabled(self):
        """Test Mode C when BACKGROUND_COMPOSITE_ENABLED=false."""
        with patch.dict(os.environ, {"BACKGROUND_COMPOSITE_ENABLED": "false"}):
            result = await self.service.process(
                clip_path="/tmp/clip.mp4",
                task_id="test_001",
                viral_score=8.5,
                duration=15.0,
                broll_prompt="cinematic background"
            )

        assert result["mode_used"] == "C"
        assert result["success"] is True
        assert result["reason"] == "feature_disabled"
        assert result["output_path"] is None

    @pytest.mark.asyncio
    async def test_mode_b_when_analysis_returns_b(self, mock_scene_analyzer):
        """Test Mode B when scene analyzer decides B."""
        mock_scene_analyzer.analyze = AsyncMock(return_value={
            "mode": "B",
            "confidence": 0.8,
            "reason": "not_suitable_for_composite"
        })

        with patch.dict(os.environ, {"BACKGROUND_COMPOSITE_ENABLED": "true"}):
            result = await self.service.process(
                clip_path="/tmp/clip.mp4",
                task_id="test_002",
                viral_score=8.5,
                duration=15.0,
                broll_prompt="cinematic background"
            )

        assert result["mode_used"] == "B"
        assert result["success"] is True
        assert result["reason"] == "not_suitable_for_composite"
        assert result["output_path"] is None

    @pytest.mark.asyncio
    async def test_mode_a_success_path(self, mock_scene_analyzer, mock_person_segmentation, 
                                        mock_composite_engine, mock_comfyui_integration):
        """Test Mode A successful execution."""
        mock_scene_analyzer.analyze = AsyncMock(return_value={
            "mode": "A",
            "confidence": 0.9,
            "reason": "talking_head_suitable",
            "metrics": {"talking_head_ratio": 0.4, "background_variance": 15.0}
        })

        with patch.dict(os.environ, {"BACKGROUND_COMPOSITE_ENABLED": "true"}):
            with patch.object(Path, "exists", return_value=True):
                result = await self.service.process(
                    clip_path="/tmp/clip.mp4",
                    task_id="test_003",
                    viral_score=8.5,
                    duration=15.0,
                    broll_prompt="cinematic background"
                )

        assert result["mode_used"] == "A"
        assert result["success"] is True
        assert result["reason"] == "ok"

    @pytest.mark.asyncio
    async def test_mode_a_fallback_to_b_when_segmentation_fails(self, mock_scene_analyzer, 
                                                                  mock_composite_engine):
        """Test fallback to Mode B when person segmentation fails."""
        mock_scene_analyzer.analyze = AsyncMock(return_value={
            "mode": "A",
            "confidence": 0.9,
            "reason": "talking_head_suitable"
        })

        with patch("src.services.background_composite_service.person_segmentation_service") as mock_seg:
            mock_seg.extract_person = AsyncMock(return_value=None)

            with patch.dict(os.environ, {"BACKGROUND_COMPOSITE_ENABLED": "true"}):
                result = await self.service.process(
                    clip_path="/tmp/clip.mp4",
                    task_id="test_004",
                    viral_score=8.5,
                    duration=15.0,
                    broll_prompt="cinematic background"
                )

        assert result["mode_used"] == "B"
        assert result["success"] is True
        assert result["reason"] == "person_segmentation_failed"

    @pytest.mark.asyncio
    async def test_mode_a_fallback_to_b_when_composite_fails(self, mock_scene_analyzer, 
                                                            mock_person_segmentation):
        """Test fallback to Mode B when compositing fails."""
        mock_scene_analyzer.analyze = AsyncMock(return_value={
            "mode": "A",
            "confidence": 0.9,
            "reason": "talking_head_suitable"
        })

        with patch("src.services.background_composite_service.composite_engine") as mock_comp:
            mock_comp.composite = AsyncMock(return_value=None)

            with patch("src.services.background_composite_service.person_segmentation_service") as mock_seg:
                mock_seg.extract_person = AsyncMock(return_value="/tmp/person.webm")

                with patch.dict(os.environ, {"BACKGROUND_COMPOSITE_ENABLED": "true"}):
                    result = await self.service.process(
                        clip_path="/tmp/clip.mp4",
                        task_id="test_005",
                        viral_score=8.5,
                        duration=15.0,
                        broll_prompt="cinematic background"
                    )

        assert result["mode_used"] == "B"
        assert result["success"] is True
        assert result["reason"] == "composite_render_failed"

    @pytest.mark.asyncio
    async def test_exception_handling(self, mock_scene_analyzer):
        """Test graceful handling of exceptions."""
        mock_scene_analyzer.analyze = AsyncMock(side_effect=Exception("Unexpected error"))

        with patch.dict(os.environ, {"BACKGROUND_COMPOSITE_ENABLED": "true"}):
            # Should not raise
            result = await self.service.process(
                clip_path="/tmp/clip.mp4",
                task_id="test_006",
                viral_score=8.5,
                duration=15.0,
                broll_prompt="cinematic background"
            )

        # Should fallback to mode B
        assert result["mode_used"] == "B"
        assert result["success"] is True


class TestSceneAnalyzerIntegration:
    """Test SceneAnalyzer integration."""

    @pytest.mark.asyncio
    async def test_analyzer_timeout_handling(self):
        """Test that analyzer timeouts are handled gracefully."""
        from src.services.scene_analyzer import SceneAnalyzer
        
        analyzer = SceneAnalyzer()
        
        # Mock asyncio timeout
        with patch("asyncio.wait_for", side_effect=TimeoutError()):
            result = await analyzer.analyze("/tmp/clip.mp4", 8.5, 15.0)

        # Should default to mode B
        assert result["mode"] == "B"
        assert result["reason"] == "analyzer_error"
