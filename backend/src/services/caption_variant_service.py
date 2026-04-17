"""
Caption Variant Generator Service — Phase 24

Generates multiple caption styles for a clip using template-based rules
(no LLM required — uses clip title/transcript keywords).

Variant styles:
  hook       → "You won't believe..." / "Watch what happens when..."
  question   → Turns the title into a question
  statement  → Direct declarative sentence
  listicle   → "#1 reason why..." style
  challenge  → "Try this..." style

Generated variants are stored in Redis (key: caption_variants:{clip_id}).
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_KEY_PREFIX = "caption_variants"
_TTL = 60 * 60 * 24 * 30  # 30 days


def _key(clip_id: str) -> str:
    return f"{_KEY_PREFIX}:{clip_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(text: str) -> str:
    """Strip trailing punctuation for reuse in templates."""
    return re.sub(r"[.!?]+$", "", text.strip())


def generate_variants(title: str, keywords: Optional[List[str]] = None) -> List[Dict]:
    """
    Generate caption variants from a clip title and optional keyword list.
    Returns a list of variant dicts with style + caption.
    """
    base = _clean(title)
    kw = keywords[0] if keywords else base.split()[0] if base else "this"

    variants = [
        {"style": "hook",      "caption": f"You won't believe what happens with {kw}!"},
        {"style": "question",  "caption": f"Have you ever wondered about {base.lower()}?"},
        {"style": "statement", "caption": f"{base}."},
        {"style": "listicle",  "caption": f"The #1 reason {base.lower()} is going viral"},
        {"style": "challenge", "caption": f"Try this: {base.lower()} 👇"},
    ]
    return variants


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


async def get_or_generate_variants(
    clip_id: str,
    title: str,
    keywords: Optional[List[str]] = None,
    force: bool = False,
) -> Dict:
    """
    Return cached caption variants or generate and cache them.
    If `force=True`, always regenerate.
    """
    if not force:
        cached = await _get_cached(clip_id)
        if cached:
            return cached

    variants = generate_variants(title, keywords)
    result = {
        "clip_id": clip_id,
        "title": title,
        "generated_at": _now(),
        "variants": variants,
    }
    await _set_cached(clip_id, result)
    return result


async def clear_variants(clip_id: str) -> None:
    """Evict cached caption variants for a clip."""
    try:
        r = await _redis()
        await r.delete(_key(clip_id))
    except Exception as exc:
        logger.warning("[caption_variants] clear failed clip=%s: %s", clip_id, exc)


async def _get_cached(clip_id: str) -> Optional[Dict]:
    try:
        r = await _redis()
        val = await r.get(_key(clip_id))
        if val:
            return json.loads(val.decode() if isinstance(val, bytes) else val)
        return None
    except Exception:
        return None


async def _set_cached(clip_id: str, data: Dict) -> None:
    try:
        r = await _redis()
        await r.setex(_key(clip_id), _TTL, json.dumps(data))
    except Exception:
        pass
