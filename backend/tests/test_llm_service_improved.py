"""
Tests for improved LLM service with validation and fallback.

Validates Pydantic schema, retry logic, and text-based fallback.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from src.services.llm_service_improved import (
    ImprovedLLMService,
    ViralityScores,
    SegmentAnalysis,
    ViralityAnalysis,
    HookType,
)


@pytest.fixture
def sample_segments():
    """Sample transcript segments for testing."""
    return [
        "I'm going to show you exactly how I made $10k in one weekend",
        "Most people don't realize this, but AI is already writing 40% of code",
        "This simple trick will change your life forever",
    ]


def test_virality_scores_validation_success():
    """Test Pydantic validation for valid scores."""
    scores = ViralityScores(
        hook_score=20,
        engagement_score=18,
        value_score=15,
        shareability_score=17,
        virality_score=70
    )
    
    assert scores.hook_score == 20
    assert scores.virality_score == 70


def test_virality_scores_validation_mismatch():
    """Test that virality_score is corrected if it doesn't match sum."""
    scores = ViralityScores(
        hook_score=20,
        engagement_score=18,
        value_score=15,
        shareability_score=17,
        virality_score=50  # Wrong! Should be 70
    )
    
    # Validator should auto-correct
    assert scores.virality_score == 70


def test_virality_scores_range_validation():
    """Test that scores are clamped to valid ranges."""
    with pytest.raises(Exception):  # Pydantic ValidationError
        ViralityScores(
            hook_score=30,  # > 25, invalid
            engagement_score=18,
            value_score=15,
            shareability_score=17,
            virality_score=80
        )


def test_segment_analysis_validation():
    """Test full segment analysis validation."""
    analysis = SegmentAnalysis(
        segment_index=0,
        hook_score=22,
        engagement_score=20,
        value_score=18,
        shareability_score=19,
        virality_score=79,
        hook_type=HookType.BOLD_CLAIM,
        suggested_title="How I made $10k",
        suggested_hashtags=["#money", "#viral"],
        reasoning="Strong financial hook",
        viral_cues="Zoom on $10k"
    )
    
    assert analysis.segment_index == 0
    assert analysis.virality_score == 79
    assert analysis.hook_type == HookType.BOLD_CLAIM


@pytest.mark.asyncio
async def test_improved_llm_service_ollama_success(sample_segments):
    """Test successful Ollama analysis with validation."""
    service = ImprovedLLMService()
    
    mock_response = {
        "analysis": [
            {
                "segment_index": 0,
                "hook_score": 24,
                "engagement_score": 20,
                "value_score": 15,
                "shareability_score": 17,
                "virality_score": 76,
                "hook_type": "Bold Claim",
                "suggested_title": "How I made $10k",
                "suggested_hashtags": ["#money"],
                "reasoning": "Strong hook",
                "viral_cues": "Zoom effect"
            }
        ]
    }
    
    with patch('httpx.AsyncClient.post') as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"response": str(mock_response).replace("'", '"')}
        )
        
        result = await service.get_virality_analysis(sample_segments[:1])
        
        assert "analysis" in result
        assert len(result["analysis"]) == 1
        assert result["analysis"][0]["virality_score"] == 76


@pytest.mark.asyncio
async def test_improved_llm_service_fallback(sample_segments):
    """Test text-based fallback when Ollama fails."""
    service = ImprovedLLMService()
    service.max_retries = 0  # Disable retries for faster test
    
    with patch('httpx.AsyncClient.post', side_effect=Exception("Connection failed")):
        result = await service.get_virality_analysis(sample_segments)
        
        assert "analysis" in result
        assert len(result["analysis"]) == 3
        
        # Verify fallback was used
        first_analysis = result["analysis"][0]
        assert "fallback" in first_analysis["reasoning"].lower()
        assert first_analysis["virality_score"] > 0


def test_text_based_fallback_keyword_detection(sample_segments):
    """Test that text-based fallback detects viral keywords."""
    service = ImprovedLLMService()
    
    result = service._text_based_fallback(sample_segments)
    
    # First segment has "$10k" (money keyword)
    analysis_0 = result["analysis"][0]
    assert analysis_0["hook_score"] > 10  # Should get bonus for money keyword
    assert analysis_0["hook_type"] == "Bold Claim"
    
    # Second segment has "40%" (number keyword)
    analysis_1 = result["analysis"][1]
    assert analysis_1["hook_type"] == "Statistic"


def test_text_based_fallback_question_detection():
    """Test question detection in fallback."""
    service = ImprovedLLMService()
    
    segments = ["What is the secret to success?"]
    result = service._text_based_fallback(segments)
    
    analysis = result["analysis"][0]
    assert analysis["hook_type"] == "Question"
    assert analysis["hook_score"] > 10


@pytest.mark.asyncio
async def test_improved_llm_service_retry_logic(sample_segments):
    """Test exponential backoff retry logic."""
    service = ImprovedLLMService()
    service.max_retries = 2
    
    call_count = 0
    
    async def mock_post_with_retries(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("Temporary failure")
        # Third attempt succeeds
        return MagicMock(
            status_code=200,
            json=lambda: {
                "response": '{"analysis": [{"segment_index": 0, "hook_score": 20, "engagement_score": 18, "value_score": 15, "shareability_score": 17, "virality_score": 70, "hook_type": "Value", "suggested_title": "", "suggested_hashtags": [], "reasoning": "test", "viral_cues": ""}]}'
            }
        )
    
    with patch('httpx.AsyncClient.post', side_effect=mock_post_with_retries):
        with patch('asyncio.sleep', new_callable=AsyncMock):  # Skip actual sleep
            result = await service.get_virality_analysis(sample_segments[:1])
            
            # Should succeed after retries
            assert "analysis" in result
            assert call_count == 3  # Initial + 2 retries


def test_hook_type_enum_validation():
    """Test that only valid hook types are accepted."""
    valid_types = [
        "Curiosity Gap", "Negative Hook", "Bold Claim",
        "Story", "Statistic", "Question", "Contrast", "Value"
    ]
    
    for hook_type in valid_types:
        analysis = SegmentAnalysis(
            segment_index=0,
            hook_score=20,
            engagement_score=18,
            value_score=15,
            shareability_score=17,
            virality_score=70,
            hook_type=hook_type,
            reasoning="test"
        )
        assert analysis.hook_type in HookType


def test_improved_prompt_includes_examples():
    """Test that improved prompt includes few-shot examples."""
    service = ImprovedLLMService()
    
    prompt = service._build_improved_prompt(["test segment"])
    
    assert "Example 1:" in prompt
    assert "Example 2:" in prompt
    assert "CRITICAL RULES:" in prompt
    assert "EXACT format:" in prompt
