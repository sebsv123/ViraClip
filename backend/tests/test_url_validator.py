"""Tests for SSRF protection — URL validation."""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from src.core.url_validator import validate_source_url


def test_youtube_url_passes():
    """Valid YouTube URL → passes."""
    url = validate_source_url("https://www.youtube.com/watch?v=test123")
    assert url == "https://www.youtube.com/watch?v=test123"


def test_localhost_url_blocked():
    """localhost URL → blocked."""
    with pytest.raises(HTTPException) as exc:
        validate_source_url("http://localhost/admin")
    assert exc.value.status_code == 400


def test_private_ip_blocked():
    """URL resolving to 192.168.x.x → blocked."""
    with patch("src.core.url_validator.socket.gethostbyname", return_value="192.168.1.1"):
        with pytest.raises(HTTPException) as exc:
            validate_source_url("https://youtube.com/watch?v=test")
        assert exc.value.status_code == 400


def test_aws_metadata_ip_blocked():
    """URL resolving to 169.254.169.254 (AWS metadata) → blocked."""
    with patch("src.core.url_validator.socket.gethostbyname", return_value="169.254.169.254"):
        with pytest.raises(HTTPException) as exc:
            validate_source_url("https://youtube.com/watch?v=test")
        assert exc.value.status_code == 400


def test_unsupported_domain_blocked():
    """Unknown domain → blocked."""
    with pytest.raises(HTTPException) as exc:
        validate_source_url("https://unknown-site.com/video")
    assert exc.value.status_code == 400
    assert "Domain not supported" in str(exc.value.detail)


def test_ftp_scheme_blocked():
    """FTP scheme → blocked."""
    with pytest.raises(HTTPException) as exc:
        validate_source_url("ftp://youtube.com/video")
    assert exc.value.status_code == 400


def test_dns_resolution_failure_allows():
    """DNS failure → allows (yt-dlp will fail safely)."""
    with patch("src.core.url_validator.socket.gethostbyname", side_effect=Exception("DNS failed")):
        url = validate_source_url("https://youtube.com/watch?v=test")
        assert url == "https://youtube.com/watch?v=test"
