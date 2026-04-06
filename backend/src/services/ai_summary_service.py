"""
AI Summary Service — Phase 26

Extracts keywords and generates a short auto-summary from a clip transcript
using rule-based NLP (no LLM required — frequency + stop-word filtering).

Results cached in Redis for 24 hours.
Key schema: ai_summary:{clip_id} → STRING (JSON)
"""

import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_KEY_PREFIX = "ai_summary"
_TTL = 60 * 60 * 24  # 24 hours
_TOP_KEYWORDS = 10
_SUMMARY_SENTENCES = 2

_STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "its", "this", "that", "was",
    "are", "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "will", "would", "could", "should", "may", "might", "shall",
    "not", "no", "so", "as", "if", "then", "than", "when", "where", "who",
    "which", "what", "how", "all", "each", "every", "both", "few", "more",
    "most", "other", "some", "such", "up", "out", "very", "just", "can",
    "i", "you", "he", "she", "we", "they", "my", "your", "his", "her",
    "our", "their", "me", "him", "us", "them",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(clip_id: str) -> str:
    return f"{_KEY_PREFIX}:{clip_id}"


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


def extract_keywords(text: str, top_n: int = _TOP_KEYWORDS) -> List[str]:
    """Extract top-N keywords from text using frequency + stop-word filtering."""
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
    filtered = [w for w in words if w not in _STOP_WORDS]
    counts = Counter(filtered)
    return [word for word, _ in counts.most_common(top_n)]


def generate_summary(text: str, n_sentences: int = _SUMMARY_SENTENCES) -> str:
    """
    Generate a short summary by selecting the highest-scoring sentences
    (scored by keyword density).
    """
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if not sentences:
        return ""
    if len(sentences) <= n_sentences:
        return " ".join(sentences)

    keywords = set(extract_keywords(text, top_n=20))
    scored = []
    for sent in sentences:
        words = re.findall(r"\b[a-zA-Z]{3,}\b", sent.lower())
        score = sum(1 for w in words if w in keywords)
        scored.append((score, sent))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [s for _, s in scored[:n_sentences]]
    original_order = [s for _, s in sorted(
        [(sentences.index(s), s) for s in top],
        key=lambda x: x[0]
    )]
    return " ".join(original_order)


async def get_or_generate_summary(
    clip_id: str,
    transcript: str,
    force: bool = False,
) -> Dict:
    """Return cached summary or compute and cache a new one."""
    if not force:
        cached = await _get_cached(clip_id)
        if cached:
            return cached

    keywords = extract_keywords(transcript)
    summary = generate_summary(transcript)
    word_count = len(transcript.split())

    result = {
        "clip_id": clip_id,
        "summary": summary,
        "keywords": keywords,
        "word_count": word_count,
        "generated_at": _now(),
    }
    await _set_cached(clip_id, result)
    return result


async def clear_summary_cache(clip_id: str) -> None:
    try:
        r = await _redis()
        await r.delete(_key(clip_id))
    except Exception as exc:
        logger.warning("[ai_summary] clear failed clip=%s: %s", clip_id, exc)


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
