"""
Webhook Security Service — Phase 16

HMAC-SHA256 signature verification for incoming platform webhooks.
Supports TikTok, Instagram (Meta), and YouTube.

Each platform uses a slightly different header + payload format:
  - TikTok:    X-TikTok-Signature  = "sha256=<hex>"    (HMAC of raw body)
  - Instagram: X-Hub-Signature-256 = "sha256=<hex>"    (Meta standard)
  - YouTube:   X-Hub-Signature     = "sha1=<hex>"      (PubSubHubbub, sha1)
"""

import hashlib
import hmac
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


# ── Secrets (from env) ────────────────────────────────────────────────────────

def _get_secret(key: str) -> Optional[bytes]:
    val = os.getenv(key, "").strip()
    return val.encode() if val else None


def _tiktok_secret() -> Optional[bytes]:
    return _get_secret("TIKTOK_WEBHOOK_SECRET")


def _meta_secret() -> Optional[bytes]:
    return _get_secret("META_WEBHOOK_SECRET") or _get_secret("INSTAGRAM_WEBHOOK_SECRET")


def _youtube_secret() -> Optional[bytes]:
    return _get_secret("YOUTUBE_WEBHOOK_SECRET")


# ── Core verification ─────────────────────────────────────────────────────────

def _verify_hmac_sha256(secret: bytes, payload: bytes, signature_header: str) -> bool:
    """
    Verify an HMAC-SHA256 signature of the form 'sha256=<hex_digest>'.
    Uses hmac.compare_digest to prevent timing attacks.
    """
    if not signature_header.startswith("sha256="):
        logger.debug("[webhook_sec] Header missing sha256= prefix")
        return False
    expected_hex = signature_header[7:]
    actual = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(actual, expected_hex)


def _verify_hmac_sha1(secret: bytes, payload: bytes, signature_header: str) -> bool:
    """Verify an HMAC-SHA1 signature of the form 'sha1=<hex_digest>'."""
    if not signature_header.startswith("sha1="):
        logger.debug("[webhook_sec] Header missing sha1= prefix")
        return False
    expected_hex = signature_header[5:]
    actual = hmac.new(secret, payload, hashlib.sha1).hexdigest()
    return hmac.compare_digest(actual, expected_hex)


# ── Public helpers per platform ───────────────────────────────────────────────

def verify_tiktok_webhook(raw_body: bytes, signature_header: str) -> bool:
    """
    Verify a TikTok webhook POST.
    Header: X-TikTok-Signature: sha256=<hex>
    If TIKTOK_WEBHOOK_SECRET is unset, verification is skipped (returns True).
    """
    secret = _tiktok_secret()
    if not secret:
        logger.debug("[webhook_sec] TIKTOK_WEBHOOK_SECRET not set — skipping verification")
        return True
    ok = _verify_hmac_sha256(secret, raw_body, signature_header)
    if not ok:
        logger.warning("[webhook_sec] TikTok signature mismatch")
    return ok


def verify_meta_webhook(raw_body: bytes, signature_header: str) -> bool:
    """
    Verify a Meta (Instagram / Facebook) webhook POST.
    Header: X-Hub-Signature-256: sha256=<hex>
    """
    secret = _meta_secret()
    if not secret:
        logger.debug("[webhook_sec] META_WEBHOOK_SECRET not set — skipping verification")
        return True
    ok = _verify_hmac_sha256(secret, raw_body, signature_header)
    if not ok:
        logger.warning("[webhook_sec] Meta signature mismatch")
    return ok


def verify_youtube_webhook(raw_body: bytes, signature_header: str) -> bool:
    """
    Verify a YouTube PubSubHubbub webhook POST.
    Header: X-Hub-Signature: sha1=<hex>
    """
    secret = _youtube_secret()
    if not secret:
        logger.debug("[webhook_sec] YOUTUBE_WEBHOOK_SECRET not set — skipping verification")
        return True
    ok = _verify_hmac_sha1(secret, raw_body, signature_header)
    if not ok:
        logger.warning("[webhook_sec] YouTube signature mismatch")
    return ok


def verify_webhook(
    platform: str,
    raw_body: bytes,
    *,
    tiktok_signature: str = "",
    meta_signature: str = "",
    youtube_signature: str = "",
) -> bool:
    """
    Unified dispatcher — calls the correct verifier based on platform.
    platform: 'tiktok' | 'instagram' | 'youtube'
    """
    platform = platform.lower()
    if platform == "tiktok":
        return verify_tiktok_webhook(raw_body, tiktok_signature)
    if platform in ("instagram", "meta"):
        return verify_meta_webhook(raw_body, meta_signature)
    if platform == "youtube":
        return verify_youtube_webhook(raw_body, youtube_signature)
    logger.warning("[webhook_sec] Unknown platform '%s' — denying", platform)
    return False
