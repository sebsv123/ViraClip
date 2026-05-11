"""
SSRF protection for source URLs.
Validates that URLs point to allowed domains and don't resolve to private IPs.
"""
import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import HTTPException

# Private/reserved IP ranges that should never be accessible
_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # AWS metadata
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 private
]

_ALLOWED_SCHEMES = {"http", "https"}

_ALLOWED_DOMAINS = {
    "youtube.com", "www.youtube.com", "youtu.be",
    "tiktok.com", "www.tiktok.com",
    "instagram.com", "www.instagram.com",
    "twitter.com", "x.com",
    "twitch.tv", "www.twitch.tv",
    "vimeo.com", "www.vimeo.com",
}


def validate_source_url(url: str) -> str:
    """
    Valida que la URL es segura y proviene de un dominio permitido.
    Lanza HTTPException 400 si no es válida.
    Retorna la URL limpia si es válida.
    
    NOTE: TOCTOU acceptable — defense in depth. The IP could change between
    validation and download, but this is a secondary defense layer.
    """
    try:
        parsed = urlparse(url.strip())
    except Exception:
        raise HTTPException(400, "Invalid URL format")

    # Scheme check
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise HTTPException(400, f"URL scheme '{parsed.scheme}' not allowed")

    # Domain check
    hostname = parsed.hostname or ""
    if not hostname:
        raise HTTPException(400, "URL has no hostname")

    domain_allowed = any(
        hostname == d or hostname.endswith(f".{d}")
        for d in _ALLOWED_DOMAINS
    )
    if not domain_allowed:
        raise HTTPException(
            400,
            {
                "error": "Domain not supported",
                "hostname": hostname,
                "message": "Only YouTube, TikTok, Instagram, Twitter/X, "
                           "Twitch and Vimeo are supported",
            },
        )

    # SSRF: resolve hostname and check it's not a private IP
    # NOTE: TOCTOU acceptable — defense in depth
    try:
        ip_str = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(ip_str)
        for private_range in _PRIVATE_RANGES:
            if ip in private_range:
                raise HTTPException(
                    400,
                    "URL resolves to a private/reserved IP address",
                )
    except HTTPException:
        raise
    except Exception:
        # DNS resolution failure → allow (yt-dlp will fail safely)
        pass

    return url.strip()
