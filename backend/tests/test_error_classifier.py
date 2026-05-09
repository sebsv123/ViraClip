"""Tests for error classifier — transient vs permanent."""
from src.core.error_classifier import classify_error


def test_503_is_transient():
    """HTTP 503 → transient."""
    assert classify_error("HTTP Error 503 Service Unavailable") == "transient"


def test_private_video_is_permanent():
    """Private video → permanent."""
    assert classify_error("This video is private") == "permanent"


def test_timeout_is_transient():
    """Timeout → transient."""
    assert classify_error("Request timed out after 30s") == "transient"


def test_unknown_error_is_unknown():
    """Unknown error → unknown."""
    assert classify_error("Something unexpected happened") == "unknown"


def test_empty_error_is_unknown():
    """Empty error → unknown."""
    assert classify_error("") == "unknown"


def test_none_error_is_unknown():
    """None error → unknown."""
    assert classify_error(None) == "unknown"


def test_rate_limit_is_transient():
    """Rate limit → transient."""
    assert classify_error("Rate limit exceeded. Try again later.") == "transient"


def test_not_found_is_permanent():
    """404 → permanent."""
    assert classify_error("Video not found (404)") == "permanent"


def test_groq_error_is_transient():
    """Groq error → transient."""
    assert classify_error("Groq API error: 429 Too Many Requests") == "transient"


def test_deleted_video_is_permanent():
    """Deleted video → permanent."""
    assert classify_error("This video has been deleted") == "permanent"
