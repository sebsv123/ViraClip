"""
Virality Engine — Phase 9 Creative Engine

Unified virality scoring that combines Phi-3, MLP scorer, and timeline
analysis into a single prediction with actionable improvement suggestions.
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

VIRAL_HOOK_WORDS = {
    "nunca", "secreto", "descubre", "increíble", "impresionante",
    "never", "secret", "discover", "incredible", "amazing",
    "wait", "stop", "listen", "shocking", "unbelievable",
}


@dataclass
class ViralityPrediction:
    score: float            # 0–100 blended
    hook_score: float       # 0–100 — first-3s quality
    pacing_score: float     # 0–100 — event density
    emotion_score: float    # 0–100 — audio energy + peaks
    improvements: list[str] = field(default_factory=list)
    marked_for_enhancement: bool = False


class ViralityEngine:
    """
    Blends all existing scoring signals into one prediction.

    Weight distribution:
      hook    30% — first impression drives scroll-stop
      pacing  20% — cut density drives retention
      emotion 20% — audio energy drives engagement
      phi3    30% — LLM/ML scorer for content quality
    """

    VIRAL_THRESHOLD = 65.0

    async def predict(
        self,
        transcript: str,
        words: "list[dict]",
        audio_features: dict,
        timeline_events: list,
    ) -> ViralityPrediction:
        hook = self._score_hook(words[:20] if words else [])
        pacing = self._score_pacing(timeline_events)
        emotion = self._score_emotion(audio_features, timeline_events)
        try:
            phi3 = await self._get_phi3_score(transcript, audio_features)
        except Exception:
            phi3 = 50.0

        score = round(
            min(100.0, max(0.0,
                0.30 * hook + 0.20 * pacing + 0.20 * emotion + 0.30 * phi3
            )), 1
        )
        improvements = self._improvements(score, hook, pacing, emotion, timeline_events)

        return ViralityPrediction(
            score=score,
            hook_score=round(hook, 1),
            pacing_score=round(pacing, 1),
            emotion_score=round(emotion, 1),
            improvements=improvements,
            marked_for_enhancement=score < self.VIRAL_THRESHOLD,
        )

    # ── Sub-scorers ───────────────────────────────────────────────────────────

    def _score_hook(self, first_words: "list[dict]") -> float:
        if not first_words:
            return 40.0
        text = " ".join(w.get("word", "") for w in first_words).lower()
        hits = sum(1 for kw in VIRAL_HOOK_WORDS if kw in text)
        has_question = "?" in text or "¿" in text
        score = 45.0 + hits * 12.0 + (15.0 if has_question else 0.0)
        return min(100.0, score)

    def _score_pacing(self, events: list) -> float:
        if not events:
            return 45.0
        duration = max(e.t for e in events) if events else 1.0
        if duration < 0.1:
            return 45.0
        eps = len(events) / duration  # events per second
        if eps < 0.2:
            return 30.0
        if eps < 0.5:
            return 30.0 + (eps - 0.2) / 0.3 * 40.0
        if eps <= 2.0:
            return 70.0 + (eps - 0.5) / 1.5 * 30.0
        return max(50.0, 100.0 - (eps - 2.0) * 10.0)

    def _score_emotion(self, audio_features: dict, events: list) -> float:
        base = 50.0
        rms = float(audio_features.get("rms_energy", 0) or audio_features.get("energy", 0))
        base += min(20.0, rms * 30.0)
        peaks = sum(1 for e in events if e.type == "audio_peak")
        base += min(20.0, peaks * 3.0)
        return min(100.0, base)

    async def _get_phi3_score(self, transcript: str, audio_features: dict) -> float:
        # Try Phi-3 LLM scorer first
        try:
            from .phi3_virality_service import get_phi3_service
            result = await get_phi3_service().score_segment(
                text=transcript, start_time=0, end_time=60,
                audio_features=audio_features or None,
            )
            return float(result.get("virality_score", 50.0))
        except Exception:
            pass

        # Try MLP scorer
        try:
            from .viral_scorer_service import get_viral_scorer
            scorer = get_viral_scorer()
            feats = scorer.extract_features(transcript, audio_features or {}, {})
            return float(scorer.predict(feats))
        except Exception:
            pass

        # Heuristic fallback — viral keyword count
        viral_words = {"viral", "trending", "nunca", "secreto", "top", "mejor", "best"}
        text_lower = transcript.lower()
        hits = sum(1 for w in viral_words if w in text_lower)
        return min(80.0, 45.0 + hits * 8.0)

    def _improvements(
        self,
        score: float,
        hook: float,
        pacing: float,
        emotion: float,
        events: list,
    ) -> "list[str]":
        out: list[str] = []
        if hook < 60:
            out.append("Strengthen hook in first 3s — add a question or surprising stat")
        if pacing < 50:
            out.append("Increase cut density — add jump cuts in slow segments")
        if emotion < 50:
            out.append("Boost audio energy or add background music")
        if not any(e.type == "audio_peak" for e in events):
            out.append("No audio peaks detected — add SFX at key moments")
        if score >= self.VIRAL_THRESHOLD and not out:
            out.append("Clip is publish-ready ✅")
        return out


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: "ViralityEngine | None" = None


def get_virality_engine() -> ViralityEngine:
    global _engine
    if _engine is None:
        _engine = ViralityEngine()
    return _engine
