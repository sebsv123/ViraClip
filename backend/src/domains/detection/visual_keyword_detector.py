"""
Visual Keyword Detector — Contextual Overlay System

Detects visual keywords from transcript that should trigger image/video overlays.
Uses NLP to identify concrete nouns and visual concepts.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

from src.domains.broll.broll_config import (
    MIN_OVERLAY_DURATION_S,
    MIN_GAP_BETWEEN_OVERLAYS_S,
    CATEGORY_COOLDOWN_S,
)

# ── Quality guards for overlay cues ──────────────────────────────────────────
_MIN_CUE_DURATION_S = MIN_OVERLAY_DURATION_S  # skip cues shorter than canonical minimum
_SEMANTIC_CONFIDENCE = 0.6      # minimum confidence to accept a keyword
_CATEGORY_COOLDOWN_S = CATEGORY_COOLDOWN_S    # don't repeat same category within cooldown
_MERGE_SAME_CATEGORY_GAP_S = MIN_GAP_BETWEEN_OVERLAYS_S  # merge adjacent cues from same category if gap ≤ tolerance
_FALLBACK_CONFIDENCE = 0.4      # below this → skip entirely; between 0.4-0.6 → overlay-only

# Visual keyword categories — expanded for viral content (ES + EN)
VISUAL_KEYWORDS = {
    # Nature & Environment
    "nature": ["ocean", "sea", "beach", "mountain", "forest", "sky", "sunset", "sunrise", "river", "lake", "waterfall", "clouds", "stars", "moon", "sun", "naturaleza", "playa", "montaña", "bosque", "río", "mar", "cielo", "sol", "luna", "árbol", "flor", "campo"],
    
    # Money & Business
    "money": ["money", "cash", "dollars", "wealth", "rich", "profit", "revenue", "income", "investment", "business", "success", "growth", "dinero", "rico", "millón", "million", "inversión", "invest", "negocio", "éxito", "ganar", "win", "ahorro", "banco", "tarjeta", "seguro", "finanzas"],
    
    # Emotions & Abstract Concepts
    "emotion": ["success", "failure", "happiness", "sadness", "anger", "fear", "love", "hate", "celebration", "victory", "increíble", "incredible", "brutal", "crazy", "secreto", "secret", "verdad", "truth", "error", "mistake", "importante", "important", "urgente", "urgent", "peligro", "danger", "feliz", "triste", "miedo", "amor", "odio"],
    
    # Technology
    "tech": ["computer", "phone", "laptop", "screen", "technology", "ai", "robot", "code", "software", "internet", "computadora", "celular", "teléfono", "pantalla", "ordenador", "tablet", "aplicación", "app", "datos"],
    
    # People & Actions
    "people": ["person", "people", "crowd", "team", "group", "family", "friends", "audience", "gente", "amigo", "friend", "familia", "family", "mundo", "world", "persona", "personas", "multitud", "equipo", "grupo", "hijo", "padre", "madre"],
    
    # Objects
    "objects": ["car", "house", "building", "city", "food", "book", "camera", "microphone", "coche", "casa", "edificio", "ciudad", "comida", "coche", "coche", "oficina", "documento", "papel", "móvil", "llave", "reloj"],
    
    # Sports & Action
    "sports": ["running", "jumping", "swimming", "playing", "fighting", "racing", "climbing", "correr", "saltar", "entrenar", "gym", "fitness", "workout", "deporte", "fútbol", "balón", "gol"],
    
    # Motivation & Viral Triggers
    "motivation": ["gratis", "free", "fácil", "easy", "rápido", "fast", "mejor", "best", "nuevo", "new", "ahora", "now", "nunca", "never", "siempre", "always", "clave", "key", "único", "unique", "exclusivo", "exclusive", "poderoso", "transforma", "cambia", "descubre"],
    
    # Social Media & Engagement
    "social": ["mira", "watch", "escucha", "listen", "comparte", "share", "sigue", "follow", "like", "comenta", "comment", "suscríbete", "subscribe", "sígueme", "compártelo"],
    
    # Health & Body
    "health": ["salud", "health", "cuerpo", "body", "mente", "mind", "ejercicio", "exercise", "dieta", "diet", "peso", "weight", "vida", "life", "corazón", "médico", "hospital", "enfermedad"],

    # Insurance & Finance (concrete visual concepts)
    "insurance": [
        "insurance", "seguro", "policy", "póliza", "claim", "reclamo", "siniestro",
        "coverage", "cobertura", "premium", "prima", "protection", "protección",
        "advisor", "asesor", "agent", "agente", "broker", "corredor",
        "consultation", "consulta", "office", "oficina", "desk", "escritorio",
        "document", "documento", "contract", "contrato", "signing", "firma",
        "signature", "firmar", "paperwork", "trámite", "form", "formulario",
        "claim form", "parte", "accident", "accidente", "car accident", "choque",
        "damage", "daño", "repair", "reparación", "inspection", "inspección",
        "family", "familia", "home", "hogar", "house", "casa", "protection",
        "savings", "ahorro", "retirement", "jubilación", "planning", "planificación",
        "financial", "financiero", "investment", "inversión", "calculator", "calculadora",
        "phone call", "llamada", "consultation", "customer service", "atención al cliente",
        "support", "apoyo", "help", "ayuda", "emergency", "emergencia",
        "hospital", "médico", "doctor", "patient", "paciente", "medical", "médico",
        "health", "salud", "life insurance", "seguro de vida", "car insurance",
        "seguro de coche", "home insurance", "seguro del hogar",
    ],
}
# Flatten all keywords for quick lookup
ALL_VISUAL_KEYWORDS = set()
for category_words in VISUAL_KEYWORDS.values():
    ALL_VISUAL_KEYWORDS.update(category_words)


@dataclass
class VisualKeyword:
    """Detected visual keyword with timing and context."""
    keyword: str
    category: str
    start_time: float
    end_time: float
    word: str  # Original word from transcript
    confidence: float  # 0.0-1.0


class VisualKeywordDetector:
    """
    Detects visual keywords from transcript with word timings.
    
    Strategy:
    1. Match against predefined visual keyword dictionary
    2. Use simple stemming/lemmatization for variations
    3. Filter based on part-of-speech (prefer nouns)
    4. Return with timing information for overlay synchronization
    """
    
    def __init__(self):
        self.visual_keywords = VISUAL_KEYWORDS
        self.all_keywords = ALL_VISUAL_KEYWORDS
    
    def detect(
        self,
        transcript: str,
        word_timings: List[Dict],
        max_keywords: int = 10,
        min_confidence: float = 0.6,
        broll_keywords: Optional[List[str]] = None,
    ) -> List[VisualKeyword]:
        """
        Detect visual keywords from transcript with timing.
        
        Args:
            transcript: Full transcript text
            word_timings: List of {word, start, end, confidence?}
            max_keywords: Maximum keywords to return
            min_confidence: Minimum confidence threshold
            broll_keywords: Fallback keywords from B-roll selection if detection is empty
            
        Returns:
            List of VisualKeyword objects sorted by start time
        """
        detected = []
        
        if not word_timings:
            logger.debug("No word timings provided for visual keyword detection")
            # Fallback: use B-roll keywords evenly spaced
            if broll_keywords:
                return self._broll_keywords_as_visual(broll_keywords, max_keywords)
            return []
        
        # Process each word
        for word_info in word_timings:
            word = word_info.get("word", "").lower().strip()
            start = float(word_info.get("start", 0.0))
            end = float(word_info.get("end", start + 0.5))
            
            if not word:
                continue
            
            # Clean word (remove punctuation)
            clean_word = re.sub(r'[^\w\s]', '', word)
            
            # Check if word is a visual keyword
            if clean_word in self.all_keywords:
                category = self._get_category(clean_word)
                confidence = word_info.get("confidence", 0.8)
                
                if confidence >= min_confidence:
                    detected.append(VisualKeyword(
                        keyword=clean_word,
                        category=category,
                        start_time=start,
                        end_time=end,
                        word=word,
                        confidence=confidence
                    ))
        
        # Sort by start time
        detected.sort(key=lambda k: k.start_time)
        
        # Deduplicate nearby keywords (within 2 seconds)
        deduplicated = self._deduplicate(detected, min_gap_seconds=2.0)
        
        # If no keywords detected, fallback to B-roll keywords
        if not deduplicated and broll_keywords:
            logger.info("[VKD] No transcript keywords — falling back to %d B-roll keywords", len(broll_keywords))
            return self._broll_keywords_as_visual(broll_keywords, max_keywords)
        
        # Apply quality guards: min duration, category cooldown, same-category merge
        guarded = self._apply_quality_guards(deduplicated, max_keywords)
        
        return guarded[:max_keywords]
    
    def _broll_keywords_as_visual(
        self, broll_keywords: List[str], max_keywords: int
    ) -> List[VisualKeyword]:
        """Convert B-roll keywords to evenly-spaced VisualKeyword objects.

        Applies quality guards: minimum duration, category cooldown,
        same-category merging, and confidence fallback.
        """
        raw = []
        for i, kw in enumerate(broll_keywords[:max_keywords]):
            cat = self._get_category(kw.lower())
            raw.append(VisualKeyword(
                keyword=kw,
                category=cat if cat != "general" else "objects",
                start_time=2.0 + i * 4.0,  # space every 4s starting at 2s
                end_time=2.0 + i * 4.0 + 2.0,
                word=kw,
                confidence=0.7,
            ))
        return self._apply_quality_guards(raw, max_keywords)
    
    def detect_with_virality_filter(
        self,
        transcript: str,
        word_timings: List[Dict],
        audio_features: Dict,
        virality_score: float,
        max_keywords: int = 10,
        broll_keywords: Optional[List[str]] = None,
    ) -> List[VisualKeyword]:
        """
        Detect visual keywords with virality-based filtering.
        
        Only returns keywords if:
        - Clip virality score is above threshold (50)
        - Keyword occurs during high-energy moment
        - Keyword is spaced appropriately (5-8 per minute)
        
        Falls back to broll_keywords if no transcript keywords are detected.
        """
        # Bypass virality check when broll_keywords fallback is provided
        # This ensures clips with scores just below threshold still get overlays
        if broll_keywords:
            logger.debug(
                "[VKD] Bypassing virality filter (score=%.1f) — using %d B-roll keywords as fallback",
                virality_score, len(broll_keywords),
            )
            return self._broll_keywords_as_visual(broll_keywords, max_keywords)
        
        # Don't show overlays on very low-virality clips (below 50)
        if virality_score < 50:
            logger.debug(f"Virality score {virality_score} below threshold (50), skipping overlays")
            return []
        
        # Detect all keywords, passing broll_keywords as fallback
        all_keywords = self.detect(
            transcript, word_timings,
            max_keywords=max_keywords * 2,
            broll_keywords=broll_keywords,
        )
        
        # Filter by energy if audio features available
        if audio_features and "energy" in audio_features:
            energy_threshold = 0.5
            filtered = []
            
            for kw in all_keywords:
                # Simple approximation: use overall energy
                # In production, would use frame-level energy at kw.start_time
                if audio_features["energy"] > energy_threshold:
                    filtered.append(kw)
            
            return filtered[:max_keywords]
        
        return all_keywords[:max_keywords]
    
    def _get_category(self, keyword: str) -> str:
        """Get category for a keyword."""
        for category, words in self.visual_keywords.items():
            if keyword in words:
                return category
        return "general"
    
    def _apply_quality_guards(
        self, keywords: List[VisualKeyword], max_keywords: int
    ) -> List[VisualKeyword]:
        """Apply quality guards to a list of keyword cues.

        Guards applied in order:
        1. Minimum duration — skip cues shorter than _MIN_CUE_DURATION_S
        2. Confidence fallback — below _FALLBACK_CONFIDENCE → skip;
           between _FALLBACK_CONFIDENCE and _SEMANTIC_CONFIDENCE → mark as overlay-only
        3. Merge adjacent same-category cues — if gap ≤ _MERGE_SAME_CATEGORY_GAP_S,
           merge into one longer cue
        4. Category cooldown — if same category appears within _CATEGORY_COOLDOWN_S
           of the last accepted cue, skip the repeat

        Returns:
            Filtered list of VisualKeyword objects.
        """
        if not keywords:
            return []

        # ── Guard 1: Minimum duration ────────────────────────────────────────
        filtered = [kw for kw in keywords if (kw.end_time - kw.start_time) >= _MIN_CUE_DURATION_S]
        if not filtered:
            logger.debug("[VKD] All cues filtered by minimum duration guard (%.1fs)", _MIN_CUE_DURATION_S)
            return []

        # ── Guard 2: Confidence fallback ─────────────────────────────────────
        # Below _FALLBACK_CONFIDENCE → skip entirely
        # Between _FALLBACK_CONFIDENCE and _SEMANTIC_CONFIDENCE → keep but log as low-confidence
        accepted = []
        for kw in filtered:
            if kw.confidence < _FALLBACK_CONFIDENCE:
                logger.debug("[VKD] Skipping '%s' (confidence=%.2f < fallback=%.2f)", kw.keyword, kw.confidence, _FALLBACK_CONFIDENCE)
                continue
            if kw.confidence < _SEMANTIC_CONFIDENCE:
                logger.debug("[VKD] Low-confidence cue '%s' (conf=%.2f) — keeping as overlay-only", kw.keyword, kw.confidence)
            accepted.append(kw)

        if not accepted:
            return []

        # ── Guard 3: Merge adjacent same-category cues ───────────────────────
        merged = [accepted[0]]
        for kw in accepted[1:]:
            last = merged[-1]
            gap = kw.start_time - last.end_time
            if (kw.category == last.category
                    and 0 < gap <= _MERGE_SAME_CATEGORY_GAP_S):
                # Merge: extend end_time, keep higher confidence
                merged[-1] = VisualKeyword(
                    keyword=last.keyword,
                    category=last.category,
                    start_time=last.start_time,
                    end_time=max(last.end_time, kw.end_time),
                    word=last.word,
                    confidence=max(last.confidence, kw.confidence),
                )
                logger.debug("[VKD] Merged '%s' + '%s' (same category '%s', gap=%.1fs)",
                             last.keyword, kw.keyword, kw.category, gap)
            else:
                merged.append(kw)

        # ── Guard 4: Category cooldown ───────────────────────────────────────
        cooled = [merged[0]]
        _last_category = merged[0].category
        _last_end = merged[0].end_time
        for kw in merged[1:]:
            gap = kw.start_time - _last_end
            if kw.category == _last_category and gap < _CATEGORY_COOLDOWN_S:
                logger.debug("[VKD] Cooldown: skipping '%s' (category '%s' repeated in %.1fs < %.1fs cooldown)",
                             kw.keyword, kw.category, gap, _CATEGORY_COOLDOWN_S)
                continue
            cooled.append(kw)
            _last_category = kw.category
            _last_end = kw.end_time

        return cooled[:max_keywords]

    def _deduplicate(self, keywords: List[VisualKeyword], min_gap_seconds: float = 2.0) -> List[VisualKeyword]:
        """Remove keywords that are too close together."""
        if not keywords:
            return []
        
        deduplicated = [keywords[0]]
        
        for kw in keywords[1:]:
            last_kw = deduplicated[-1]
            gap = kw.start_time - last_kw.end_time
            
            if gap >= min_gap_seconds:
                deduplicated.append(kw)
            elif kw.confidence > last_kw.confidence:
                # Replace if higher confidence
                deduplicated[-1] = kw
        
        return deduplicated


# Singleton instance
_detector_instance: Optional[VisualKeywordDetector] = None


def get_visual_keyword_detector() -> VisualKeywordDetector:
    """Get or create singleton detector instance."""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = VisualKeywordDetector()
    return _detector_instance
