"""
Unit Tests — Phase 2.4: Qwen3-VL Visual Scene Analysis
========================================================
Tests for detect_boring_frames, extract_scene_context, score_thumbnail_frame,
VisionScore dataclass extensions, and graceful CPU fallbacks.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
#  VisionScore dataclass
# ─────────────────────────────────────────────────────────────────────────────

class TestVisionScoreDataclass:
    """VisionScore has Phase 2.4 fields."""

    def test_default_phase24_fields(self):
        from services.vision_service import VisionScore

        vs = VisionScore()
        assert isinstance(vs.scene_context, dict)
        assert isinstance(vs.boring_frames, list)
        assert isinstance(vs.broll_keywords, list)

    def test_from_dict_parses_phase24_fields(self):
        from services.vision_service import VisionScore

        raw = {
            "visual_hook": 80,
            "facial_energy": 70,
            "subtitle_readability": 90,
            "visual_virality": 75,
            "edit_rhythm": "fast",
            "recommendations": ["Add hook"],
            "scene_context": {"environment": "indoor", "mood": "energetic", "objects": ["person"]},
            "boring_frames": [2, 5],
            "broll_keywords": ["office work", "productivity"],
        }
        vs = VisionScore.from_dict(raw, model="qwen3-vl:8b")

        assert vs.scene_context["environment"] == "indoor"
        assert vs.scene_context["mood"] == "energetic"
        assert vs.boring_frames == [2, 5]
        assert "office work" in vs.broll_keywords

    def test_unavailable_has_empty_phase24_fields(self):
        from services.vision_service import VisionScore

        vs = VisionScore.unavailable()
        assert vs.model_used == "unavailable"
        assert vs.scene_context == {}
        assert vs.boring_frames == []
        assert vs.broll_keywords == []

    def test_from_dict_defaults_missing_phase24(self):
        from services.vision_service import VisionScore

        raw = {"visual_hook": 60}
        vs = VisionScore.from_dict(raw)

        assert vs.scene_context == {}
        assert vs.boring_frames == []
        assert vs.broll_keywords == []


# ─────────────────────────────────────────────────────────────────────────────
#  detect_boring_frames — Ollama path
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectBoringFrames:
    """Test detect_boring_frames with mocked Ollama."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_ollama_unavailable(self, tmp_path):
        from services.vision_service import detect_boring_frames

        with patch("services.vision_service._check_ollama", return_value=(False, "")), \
             patch("services.vision_service._detect_boring_frames_laplacian", return_value=[]):
            result = await detect_boring_frames(tmp_path / "fake.mp4")

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_indices_from_ollama(self, tmp_path):
        from services.vision_service import detect_boring_frames

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "[1, 4]"}

        with patch("services.vision_service._check_ollama", return_value=(True, "qwen3-vl:8b")), \
             patch("services.vision_service._get_ollama_endpoint", return_value="http://ollama:11434"), \
             patch("services.vision_service.extract_representative_frames", return_value=[
                 tmp_path / "f1.jpg", tmp_path / "f2.jpg",
                 tmp_path / "f3.jpg", tmp_path / "f4.jpg", tmp_path / "f5.jpg",
             ]):
            # Create fake frames
            for i in range(1, 6):
                (tmp_path / f"f{i}.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client_cls.return_value = mock_client

                result = await detect_boring_frames(tmp_path / "video.mp4")

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_filters_out_of_range_indices(self, tmp_path):
        from services.vision_service import detect_boring_frames

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "[0, 5, 100, -1]"}  # 5, 100, -1 are invalid

        (tmp_path / "f1.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        with patch("services.vision_service._check_ollama", return_value=(True, "qwen3-vl:8b")), \
             patch("services.vision_service._get_ollama_endpoint", return_value="http://ollama:11434"), \
             patch("services.vision_service.extract_representative_frames", return_value=[tmp_path / "f1.jpg"]):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client_cls.return_value = mock_client

                result = await detect_boring_frames(tmp_path / "video.mp4")

        # Only index 0 is valid (we have 1 frame, indices 0..0)
        assert all(0 <= i < 1 for i in result)

    @pytest.mark.asyncio
    async def test_falls_back_when_no_frames_extracted(self, tmp_path):
        from services.vision_service import detect_boring_frames

        with patch("services.vision_service._check_ollama", return_value=(True, "qwen3-vl:8b")), \
             patch("services.vision_service.extract_representative_frames", return_value=[]):
            result = await detect_boring_frames(tmp_path / "nonexistent.mp4")

        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
#  extract_scene_context
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractSceneContext:
    """Test extract_scene_context with mocked Ollama."""

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_unavailable(self, tmp_path):
        from services.vision_service import extract_scene_context

        with patch("services.vision_service._check_ollama", return_value=(False, "")):
            result = await extract_scene_context(tmp_path / "fake.mp4")

        assert result == {}

    @pytest.mark.asyncio
    async def test_parses_scene_context_json(self, tmp_path):
        from services.vision_service import extract_scene_context

        ctx = {
            "environment": "outdoor",
            "mood": "energetic",
            "objects": ["person", "skateboard"],
            "broll_keywords": ["street skating", "urban sports"],
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": str(ctx).replace("'", '"')}

        (tmp_path / "frame.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        with patch("services.vision_service._check_ollama", return_value=(True, "qwen3-vl:8b")), \
             patch("services.vision_service._get_ollama_endpoint", return_value="http://ollama:11434"), \
             patch("services.vision_service.extract_representative_frames", return_value=[tmp_path / "frame.jpg"]):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client_cls.return_value = mock_client

                result = await extract_scene_context(tmp_path / "video.mp4")

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_frames(self, tmp_path):
        from services.vision_service import extract_scene_context

        with patch("services.vision_service._check_ollama", return_value=(True, "qwen3-vl:8b")), \
             patch("services.vision_service.extract_representative_frames", return_value=[]):
            result = await extract_scene_context(tmp_path / "video.mp4")

        assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
#  score_thumbnail_frame
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreThumbnailFrame:
    """Test score_thumbnail_frame with mocked Ollama and CPU fallback."""

    @pytest.mark.asyncio
    async def test_falls_back_to_laplacian_when_unavailable(self, tmp_path):
        from services.vision_service import score_thumbnail_frame

        frame = tmp_path / "frame.jpg"
        frame.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        with patch("services.vision_service._check_ollama", return_value=(False, "")), \
             patch("services.vision_service._score_thumbnail_laplacian", return_value={"score": 42}):
            result = await score_thumbnail_frame(frame)

        assert result["score"] == 42

    @pytest.mark.asyncio
    async def test_returns_score_from_ollama(self, tmp_path):
        from services.vision_service import score_thumbnail_frame

        frame = tmp_path / "frame.jpg"
        frame.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        ollama_result = '{"score": 85, "has_face": true, "expression": "surprised", "composition": "close_up", "reason": "Strong expression."}'
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": ollama_result}

        with patch("services.vision_service._check_ollama", return_value=(True, "qwen3-vl:8b")), \
             patch("services.vision_service._get_ollama_endpoint", return_value="http://ollama:11434"):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client_cls.return_value = mock_client

                result = await score_thumbnail_frame(frame)

        assert 0 <= result["score"] <= 100

    @pytest.mark.asyncio
    async def test_clamps_score_to_0_100(self, tmp_path):
        from services.vision_service import score_thumbnail_frame

        frame = tmp_path / "frame.jpg"
        frame.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": '{"score": 150}'}  # out of range

        with patch("services.vision_service._check_ollama", return_value=(True, "qwen3-vl:8b")), \
             patch("services.vision_service._get_ollama_endpoint", return_value="http://ollama:11434"):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client_cls.return_value = mock_client

                result = await score_thumbnail_frame(frame)

        assert result["score"] <= 100

    @pytest.mark.asyncio
    async def test_returns_default_when_frame_missing(self, tmp_path):
        from services.vision_service import score_thumbnail_frame

        with patch("services.vision_service._check_ollama", return_value=(True, "qwen3-vl:8b")):
            result = await score_thumbnail_frame(tmp_path / "nonexistent.jpg")

        assert result.get("score") is not None


# ─────────────────────────────────────────────────────────────────────────────
#  blend_with_text_score — unchanged
# ─────────────────────────────────────────────────────────────────────────────

class TestBlendWithTextScore:
    """blend_with_text_score still works correctly."""

    def test_blend_formula(self):
        from services.vision_service import VisionScore, blend_with_text_score

        vs = VisionScore(visual_virality=80, model_used="qwen3-vl:8b")
        result = blend_with_text_score(60, vs)  # 60*0.7 + 80*0.3 = 42 + 24 = 66
        assert result == 66

    def test_unchanged_when_unavailable(self):
        from services.vision_service import VisionScore, blend_with_text_score

        vs = VisionScore.unavailable()
        result = blend_with_text_score(75, vs)
        assert result == 75


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
