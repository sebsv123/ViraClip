"""
Tests for fast video segment extraction.

Validates that pre-extraction optimization works correctly.
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from src.utils.video_extraction import extract_segments_fast, _extract_single_segment, cleanup_extracted_segments


@pytest.fixture
def sample_segments():
    """Sample segment data for testing."""
    return [
        {"start_time": "00:15", "end_time": "00:45"},
        {"start_time": "01:20", "end_time": "02:00"},
        {"start_time": "03:00", "end_time": "03:30"},
    ]


@pytest.fixture
def temp_output_dir(tmp_path):
    """Temporary directory for test outputs."""
    output_dir = tmp_path / "segments"
    output_dir.mkdir()
    return output_dir


@pytest.mark.asyncio
async def test_extract_segments_fast_success(sample_segments, temp_output_dir, tmp_path):
    """Test successful extraction of multiple segments."""
    video_path = tmp_path / "test_video.mp4"
    video_path.touch()  # Create dummy file
    
    with patch('src.utils.video_extraction.asyncio.create_subprocess_exec') as mock_subprocess:
        # Mock successful ffmpeg execution
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_subprocess.return_value = mock_proc
        
        # Mock file existence check
        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.stat') as mock_stat:
                mock_stat.return_value = MagicMock(st_size=1024 * 1024)  # 1MB file
                
                results = await extract_segments_fast(
                    video_path=video_path,
                    segments=sample_segments,
                    output_dir=temp_output_dir,
                    task_id="test_task"
                )
        
        # Verify all segments extracted
        assert len(results) == 3
        assert all(r is not None for r in results)
        
        # Verify ffmpeg was called 3 times (once per segment)
        assert mock_subprocess.call_count == 3


@pytest.mark.asyncio
async def test_extract_single_segment_invalid_duration(temp_output_dir, tmp_path):
    """Test handling of invalid segment duration."""
    video_path = tmp_path / "test_video.mp4"
    video_path.touch()
    
    invalid_segment = {"start_time": "01:00", "end_time": "00:30"}  # End before start
    
    result = await _extract_single_segment(
        video_path=video_path,
        segment=invalid_segment,
        segment_index=0,
        output_dir=temp_output_dir,
        task_id="test"
    )
    
    assert result is None


@pytest.mark.asyncio
async def test_extract_single_segment_ffmpeg_failure(temp_output_dir, tmp_path):
    """Test handling of ffmpeg failure."""
    video_path = tmp_path / "test_video.mp4"
    video_path.touch()
    
    segment = {"start_time": "00:00", "end_time": "00:10"}
    
    with patch('src.utils.video_extraction.asyncio.create_subprocess_exec') as mock_subprocess:
        # Mock ffmpeg failure
        mock_proc = AsyncMock()
        mock_proc.returncode = 1  # Error
        mock_proc.communicate = AsyncMock(return_value=(b"", b"ffmpeg error"))
        mock_subprocess.return_value = mock_proc
        
        result = await _extract_single_segment(
            video_path=video_path,
            segment=segment,
            segment_index=0,
            output_dir=temp_output_dir,
            task_id="test"
        )
        
        assert result is None


def test_cleanup_extracted_segments(tmp_path):
    """Test cleanup of temporary segment files."""
    # Create dummy segment files
    segment_paths = [
        tmp_path / "segment_0.mp4",
        tmp_path / "segment_1.mp4",
        None,  # Simulate failed extraction
    ]
    
    for path in segment_paths:
        if path:
            path.touch()
    
    # Verify files exist
    assert segment_paths[0].exists()
    assert segment_paths[1].exists()
    
    # Cleanup
    cleanup_extracted_segments(segment_paths)
    
    # Verify files deleted
    assert not segment_paths[0].exists()
    assert not segment_paths[1].exists()


@pytest.mark.asyncio
async def test_extract_segments_partial_failure(sample_segments, temp_output_dir, tmp_path):
    """Test that extraction continues even if some segments fail."""
    video_path = tmp_path / "test_video.mp4"
    video_path.touch()
    
    call_count = 0
    
    async def mock_create_subprocess(*args, **kwargs):
        nonlocal call_count
        mock_proc = AsyncMock()
        # First call succeeds, second fails, third succeeds
        if call_count == 1:
            mock_proc.returncode = 1  # Failure
            mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))
        else:
            mock_proc.returncode = 0  # Success
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        call_count += 1
        return mock_proc
    
    with patch('src.utils.video_extraction.asyncio.create_subprocess_exec', side_effect=mock_create_subprocess):
        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.stat') as mock_stat:
                mock_stat.return_value = MagicMock(st_size=1024 * 1024)
                
                results = await extract_segments_fast(
                    video_path=video_path,
                    segments=sample_segments,
                    output_dir=temp_output_dir,
                    task_id="test_task"
                )
    
    # Should have 3 results (2 success, 1 None)
    assert len(results) == 3
    assert results[0] is not None
    assert results[1] is None  # Failed
    assert results[2] is not None
