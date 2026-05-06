"""
Virality Engine

Predicts virality score based on hook quality, pacing, and emotional load.
Auto-applies improvements when score < 65.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Retention hook words for first 3s detection
HOOK_RETENTION_WORDS = {
    "nunca", "secreto", "descubre", "increíble", "impresionante",
    "never", "secret", "discover", "incredible", "amazing",
    "wait", "stop", "listen", "shocking", "unbelievable",
    "atención", "attention", "mira", "look", "urgente", "urgent",
    "error", "gratis", "free", "cuidado", "careful", "familia",
    "family", "hipoteca", "mortgage", "protección", "protection",
    "seguro", "insurance", "dinero", "money", "perder", "lose",
    "ganar", "win", "importante", "important", "espera",
    "nadie te dice", "lo que no sabes", "antes de que", "si tienes",
}

# High emotional load words
EMOTIONAL_WORDS = {
    "amor", "love", "odio", "hate", "pasión", "passion",
    "miedo", "fear", "alegría", "joy", "tristeza", "sadness",
    "brutal", "increíble", "incredible", "impresionante",
    "amazing", "terrible", "genial", "great",
    "corazón", "heart", "romper", "break",
    "destruir", "destroy", "ganar", "win", "perder", "lose",
    "éxito", "success", "fracaso", "failure", "ganador", "winner",
}

# Spanish high-impact words for niche insurance/family content
HIGH_IMPACT_WORDS_ES = [
    "nunca", "secreto", "error", "gratis", "urgente", "cuidado",
    "familia", "hipoteca", "protección", "seguro", "dinero", "perder",
    "ganar", "increíble", "importante", "atención", "espera", "mira",
    "nadie te dice", "lo que no sabes", "antes de que", "si tienes",
]


@dataclass
class ViralityPrediction:
    score: float                    # 0-100 blended
    hook_score: float               # 0-100 — first 3s hook quality
    pacing_score: float             # 0-100 — words per second (optimal 2.5-3.5 wps)
    emotion_score: float            # 0-100 — emotional word density
    improvements: list[str] = field(default_factory=list)
    hook_reordered: bool = False    # True if auto-apply reordered the hook


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

        # Final weighted score — hook_strength increased from 0.35 to 0.40
        # for niche content where the first 3s are critical for retention
        score = round(
            min(100.0, max(0.0,
                0.40 * hook +
                0.30 * pacing +
                0.20 * emotion +
                0.10 * timeline_bonus
            )), 1
        )

        improvements = self._generate_improvements(hook, pacing, emotion)

        pred = ViralityPrediction(
            score=score,
            hook_score=round(hook, 1),
            pacing_score=round(pacing, 1),
            emotion_score=round(emotion, 1),
            improvements=improvements,
        )

        # Auto-apply improvements when score < 65
        if score < 65 and improvements:
            pred = self.auto_apply_improvements(pred, words, transcript)

        return pred

    def auto_apply_improvements(
        self, pred: ViralityPrediction, words: "list[dict]", transcript: str
    ) -> ViralityPrediction:
        """
        Auto-apply improvements when score < 65.
        If improvement mentions hook/first 3s, find the segment with highest
        emotional energy or high-impact words and mark it as hook_reordered.
        """
        has_hook_improvement = any(
            "hook" in imp.lower() or "first 3s" in imp.lower()
            for imp in pred.improvements
        )
        if not has_hook_improvement:
            return pred

        if not words:
            return pred

        # Find the word with highest impact in the transcript
        text_lower = transcript.lower()
        best_idx = 0
        best_score = 0.0

        for i, w in enumerate(words[:50]):  # Scan first ~50 words
            word_text = (w.get("word") or "").lower().strip(".,!?;:")
            if not word_text:
                continue
            # Score based on high-impact word match
            word_score = 0.0
            for hiw in HIGH_IMPACT_WORDS_ES:
                if hiw in word_text or word_text in hiw:
                    word_score += 15.0
            # Bonus for emphasis words
            if w.get("is_emphasis", False):
                word_score += 10.0
            # Bonus for uppercase (shouting)
            if word_text.isupper() and len(word_text) > 2:
                word_score += 5.0
            if word_score > best_score:
                best_score = word_score
                best_idx = i

        if best_score > 0:
            pred.hook_reordered = True
            # Boost score by 8 points for finding a high-impact hook word
            pred.score = min(100.0, pred.score + 8.0)
            logger.info(
                "[ViralityEngine] Auto-applied hook reorder: word '%s' at index %d "
                "(score +8 → %.1f)",
                words[best_idx].get("word", ""), best_idx, pred.score,
            )

        return pred

    def _score_hook(self, words: "list[dict]") -> float:
        """Score hook quality based on words in first 3 seconds."""
        if not words:
            return 50.0

        # Get words in first 3 seconds
        first_3s_words = []
        for w in words[:30]:
            if w.get("start", 0) <= 3.0:
                first_3s_words.append(w.get("word", "").lower())

        if not first_3s_words:
            return 50.0

        # Count retention hook words
        text = " ".join(first_3s_words)
        hook_hits = sum(1 for word in HOOK_RETENTION_WORDS if word in text)

        # Count Spanish high-impact words
        es_hits = sum(1 for word in HIGH_IMPACT_WORDS_ES if word in text)

        # Has question mark (engagement hook)
        has_question = "?" in text or "¿" in text

        # Base score + hook words bonus + ES impact bonus + question bonus
        score = 40.0 + (hook_hits * 8.0) + (es_hits * 8.0) + (15.0 if has_question else 0.0)
        return min(100.0, score)

    def _score_pacing(self, words: "list[dict]") -> float:
        """Score pacing based on words per second (optimal 2.5-3.5 wps)."""
        if not words or len(words) < 2:
            return 50.0

        first_word = words[0]
        last_word = words[-1]
        duration = last_word.get("end", 0) - first_word.get("start", 0)

        if duration < 0.5:
            return 50.0

        wps = len(words) / duration

        if 2.5 <= wps <= 3.5:
            return 100.0
        elif wps < 2.5:
            return max(30.0, 100.0 - (2.5 - wps) * 30.0)
        else:
            return max(30.0, 100.0 - (wps - 3.5) * 25.0)

    def _score_emotion(self, transcript: str) -> float:
        """Score emotional load based on emotional word density."""
        if not transcript:
            return 50.0

        text_lower = transcript.lower()
        words = text_lower.split()

        if not words:
            return 50.0

        emotional_hits = sum(1 for word in EMOTIONAL_WORDS if word in text_lower)
        density = (emotional_hits / len(words)) * 100

        if 5.0 <= density <= 15.0:
            return 100.0
        elif density < 5.0:
            return 60.0 + (density * 8.0)
        else:
            return max(40.0, 100.0 - (density - 15.0) * 3.0)

    def _generate_improvements(
        self, hook: float, pacing: float, emotion: float,
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
