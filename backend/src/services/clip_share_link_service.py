"""
Signed share links for clips with HMAC verification and Redis-based revocation.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

SHARE_SECRET = os.getenv("SHARE_LINK_SECRET", secrets.token_hex(32))
SHARE_BASE_URL = os.getenv("SHARE_BASE_URL", "https://app.viraclip.com")
DEFAULT_EXPIRY_HOURS = int(os.getenv("SHARE_LINK_EXPIRY_HOURS", "48"))


def _generate_token(clip_id: str, expires_at: datetime) -> str:
    """Generate HMAC-SHA256 signed token for share link."""
    payload = {"clip_id": clip_id, "exp": expires_at.isoformat()}
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).decode().rstrip("=")
    sig = hmac.new(
        SHARE_SECRET.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    return f"{payload_b64}.{sig}"


def _verify_token(token: str) -> dict | None:
    """Verify token signature and expiry. Returns payload or None."""
    try:
        payload_b64, sig = token.rsplit(".", 1)
        expected = hmac.new(
            SHARE_SECRET.encode(),
            payload_b64.encode(),
            hashlib.sha256,
        ).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            return None
        padding = 4 - len(payload_b64) % 4
        payload = json.loads(
            base64.urlsafe_b64decode(payload_b64 + "=" * padding)
        )
        exp = datetime.fromisoformat(payload["exp"])
        if datetime.utcnow() > exp:
            return None
        return payload
    except Exception:
        return None


MAX_SHARE_LINKS_PER_CLIP = int(os.getenv("MAX_SHARE_LINKS_PER_CLIP", "10"))


async def _count_active_share_links(clip_id: str, redis) -> int:
    """Count active share links in Redis for this clip."""
    try:
        env = os.getenv("APP_ENV", "production")
        pattern = f"{env}:share:{clip_id}:*"
        count = 0
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
            count += len(keys)
            if cursor == 0:
                break
        return count
    except Exception:
        return 0


async def create_share_link(
    clip_id: str,
    user_id: str,
    redis,
    expiry_hours: int = DEFAULT_EXPIRY_HOURS,
) -> dict:
    """Create a signed share link with Redis metadata."""
    # Check active share links limit
    active_count = await _count_active_share_links(clip_id, redis)
    if active_count >= MAX_SHARE_LINKS_PER_CLIP:
        from fastapi import HTTPException
        raise HTTPException(
            429,
            {
                "error": "Too many active share links",
                "active": active_count,
                "max": MAX_SHARE_LINKS_PER_CLIP,
                "message": f"This clip has {active_count} active share links. "
                           f"Revoke some before creating new ones.",
            },
        )

    expires_at = datetime.utcnow() + timedelta(hours=expiry_hours)
    token = _generate_token(clip_id, expires_at)
    share_url = f"{SHARE_BASE_URL}/share/{token}"

    env = os.getenv("APP_ENV", "production")
    redis_key = f"{env}:share:{clip_id}:{token[:16]}"
    await redis.setex(
        redis_key,
        int(timedelta(hours=expiry_hours).total_seconds()),
        json.dumps({
            "clip_id": clip_id,
            "user_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
        }),
    )

    return {
        "url": share_url,
        "token": token,
        "expires_at": expires_at.isoformat() + "Z",
        "expires_in_hours": expiry_hours,
    }


async def revoke_share_link(clip_id: str, token: str, redis) -> bool:
    """Revoke a share link by deleting its Redis key."""
    try:
        env = os.getenv("APP_ENV", "production")
        redis_key = f"{env}:share:{clip_id}:{token[:16]}"
        deleted = await redis.delete(redis_key)
        return deleted > 0
    except Exception:
        return False
