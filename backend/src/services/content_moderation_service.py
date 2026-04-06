"""
Content Moderation Service — Phase 21

Scans clip transcripts for flagged keyword categories and marks clips accordingly.
Flag results cached in Redis: moderation:{clip_id}

Categories (extensible):
  - profanity  → common strong language
  - violence   → descriptions of violent acts
  - hate_speech → slurs and discriminatory language triggers

Scoring: returns a dict with category → hit_count + overall severity (none/low/medium/high)
"""

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_CACHE_TTL = 60 * 60 * 24  # 24 hours
_KEY_PREFIX = "moderation"

# Keyword lists (lowercase, stripped) — intentionally minimal placeholder lists
_PROFANITY_PATTERNS = [r"\bf+u+c+k\b", r"\bs+h+i+t\b", r"\ba+s+s\b", r"\bb+i+t+c+h\b"]
_VIOLENCE_PATTERNS = [r"\bkill\b", r"\bmurder\b", r"\bshoot\b", r"\bstab\b", r"\bblood\b"]
_HATE_SPEECH_PATTERNS = [r"\bn-?word\b"]

_CATEGORIES: Dict[str, List[str]] = {
    "profanity": _PROFANITY_PATTERNS,
    "violence": _VIOLENCE_PATTERNS,
    "hate_speech": _HATE_SPEECH_PATTERNS,
}


def scan_transcript(transcript: str) -> Dict:
    """
    Scan a transcript string and return a moderation result dict:
      {
        "flagged": bool,
        "severity": "none" | "low" | "medium" | "high",
        "categories": {"profanity": N, "violence": N, "hate_speech": N},
        "total_hits": int,
      }
    """
    text = transcript.lower()
    category_hits: Dict[str, int] = {}
    total_hits = 0

    for category, patterns in _CATEGORIES.items():
        hits = 0
        for pattern in patterns:
            hits += len(re.findall(pattern, text))
        category_hits[category] = hits
        total_hits += hits

    flagged = total_hits > 0
    if not flagged:
        severity = "none"
    elif total_hits <= 2:
        severity = "low"
    elif total_hits <= 6:
        severity = "medium"
    else:
        severity = "high"

    return {
        "flagged": flagged,
        "severity": severity,
        "categories": category_hits,
        "total_hits": total_hits,
    }


async def moderate_clip(clip_id: str, transcript: str, use_cache: bool = True) -> Dict:
    """
    Moderate a clip transcript, optionally returning cached results.
    Stores result in Redis.
    """
    if use_cache:
        cached = await _get_cached(clip_id)
        if cached is not None:
            return cached

    result = scan_transcript(transcript)
    result["clip_id"] = clip_id

    await _set_cached(clip_id, result)
    logger.debug("[moderation] clip=%s severity=%s hits=%d",
                 clip_id, result["severity"], result["total_hits"])
    return result


async def get_moderation_result(clip_id: str) -> Optional[Dict]:
    """Return cached moderation result or None."""
    return await _get_cached(clip_id)


async def clear_moderation_cache(clip_id: str) -> None:
    """Evict cached moderation result for a clip."""
    try:
        from src.workers.job_queue import JobQueue
        r = await JobQueue.get_pool()
        await r.delete(f"{_KEY_PREFIX}:{clip_id}")
    except Exception as exc:
        logger.warning("[moderation] clear_cache failed clip=%s: %s", clip_id, exc)


async def _get_cached(clip_id: str) -> Optional[Dict]:
    import json
    try:
        from src.workers.job_queue import JobQueue
        r = await JobQueue.get_pool()
        val = await r.get(f"{_KEY_PREFIX}:{clip_id}")
        if val:
            return json.loads(val.decode() if isinstance(val, bytes) else val)
        return None
    except Exception:
        return None


async def _set_cached(clip_id: str, result: Dict) -> None:
    import json
    try:
        from src.workers.job_queue import JobQueue
        r = await JobQueue.get_pool()
        await r.setex(f"{_KEY_PREFIX}:{clip_id}", _CACHE_TTL, json.dumps(result))
    except Exception:
        pass
