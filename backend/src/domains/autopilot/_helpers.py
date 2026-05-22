"""Shared helpers for the autopilot domain.

These pure utility functions are used by both the public `TaskService`
facade and the internal mixins, so they live here to avoid circular
imports between `task_service.py` and `_processor_mixin.py`.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def build_hook_title(segment: Dict[str, Any]) -> Optional[str]:
    """
    Generate a concise hook-title overlay for a clip.

    Priority order:
        1. AI-generated `suggested_title` (highest quality, rare)
        2. First 4–6 words of the segment text (short enough to read in 3s)
        3. None (no overlay) — avoids showing raw hook_type strings like "QUESTION"
    """
    if segment.get("suggested_title"):
        raw = segment["suggested_title"].strip()
        return raw[:60] if raw else None

    text = (segment.get("text") or "").strip()
    if not text:
        return None

    filler_starts = {
        "uh", "um", "like", "so", "and", "but", "well",
        "okay", "ok", "right", "you know",
        # Spanish fillers
        "bueno", "o sea", "es que", "pues", "la verdad", "sabes",
        "me refiero", "tipo", "tío", "o sea que", "claro", "entonces",
        "básicamente", "literalmente", "o sea tío",
    }
    words = text.split()
    while words and words[0].lower().strip(".,!?") in filler_starts:
        words = words[1:]

    if not words:
        return None

    result_words = []
    for w in words[:6]:
        result_words.append(w)
        if any(w.endswith(p) for p in [".", "!", "?", ","]):
            break

    title = " ".join(result_words).strip(".,")
    if len(result_words) >= 2 and len(title) <= 50:
        return title

    return None
