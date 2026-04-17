"""
Integration tests for Week 1 Foundation features.

Tests:
- Pydantic validation with retry loop
- Cache checker mtime validation
- Progress emitter Redis Pub/Sub
- Static/dynamic prompt generation
- Task manager background tasks
"""

import pytest
import asyncio
from datetime import datetime
from pathlib import Path
import json


# ============================================================================
# Test 1: Pydantic Validation
# ============================================================================

class TestPydanticValidation:
    """Test viral segment validation models."""
    
    def test_valid_segment(self):
        """Test valid segment passes all validators."""
        from src.models.viral_segment import ViralSegment
        
        data = {
            "start": "0:30",
            "end": "1:15",
            "hook_strength": 8.0,
            "emotional_peak": 7.5,
            "shareability": 9.0,
            "retention": 8.5,
            "viral_score": 8.25,
            "reason": "Strong opening hook with emotional arc"
        }
        
        segment = ViralSegment(**data)
        assert segment.start == "0:30"
        assert segment.end == "1:15"
        assert segment.viral_score == 8.25
    
    def test_duration_too_short(self):
        """Test validation fails for segments < 30 seconds."""
        from src.models.viral_segment import ViralSegment
        from pydantic import ValidationError
        
        data = {
            "start": "0:00",
            "end": "0:20",  # Only 20 seconds
            "hook_strength": 8.0,
            "emotional_peak": 7.5,
            "shareability": 9.0,
            "retention": 8.5,
            "viral_score": 8.25,
            "reason": "Too short"
        }
        
        with pytest.raises(ValidationError) as exc_info:
            ViralSegment(**data)
        
        assert "at least 30 seconds" in str(exc_info.value)
    
    def test_end_before_start(self):
        """Test validation fails when end <= start."""
        from src.models.viral_segment import ViralSegment
        from pydantic import ValidationError
        
        data = {
            "start": "1:00",
            "end": "0:50",  # Before start!
            "hook_strength": 8.0,
            "emotional_peak": 7.5,
            "shareability": 9.0,
            "retention": 8.5,
            "viral_score": 8.25,
            "reason": "Invalid timing"
        }
        
        with pytest.raises(ValidationError) as exc_info:
            ViralSegment(**data)
        
        assert "must be after start" in str(exc_info.value)
    
    def test_viral_score_average_validation(self):
        """Test viral_score must be close to average of dimensions."""
        from src.models.viral_segment import ViralSegment
        from pydantic import ValidationError
        
        # Correct average: (8+7+9+8)/4 = 8.0
        # But viral_score = 5.0 (too far off)
        data = {
            "start": "0:30",
            "end": "1:15",
            "hook_strength": 8.0,
            "emotional_peak": 7.0,
            "shareability": 9.0,
            "retention": 8.0,
            "viral_score": 5.0,  # Should be ~8.0
            "reason": "Test"
        }
        
        with pytest.raises(ValidationError) as exc_info:
            ViralSegment(**data)
        
        assert "should be close to average" in str(exc_info.value)
    
    def test_distinct_scores_validation(self):
        """Test all viral scores must be distinct."""
        from src.models.viral_segment import ScoringResponse
        from pydantic import ValidationError
        
        data = {
            "segments": [
                {
                    "start": "0:30",
                    "end": "1:00",
                    "hook_strength": 8.0,
                    "emotional_peak": 7.0,
                    "shareability": 9.0,
                    "retention": 8.0,
                    "viral_score": 8.0,
                    "reason": "First segment"
                },
                {
                    "start": "1:30",
                    "end": "2:00",
                    "hook_strength": 7.0,
                    "emotional_peak": 8.0,
                    "shareability": 8.0,
                    "retention": 9.0,
                    "viral_score": 8.0,  # Duplicate!
                    "reason": "Second segment"
                }
            ]
        }
        
        with pytest.raises(ValidationError) as exc_info:
            ScoringResponse(**data)
        
        assert "must be distinct" in str(exc_info.value)


# ============================================================================
# Test 2: AI Validator Retry Loop
# ============================================================================

class TestAIValidator:
    """Test retry loop with error feedback."""
    
    @pytest.mark.asyncio
    async def test_successful_validation_first_attempt(self):
        """Test successful validation on first try."""
        from src.services.ai_validator import get_validated_segments
        
        # Mock scoring function that returns valid JSON
        async def mock_scorer(transcript, language, num_clips, previous_error=None):
            return json.dumps({
                "segments": [
                    {
                        "start": "0:30",
                        "end": "1:15",
                        "hook_strength": 8.0,
                        "emotional_peak": 7.5,
                        "shareability": 9.0,
                        "retention": 8.5,
                        "viral_score": 8.25,
                        "reason": "Strong hook"
                    }
                ]
            })
        
        segments = await get_validated_segments(
            scoring_function=mock_scorer,
            transcript="Test transcript",
            language="es",
            num_clips=1,
            max_retries=3
        )
        
        assert len(segments) == 1
        assert segments[0].start == "0:30"
    
    @pytest.mark.asyncio
    async def test_retry_on_invalid_json(self):
        """Test retry when LLM returns invalid JSON."""
        from src.services.ai_validator import get_validated_segments
        
        attempt_count = 0
        
        async def mock_scorer_with_retry(transcript, language, num_clips, previous_error=None):
            nonlocal attempt_count
            attempt_count += 1
            
            if attempt_count == 1:
                # First attempt: invalid JSON
                return "This is not JSON at all"
            else:
                # Second attempt: valid JSON
                return json.dumps({
                    "segments": [
                        {
                            "start": "0:30",
                            "end": "1:15",
                            "hook_strength": 8.0,
                            "emotional_peak": 7.5,
                            "shareability": 9.0,
                            "retention": 8.5,
                            "viral_score": 8.25,
                            "reason": "Fixed on retry"
                        }
                    ]
                })
        
        segments = await get_validated_segments(
            scoring_function=mock_scorer_with_retry,
            transcript="Test",
            language="es",
            num_clips=1,
            max_retries=3
        )
        
        assert attempt_count == 2  # Should retry once
        assert len(segments) == 1
    
    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """Test failure after max retries."""
        from src.services.ai_validator import get_validated_segments
        
        async def always_fails(transcript, language, num_clips, previous_error=None):
            return "Invalid JSON every time"
        
        with pytest.raises(RuntimeError) as exc_info:
            await get_validated_segments(
                scoring_function=always_fails,
                transcript="Test",
                language="es",
                num_clips=1,
                max_retries=3
            )
        
        assert "failed after 3 attempts" in str(exc_info.value)


# ============================================================================
# Test 3: Cache Checker
# ============================================================================

class TestCacheChecker:
    """Test mtime-based cache validation."""
    
    @pytest.mark.asyncio
    async def test_cache_miss_no_clips(self, tmp_path):
        """Test cache miss when no clips exist."""
        from src.services.cache_checker import CacheChecker
        
        checker = CacheChecker(temp_dir=str(tmp_path))
        
        # Create fake video
        video_path = tmp_path / "test_video.mp4"
        video_path.write_text("fake video")
        
        result = await checker.check_existing_clips(
            task_id="nonexistent-task",
            video_path=str(video_path)
        )
        
        assert result is None  # Cache miss
    
    @pytest.mark.asyncio
    async def test_cache_hit_valid_clips(self, tmp_path):
        """Test cache hit when valid clips exist."""
        from src.services.cache_checker import CacheChecker
        import time
        
        # Create video file first
        video_path = tmp_path / "test_video.mp4"
        video_path.write_text("fake video")
        video_mtime = video_path.stat().st_mtime
        
        # Wait to ensure clips have newer mtime
        time.sleep(0.1)
        
        # Create clips directory and clips
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        
        task_id = "test-task-123"
        clip1 = clips_dir / f"clip_1_viral_{task_id}.mp4"
        clip2 = clips_dir / f"clip_2_viral_{task_id}.mp4"
        
        clip1.write_text("fake clip 1")
        clip2.write_text("fake clip 2")
        
        # Verify clips are newer
        assert clip1.stat().st_mtime > video_mtime
        
        checker = CacheChecker(temp_dir=str(tmp_path))
        result = await checker.check_existing_clips(
            task_id=task_id,
            video_path=str(video_path),
            min_clips=2
        )
        
        assert result is not None  # Cache hit
        assert len(result) == 2
        assert result[0]["filename"] == clip1.name
    
    @pytest.mark.asyncio
    async def test_cache_invalid_old_clips(self, tmp_path):
        """Test cache miss when clips are older than video."""
        from src.services.cache_checker import CacheChecker
        import time
        
        # Create old clips first
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        
        task_id = "test-task-456"
        clip1 = clips_dir / f"clip_1_viral_{task_id}.mp4"
        clip1.write_text("old clip")
        
        # Wait and create newer video
        time.sleep(0.1)
        video_path = tmp_path / "test_video.mp4"
        video_path.write_text("new video")
        
        checker = CacheChecker(temp_dir=str(tmp_path))
        result = await checker.check_existing_clips(
            task_id=task_id,
            video_path=str(video_path)
        )
        
        assert result is None  # Cache invalid (clips older than video)


# ============================================================================
# Test 4: Progress Emitter
# ============================================================================

class TestProgressEmitter:
    """Test Redis Pub/Sub progress events."""
    
    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires real Redis — run: pytest -m integration")
    @pytest.mark.asyncio
    async def test_emit_and_receive_progress(self):
        """Test emitting and receiving progress events."""
        from src.services.progress_emitter import emit_progress, get_progress_subscriber
        
        task_id = "test-progress-task"
        
        # Start subscriber in background
        events_received = []
        
        async def collect_events():
            async for event in get_progress_subscriber(task_id):
                data = json.loads(event)
                events_received.append(data)
                if data["stage"] == "done":
                    break
        
        subscriber_task = asyncio.create_task(collect_events())
        
        # Give subscriber time to connect
        await asyncio.sleep(0.1)
        
        # Emit events
        await emit_progress(task_id, "transcription", 30, "Transcribing...")
        await emit_progress(task_id, "scoring", 60, "Scoring segments...")
        await emit_progress(task_id, "done", 100, "Complete")
        
        # Wait for events
        await asyncio.wait_for(subscriber_task, timeout=5.0)
        
        assert len(events_received) >= 3
        assert events_received[0]["stage"] == "transcription"
        assert events_received[-1]["stage"] == "done"


# ============================================================================
# Test 5: Task Manager
# ============================================================================

class TestTaskManager:
    """Test background task management."""
    
    @pytest.mark.asyncio
    async def test_create_and_track_task(self):
        """Test creating and tracking a task."""
        from src.services.task_manager import TaskManager
        
        async def dummy_task():
            await asyncio.sleep(0.1)
            return "completed"
        
        task_id = TaskManager.create_task(
            coro=dummy_task(),
            metadata={"test": "data"}
        )
        
        assert task_id is not None
        
        status = TaskManager.get_task_status(task_id)
        assert status["status"] == "running"
        assert status["metadata"]["test"] == "data"
        
        # Wait for completion
        result = await TaskManager.wait_for_task(task_id, timeout=1.0)
        assert result == "completed"
        
        # Check final status
        final_status = TaskManager.get_task_status(task_id)
        assert final_status["status"] == "completed"
    
    @pytest.mark.asyncio
    async def test_cancel_task(self):
        """Test cancelling a running task."""
        from src.services.task_manager import TaskManager
        
        async def long_task():
            await asyncio.sleep(10)  # Long task
            return "should not complete"
        
        task_id = TaskManager.create_task(coro=long_task())
        
        # Let it start
        await asyncio.sleep(0.1)
        
        # Cancel it
        cancelled = await TaskManager.cancel_task(task_id)
        assert cancelled is True
        
        # Check status
        status = TaskManager.get_task_status(task_id)
        assert status["status"] == "cancelled"


# ============================================================================
# Test 6: Prompts
# ============================================================================

class TestAIPrompts:
    """Test static/dynamic prompt generation."""
    
    def test_static_prompt_is_string(self):
        """Test static prompt is defined."""
        from src.services.ai_prompts import VIRAL_SCORER_SYSTEM_PROMPT
        
        assert isinstance(VIRAL_SCORER_SYSTEM_PROMPT, str)
        assert len(VIRAL_SCORER_SYSTEM_PROMPT) > 100
        assert "viral" in VIRAL_SCORER_SYSTEM_PROMPT.lower()
    
    def test_dynamic_prompt_generation(self):
        """Test dynamic prompt includes context."""
        from src.services.ai_prompts import build_dynamic_user_prompt
        
        prompt = build_dynamic_user_prompt(
            transcript="Test transcript here",
            language="es",
            num_clips=3
        )
        
        assert "Test transcript here" in prompt
        assert "es" in prompt
        assert "3" in prompt
    
    def test_dynamic_prompt_with_error(self):
        """Test dynamic prompt includes previous error."""
        from src.services.ai_prompts import build_dynamic_user_prompt
        
        prompt = build_dynamic_user_prompt(
            transcript="Test",
            language="en",
            num_clips=2,
            previous_error="Duration too short"
        )
        
        assert "Duration too short" in prompt
        assert "CORRECCIÓN" in prompt or "error" in prompt.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
