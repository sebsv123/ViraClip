"""
Hook Engine — Phase 9 Creative Engine

Identifies the most impactful hook moment and flags whether the clip
already starts with it or needs reordering.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

HOOK_SIGNALS: "list[tuple[str, float]]" = [
    ("¿", 0.90), ("?", 0.90),
    ("nunca", 0.88), ("never", 0.88),
    ("secreto", 0.85), ("secret", 0.85),
    ("increíble", 0.82), ("incredible", 0.82),
    ("descubre", 0.80), ("discover", 0.80),
    ("impresionante", 0.78), ("amazing", 0.78),
    ("espera", 0.75), ("wait", 0.75),
    ("stop", 0.75), ("listen", 0.72),
    ("shocking", 0.85), ("unbelievable", 0.85),
]

HOOK_WINDOW_S = 3.0  # candidate must appear in first 3s to be "already optimized"


@dataclass
class HookResult:
    hook_start: float       # seconds into segment
    hook_end: float
    hook_text: str
    hook_score: float       # 0–1
    reorder: bool           # True → hook is not in first 3s, suggest reordering
    already_optimized: bool


class HookEngine:
    """
    Scans word-level transcript for the strongest hook candidate
    and returns positioning metadata.
    """

    def find_best_hook(
        self,
        words: "list[dict]",
        segment_duration: float,
    ) -> HookResult:
        """
        Args:
            words:              Word dicts relative to segment (t=0 at clip start).
            segment_duration:   Total clip duration in seconds.
        """
        if not words:
            return HookResult(0.0, 0.0, "", 0.0, False, True)

        best_score = 0.0
        best_idx = 0

        for i, w in enumerate(words):
            word = w.get("word", "").lower().strip(".,!?¡¿\"'")
            raw = w.get("word", "")
            t = float(w.get("start", 0.0))

            for signal, base_score in HOOK_SIGNALS:
                if signal in word or signal in raw:
                    # Penalise late appearances slightly
                    pos_factor = 1.0 if t <= segment_duration * 0.25 else 0.85
                    # Bonus if followed by emphasis punctuation
                    next_raw = words[i + 1].get("word", "") if i + 1 < len(words) else ""
                    emphasis = 1.1 if ("!" in next_raw or "?" in next_raw) else 1.0
                    effective = base_score * pos_factor * emphasis
                    if effective > best_score:
                        best_score = effective
                        best_idx = i

        if best_score == 0.0:
            return HookResult(0.0, 0.0, "", 0.0, False, True)

        bw = words[best_idx]
        snippet_words = words[max(0, best_idx - 2): best_idx + 5]
        hook_text = " ".join(x.get("word", "") for x in snippet_words).strip()
        hook_start = float(bw.get("start", 0.0))
        hook_end = float(bw.get("end", hook_start + 0.5))

        already_optimized = hook_start <= HOOK_WINDOW_S
        reorder = not already_optimized and best_score >= 0.6

        return HookResult(
            hook_start=round(hook_start, 3),
            hook_end=round(hook_end, 3),
            hook_text=hook_text,
            hook_score=round(best_score, 3),
            reorder=reorder,
            already_optimized=already_optimized,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: "HookEngine | None" = None


def get_hook_engine() -> HookEngine:
    global _engine
    if _engine is None:
        _engine = HookEngine()
    return _engine
