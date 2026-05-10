"""Tests for thumbnail candidate generator."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_generates_3_candidates(tmp_path):
    """All extractions succeed → 3 candidates."""
    from src.services.thumbnail_generator import generate_thumbnail_candidates
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_text("fake")

    with patch("src.services.thumbnail_generator._get_duration", new_callable=AsyncMock) as mock_dur:
        mock_dur.return_value = 60.0
        with patch("src.services.thumbnail_generator._extract_frame_as_thumbnail", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = True
            results = await generate_thumbnail_candidates(clip_path, "clip_1", tmp_path)
            assert len(results) == 3


@pytest.mark.asyncio
async def test_failed_extraction_excluded_from_results(tmp_path):
    """Failed extraction → excluded."""
    from src.services.thumbnail_generator import generate_thumbnail_candidates
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_text("fake")

    with patch("src.services.thumbnail_generator._get_duration", new_callable=AsyncMock) as mock_dur:
        mock_dur.return_value = 60.0
        with patch("src.services.thumbnail_generator._extract_frame_as_thumbnail", new_callable=AsyncMock) as mock_extract:
            mock_extract.side_effect = [True, False, True]
            results = await generate_thumbnail_candidates(clip_path, "clip_1", tmp_path)
            assert len(results) == 2


@pytest.mark.asyncio
async def test_candidate_has_required_fields(tmp_path):
    """Each candidate has required fields."""
    from src.services.thumbnail_generator import generate_thumbnail_candidates
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_text("fake")

    with patch("src.services.thumbnail_generator._get_duration", new_callable=AsyncMock) as mock_dur:
        mock_dur.return_value = 60.0
        with patch("src.services.thumbnail_generator._extract_frame_as_thumbnail", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = True
            results = await generate_thumbnail_candidates(clip_path, "clip_1", tmp_path)
            for c in results:
                assert "type" in c
                assert "label" in c
                assert "path" in c
                assert "offset_s" in c
                assert "url" in c
