"""Tests for prompt registry — version tracking."""
from unittest.mock import MagicMock

from src.domains.ai.prompt_registry import (
    PROMPT_VERSIONS,
    get_prompt_version,
    log_prompt_usage,
)


def test_get_known_prompt_version():
    """Known prompt returns its version."""
    version = get_prompt_version("viral_scorer")
    assert version == "v1.0"
    assert version != "unknown"


def test_get_unknown_prompt_returns_unknown():
    """Unknown prompt returns 'unknown'."""
    version = get_prompt_version("nonexistent_prompt")
    assert version == "unknown"


def test_log_prompt_usage_calls_debug():
    """log_prompt_usage calls logger.debug with prompt name."""
    mock_logger = MagicMock()
    log_prompt_usage("viral_scorer", mock_logger)
    mock_logger.debug.assert_called_once()
    call_args = mock_logger.debug.call_args[0]
    assert "viral_scorer" in str(call_args)


def test_registry_has_expected_prompts():
    """Registry contains all expected prompt names."""
    expected = [
        "viral_scorer",
        "script_writer",
        "yt_metadata",
        "transcript_analysis",
        "creative_director",
        "hook_rewriter",
        "edit_decision",
        "broll_director",
        "quality_judge",
        "audio_mix",
        "subagent_pipeline",
        "elite_trend_researcher",
        "elite_community_mgr",
    ]
    for name in expected:
        assert name in PROMPT_VERSIONS, f"Missing: {name}"
