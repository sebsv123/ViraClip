"""
Virality Engine

Predicts virality score based on hook quality, pacing, and emotional load.
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Retention hook words for first 3s detection
HOOK_RETENTION_WORDS = {
    "nunca", "secreto", "descubre", "increíble", "impresionante",
    "never", "secret", "discover", "incredible", "amazing",
    "wait", "stop", "listen", "shocking", "unbelievable",
    "atención", "attention", "mira", "look", "urgente", "urgent",
}

# High emotional load words
EMOTIONAL_WORDS = {
    "amor", "love", "odio", "hate", "pasión", "passion",
    "miedo", "fear", "alegría", "joy", "tristeza", "sadness",
    "brutal", "brutal", "increíble", "incredible", "impresionante",
    "amazing", "terrible", "terrible", "genial", "great",
    "odio", "hate", "corazón", "heart", "romper", "break",
    "destruir", "destroy", "ganar", "win", "perder", "lose",
    "éxito", "success", "fracaso", "failure", "ganador", "winner",
}


@dataclass
class ViralityPrediction:
    score: float                    # 0-100 blended
    hook_score: float               # 0-100 — first 3s hook quality
    pacing_score: float             # 0-100 — words per second (optimal 2.5-3.5 wps)
    emotion_score: float            # 0-100 — emotional word density
    improvements: list[str] = field(default_factory=list)


class ViralityEngine:
    """Calculate virality prediction based on content analysis."""

    async def predict(
        self,
        transcript: str,
        words: "list[dict]",
        audio_features: dict,
        timeline_events: list,
    ) -> ViralityPrediction:
        """Predict virality score with component breakdown."""
        hook = self._score_hook(words)
        pacing = self._score_pacing(words)
        emotion = self._score_emotion(transcript)
        
        # Timeline bonus (max 10 points)
        timeline_bonus = min(len(timeline_events) * 2, 10)
        
        # Final weighted score
        score = round(
            min(100.0, max(0.0,
                0.35 * hook + 
                0.30 * pacing + 
                0.25 * emotion + 
                0.10 * timeline_bonus
            )), 1
        )
        
        improvements = self._generate_improvements(hook, pacing, emotion)
        
        return ViralityPrediction(
            score=score,
            hook_score=round(hook, 1),
            pacing_score=round(pacing, 1),
            emotion_score=round(emotion, 1),
            improvements=improvements,
        )

    def _score_hook(self, words: "list[dict]") -> float:
        """Score hook quality based on words in first 3 seconds."""
        if not words:
            return 50.0
        
        # Get words in first 3 seconds
        first_3s_words = []
        for w in words[:30]:  # Approximate first 30 words ~3s
            if w.get("start", 0) <= 3.0:
                first_3s_words.append(w.get("word", "").lower())
        
        if not first_3s_words:
            return 50.0
        
        # Count retention hook words
        text = " ".join(first_3s_words)
        hook_hits = sum(1 for word in HOOK_RETENTION_WORDS if word in text)
        
        # Has question mark (engagement hook)
        has_question = "?" in text or "¿" in text
        
        # Base score + hook words bonus + question bonus
        score = 40.0 + (hook_hits * 10.0) + (15.0 if has_question else 0.0)
        return min(100.0, score)

    def _score_pacing(self, words: "list[dict]") -> float:
        """Score pacing based on words per second (optimal 2.5-3.5 wps)."""
        if not words or len(words) < 2:
            return 50.0
        
        # Calculate total duration
        first_word = words[0]
        last_word = words[-1]
        duration = last_word.get("end", 0) - first_word.get("start", 0)
        
        if duration < 0.5:
            return 50.0
        
        # Words per second
        wps = len(words) / duration
        
        # Optimal range: 2.5-3.5 wps = 100 points
        # Deviations reduce score linearly
        if 2.5 <= wps <= 3.5:
            return 100.0
        elif wps < 2.5:
            # Too slow: linear penalty from 2.5 to 1.0
            return max(30.0, 100.0 - (2.5 - wps) * 30.0)
        else:
            # Too fast: linear penalty from 3.5 to 6.0
            return max(30.0, 100.0 - (wps - 3.5) * 25.0)

    def _score_emotion(self, transcript: str) -> float:
        """Score emotional load based on emotional word density."""
        if not transcript:
            return 50.0
        
        text_lower = transcript.lower()
        words = text_lower.split()
        
        if not words:
            return 50.0
        
        # Count emotional words
        emotional_hits = sum(1 for word in EMOTIONAL_WORDS if word in text_lower)
        
        # Calculate density (emotional words per 100 words)
        density = (emotional_hits / len(words)) * 100
        
        # Optimal emotional density: 5-15%
        if 5.0 <= density <= 15.0:
            return 100.0
        elif density < 5.0:
            return 60.0 + (density * 8.0)  # 0% = 60, 5% = 100
        else:
            return max(40.0, 100.0 - (density - 15.0) * 3.0)

    def _generate_improvements(
        self,
        hook: float,
        pacing: float,
        emotion: float,
    ) -> "list[str]":
        """Generate actionable improvement suggestions."""
        out: list[str] = []
        
        if hook < 60:
            out.append("Add hook retention word in first 3s (e.g., 'wait', 'secret', 'never')")
        if pacing < 60:
            if pacing < 40:
                out.append("Pacing too slow — increase speech rate or add jump cuts")
            else:
                out.append("Pacing slightly off — aim for 2.5-3.5 words per second")
        if emotion < 60:
            out.append("Increase emotional words (passion, love, fear, success, etc.)")
        
        if not out:
            out.append("Content is well-optimized for virality")
        
        return out


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: "ViralityEngine | None" = None


def get_virality_engine() -> ViralityEngine:
    """Get or create singleton virality engine."""
    global _engine
    if _engine is None:
        _engine = ViralityEngine()
    return _engine
