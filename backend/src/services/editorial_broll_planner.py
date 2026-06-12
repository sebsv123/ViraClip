"""Local heuristic planner for insurance-first editorial B-roll cues.

VPI Editorial B-roll Category Mapper
Centralised local mapper that maps Spanish trigger text to allowed VPI B-roll
categories BEFORE any LLM call.  This ensures stopwords/fillers produce NO
B-roll slot and that only editorial-relevant categories are selected.

Allowed VPI B-roll categories:
    family_relief, family_protection, health_access, risk_warning_context,
    paperwork_support, documents_admin, financial_planning,
    practical_explanation, autonomous_work_stability, emotional_reassurance

Confidence threshold: 0.65
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .vpi_broll_intent import VisualIntent, detect_intent

logger = logging.getLogger(__name__)

# ── Allowed VPI B-roll categories ────────────────────────────────────────────
ALLOWED_VPI_BROLL_CATEGORIES: set[str] = {
    "family_relief",
    "family_protection",
    "health_access",
    "risk_warning_context",
    "paperwork_support",
    "documents_admin",
    "financial_planning",
    "practical_explanation",
    "autonomous_work_stability",
    "emotional_reassurance",
}

_APPROVED_CATEGORY_ALIASES: Dict[str, Tuple[str, ...]] = {
    "documents_admin": ("paperwork_support",),
    "emotional_reassurance": ("family_relief",),
    "family_protection": ("family_relief",),
    "financial_planning": ("practical_explanation", "paperwork_support"),
}

# ── Confidence thresholds ────────────────────────────────────────────────────
# Primary editorial category match (direct VPI category from mapper)
_PRIMARY_CONFIDENCE_THRESHOLD = 0.65
# Fallback/generic/alias category match (resolved via alias or generic cue)
_FALLBACK_CONFIDENCE_THRESHOLD = 0.75
# Generic/cinematic abstract is never allowed for VPI insurance unless explicitly
# approved with high confidence from a strong editorial cue
_GENERIC_BROLL_NOT_ALLOWED = True

# ── Skip reasons ─────────────────────────────────────────────────────────────
_SKIP_REASON_LOW_EDITORIAL_CONFIDENCE = "low_editorial_confidence"
_SKIP_REASON_GENERIC_BROLL_NOT_ALLOWED = "generic_broll_not_allowed"
_SKIP_REASON_WEAK_ASSET_BRAND_FIT = "weak_asset_brand_fit"
_SKIP_REASON_NO_TIMING_ANCHOR = "no_timing_anchor"


# ── Spanish-to-VPI-category local mapper ─────────────────────────────────────
# Maps Spanish trigger words/phrases directly to allowed VPI categories.
# This is used BEFORE any LLM call to avoid unnecessary API usage.
_VPI_CATEGORY_MAPPER: dict[str, str] = {
    # miedo → risk_warning_context
    "miedo": "risk_warning_context",
    "temor": "risk_warning_context",
    "peligro": "risk_warning_context",
    "riesgo": "risk_warning_context",
    "accidente": "risk_warning_context",
    "imprevisto": "risk_warning_context",
    "fallecimiento": "risk_warning_context",
    "incapacidad": "risk_warning_context",
    "enfermedad grave": "risk_warning_context",
    "te pasa algo": "risk_warning_context",
    "si faltas": "risk_warning_context",
    "desprotegido": "risk_warning_context",
    "desprotegida": "risk_warning_context",
    "si manana te pasa algo": "risk_warning_context",
    "vender miedo": "risk_warning_context",
    # proteger → family_relief / family_protection
    "proteger": "family_protection",
    "proteccion": "family_protection",
    "proteger a tu familia": "family_protection",
    "proteger a los tuyos": "family_protection",
    "seguro de vida": "family_protection",
    "seguros de vida": "family_protection",
    "proteccion familiar": "family_protection",
    "dependen de ti": "family_protection",
    "personas que dependen": "family_protection",
    "familia": "family_relief",
    "hijos": "family_relief",
    "pareja": "family_relief",
    "hogar": "family_relief",
    "tranquilidad": "emotional_reassurance",
    "tranquilo": "emotional_reassurance",
    "calma": "emotional_reassurance",
    "paz": "emotional_reassurance",
    "para ti y los tuyos": "emotional_reassurance",
    "los tuyos": "emotional_reassurance",
    # salud → health_access
    "salud": "health_access",
    "salud preventiva": "health_access",
    "estilo de vida saludable": "health_access",
    "vida saludable": "health_access",
    "deporte": "health_access",
    "actividad fisica": "health_access",
    "caminar": "health_access",
    "ejercicio": "health_access",
    # documentos → paperwork_support / documents_admin
    "papeleo": "paperwork_support",
    "papeles": "documents_admin",
    "documentos": "documents_admin",
    "documentacion": "documents_admin",
    "tramite": "paperwork_support",
    "tramites": "paperwork_support",
    "solicitud": "documents_admin",
    "gestion administrativa": "paperwork_support",
    "extranjeria": "paperwork_support",
    "residencia": "paperwork_support",
    "nie": "documents_admin",
    "permiso de residencia": "documents_admin",
    "contrato": "documents_admin",
    "contratos": "documents_admin",
    "firma": "documents_admin",
    "formulario": "documents_admin",
    "formularios": "documents_admin",
    "recibo": "documents_admin",
    "condiciones": "documents_admin",
    "letra pequena": "documents_admin",
    "contratar": "documents_admin",
    "poliza": "documents_admin",
    "cobertura": "paperwork_support",
    "cubre": "paperwork_support",
    "no cubre": "paperwork_support",
    "capital": "paperwork_support",
    "prima": "paperwork_support",
    "indemnizacion": "paperwork_support",
    "carencia": "paperwork_support",
    "exclusion": "paperwork_support",
    # finanzas → financial_planning
    "ahorro": "financial_planning",
    "planificacion": "financial_planning",
    "hipoteca": "financial_planning",
    "prestamo": "financial_planning",
    "pagos": "financial_planning",
    "economia": "financial_planning",
    "presupuesto": "financial_planning",
    "responsabilidad": "financial_planning",
    "proyecto": "financial_planning",
    # explicacion → practical_explanation
    "dar claridad": "practical_explanation",
    "explicar claro": "practical_explanation",
    "de forma clara": "practical_explanation",
    "paso a paso": "practical_explanation",
    "te explico": "practical_explanation",
    # autonomo → autonomous_work_stability
    "autonomo": "autonomous_work_stability",
    "autonoma": "autonomous_work_stability",
    "trabajo autonomo": "autonomous_work_stability",
    "sosteniendo": "autonomous_work_stability",
    "estructura": "autonomous_work_stability",
}

# ── Stopwords that must produce NO B-roll slot ───────────────────────────────
_VPI_STOPWORDS: set[str] = {
    "de", "la", "el", "los", "las", "que", "sea", "o", "y", "les", "me", "te",
    "un", "una", "es", "en", "por", "para", "con", "como", "esto", "este",
    "esta", "momento", "pues", "hola", "si", "no", "lo", "su", "se", "del",
    "al", "ha", "he", "has", "han", "habia", "haber", "ser", "era", "fue",
    "sido", "siendo", "estoy", "estas", "esta", "estamos", "estais", "estan",
    "estaba", "estado", "tengo", "tiene", "tenemos", "tienen", "tenia",
    "tuve", "tener", "teniendo", "hacer", "hago", "hace", "hacemos", "hacen",
    "hacia", "hizo", "haciendo", "puedo", "puede", "podemos", "pueden",
    "podia", "pudo", "poder", "pudiendo", "voy", "vas", "va", "vamos", "van",
    "iba", "fui", "ir", "yendo", "doy", "das", "da", "damos", "dan", "daba",
    "dio", "dar", "dando", "mi", "mis", "tu", "tus", "su", "sus", "nuestro",
    "nuestra", "vuestro", "vuestra", "mas", "menos", "muy", "mucho", "poco",
    "bastante", "demasiado", "tan", "tanto", "cada", "todo", "toda", "todos",
    "todas", "algun", "alguna", "algunos", "algunas", "ningun", "ninguna",
    "ningunos", "ningunas", "otro", "otra", "otros", "otras", "mismo",
    "misma", "mismos", "mismas", "tal", "tales", "aquel", "aquella",
    "aquellos", "aquellas", "alli", "aqui", "aca", "ahi", "donde", "cuando",
    "como", "que", "cual", "cuales", "quien", "quienes", "cuyo", "cuya",
    "cuyos", "cuyas", "cuanto", "cuanta", "cuantos", "cuantas",
}


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


def map_text_to_vpi_category(text: str) -> Optional[str]:
    """Local editorial VPI category mapper.

    Maps Spanish trigger text to an allowed VPI B-roll category using
    the local _VPI_CATEGORY_MAPPER.  Returns None if no match is found
    (caller should then decide whether to use LLM or skip).

    This is a local-only operation — no API calls.
    """
    normalized = _normalize_text(text)
    if not normalized:
        return None

    # Check for stopwords first — these produce NO category
    words = normalized.split()
    if len(words) <= 2 and all(w in _VPI_STOPWORDS for w in words):
        return None

    # Try multi-word patterns first (longest match wins)
    sorted_patterns = sorted(_VPI_CATEGORY_MAPPER.keys(), key=len, reverse=True)
    for pattern in sorted_patterns:
        norm_pattern = _normalize_text(pattern)
        if norm_pattern in normalized:
            category = _VPI_CATEGORY_MAPPER[pattern]
            if category in ALLOWED_VPI_BROLL_CATEGORIES:
                return category

    # Try single-word matches
    for word in words:
        if word in _VPI_STOPWORDS:
            continue
        if word in _VPI_CATEGORY_MAPPER:
            category = _VPI_CATEGORY_MAPPER[word]
            if category in ALLOWED_VPI_BROLL_CATEGORIES:
                return category

    return None


def _normalize_text(text: str) -> str:
    """Normalize text: lowercase, NFKD-decompose, remove diacritics."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


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
        "family_relief": "emotional_reassurance",
        "health_access": "lifestyle_health",
        "risk_warning_context": "risk_warning",
        "paperwork_support": "documents_admin",
        "practical_explanation": "practical_explanation",
        "autonomous_work_stability": "financial_planning",
    }

    _PATTERNS: Dict[str, Tuple[str, ...]] = {
        "emotional_reassurance": (
            "calma",
            "tranquilidad",
            "tranquilo",
            "desde la calma",
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
            "vender miedo",
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
            "seguro de vida",
            "seguros de vida",
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
        "practical_explanation": (
            "dar claridad",
            "explicar claro",
            "de forma clara",
            "paso a paso",
            "te explico",
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
        "practical_explanation": "advisor explaining paperwork clearly, practical explanation meeting",
    }

    _STYLE: Dict[str, Tuple[str, str, float]] = {
        "emotional_reassurance": ("soft_crossfade", "slow_push", 0.85),
        "lifestyle_health": ("clean_cut", "gentle_push", 0.85),
        "risk_warning": ("soft_crossfade", "static", 0.80),
        "explain_coverage": ("soft_crossfade", "static", 0.85),
        "documents_admin": ("clean_cut", "static", 0.85),
        "family_protection": ("soft_crossfade", "slow_push", 0.85),
        "financial_planning": ("clean_cut", "static", 0.85),
        "practical_explanation": ("clean_cut", "static", 0.85),
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
        "practical_explanation": 1.8,
    }

    @staticmethod
    def _resolve_local_asset_category(vpi_category: str) -> Tuple[str, List[Path]]:
        from .local_broll_asset_bank import list_assets as _list_local_assets

        primary_assets = _list_local_assets(vpi_category)
        if primary_assets:
            return vpi_category, primary_assets

        for alias in _APPROVED_CATEGORY_ALIASES.get(vpi_category, tuple()):
            alias_assets = _list_local_assets(alias)
            if not alias_assets:
                continue
            logger.info(
                "ASSET_CATEGORY_ALIAS_USED from=%s to=%s reason=no_primary_category_assets",
                vpi_category,
                alias,
            )
            return alias, alias_assets
        return vpi_category, []

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

        # ── VPI editorial B-roll category mapper + Groq budget ──────────────
        # Use local mapper first; only fall back to LLM when local fails.
        # Max 3 Groq calls per task for B-roll planning.
        llm_calls_used = 0
        LLM_CALL_BUDGET = 3

        for cue_type, trigger, char_start in matches:
            # ── Stopword guard: produce NO B-roll slot ──────────────────────
            trigger_normalized = _normalize_text(trigger)
            trigger_words = trigger_normalized.split()
            meaningful_words = [w for w in trigger_words if w not in _VPI_STOPWORDS]
            if not meaningful_words:
                logger.info(
                    "EDITORIAL_BROLL_SKIPPED reason=stopword_only cue_type=%s trigger=%r",
                    cue_type, trigger,
                )
                decisions.append(
                    self._decision(
                        "reject", "no_broll", trigger, None, None, 2.8, 0.0,
                        "Stopword-only cue: no B-roll slot",
                    )
                )
                continue

            # ── Local VPI category mapper (no API call) ─────────────────────
            vpi_category = map_text_to_vpi_category(trigger)
            if vpi_category is not None:
                # Local mapper found a category — use it directly
                logger.info(
                    "EDITORIAL_BROLL_SELECTED reason=local_vpi_mapper cue_type=%s trigger=%r vpi_category=%s",
                    cue_type, trigger, vpi_category,
                )
                resolved_category, local_assets = self._resolve_local_asset_category(vpi_category)
                # Map VPI category back to internal cue_type for asset lookup
                mapped_cue = self._CUE_ALIASES.get(resolved_category, resolved_category)
                if not local_assets:
                    logger.info(
                        "EDITORIAL_BROLL_SKIPPED reason=no_local_asset vpi_category=%s trigger=%r",
                        vpi_category, trigger,
                    )
                    decisions.append(
                        self._decision(
                            "reject", "no_broll", trigger, None, None, 2.8, 0.0,
                            f"No local asset for VPI category {vpi_category}",
                        )
                    )
                    continue

                # ── Manifest-based editorial asset validation ────────────────
                manifest_validation = self._validate_asset_against_manifest(
                    vpi_category=vpi_category,
                    resolved_category=resolved_category,
                    cue_type=cue_type,
                    trigger=trigger,
                )
                if manifest_validation.get("skip"):
                    logger.info(
                        "EDITORIAL_BROLL_SKIPPED reason=%s cue_type=%s trigger=%r vpi_category=%s",
                        manifest_validation["reason"],
                        cue_type, trigger, vpi_category,
                    )
                    decisions.append(
                        self._decision(
                            "reject", "no_broll", trigger, None, None, 2.8, 0.0,
                            manifest_validation["reason"],
                        )
                    )
                    continue

                # Use the mapped cue_type for the rest of the pipeline
                effective_cue_type = mapped_cue if mapped_cue in self._PATTERNS else cue_type
            else:
                # Local mapper found nothing — check if we should try LLM
                if len(meaningful_words) < 2:
                    logger.info(
                        "EDITORIAL_BROLL_SKIPPED reason=too_few_meaningful_words cue_type=%s trigger=%r words=%d",
                        cue_type, trigger, len(meaningful_words),
                    )
                    decisions.append(
                        self._decision(
                            "reject", "no_broll", trigger, None, None, 2.8, 0.0,
                            "Too few meaningful words for B-roll cue",
                        )
                    )
                    continue

                # Check Groq budget
                if llm_calls_used >= LLM_CALL_BUDGET:
                    logger.info(
                        "EDITORIAL_BROLL_SKIPPED reason=llm_budget_exhausted cue_type=%s trigger=%r",
                        cue_type, trigger,
                    )
                    decisions.append(
                        self._decision(
                            "reject", "no_broll", trigger, None, None, 2.8, 0.0,
                            "LLM budget exhausted for B-roll planning",
                        )
                    )
                    continue

                # Try LLM (Groq) for category detection
                llm_category = self._llm_detect_category(trigger, text)
                llm_calls_used += 1
                if llm_category is None:
                    logger.info(
                        "BROLL_LLM_FALLBACK reason=llm_no_match cue_type=%s trigger=%r",
                        cue_type, trigger,
                    )
                    decisions.append(
                        self._decision(
                            "reject", "no_broll", trigger, None, None, 2.8, 0.0,
                            "LLM could not determine B-roll category",
                        )
                    )
                    continue

                if llm_category not in ALLOWED_VPI_BROLL_CATEGORIES:
                    logger.info(
                        "EDITORIAL_BROLL_SKIPPED reason=category_not_allowed cue_type=%s trigger=%r llm_category=%s",
                        cue_type, trigger, llm_category,
                    )
                    decisions.append(
                        self._decision(
                            "reject", "no_broll", trigger, None, None, 2.8, 0.0,
                            f"LLM category {llm_category} not in allowed VPI categories",
                        )
                    )
                    continue

                logger.info(
                    "BROLL_LLM_FALLBACK reason=llm_match cue_type=%s trigger=%r llm_category=%s",
                    cue_type, trigger, llm_category,
                )
                vpi_category = llm_category
                effective_cue_type = self._CUE_ALIASES.get(vpi_category, cue_type)

            # ── Build visual intent and timing ──────────────────────────────
            visual_intent = self._build_visual_intent(effective_cue_type, normalized, trigger)
            duration = min(self._duration_for(effective_cue_type), visual_intent.max_duration)
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
                cue_type=effective_cue_type,
                intent_type=visual_intent.intent_type,
                clip_duration=clip_duration,
            )
            confidence = self._confidence_for(trigger)
            reason = "Editorial intent matched"
            decision = "approve"
            min_start_s = 3.2 if visual_intent.intent_type in {"myth_debunk_age", "client_objection"} else 4.5

            # ── Determine if this is a primary or fallback match ────────────
            # Primary = direct VPI category from local mapper
            # Fallback = resolved via alias, LLM fallback, or generic cue
            is_primary_match = vpi_category is not None and effective_cue_type in self._PATTERNS
            is_alias_match = (
                vpi_category is not None
                and effective_cue_type not in self._PATTERNS
                and any(
                    alias in self._PATTERNS
                    for alias in _APPROVED_CATEGORY_ALIASES.get(vpi_category, ())
                )
            )
            is_fallback = not is_primary_match

            # ── Apply editorial gates ───────────────────────────────────────
            if effective_cue_type == "revelation_hook":
                decision = "reject"
                reason = "Hook/revelation moment: keep talking head"
            elif effective_cue_type == "direct_cta":
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
            # ── Generic/cinematic abstract guard ────────────────────────────
            elif (
                _GENERIC_BROLL_NOT_ALLOWED
                and visual_intent.intent_type == "generic"
                and visual_intent.confidence < _FALLBACK_CONFIDENCE_THRESHOLD
            ):
                logger.info(
                    "EDITORIAL_BROLL_SKIPPED reason=%s cue_type=%s trigger=%r confidence=%.2f intent_type=%s",
                    _SKIP_REASON_GENERIC_BROLL_NOT_ALLOWED,
                    effective_cue_type, trigger, confidence, visual_intent.intent_type,
                )
                decision = "reject"
                reason = _SKIP_REASON_GENERIC_BROLL_NOT_ALLOWED
            # ── Dual-threshold confidence check ─────────────────────────────
            # Primary matches use _PRIMARY_CONFIDENCE_THRESHOLD (0.65)
            # Fallback/alias matches use _FALLBACK_CONFIDENCE_THRESHOLD (0.75)
            elif is_fallback and confidence < _FALLBACK_CONFIDENCE_THRESHOLD:
                logger.info(
                    "EDITORIAL_BROLL_SKIPPED reason=%s cue_type=%s trigger=%r confidence=%.2f threshold=%.2f is_fallback=true",
                    _SKIP_REASON_LOW_EDITORIAL_CONFIDENCE,
                    effective_cue_type, trigger, confidence, _FALLBACK_CONFIDENCE_THRESHOLD,
                )
                decision = "reject"
                reason = f"{_SKIP_REASON_LOW_EDITORIAL_CONFIDENCE} (fallback threshold={_FALLBACK_CONFIDENCE_THRESHOLD})"
            elif is_primary_match and confidence < _PRIMARY_CONFIDENCE_THRESHOLD:
                logger.info(
                    "EDITORIAL_BROLL_SKIPPED reason=%s cue_type=%s trigger=%r confidence=%.2f threshold=%.2f is_primary=true",
                    _SKIP_REASON_LOW_EDITORIAL_CONFIDENCE,
                    effective_cue_type, trigger, confidence, _PRIMARY_CONFIDENCE_THRESHOLD,
                )
                decision = "reject"
                reason = f"{_SKIP_REASON_LOW_EDITORIAL_CONFIDENCE} (primary threshold={_PRIMARY_CONFIDENCE_THRESHOLD})"
            # ── Timing anchor check ─────────────────────────────────────────
            # If the trigger text doesn't map to a clear editorial VPI category
            # and confidence is below fallback threshold, skip
            elif vpi_category is None and confidence < _FALLBACK_CONFIDENCE_THRESHOLD:
                logger.info(
                    "EDITORIAL_BROLL_SKIPPED reason=%s cue_type=%s trigger=%r confidence=%.2f vpi_category=None",
                    _SKIP_REASON_NO_TIMING_ANCHOR,
                    effective_cue_type, trigger, confidence,
                )
                decision = "reject"
                reason = _SKIP_REASON_NO_TIMING_ANCHOR
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
                logger.info(
                    "EDITORIAL_BROLL_SELECTED reason=approved cue_type=%s trigger=%r "
                    "confidence=%.2f start_s=%.1f timing_anchor=%s score=%.2f is_primary=%s",
                    effective_cue_type, trigger, confidence, start_s,
                    vpi_category or "none",
                    visual_intent.confidence,
                    is_primary_match,
                )

            decisions.append(
                self._decision(
                    decision,
                    effective_cue_type,
                    trigger,
                    (visual_intent.preferred_queries[0] if visual_intent.preferred_queries else self._VISUAL_QUERIES.get(effective_cue_type)),
                    start_s,
                    duration,
                    confidence,
                    reason,
                    visual_intent,
                )
            )

        # ── VPI Premium Productive Hardening: B-roll Budget Log ──────────────
        approved_count = len([d for d in decisions if d.decision == "approve"])
        total_requested = len(decisions)
        max_broll_slots = cue_limit
        logger.info(
            "BROLL_BUDGET_APPLIED requested=%d kept=%d max=%d",
            total_requested, approved_count, max_broll_slots,
        )

        return decisions

    @staticmethod
    def _validate_asset_against_manifest(
        *,
        vpi_category: str,
        resolved_category: Optional[str] = None,
        cue_type: str,
        trigger: str,
    ) -> Dict[str, Any]:
        """Validate a VPI category against the asset manifest.

        Checks:
        - Taxonomy matches the selected category
        - brand_fit is not false
        - avoid_contexts don't match current cue/context

        Returns dict with 'skip' (bool) and 'reason' (str).
        """
        result: Dict[str, Any] = {"skip": False, "reason": ""}

        try:
            from .vpi_asset_library_service import build_asset_index as _build_index
            index = _build_index()
            verified_broll = list((index.get("verified") or {}).get("broll") or [])
            if not verified_broll:
                # No manifest assets to validate against — allow through
                return result

            active_category = resolved_category or vpi_category
            accepted_categories = {vpi_category, active_category}
            accepted_categories.update(_APPROVED_CATEGORY_ALIASES.get(vpi_category, tuple()))

            # Check if any verified asset matches this category (or approved alias) with valid taxonomy
            compatible_assets = []
            for asset in verified_broll:
                asset_category = str(asset.get("category") or "").strip()
                asset_taxonomy = str(asset.get("taxonomy") or "").strip()
                asset_brand_fit = bool(asset.get("brand_fit", True))
                asset_avoid_contexts = list(asset.get("avoid_contexts") or [])

                # Taxonomy match: asset category/taxonomy must align with primary or approved alias categories
                taxonomy_match = (
                    asset_category in accepted_categories
                    or asset_taxonomy in accepted_categories
                    or any(c in asset_taxonomy for c in accepted_categories)
                    or any(c in asset_category for c in accepted_categories)
                )
                if not taxonomy_match:
                    continue

                # Brand fit check
                if not asset_brand_fit:
                    logger.info(
                        "EDITORIAL_BROLL_SKIPPED reason=asset_brand_fit_false "
                        "vpi_category=%s asset=%s",
                        vpi_category,
                        str(asset.get("path") or ""),
                    )
                    result["skip"] = True
                    result["reason"] = "asset_brand_fit_false"
                    return result

                # Avoid contexts check
                for avoid_ctx in asset_avoid_contexts:
                    if avoid_ctx and (
                        avoid_ctx in vpi_category
                        or avoid_ctx in cue_type
                        or avoid_ctx in trigger
                    ):
                        logger.info(
                            "EDITORIAL_BROLL_SKIPPED reason=avoid_context_match "
                            "vpi_category=%s avoid_context=%s asset=%s",
                            vpi_category,
                            avoid_ctx,
                            str(asset.get("path") or ""),
                        )
                        result["skip"] = True
                        result["reason"] = "avoid_context_match"
                        return result

                compatible_assets.append(asset)

            if not compatible_assets:
                # No manifest asset matched this category — taxonomy mismatch
                logger.info(
                    "EDITORIAL_BROLL_SKIPPED reason=asset_taxonomy_mismatch "
                    "vpi_category=%s cue_type=%s",
                    vpi_category,
                    cue_type,
                )
                result["skip"] = True
                result["reason"] = "asset_taxonomy_mismatch"
                return result

            # All checks passed — manifest validated
            logger.info(
                "EDITORIAL_BROLL_SELECTED reason=manifest_validated "
                "vpi_category=%s cue_type=%s manifest_validated=true "
                "compatible_assets=%d",
                vpi_category,
                cue_type,
                len(compatible_assets),
            )
            return result

        except Exception as exc:
            logger.debug(
                "[editorial-broll] manifest validation error for %s: %s",
                vpi_category, exc,
            )
            # On error, allow through (don't block B-roll)
            return result

    @staticmethod
    def _llm_detect_category(trigger: str, text: str) -> Optional[str]:
        """Use Groq LLM to detect VPI B-roll category for a trigger text.

        Returns an allowed VPI category string, or None if:
        - No Groq API key configured
        - 429 rate limit (fallback silently)
        - LLM response is unparseable
        - Category not in ALLOWED_VPI_BROLL_CATEGORIES
        """
        import httpx
        groq_key = os.getenv("GROQ_API_KEY", "")
        if not groq_key:
            logger.info("BROLL_LLM_FALLBACK reason=no_groq_key trigger=%r", trigger)
            return None

        prompt = (
            "You are a B-roll category classifier for Spanish insurance/finance videos. "
            "Given a trigger phrase and transcript context, classify the trigger into "
            "exactly one of these VPI B-roll categories:\n"
            + ", ".join(sorted(ALLOWED_VPI_BROLL_CATEGORIES)) + "\n\n"
            "Rules:\n"
            "- Return ONLY the category name, nothing else.\n"
            "- If none match, return 'none'.\n"
            "- Do NOT invent categories outside the list.\n\n"
            f"Transcript context: ...{text[-300:]}...\n"
            f"Trigger phrase: {trigger}\n"
            "Category:"
        )
        try:
            resp = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}"},
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 20,
                    "temperature": 0.1,
                },
                timeout=8,
            )
            if resp.status_code == 429:
                logger.info("BROLL_LLM_FALLBACK reason=429 trigger=%r", trigger)
                return None
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip().lower()
            # Clean up the response
            content = content.strip("'\"").strip()
            if content in ALLOWED_VPI_BROLL_CATEGORIES:
                logger.info(
                    "BROLL_LLM_FALLBACK reason=llm_match trigger=%r category=%s",
                    trigger, content,
                )
                return content
            logger.info(
                "BROLL_LLM_FALLBACK reason=llm_no_match trigger=%r llm_output=%r",
                trigger, content,
            )
            return None
        except Exception as exc:
            logger.debug(
                "[editorial-broll] LLM category detection failed for %r: %s",
                trigger, exc,
            )
            return None

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
