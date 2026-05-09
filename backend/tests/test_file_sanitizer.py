"""Tests for filename sanitization and safe upload paths."""
from pathlib import Path

import pytest

from src.core.file_sanitizer import sanitize_filename, safe_upload_path


def test_normal_filename_unchanged():
    """Normal filename → unchanged."""
    result = sanitize_filename("video_2026.mp4")
    assert result == "video_2026.mp4"


def test_path_traversal_sanitized():
    """Path traversal → sanitized."""
    result = sanitize_filename("../../etc/passwd.mp4")
    assert ".." not in result
    assert "/" not in result


def test_dangerous_chars_replaced():
    """Dangerous chars → replaced with underscore."""
    result = sanitize_filename("; rm -rf /.mp4")
    assert all(c.isalnum() or c in "._-" for c in result)


def test_invalid_extension_becomes_mp4():
    """Invalid extension → default mp4."""
    result = sanitize_filename("video.exe")
    assert result.endswith(".mp4")


def test_safe_upload_path_stays_in_base_dir(tmp_path):
    """Safe upload path stays within base dir."""
    base = tmp_path / "uploads"
    result = safe_upload_path(base, "video.mp4", "task123")
    assert str(result).startswith(str(base))
    assert "task123" in str(result)


def test_safe_upload_path_traversal_raises(tmp_path):
    """Path traversal → raises ValueError."""
    base = tmp_path / "uploads"
    base.mkdir()
    with pytest.raises(ValueError, match="Path traversal"):
        safe_upload_path(base, "../../secret.mp4", "task123")
