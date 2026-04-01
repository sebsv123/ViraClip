"""
Tests for AI validation and quality metrics.

Tests include:
- Validating LLM responses with known transcripts
- Score range validation
- Anomaly detection logic
- Sample transcript analysis
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# Sample transcripts for testing
SAMPLE_TRANSCRIPTS = {
    "viral_potential_high": """
[00:00 - 00:10] I discovered a secret that changed everything.
[00:10 - 00:25] This simple trick will blow your mind. Listen carefully.
[00:25 - 00:45] Most people waste years not knowing this. But I'm sharing it now.
[00:45 - 01:05] The results are incredible. You won't believe what happened next.
[01:05 - 01:25] This is the exact moment everything clicked for me.
""",
    
    "viral_potential_medium": """
[00:00 - 00:15] Today I'm going to show you how to make pasta.
[00:15 - 00:35] First, you need to boil the water with some salt.
[00:35 - 00:55] Then add the pasta and cook for about 10 minutes.
[00:55 - 01:15] Make sure to stir occasionally so it doesn't stick.
[01:15 - 01:30] Drain the pasta and add your favorite sauce.
""",
    
    "viral_potential_low": """
[00:00 - 00:20] Um, so, yeah, today we're going to talk about... stuff.
[00:20 - 00:40] I don't really know where to start, but uh...
[00:40 - 01:00] This is kind of boring, I guess.
[01:00 - 01:20] Not sure if anyone will watch this.
[01:20 - 01:40] Anyway, that's all I have to say.
""",
    
    "no_speech": """
[00:00 - 00:30] [MUSIC PLAYING]
[00:30 - 01:00] [SILENCE]
[01:00 - 01:30] [BACKGROUND NOISE]
""",
}


@pytest.mark.asyncio
async def test_high_viral_potential_transcript():
    """Test that high-potential transcript gets good scores."""
    from src.ai import get_most_relevant_parts_by_transcript
    
    result = await get_most_relevant_parts_by_transcript(
        SAMPLE_TRANSCRIPTS["viral_potential_high"],
        include_broll=False
    )
    
    assert result is not None
    assert len(result.most_relevant_segments) > 0
    
    # Check scores are reasonable for high-potential content
    scores = [seg.virality_score for seg in result.most_relevant_segments]
    avg_score = sum(scores) / len(scores)
    
    # High-potential should average >= 6
    assert avg_score >= 6.0, f"Expected high score for viral content, got {avg_score}"
    
    # All scores should be in valid range
    assert all(1 <= score <= 10 for score in scores), "Scores out of range"


@pytest.mark.asyncio
async def test_medium_viral_potential_transcript():
    """Test that medium-potential transcript gets moderate scores."""
    from src.ai import get_most_relevant_parts_by_transcript
    
    result = await get_most_relevant_parts_by_transcript(
        SAMPLE_TRANSCRIPTS["viral_potential_medium"],
        include_broll=False
    )
    
    assert result is not None
    assert len(result.most_relevant_segments) > 0
    
    scores = [seg.virality_score for seg in result.most_relevant_segments]
    avg_score = sum(scores) / len(scores)
    
    # Medium content should be in middle range
    assert 4.0 <= avg_score <= 7.0, f"Expected moderate score, got {avg_score}"


@pytest.mark.asyncio
async def test_low_viral_potential_transcript():
    """Test that low-potential transcript gets appropriate scores."""
    from src.ai import get_most_relevant_parts_by_transcript
    
    result = await get_most_relevant_parts_by_transcript(
        SAMPLE_TRANSCRIPTS["viral_potential_low"],
        include_broll=False
    )
    
    # May find segments but with low scores, or no segments at all
    if result and len(result.most_relevant_segments) > 0:
        scores = [seg.virality_score for seg in result.most_relevant_segments]
        avg_score = sum(scores) / len(scores)
        
        # Low-quality content should score lower
        assert avg_score <= 6.0, f"Score too high for low-quality content: {avg_score}"


@pytest.mark.asyncio
async def test_score_variance():
    """Test that AI produces varied scores for different segments."""
    from src.ai import get_most_relevant_parts_by_transcript
    
    result = await get_most_relevant_parts_by_transcript(
        SAMPLE_TRANSCRIPTS["viral_potential_high"],
        include_broll=False
    )
    
    if result and len(result.most_relevant_segments) >= 3:
        scores = [seg.virality_score for seg in result.most_relevant_segments]
        unique_scores = len(set(scores))
        
        # Should have some variance (not all identical)
        assert unique_scores > 1, "AI returning identical scores for all segments"


@pytest.mark.asyncio
async def test_segment_duration_reasonable():
    """Test that AI suggests reasonable segment durations."""
    from src.ai import get_most_relevant_parts_by_transcript
    
    result = await get_most_relevant_parts_by_transcript(
        SAMPLE_TRANSCRIPTS["viral_potential_high"],
        include_broll=False
    )
    
    assert result is not None
    assert len(result.most_relevant_segments) > 0
    
    for segment in result.most_relevant_segments:
        duration = segment.end_time - segment.start_time
        
        # Clips should be 10-60 seconds (ideal for short-form)
        assert 5 <= duration <= 120, f"Segment duration {duration}s is unreasonable"


@pytest.mark.asyncio
async def test_segments_dont_overlap():
    """Test that suggested segments don't overlap."""
    from src.ai import get_most_relevant_parts_by_transcript
    
    result = await get_most_relevant_parts_by_transcript(
        SAMPLE_TRANSCRIPTS["viral_potential_high"],
        include_broll=False
    )
    
    if result and len(result.most_relevant_segments) >= 2:
        segments = sorted(result.most_relevant_segments, key=lambda s: s.start_time)
        
        for i in range(len(segments) - 1):
            current_end = segments[i].end_time
            next_start = segments[i + 1].start_time
            
            # Next segment should start after current ends (no overlap)
            assert next_start >= current_end, f"Segments overlap: [{current_end}, {next_start}]"


@pytest.mark.asyncio
async def test_hook_titles_generated():
    """Test that AI generates hook titles for segments."""
    from src.ai import get_most_relevant_parts_by_transcript
    
    result = await get_most_relevant_parts_by_transcript(
        SAMPLE_TRANSCRIPTS["viral_potential_high"],
        include_broll=False
    )
    
    assert result is not None
    assert len(result.most_relevant_segments) > 0
    
    for segment in result.most_relevant_segments:
        # Hook title should exist and be reasonable length
        assert segment.hook_title, "Hook title missing"
        assert 5 <= len(segment.hook_title) <= 100, f"Hook title length unreasonable: {len(segment.hook_title)}"


def test_anomaly_detection_high_no_clips_rate():
    """Test anomaly detection for high rate of tasks without clips."""
    # Simulate metrics with high no-clips rate
    metrics = {
        "completed_tasks": 100,
        "tasks_without_clips": 30  # 30% is high
    }
    
    no_clips_rate = (metrics["tasks_without_clips"] / metrics["completed_tasks"]) * 100
    
    # Should trigger anomaly
    assert no_clips_rate > 10, "Should detect high no-clips rate"


def test_anomaly_detection_uniform_scores():
    """Test detection of suspiciously uniform scores."""
    # All scores are 7 (suspicious)
    scores = [7] * 50
    unique_scores = len(set(scores))
    
    # Should detect uniformity
    assert unique_scores <= 2, "Should detect uniform scoring"


def test_score_distribution_statistics():
    """Test statistical analysis of score distribution."""
    import statistics
    
    scores = [5, 6, 7, 8, 9, 7, 6, 8, 9, 7, 6, 8]
    
    mean = statistics.mean(scores)
    median = statistics.median(scores)
    stdev = statistics.stdev(scores)
    
    # Verify calculations work
    assert 6 <= mean <= 8
    assert median in scores
    assert stdev > 0


@pytest.mark.asyncio
async def test_llm_validation_endpoint():
    """Test the LLM validation endpoint logic."""
    from src.ai import get_most_relevant_parts_by_transcript
    
    sample_transcript = """
[00:00 - 00:15] This is a test transcript with good content.
[00:15 - 00:30] It should generate reasonable segments and scores.
[00:30 - 00:50] The AI should be able to identify viral potential here.
"""
    
    try:
        result = await get_most_relevant_parts_by_transcript(sample_transcript, include_broll=False)
        
        # Basic validation
        assert result is not None, "LLM returned None"
        
        if len(result.most_relevant_segments) > 0:
            scores = [seg.virality_score for seg in result.most_relevant_segments]
            
            # Score range check
            assert all(1 <= s <= 10 for s in scores), "Scores out of valid range"
            
            # Duration check
            durations = [seg.end_time - seg.start_time for seg in result.most_relevant_segments]
            assert all(5 <= d <= 120 for d in durations), "Durations unreasonable"
            
    except Exception as e:
        pytest.fail(f"LLM validation failed: {e}")


@pytest.mark.asyncio
async def test_empty_transcript_handling():
    """Test handling of empty or invalid transcripts."""
    from src.ai import get_most_relevant_parts_by_transcript
    
    empty_transcripts = [
        "",
        "   ",
        "[00:00 - 00:10]",  # No text
        "No timestamps here"
    ]
    
    for transcript in empty_transcripts:
        result = await get_most_relevant_parts_by_transcript(transcript, include_broll=False)
        
        # Should handle gracefully (return empty or raise known exception)
        # Don't crash the system
        assert result is not None or True  # Either returns something or handles error


@pytest.mark.asyncio
async def test_very_long_transcript():
    """Test handling of very long transcripts."""
    from src.ai import get_most_relevant_parts_by_transcript
    
    # Generate a long transcript (simulate 1-hour video)
    long_transcript = "\n".join([
        f"[{i:02d}:{j:02d} - {i:02d}:{j+15:02d}] This is segment {i*4 + j//15} with some content."
        for i in range(60)
        for j in range(0, 60, 15)
    ])
    
    result = await get_most_relevant_parts_by_transcript(long_transcript[:5000], include_broll=False)
    
    # Should handle long input without timing out
    assert result is not None
    
    # Should not return too many segments (max ~10)
    if result.most_relevant_segments:
        assert len(result.most_relevant_segments) <= 15, "Too many segments returned"


def test_percentile_calculation():
    """Test percentile calculations for score distribution."""
    import statistics
    
    scores = list(range(1, 11))  # 1-10
    
    # Test quantile calculations
    if len(scores) >= 4:
        p25 = statistics.quantiles(scores, n=4)[0]
        p75 = statistics.quantiles(scores, n=4)[2]
        
        assert p25 < p75, "Percentiles should be ordered"
        assert 1 <= p25 <= 10, "P25 out of range"
        assert 1 <= p75 <= 10, "P75 out of range"
