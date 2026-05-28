"""Local heuristic planner for insurance-first editorial B-roll cues."""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .vpi_broll_intent import VisualIntent, detect_intent

logger = logging.getLogger(__name__)


@dataclass
class BrollCueDecision:
    decision: str
    cue_type: str
    trigger_text: str
    visual_query: Optional[str]
    start_s: Optional[float]
    duration_s: float
    transition: str
    motion: str
    opacity: float
    confidence: float
    reason: str
    intent_type: str = ""
    preferred_queries: Optional[List[str]] = None
    avoid_terms: Optional[List[str]] = None
    preferred_categories: Optional[List[str]] = None
    asset_style: str = "video"
    min_score: float = 55.0


class EditorialBrollPlanner:
    """Plan sober, local B-roll cues for Spanish insurance/finance clips."""

    # Map suggested_broll_cue_type from VPI scorer to local asset categories.
    _CUE_ALIASES: Dict[str, str] = {
        "documents_admin": "documents_admin",
        "emotional_reassurance": "emotional_reassurance",
        "family_protection": "family_protection",
        "financial_planning": "financial_planning",
        "risk_warning": "risk_warning",
        "explain_coverage": "documents_admin",
    }

    _PATTERNS: Dict[str, Tuple[str, ...]] = {
        "emotional_reassurance": (
            "calma",
            "tranquilidad",
            "tranquilo",
            "paz",
            "para ti y los tuyos",
            "los tuyos",
            "proteger",
            "proteccion",
            "miedo",
            "conviene proteger",
            "organizacion",
        ),
        "lifestyle_health": (
            "estilo de vida saludable",
            "vida saludable",
            "deporte",
            "actividad fisica",
            "caminar",
            "ejercicio",
            "salud preventiva",
        ),
        "risk_warning": (
            "si manana te pasa algo",
            "accidente",
            "imprevisto",
            "riesgo",
            "problema",
            "fallecimiento",
            "incapacidad",
            "enfermedad grave",
            "te pasa algo",
            "si faltas",
            "desprotegido",
            "desprotegida",
        ),
        "explain_coverage": (
            "cobertura",
            "cubre",
            "no cubre",
            "poliza",
            "capital",
            "prima",
            "indemnizacion",
            "carencia",
            "exclusion",
            "seguro de vida",
            "seguros de vida",
        ),
        "documents_admin": (
            "documentos",
            "contrato",
            "firma",
            "formulario",
            "recibo",
            "condiciones",
            "letra pequena",
            "poliza",
            "documentacion",
            "contratar",
            "personas mayores",
            "mas adelante",
            "por la edad",
            "no es solo para",
            "la realidad es que",
            "no suele tener sentido",
        ),
        "family_protection": (
            "familia",
            "hijos",
            "pareja",
            "hogar",
            "proteccion familiar",
            "proteger a tu familia",
            "dependen de ti",
            "personas que dependen",
            "sosteniendo",
            "estructura",
        ),
        "financial_planning": (
            "ahorro",
            "planificacion",
            "hipoteca",
            "prestamo",
            "pagos",
            "economia",
            "presupuesto",
            "responsabilidad",
            "capital",
            "prima",
            "proyecto",
        ),
        "revelation_hook": (
            "esto mucha gente no lo sabe",
            "poca gente sabe",
            "ojo con esto",
            "atencion a esto",
            "importante",
        ),
        "direct_cta": (
            "llamanos",
            "escribenos",
            "consulta",
            "pide cita",
            "contacta",
            "te esperamos",
        ),
    }

    _VISUAL_QUERIES: Dict[str, str] = {
        "emotional_reassurance": "serene family at home, calm protection, warm light",
        "lifestyle_health": "healthy lifestyle outdoor activity, walking, wellbeing",
        "risk_warning": "insurance documents, serious phone call, family planning",
        "explain_coverage": "insurance policy documents, advisor explaining coverage",
        "documents_admin": "contract documents, insurance forms, signing paperwork",
        "family_protection": "family protection at home, parents and children calm",
        "financial_planning": "financial planning documents, calculator, advisor meeting",
    }

    _STYLE: Dict[str, Tuple[str, str, float]] = {
        "emotional_reassurance": ("soft_crossfade", "slow_push", 0.85),
        "lifestyle_health": ("clean_cut", "gentle_push", 0.85),
        "risk_warning": ("soft_crossfade", "static", 0.80),
        "explain_coverage": ("soft_crossfade", "static", 0.85),
        "documents_admin": ("clean_cut", "static", 0.85),
        "family_protection": ("soft_crossfade", "slow_push", 0.85),
        "financial_planning": ("clean_cut", "static", 0.85),
        "revelation_hook": ("clean_cut", "static", 1.0),
        "direct_cta": ("clean_cut", "static", 1.0),
        "no_broll": ("clean_cut", "static", 1.0),
    }

    _DURATIONS: Dict[str, float] = {
        "emotional_reassurance": 2.2,
        "risk_warning": 1.7,
        "explain_coverage": 1.8,
        "lifestyle_health": 2.2,
        "documents_admin": 1.8,
        "family_protection": 2.2,
        "financial_planning": 2.0,
    }

    def plan(
        self,
        transcript_segments: Any,
        clip_duration: float,
        word_timestamps: Optional[Sequence[Dict[str, Any]]] = None,
        max_cues: Optional[int] = None,
        suggested_broll_cue_type: Optional[str] = None,
    ) -> List[BrollCueDecision]:
        text = self._segments_to_text(transcript_segments)
        normalized = self._normalize(text)
        if not normalized or clip_duration <= 0:
            return [
                self._decision(
                    "reject",
                    "no_broll",
                    "",
                    None,
                    None,
                    2.8,
                    0.0,
                    "No transcript or invalid clip duration",
                )
            ]

        matches = self._find_matches(normalized)
        segment_intent = detect_intent(
            text,
            editorial_type=None,
            suggested_broll_cue_type=suggested_broll_cue_type,
            matched_patterns=[trigger for _, trigger, _ in matches],
            segment_duration=clip_duration,
        )
        cue_limit = max_cues if max_cues is not None else segment_intent.max_overlays
        cue_limit = max(0, min(cue_limit, segment_intent.max_overlays, self._default_max_cues(clip_duration)))

        # ── Use suggested_broll_cue_type from VPI scorer as strong signal ──
        if suggested_broll_cue_type:
            _mapped = self._CUE_ALIASES.get(suggested_broll_cue_type, suggested_broll_cue_type)
            if _mapped in self._PATTERNS and not any(m[0] == _mapped for m in matches):
                # Use a negative char_start to mark this as a suggested cue
                # (no real text position). _estimate_start_s will detect this
                # and assign a safe start time.
                matches.insert(0, (_mapped, f"suggested:{suggested_broll_cue_type}", -1))
                logger.info(
                    "[editorial-broll] added suggested cue type=%s (mapped from %s) priority=first",
                    _mapped, suggested_broll_cue_type,
                )

        if not matches:
            return [
                self._decision(
                    "reject",
                    "no_broll",
                    "",
                    None,
                    None,
                    2.8,
                    0.0,
                    "No editorial insurance B-roll intent detected",
                )
            ]

        decisions: List[BrollCueDecision] = []
        approved_starts: List[float] = []
        approved_duration = 0.0
        max_coverage = clip_duration * 0.25

        for cue_type, trigger, char_start in matches:
            visual_intent = self._build_visual_intent(cue_type, normalized, trigger)
            duration = min(self._duration_for(cue_type), visual_intent.max_duration)
            start_s = self._estimate_start_s(
                normalized=normalized,
                trigger=trigger,
                char_start=char_start,
                clip_duration=clip_duration,
                word_timestamps=word_timestamps,
            )
            start_s, duration = self._polish_timing(
                start_s=start_s,
                duration_s=duration,
                cue_type=cue_type,
                intent_type=visual_intent.intent_type,
                clip_duration=clip_duration,
            )
            confidence = self._confidence_for(trigger)
            reason = "Editorial intent matched"
            decision = "approve"
            min_start_s = 3.2 if visual_intent.intent_type in {"myth_debunk_age", "client_objection"} else 4.5

            if cue_type == "revelation_hook":
                decision = "reject"
                reason = "Hook/revelation moment: keep talking head"
            elif cue_type == "direct_cta":
                decision = "reject"
                reason = "CTA moment: keep speaker visible"
            elif visual_intent.intent_type == "weak_intro":
                decision = "reject"
                reason = "Weak intro: keep speaker on screen"
            elif start_s is None:
                decision = "reject"
                reason = "No reliable timestamp"
            elif start_s < min_start_s:
                decision = "reject"
                reason = "Hook protected"
            elif start_s > clip_duration - 2.0:
                decision = "reject"
                reason = "CTA/end protected"
            elif confidence < 0.55:
                decision = "reject"
                reason = "Confidence below threshold"
            elif any(abs(start_s - previous) < 5.5 for previous in approved_starts):
                decision = "reject"
                reason = "Too close to previous approved B-roll"
            elif len(approved_starts) >= cue_limit:
                decision = "reject"
                reason = "Max editorial B-roll cues reached"
            elif approved_duration + duration > max_coverage:
                decision = "reject"
                reason = "B-roll coverage limit exceeded"

            if decision == "approve" and start_s is not None:
                approved_starts.append(start_s)
                approved_duration += duration

            decisions.append(
                self._decision(
                    decision,
                cue_type,
                trigger,
                (visual_intent.preferred_queries[0] if visual_intent.preferred_queries else self._VISUAL_QUERIES.get(cue_type)),
                start_s,
                duration,
                confidence,
                reason,
                visual_intent,
            )
            )

        return decisions

    @classmethod
    def _decision(
        cls,
        decision: str,
        cue_type: str,
        trigger_text: str,
        visual_query: Optional[str],
        start_s: Optional[float],
        duration_s: float,
        confidence: float,
        reason: str,
        visual_intent: Optional[VisualIntent] = None,
    ) -> BrollCueDecision:
        transition, motion, opacity = cls._STYLE.get(cue_type, cls._STYLE["no_broll"])
        intent_type = visual_intent.intent_type if visual_intent else ""
        preferred_queries = visual_intent.preferred_queries if visual_intent else None
        avoid_terms = visual_intent.avoid_terms if visual_intent else None
        preferred_categories = visual_intent.preferred_categories if visual_intent else None
        asset_style = visual_intent.asset_style if visual_intent else "video"
        min_score = visual_intent.min_score if visual_intent else 55.0
        if visual_intent:
            logger.info(
                "[visual-intent] type=%s queries=%s avoid=%s categories=%s",
                visual_intent.intent_type,
                "|".join(visual_intent.preferred_queries[:5]),
                "|".join(visual_intent.avoid_terms[:6]),
                "|".join(visual_intent.preferred_categories),
            )
        return BrollCueDecision(
            decision=decision,
            cue_type=cue_type,
            trigger_text=trigger_text,
            visual_query=visual_query,
            start_s=start_s,
            duration_s=duration_s,
            transition=transition,
            motion=motion,
            opacity=opacity,
            confidence=confidence,
            reason=reason,
            intent_type=intent_type,
            preferred_queries=preferred_queries,
            avoid_terms=avoid_terms,
            preferred_categories=preferred_categories,
            asset_style=asset_style,
            min_score=min_score,
        )

    @staticmethod
    def _segments_to_text(transcript_segments: Any) -> str:
        if isinstance(transcript_segments, str):
            return transcript_segments
        if isinstance(transcript_segments, dict):
            return str(transcript_segments.get("text") or "")
        if isinstance(transcript_segments, Iterable):
            parts: List[str] = []
            for segment in transcript_segments:
                if isinstance(segment, str):
                    parts.append(segment)
                elif isinstance(segment, dict):
                    parts.append(str(segment.get("text") or ""))
                else:
                    parts.append(str(getattr(segment, "text", "") or ""))
            return " ".join(part for part in parts if part)
        return str(transcript_segments or "")

    @staticmethod
    def _normalize(text: str) -> str:
        decomposed = unicodedata.normalize("NFKD", text.lower())
        ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
        ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
        return re.sub(r"\s+", " ", ascii_text).strip()

    @classmethod
    def _find_matches(cls, normalized_text: str) -> List[Tuple[str, str, int]]:
        matches: List[Tuple[str, str, int, int]] = []
        for cue_type, patterns in cls._PATTERNS.items():
            for pattern in patterns:
                normalized_pattern = cls._normalize(pattern)
                regex = r"(?<!\w)" + re.escape(normalized_pattern) + r"(?!\w)"
                for match in re.finditer(regex, normalized_text):
                    matches.append((cue_type, normalized_pattern, match.start(), len(normalized_pattern)))
        matches.sort(key=lambda item: (item[2], -item[3]))

        deduped: List[Tuple[str, str, int]] = []
        occupied: List[Tuple[int, int]] = []
        for cue_type, trigger, start, length in matches:
            end = start + length
            if any(start < used_end and end > used_start for used_start, used_end in occupied):
                continue
            occupied.append((start, end))
            deduped.append((cue_type, trigger, start))
        return deduped

    @classmethod
    def _safe_suggested_start_s(cls, clip_duration: float) -> float:
        """Return a safe start time for suggested cues (no real text position)."""
        if clip_duration >= 25.0:
            return 6.0
        if clip_duration >= 16.0:
            return 6.0
        return max(4.5, clip_duration * 0.35)

    @classmethod
    def _estimate_start_s(
        cls,
        normalized: str,
        trigger: str,
        char_start: int,
        clip_duration: float,
        word_timestamps: Optional[Sequence[Dict[str, Any]]],
    ) -> Optional[float]:
        # Suggested cues (char_start == -1) have no real text position.
        # Assign a safe start time that avoids hook protection.
        if char_start == -1:
            safe_start = cls._safe_suggested_start_s(clip_duration)
            logger.info(
                "[editorial-broll] suggested cue safe_start=%.1fs clip_duration=%.1fs",
                safe_start, clip_duration,
            )
            return safe_start

        timestamp = cls._timestamp_from_words(trigger, word_timestamps)
        if timestamp is not None:
            return round(max(0.0, timestamp), 2)
        if not normalized:
            return None
        ratio = char_start / max(1, len(normalized))
        return round(max(0.0, min(clip_duration, ratio * clip_duration)), 2)

    @classmethod
    def _timestamp_from_words(
        cls,
        trigger: str,
        word_timestamps: Optional[Sequence[Dict[str, Any]]],
    ) -> Optional[float]:
        if not word_timestamps:
            return None

        words: List[Tuple[str, float, Optional[float]]] = []
        for item in word_timestamps:
            raw_word = str(item.get("word") or item.get("text") or "")
            normalized_word = cls._normalize(raw_word)
            if not normalized_word:
                continue
            try:
                start = float(item.get("start", item.get("start_s", 0.0)) or 0.0)
            except (TypeError, ValueError):
                continue
            end_value = item.get("end", item.get("end_s"))
            try:
                end = float(end_value) if end_value is not None else None
            except (TypeError, ValueError):
                end = None
            words.append((normalized_word, start, end))

        trigger_words = trigger.split()
        if not trigger_words:
            return None

        for idx in range(0, len(words) - len(trigger_words) + 1):
            candidate = [word for word, _, _ in words[idx : idx + len(trigger_words)]]
            if candidate == trigger_words:
                first_start = words[idx][1]
                first_end = words[idx][2]
                return first_end if first_end is not None else first_start

        first = trigger_words[0]
        for word, start, end in words:
            if word == first:
                return end if end is not None else start
        return None

    @staticmethod
    def _default_max_cues(clip_duration: float) -> int:
        if clip_duration <= 30:
            return 3
        if clip_duration <= 60:
            return 3
        return 3

    @classmethod
    def _duration_for(cls, cue_type: str) -> float:
        return cls._DURATIONS.get(cue_type, 2.0)

    @classmethod
    def _polish_timing(
        cls,
        *,
        start_s: Optional[float],
        duration_s: float,
        cue_type: str,
        intent_type: str,
        clip_duration: float,
    ) -> Tuple[Optional[float], float]:
        original_start = start_s
        original_duration = duration_s
        if cue_type in {"documents_admin", "explain_coverage"}:
            duration_s = min(1.8, max(1.4, duration_s))
        elif cue_type in {"family_protection", "emotional_reassurance", "financial_planning"}:
            duration_s = min(2.2, max(1.8, duration_s))
        elif cue_type == "risk_warning":
            duration_s = min(1.8, max(1.4, duration_s))
        else:
            duration_s = min(2.3, max(1.4, duration_s))

        if start_s is not None:
            if intent_type in {"family_responsibility", "emotional_protection"} or cue_type in {"family_protection", "emotional_reassurance"}:
                start_s = max(4.5, start_s)
            elif intent_type in {"myth_debunk_age", "client_objection"}:
                start_s = max(3.2, start_s)
            else:
                start_s = max(4.0, start_s)
            start_s = min(start_s, max(0.0, clip_duration - duration_s - 2.0))

        if original_start is not None and start_s is not None and abs(original_start - start_s) > 0.01:
            logger.info("[broll-timing-polish] adjusted start=%.2f reason=%s", start_s, intent_type or cue_type)
        if abs(original_duration - duration_s) > 0.01:
            logger.info("[broll-timing-polish] adjusted duration=%.2f reason=%s", duration_s, cue_type)
        return start_s, duration_s

    @classmethod
    def _build_visual_intent(cls, cue_type: str, normalized_text: str, trigger: str) -> VisualIntent:
        return detect_intent(
            normalized_text,
            suggested_broll_cue_type=cue_type,
            matched_patterns=[trigger] if trigger else [],
        )

    @staticmethod
    def _confidence_for(trigger: str) -> float:
        # Suggested cues from VPI scorer get maximum confidence
        if trigger.startswith("suggested:"):
            return 0.95
        word_count = len(trigger.split())
        if word_count >= 4:
            return 0.9
        if word_count >= 2:
            return 0.75
        return 0.62
