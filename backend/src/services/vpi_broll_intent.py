"""
VPI B-roll intent intelligence.

This module is the canonical local brain for Beta Clean editorial B-roll:
intent detection, stock-query building, asset penalties, candidate scoring,
and candidate selection. It intentionally uses deterministic heuristics only.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".avif"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v"}


VPI_ASSET_PENALTIES: Dict[str, int] = {
    ".jpg": -40,
    ".jpeg": -40,
    ".png": -40,
    "family_protection/03.jpg": -45,
    "emotional_reassurance/03.jpg": -50,
    "financial_planning/03.jpg": -40,
    "documents_admin/03.jpg": -40,
    "risk_warning/03.jpg": -45,
}

EDITORIAL_CUE_PRIORITY: Dict[str, List[str]] = {
    "emotional_protection": ["family_relief", "family_protection", "emotional_reassurance", "financial_planning"],
    "client_objection": ["documents_admin", "financial_planning", "practical_explanation", "advisor_consultation"],
    "myth_debunk": ["documents_admin", "financial_planning", "practical_explanation", "advisor_consultation"],
    "coverage_explanation": ["practical_explanation", "documents_admin", "financial_planning"],
    "advisor_explanation": ["practical_explanation", "documents_admin", "financial_planning"],
    "travel_assistance": ["travel_assistance", "documents_admin", "financial_planning"],
    "student_abroad": ["student_abroad", "documents_admin", "practical_explanation"],
    "risk_warning": ["risk_warning", "risk_warning_context", "health_access", "family_protection", "financial_planning"],
    "actionable_advice": ["documents_admin", "financial_planning"],
    "example_story": ["family_relief", "family_protection", "financial_planning", "location_context"],
}

CUE_ALIASES: Dict[str, str] = {
    "documents_admin": "documents_admin",
    "paperwork_support": "documents_admin",
    "emotional_reassurance": "emotional_reassurance",
    "emotional_support": "emotional_reassurance",
    "family_relief": "family_relief",
    "family_protection": "family_protection",
    "financial_planning": "financial_planning",
    "risk_warning": "risk_warning",
    "risk_warning_context": "risk_warning",
    "health_access": "health_access",
    "healthcare": "health_access",
    "practical_explanation": "practical_explanation",
    "advisor_explanation": "practical_explanation",
    "coverage_explanation": "practical_explanation",
    "travel_assistance": "travel_assistance",
    "student_abroad": "student_abroad",
    "explain_coverage": "documents_admin",
    "advisor_meeting": "advisor_consultation",
}

TAXONOMY_COMPATIBLE_FAMILIES: Dict[str, Tuple[str, ...]] = {
    "emotional_protection": ("family_relief", "family_protection", "emotional_reassurance", "financial_planning"),
    "family_responsibility": ("family_relief", "family_protection", "home_family", "emotional_reassurance", "financial_planning"),
    "family_relief": ("family_relief", "family_protection", "emotional_reassurance"),
    "risk_warning": ("risk_warning", "risk_warning_context", "health_access", "documents_admin", "financial_planning"),
    "risk_warning_family": ("risk_warning", "risk_warning_context", "family_protection", "financial_planning"),
    "travel_assistance": ("travel_assistance", "documents_admin", "financial_planning"),
    "student_abroad": ("student_abroad", "documents_admin", "practical_explanation"),
    "coverage_explanation": ("practical_explanation", "documents_admin", "financial_planning"),
    "advisor_explanation": ("practical_explanation", "documents_admin", "financial_planning"),
    "insurance_documents": ("documents_admin", "practical_explanation", "financial_planning"),
    "financial_planning": ("financial_planning", "documents_admin", "practical_explanation"),
    "client_objection": ("practical_explanation", "documents_admin", "financial_planning"),
    "myth_debunk": ("practical_explanation", "documents_admin", "financial_planning"),
    "myth_debunk_age": ("practical_explanation", "documents_admin", "financial_planning", "family_protection"),
}


def _canonical_broll_family(category: str) -> str:
    category = str(category or "").strip().lower()
    return CUE_ALIASES.get(category, category)


def _compatible_families_for_intent(intent: VisualIntent) -> Tuple[str, ...]:
    families: List[str] = []
    for key in (
        intent.intent_type,
        intent.narrative_function,
        intent.primary_cue or "",
        *(intent.preferred_categories or []),
    ):
        canonical = _canonical_broll_family(str(key or ""))
        if canonical:
            families.append(canonical)
        families.extend(TAXONOMY_COMPATIBLE_FAMILIES.get(str(key or ""), ()))
        families.extend(TAXONOMY_COMPATIBLE_FAMILIES.get(canonical, ()))
    out: List[str] = []
    for family in families:
        canonical = _canonical_broll_family(family)
        if canonical and canonical not in out:
            out.append(canonical)
    return tuple(out)


@dataclass
class VisualIntent:
    intent_type: str
    confidence: float
    primary_cue: Optional[str]
    preferred_categories: List[str]
    pexels_queries: List[str]
    avoid_terms: List[str] = field(default_factory=list)
    positive_terms: List[str] = field(default_factory=list)
    visual_style: str = "editorial_video"
    max_overlays: int = 2
    min_candidate_score: float = 60.0
    allow_stock: bool = True
    allow_static_images: bool = False
    reasoning: str = ""
    domain: str = "unknown"
    narrative_function: str = "generic_transition"

    @property
    def preferred_queries(self) -> List[str]:
        return self.pexels_queries

    @property
    def min_score(self) -> float:
        return self.min_candidate_score

    @property
    def asset_style(self) -> str:
        if not self.allow_stock and self.max_overlays <= 0:
            return "none"
        return self.visual_style

    @property
    def max_duration(self) -> float:
        if self.intent_type == "weak_intro":
            return 0.0
        if self.primary_cue == "documents_admin":
            return 1.8
        if self.primary_cue == "financial_planning":
            return 2.0
        if self.primary_cue == "risk_warning":
            return 1.8
        if self.primary_cue in {"family_protection", "emotional_reassurance"}:
            return 2.2
        return 1.8


@dataclass
class ClipTheme:
    domain: str
    central_topic: str
    emotional_frame: str
    commercial_goal: str
    preferred_visual_mix: List[str]
    avoid_visual_overuse: List[str]
    visual_story_arc: List[str]
    reasoning: str


def normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or "").lower())
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def _contains(text: str, terms: Sequence[str]) -> bool:
    return any(normalize_text(term) in text for term in terms)


def _domain_for(text: str) -> str:
    if _contains(text, ["seguro", "seguros", "poliza", "cobertura", "prima", "hipoteca", "capital"]):
        return "insurance_finance"
    if _contains(text, ["salud", "medico", "hospital", "paciente", "clinica"]):
        return "health"
    if _contains(text, ["viaje", "hotel", "vuelo", "destino", "turismo"]):
        return "travel"
    if _contains(text, ["legal", "contrato", "tramite", "administracion", "documentacion"]):
        return "legal_admin"
    if _contains(text, ["casa", "vivienda", "inmueble", "alquiler", "comprar piso"]):
        return "real_estate_housing"
    if _contains(text, ["hola soy", "hoy quiero hablar", "vengo a hablar"]):
        return "generic_talk"
    return "unknown"


def _high_density(text: str, matched_patterns: Sequence[str], vpi_score: Optional[float]) -> bool:
    if vpi_score is not None and vpi_score >= 75 and len(matched_patterns) >= 2:
        return True
    return sum(text.count(term) for term in ("familia", "hipoteca", "cobertura", "riesgo", "documentos")) >= 3


def detect_clip_theme(
    text: str,
    editorial_type: Optional[str] = None,
    matched_patterns: Optional[List[str]] = None,
    suggested_broll_cue_type: Optional[str] = None,
    vpi_score: Optional[float] = None,
) -> ClipTheme:
    normalized = normalize_text(" ".join([text or "", editorial_type or "", suggested_broll_cue_type or "", " ".join(matched_patterns or [])]))
    domain = _domain_for(normalized)
    life_insurance = domain == "insurance_finance" or _contains(
        normalized,
        ["seguro de vida", "seguros de vida", "proteccion", "familia", "dependen de ti", "personas mayores"],
    )
    if life_insurance:
        return ClipTheme(
            domain="insurance_finance",
            central_topic="life_insurance_family_protection",
            emotional_frame="responsibility, protection, future planning, calm confidence",
            commercial_goal="make life insurance feel relevant, human and responsible",
            preferred_visual_mix=[
                "family_protection",
                "advisor_consultation",
                "financial_planning",
                "home_responsibility",
                "documents_admin",
            ],
            avoid_visual_overuse=[
                "documents_admin",
                "paperwork_closeups",
                "generic_office",
                "wellness",
                "tea",
                "meditation",
            ],
            visual_story_arc=[
                "human/family context",
                "responsibility/planning",
                "documents/advisor only as support",
            ],
            reasoning="life insurance should feel human, responsible, and commercially reassuring; documents are support, not the whole story",
        )
    if domain == "health":
        return ClipTheme(
            domain=domain,
            central_topic="health_consultation",
            emotional_frame="trust, clarity, practical care",
            commercial_goal="make the advice feel credible and human",
            preferred_visual_mix=["doctor_patient", "consultation", "documents_admin"],
            avoid_visual_overuse=["hospital_bed", "generic_office", "paperwork_closeups"],
            visual_story_arc=["human consultation", "care context", "documents only as support"],
            reasoning="health content needs human consultation before paperwork",
        )
    if domain == "travel":
        return ClipTheme(
            domain=domain,
            central_topic="travel_planning",
            emotional_frame="anticipation, clarity, confidence",
            commercial_goal="make the recommendation feel useful and concrete",
            preferred_visual_mix=["location_context", "planning", "documents_admin"],
            avoid_visual_overuse=["generic_office", "paperwork_closeups"],
            visual_story_arc=["destination/context", "planning action", "documents support"],
            reasoning="travel content needs concrete location/planning visuals",
        )
    return ClipTheme(
        domain=domain,
        central_topic="generic_explanation",
        emotional_frame="clarity, relevance",
        commercial_goal="support the speaker only when visuals add concrete context",
        preferred_visual_mix=["human_context", "example_visual", "screen_or_document_support"],
        avoid_visual_overuse=["documents_admin", "generic_office", "paperwork_closeups"],
        visual_story_arc=["human/context", "example", "supporting detail"],
        reasoning="generic fallback favors speaker unless a concrete support visual exists",
    )


def detect_intent(
    text: str,
    editorial_type: Optional[str] = None,
    suggested_broll_cue_type: Optional[str] = None,
    matched_patterns: Optional[List[str]] = None,
    vpi_score: Optional[float] = None,
    segment_duration: Optional[float] = None,
    trigger_phrases: Optional[List[str]] = None,
    word_timestamps: Optional[Sequence[Dict[str, Any]]] = None,
    domain_hints: Optional[List[str]] = None,
) -> VisualIntent:
    del word_timestamps
    normalized = normalize_text(" ".join([text or "", " ".join(matched_patterns or []), " ".join(trigger_phrases or [])]))
    domain = (domain_hints or [None])[0] or _domain_for(normalized)
    cue = CUE_ALIASES.get(suggested_broll_cue_type or "", suggested_broll_cue_type or None)
    high_density = _high_density(normalized, matched_patterns or [], vpi_score)
    normal_max = 3 if high_density and (segment_duration or 30) >= 24 else 2
    if vpi_score is not None and vpi_score < 50:
        normal_max = min(normal_max, 1)

    if _contains(normalized, ["hola soy", "vengo a hablar", "en este momento", "hoy quiero hablar"]):
        return VisualIntent(
            intent_type="weak_intro",
            confidence=0.9,
            primary_cue=None,
            preferred_categories=[],
            pexels_queries=[],
            avoid_terms=["stock", "meditation", "tea", "coffee", "yoga", "wellness", "random office"],
            positive_terms=[],
            visual_style="speaker_focus",
            max_overlays=0,
            min_candidate_score=80.0,
            allow_stock=False,
            allow_static_images=False,
            reasoning="weak intro: keep speaker on screen unless an exceptional candidate appears",
            domain=domain,
            narrative_function="weak_intro",
        )

    if _contains(normalized, ["pareja", "hijos", "familia", "dependen de ti", "personas que dependen", "sostener", "sosteniendo", "estructura", "los tuyos"]):
        return VisualIntent(
            intent_type="family_responsibility",
            confidence=0.88,
            primary_cue="family_protection",
            preferred_categories=["family_protection", "emotional_reassurance", "financial_planning"],
            pexels_queries=[
                "family financial planning at home",
                "parents child home paperwork",
                "couple reviewing documents kitchen table",
                "family protection home",
                "parents planning future child",
                "family budget planning at home",
            ],
            avoid_terms=["meditation", "yoga", "tea", "coffee", "wellness", "funeral", "hospital", "sad alone", "luxury", "stock market"],
            positive_terms=["family", "parents", "child", "home", "planning", "future", "couple", "budget"],
            visual_style="warm_people_home_video",
            max_overlays=normal_max,
            min_candidate_score=60.0,
            allow_stock=True,
            allow_static_images=False,
            reasoning="family responsibility cue: prefer warm family/home planning scenes",
            domain=domain,
            narrative_function="emotional_protection",
        )

    if _contains(normalized, ["personas mayores", "por la edad", "no es solo para", "no suele tener sentido", "mas adelante", "ya lo mirare", "la realidad es que"]):
        return VisualIntent(
            intent_type="myth_debunk_age",
            confidence=0.86,
            primary_cue="advisor_consultation",
            preferred_categories=["advisor_consultation", "financial_planning", "documents_admin", "family_protection"],
            pexels_queries=[
                "financial advisor explaining contract to young couple",
                "young couple financial planning consultation",
                "insurance advisor consultation documents",
                "adult reviewing insurance policy with advisor",
                "couple meeting financial advisor paperwork",
            ],
            avoid_terms=["elderly only", "hospital bed", "funeral", "nursing home", "meditation", "tea", "wellness"],
            positive_terms=["young", "adult", "documents", "advisor", "contract", "signing", "policy"],
            visual_style="consultation_documents_video",
            max_overlays=normal_max,
            min_candidate_score=60.0,
            allow_stock=True,
            allow_static_images=False,
            reasoning="age myth/client objection: show documents/advisor, not elderly/fear imagery",
            domain=domain,
            narrative_function="client_objection",
        )

    if _contains(normalized, ["riesgo", "imprevisto", "si manana", "te pasa algo", "si faltas", "desprotegido", "desprotegida"]):
        return VisualIntent(
            intent_type="risk_warning_family",
            confidence=0.82,
            primary_cue="risk_warning",
            preferred_categories=["risk_warning", "family_protection", "financial_planning"],
            pexels_queries=[
                "worried family planning finances",
                "family protection serious conversation",
                "unexpected financial problem documents",
                "parents discussing finances at home",
            ],
            avoid_terms=["violence", "horror", "ambulance", "hospital bed", "funeral", "stock market"],
            positive_terms=["worried", "family", "parents", "finances", "serious", "documents", "home"],
            visual_style="sober_people_documents_video",
            max_overlays=normal_max,
            min_candidate_score=62.0,
            allow_stock=True,
            allow_static_images=False,
            reasoning="risk warning: sober family/finance concern without fear-mongering",
            domain=domain,
            narrative_function="risk_warning",
        )

    if _contains(normalized, ["la salud no siempre avisa", "salud no siempre avisa", "por si acaso", "cuando ya es tarde", "antes de que pase", "no siempre avisa"]) and not _contains(
        normalized,
        # OUTPUT-VISUALS-15B: an incidental "por si acaso" must not hijack the
        # visual intent of a text dominated by explicit travel/student subject
        # matter — the specific domain wins and falls through to those branches.
        ["viaje", "pasaje", "asistencia en viaje", "aeropuerto", "equipaje", "estudiante", "estudios", "visado", "campus"],
    ):
        return VisualIntent(
            intent_type="risk_warning",
            confidence=0.8,
            primary_cue="risk_warning",
            preferred_categories=["risk_warning", "risk_warning_context", "health_access", "documents_admin"],
            pexels_queries=[
                "doctor patient consultation serious",
                "health documents consultation",
                "person reviewing health paperwork",
                "sober planning documents",
            ],
            avoid_terms=["violence", "horror", "ambulance", "hospital bed", "funeral", "sad alone", "dramatic crying"],
            positive_terms=["health", "patient", "doctor", "documents", "planning", "risk", "warning"],
            visual_style="sober_health_warning_video",
            max_overlays=normal_max,
            min_candidate_score=64.0,
            allow_stock=True,
            allow_static_images=False,
            reasoning="health risk warning: use sober healthcare/planning context only",
            domain=domain,
            narrative_function="risk_warning",
        )

    if _contains(normalized, ["estudiante", "estudios", "study visa", "campus", "universidad", "visado", "estancia de estudios"]):
        # OUTPUT-BROLL-14: student-abroad family (folder may be empty until the
        # user drops local clips; the matcher then skips with a clear reason).
        return VisualIntent(
            intent_type="student_abroad",
            confidence=0.78,
            primary_cue="student_abroad",
            preferred_categories=["student_abroad", "documents_admin", "practical_explanation"],
            pexels_queries=[
                "student reviewing documents on campus",
                "student with backpack at university",
                "study visa paperwork",
            ],
            avoid_terms=["party", "dorm party", "dramatic exam stress"],
            positive_terms=["student", "campus", "university", "documents", "visa", "abroad"],
            visual_style="student_documents_campus_video",
            max_overlays=normal_max,
            min_candidate_score=66.0,
            allow_stock=True,
            allow_static_images=False,
            reasoning="student abroad: prefer local student_abroad family, documents as support",
            domain=domain,
            narrative_function="student_abroad",
        )

    if _contains(normalized, ["viaje", "pasaje", "asistencia en viaje", "extranjero", "fuera de casa", "aeropuerto"]):
        return VisualIntent(
            intent_type="travel_assistance",
            confidence=0.78,
            primary_cue="travel_assistance",
            preferred_categories=["travel_assistance", "documents_admin", "financial_planning"],
            pexels_queries=[
                "traveler reviewing travel documents",
                "person planning trip with documents",
                "travel insurance documents",
            ],
            avoid_terms=["luxury hotel", "party travel", "random beach", "dramatic airport delay"],
            positive_terms=["travel", "documents", "planning", "luggage", "airport", "passport"],
            visual_style="travel_documents_planning_video",
            max_overlays=normal_max,
            min_candidate_score=66.0,
            allow_stock=True,
            allow_static_images=False,
            reasoning="travel assistance: prefer local travel_assistance family, documents/planning as support",
            domain=domain,
            narrative_function="travel_assistance",
        )

    if _contains(normalized, ["hipoteca", "proyecto", "responsabilidad", "capital", "prima", "planificacion", "ahorro", "presupuesto"]):
        return VisualIntent(
            intent_type="financial_planning",
            confidence=0.8,
            primary_cue="financial_planning",
            preferred_categories=["financial_planning", "documents_admin", "family_protection"],
            pexels_queries=[
                "couple reviewing mortgage documents",
                "family home financial planning",
                "mortgage paperwork close up",
                "financial advisor family documents",
                "household budget paperwork",
            ],
            avoid_terms=["trading", "stock market", "luxury money", "skyscraper", "random office", "coffee"],
            positive_terms=["mortgage", "documents", "family", "home", "planning", "budget", "advisor"],
            visual_style="practical_documents_people_video",
            max_overlays=normal_max,
            min_candidate_score=60.0,
            allow_stock=True,
            allow_static_images=False,
            reasoning="financial planning cue: household/advisor/document action",
            domain=domain,
            narrative_function="coverage_explanation",
        )

    if _contains(normalized, ["seguro de vida", "seguros de vida", "poliza", "cobertura", "contratar", "documentos", "contrato", "documentacion"]):
        return VisualIntent(
            intent_type="insurance_documents",
            confidence=0.76,
            primary_cue="documents_admin",
            preferred_categories=["documents_admin", "practical_explanation", "financial_planning"],
            pexels_queries=[
                "insurance policy documents",
                "signing insurance paperwork",
                "financial advisor explaining contract",
                "close up contract signing",
                "person reviewing insurance documents",
            ],
            avoid_terms=["random office", "stock market", "business handshake cliche", "tea", "meditation", "wellness"],
            positive_terms=["insurance", "policy", "documents", "signing", "contract", "advisor"],
            visual_style="documents_closeup_video",
            max_overlays=normal_max,
            min_candidate_score=60.0,
            allow_stock=True,
            allow_static_images=False,
            reasoning="insurance/document explanation: use concrete paperwork support",
            domain=domain,
            narrative_function="coverage_explanation",
        )

    if editorial_type in EDITORIAL_CUE_PRIORITY:
        categories = EDITORIAL_CUE_PRIORITY[editorial_type or ""]
        primary = cue or (categories[0] if categories else None)
        _editorial_confidence = 0.62
        if any(
            term in normalized
            for term in (
                "seguro", "seguros", "poliza", "cobertura", "proteccion",
                "proteger", "calma", "tranquilidad", "salud", "decesos",
                "prima", "ahorro", "documentos", "contratar",
            )
        ):
            # Local B-roll still needs phrase timing + asset matching later; this
            # only prevents clear insurance clips from dying at the generic 0.62.
            _editorial_confidence = 0.76
        return VisualIntent(
            intent_type=str(editorial_type),
            confidence=_editorial_confidence,
            primary_cue=primary,
            preferred_categories=categories,
            pexels_queries=_generic_queries_for_domain(domain, primary),
            avoid_terms=["meditation", "tea", "coffee", "wellness", "luxury", "random office"],
            positive_terms=_positive_terms_for_domain(domain),
            visual_style="generic_editorial_video",
            max_overlays=1 if (vpi_score or 0) < 50 else 2,
            min_candidate_score=64.0,
            allow_stock=True,
            allow_static_images=False,
            reasoning=f"fallback from editorial_type={editorial_type}",
            domain=domain,
            narrative_function=str(editorial_type),
        )

    return VisualIntent(
        intent_type="speaker_focus" if domain == "unknown" else "generic_context",
        confidence=0.45,
        primary_cue=cue,
        preferred_categories=[cue] if cue else [],
        pexels_queries=_generic_queries_for_domain(domain, cue),
        avoid_terms=["meditation", "tea", "coffee", "wellness", "luxury", "stock market", "random office"],
        positive_terms=_positive_terms_for_domain(domain),
        visual_style="generic_editorial_video",
        max_overlays=0 if domain == "unknown" else 1,
        min_candidate_score=70.0,
        allow_stock=domain != "unknown",
        allow_static_images=False,
        reasoning="generic fallback: use B-roll only with strong concrete context",
        domain=domain,
        narrative_function="generic_transition",
    )


def _generic_queries_for_domain(domain: str, primary_cue: Optional[str]) -> List[str]:
    if primary_cue == "documents_admin" or domain == "legal_admin":
        return ["person reviewing documents at desk", "advisor explaining contract documents", "close up contract signing"]
    if domain == "health":
        return ["doctor explaining documents to patient", "patient consultation clinic office", "health paperwork consultation"]
    if domain == "travel":
        return ["traveler planning trip with laptop", "couple reviewing travel documents", "person packing suitcase at home"]
    if domain == "real_estate_housing":
        return ["couple reviewing mortgage documents", "real estate agent explaining contract", "family planning home budget"]
    if domain == "insurance_finance":
        return ["financial advisor explaining contract", "family financial planning at home", "couple reviewing documents kitchen table"]
    return []


def _positive_terms_for_domain(domain: str) -> List[str]:
    if domain in {"insurance_finance", "real_estate_housing"}:
        return ["family", "advisor", "documents", "contract", "planning", "home"]
    if domain == "health":
        return ["doctor", "patient", "consultation", "clinic", "documents"]
    if domain == "travel":
        return ["travel", "planning", "luggage", "documents", "airport"]
    if domain == "legal_admin":
        return ["documents", "contract", "signing", "advisor", "desk"]
    return []


def build_stock_queries(intent: VisualIntent, limit: int = 5) -> List[str]:
    queries: List[str] = []
    for query in intent.pexels_queries:
        clean = " ".join(str(query).lower().split())
        if len(clean.split()) < 3:
            continue
        if clean in {"fear", "calm", "protection", "money", "family"}:
            continue
        if clean not in queries:
            queries.append(clean)
    return queries[: max(0, limit)]


def build_pexels_queries(intent: VisualIntent) -> List[str]:
    return build_stock_queries(intent, limit=5)


# ── Known weak/generic cue patterns ──────────────────────────────────────────
_WEAK_CUE_FILENAMES: List[str] = [
    "abstract", "generic", "cinematic", "stock", "placeholder",
    "filler", "motion_background", "bokeh", "blur_background",
    "particles", "transition", "loop", "background_loop",
]
_KNOWN_BAD_GENERIC_CUES: List[str] = [
    "cinematic abstract", "generic abstract", "abstract background",
    "motion graphics", "animated background", "generic transition",
]


def _is_weak_cue_asset(candidate: Dict[str, Any]) -> bool:
    """Check if an asset filename or cue suggests it was generated from a weak cue."""
    path = str(candidate.get("path") or candidate.get("url") or "").lower()
    category = str(candidate.get("category") or candidate.get("cue") or "").lower()
    query = str(candidate.get("query") or "").lower()
    title = str(candidate.get("title") or "").lower()
    text = " ".join([path, category, query, title])
    for pattern in _WEAK_CUE_FILENAMES:
        if pattern in text:
            return True
    for pattern in _KNOWN_BAD_GENERIC_CUES:
        if pattern in text:
            return True
    return False


def _check_taxonomy_match(
    candidate: Dict[str, Any],
    intent: VisualIntent,
) -> Tuple[bool, str]:
    """Check if candidate's category matches the expected VPI taxonomy."""
    category = _canonical_broll_family(str(candidate.get("category") or candidate.get("cue") or "").lower())
    if not category:
        return False, "no_category"
    compatible = _compatible_families_for_intent(intent)
    # Must be in preferred categories or match primary cue
    if intent.primary_cue and category == _canonical_broll_family(intent.primary_cue):
        return True, "primary_cue_match"
    preferred = {_canonical_broll_family(item) for item in intent.preferred_categories}
    if category in preferred:
        return True, "preferred_category_match"
    if category in compatible:
        logger.info(
            "VPI_BROLL_TAXONOMY_MATCH intent=%s category=%s reason=compatible_family families=%s",
            intent.intent_type,
            category,
            ",".join(compatible),
        )
        return True, "compatible_family_match"
    logger.info(
        "VPI_BROLL_TAXONOMY_NO_MATCH intent=%s category=%s families=%s",
        intent.intent_type,
        category,
        ",".join(compatible),
    )
    return False, "taxonomy_mismatch"


def _check_brand_fit(
    candidate: Dict[str, Any],
    intent: VisualIntent,
) -> Tuple[bool, str]:
    """Check if asset has explicit brand_fit flag or matches brand context."""
    brand_fit = candidate.get("brand_fit")
    if brand_fit is False:
        return False, "brand_fit_false"
    if brand_fit is True:
        return True, "brand_fit_true"
    # No explicit flag: check domain alignment
    category = _canonical_broll_family(str(candidate.get("category") or candidate.get("cue") or "").lower())
    domain = intent.domain
    if domain == "insurance_finance" and category in {
        "family_protection", "financial_planning", "documents_admin",
        "advisor_consultation", "risk_warning", "risk_warning_context",
        "emotional_reassurance", "family_relief", "practical_explanation",
        "health_access",
    }:
        return True, "domain_aligned_category"
    if domain == "legal_admin" and category in {"documents_admin", "advisor_consultation"}:
        return True, "domain_aligned_category"
    return True, "no_brand_fit_flag"  # neutral — not a rejection


def _check_avoid_context(
    candidate: Dict[str, Any],
    intent: VisualIntent,
) -> Tuple[bool, str]:
    """Check if asset matches any avoid_context from intent."""
    category = _canonical_broll_family(str(candidate.get("category") or candidate.get("cue") or "").lower())
    path = str(candidate.get("path") or candidate.get("url") or "").lower()
    query = str(candidate.get("query") or "").lower()
    title = str(candidate.get("title") or "").lower()
    tags = " ".join(str(t) for t in (candidate.get("tags") or [])).lower()
    text = " ".join([path, category, query, title, tags])
    for avoid in intent.avoid_terms:
        avoid_norm = avoid.lower()
        if avoid_norm and avoid_norm in text:
            return True, f"avoid_context_match:{avoid_norm}"
    return False, ""


def _score_category_match(category: str, intent: VisualIntent) -> Tuple[float, List[str]]:
    """Score how well the category matches the intent's preferred categories."""
    reasons: List[str] = []
    score = 0.0
    category = _canonical_broll_family(category)
    preferred = [_canonical_broll_family(item) for item in intent.preferred_categories]
    compatible = _compatible_families_for_intent(intent)
    if preferred and category == preferred[0]:
        score += 35
        reasons.append("category_match_primary:+35")
    elif category in preferred:
        score += 25
        reasons.append("category_match_preferred:+25")
    elif category in compatible:
        score += 18
        reasons.append("category_match_compatible:+18")
    if intent.primary_cue and category == _canonical_broll_family(intent.primary_cue):
        score += 20
        reasons.append("category_match_primary_cue:+20")
    return score, reasons


def _score_allowed_context(candidate: Dict[str, Any], intent: VisualIntent) -> Tuple[float, List[str]]:
    """Score based on allowed_context metadata."""
    reasons: List[str] = []
    score = 0.0
    allowed = candidate.get("allowed_context") or []
    if isinstance(allowed, str):
        allowed = [allowed]
    if allowed:
        intent_narrative = intent.narrative_function
        if intent_narrative in allowed:
            score += 20
            reasons.append(f"allowed_context_match:{intent_narrative}:+20")
        else:
            score -= 10
            reasons.append("allowed_context_mismatch:-10")
    return score, reasons


def _score_intensity_match(candidate: Dict[str, Any], intent: VisualIntent) -> Tuple[float, List[str]]:
    """Score based on intensity metadata alignment with intent."""
    reasons: List[str] = []
    score = 0.0
    intensity = candidate.get("intensity") or ""
    if isinstance(intensity, str):
        intensity = intensity.lower()
    else:
        return score, reasons
    # Map intent types to expected intensity
    if intent.intent_type in {"risk_warning_family", "myth_debunk_age"}:
        if intensity in {"moderate", "serious"}:
            score += 15
            reasons.append(f"intensity_match:{intensity}:+15")
        elif intensity == "light":
            score -= 10
            reasons.append(f"intensity_too_light:{intensity}:-10")
    elif intent.intent_type in {"family_responsibility", "emotional_reassurance", "emotional_protection"}:
        if intensity in {"warm", "light", "moderate"}:
            score += 10
            reasons.append(f"intensity_match:{intensity}:+10")
        elif intensity == "serious":
            score -= 5
            reasons.append(f"intensity_too_serious:{intensity}:-5")
    return score, reasons


def _score_visual_relevance(candidate: Dict[str, Any], intent: VisualIntent) -> Tuple[float, List[str]]:
    """Score visual relevance based on concrete visual terms in candidate metadata."""
    reasons: List[str] = []
    score = 0.0
    path = str(candidate.get("path") or candidate.get("url") or "").lower()
    query = str(candidate.get("query") or "").lower()
    title = str(candidate.get("title") or "").lower()
    tags = " ".join(str(t) for t in (candidate.get("tags") or [])).lower()
    text = " ".join([path, query, title, tags])
    concrete_terms = {
        "family", "parents", "child", "home", "couple", "advisor",
        "documents", "planning", "consultation", "contract", "signing",
        "mortgage", "budget", "protection", "office", "desk",
        "discussing", "reviewing", "explaining", "meeting",
    }
    matched = [t for t in concrete_terms if t in text]
    if matched:
        bonus = min(len(matched) * 8, 25)
        score += bonus
        reasons.append(f"visual_relevance_terms:{','.join(matched)}:+{bonus}")
    # Penalty for abstract/no-visual-hook text
    if not matched and not any(
        term in text for term in ("people", "person", "man", "woman", "group", "office", "home", "table")
    ):
        score -= 15
        reasons.append("abstract_no_visual_hook:-15")
    return score, reasons


def score_broll_candidate(
    candidate: Dict[str, Any],
    intent: VisualIntent,
    theme: Optional[ClipTheme | Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Tuple[float, List[str]]:
    if context is None and isinstance(theme, dict) and "central_topic" not in theme:
        context = theme
        theme = None
    context = context or {}
    if theme is None:
        theme = detect_clip_theme("", editorial_type=intent.narrative_function, suggested_broll_cue_type=intent.primary_cue)
    reasons: List[str] = []
    score = 0.0

    category = _canonical_broll_family(str(candidate.get("category") or candidate.get("cue") or "").lower())
    source = str(candidate.get("source") or "").lower()
    path = candidate.get("path") or candidate.get("url") or ""
    path_text = str(path).lower()
    query = str(candidate.get("query") or "").lower()
    title = str(candidate.get("title") or "").lower()
    tags = " ".join(str(tag).lower() for tag in candidate.get("tags", []) or [])
    text = " ".join([path_text, category, query, title, tags, str(candidate.get("metadata") or "").lower()])

    suffix = Path(path_text).suffix.lower()
    is_image = bool(candidate.get("is_image")) or suffix in IMAGE_EXTS
    is_video = bool(candidate.get("is_video")) or suffix in VIDEO_EXTS or (not is_image and source in {"pexels", "stock", "local"})
    orientation = str(candidate.get("orientation") or "").lower()
    used_in_task = bool(candidate.get("used_in_task") or str(path) in set(context.get("task_seen_assets") or []))
    recent_use_count = int(candidate.get("recent_use_count") or 0)
    category_repeated = bool(candidate.get("category_repeated")) or int(context.get("category_seen", {}).get(category, 0)) > 0
    selected_categories = list(context.get("selected_categories") or context.get("category_seen", {}).keys())
    selected_visual_types = list(context.get("selected_visual_types") or [])
    visual_type = _visual_type_for_category(category, text)

    # ── Reject/skip checks ──────────────────────────────────────────────────
    # Taxonomy mismatch
    tax_match, tax_reason = _check_taxonomy_match(candidate, intent)
    if not tax_match:
        logger.info(
            "EDITORIAL_BROLL_SKIPPED reason=taxonomy_mismatch category=%s intent_primary=%s preferred=%s",
            category, intent.primary_cue, intent.preferred_categories,
        )
        return -999.0, [f"taxonomy_mismatch:{tax_reason}"]

    # Brand fit check
    brand_ok, brand_reason = _check_brand_fit(candidate, intent)
    if not brand_ok:
        logger.info(
            "EDITORIAL_BROLL_SKIPPED reason=brand_fit_false category=%s asset=%s",
            category, path_text,
        )
        return -999.0, [f"brand_fit_false:{brand_reason}"]

    # Avoid context match
    avoid_match, avoid_reason = _check_avoid_context(candidate, intent)
    if avoid_match:
        logger.info(
            "EDITORIAL_BROLL_SKIPPED reason=avoid_context_match category=%s asset=%s context=%s",
            category, path_text, avoid_reason,
        )
        return -999.0, [f"avoid_context_match:{avoid_reason}"]

    # Weak cue / generic asset check
    if _is_weak_cue_asset(candidate):
        logger.info(
            "EDITORIAL_BROLL_SKIPPED reason=weak_cue_asset category=%s asset=%s",
            category, path_text,
        )
        return -999.0, [f"weak_cue_asset:{path_text}"]

    # ── Scoring dimensions ──────────────────────────────────────────────────
    # 1. Category match
    cat_score, cat_reasons = _score_category_match(category, intent)
    score += cat_score
    reasons.extend(cat_reasons)

    # 2. Allowed context match
    ctx_score, ctx_reasons = _score_allowed_context(candidate, intent)
    score += ctx_score
    reasons.extend(ctx_reasons)

    # 3. Brand fit scoring (positive signal)
    if brand_reason == "brand_fit_true":
        score += 20
        reasons.append("brand_fit_explicit:+20")
    elif brand_reason == "domain_aligned_category":
        score += 10
        reasons.append("brand_fit_domain_aligned:+10")

    # 4. Intensity match
    int_score, int_reasons = _score_intensity_match(candidate, intent)
    score += int_score
    reasons.extend(int_reasons)

    # 5. Visual relevance
    vis_score, vis_reasons = _score_visual_relevance(candidate, intent)
    score += vis_score
    reasons.extend(vis_reasons)

    # 6. Recency / usage diversity
    if not used_in_task:
        score += 15
        reasons.append("fresh_task_asset:+15")
    else:
        score -= 45
        reasons.append("repeated_asset:-45")
    if recent_use_count <= 1:
        score += 10
        reasons.append("low_recent_use:+10")
    elif recent_use_count >= 3:
        score -= 10
        reasons.append("recent_overuse:-10")

    # ── Legacy scoring (preserved) ──────────────────────────────────────────
    preferred = intent.preferred_categories
    if preferred and category == preferred[0]:
        score += 35
        reasons.append("primary_category:+35")
    elif category in preferred:
        score += 25
        reasons.append("preferred_category:+25")

    suggested = CUE_ALIASES.get(str(context.get("suggested_broll_cue_type") or ""), str(context.get("suggested_broll_cue_type") or ""))
    if suggested and category == suggested:
        score += 25
        reasons.append("suggested_cue:+25")
    if intent.primary_cue and category == intent.primary_cue:
        score += 20
        reasons.append("intent_primary_cue:+20")

    if any(term and term in text for term in intent.positive_terms):
        score += 20
        reasons.append("positive_terms:+20")

    if is_video:
        score += 25
        reasons.append("video:+25")
    if is_image:
        score -= 40
        reasons.append("static_image:-40")
        if not intent.allow_static_images:
            score -= 30
            reasons.append("image_not_allowed:-30")

    if orientation in {"portrait", "vertical"} or any(token in text for token in ("portrait", "vertical", "1080x1920", "9:16")):
        score += 15
        reasons.append("vertical_friendly:+15")

    if intent.intent_type == "family_responsibility" and category == "family_protection":
        score += 30
        reasons.append("family_responsibility_match:+30")
    if intent.intent_type == "emotional_protection" and category in {"family_relief", "family_protection", "emotional_reassurance"}:
        score += 32
        reasons.append("emotional_protection_family_match:+32")
    if intent.intent_type in {"coverage_explanation", "advisor_explanation", "insurance_documents"} and category == "practical_explanation":
        score += 28
        reasons.append("coverage_practical_explanation_match:+28")
    if intent.intent_type in {"myth_debunk_age", "client_objection"} and category == "advisor_consultation":
        score += 30
        reasons.append("objection_advisor_match:+30")
    if intent.intent_type in {"myth_debunk_age", "client_objection"} and category == "financial_planning":
        score += 20
        reasons.append("objection_financial_match:+20")
    if intent.intent_type in {"myth_debunk_age", "client_objection"} and category == "documents_admin":
        score += 10
        reasons.append("objection_documents_support:+10")
    if intent.intent_type == "risk_warning_family" and category == "risk_warning":
        score += 30
        reasons.append("risk_warning_match:+30")
    if intent.intent_type in {"risk_warning", "risk_warning_family"} and category in {"risk_warning", "health_access"}:
        score += 24
        reasons.append("risk_warning_compatible_match:+24")
    if source in {"pexels", "stock"} and query in {q.lower() for q in intent.pexels_queries}:
        score += 15
        reasons.append("intent_query_match:+15")

    theme_delta, theme_reasons = score_theme_fit(category, text, intent, theme, selected_categories, selected_visual_types)
    score += theme_delta
    reasons.extend(theme_reasons)

    insurance_finance = intent.domain in {"insurance_finance", "real_estate_housing", "legal_admin"}
    if insurance_finance and any(term in text for term in ("tea", "coffee", "meditation", "yoga", "wellness", "spa", "zen")):
        score -= 50
        reasons.append("wellness_mismatch:-50")
    if any(term in text for term in ("funeral", "hospital bed", "nursing home")) and intent.intent_type != "risk_warning_family":
        score -= 45
        reasons.append("severe_risk_mismatch:-45")
    if "sad alone" in text and intent.intent_type != "risk_warning_family":
        score -= 30
        reasons.append("sad_alone_mismatch:-30")
    if any(term in text for term in ("stock market", "trading", "luxury cash", "skyscraper")):
        score -= 35
        reasons.append("finance_cliche:-35")
    if any(term in text for term in ("random office", "business handshake")):
        score -= 25
        reasons.append("generic_office:-25")
    if category_repeated:
        score -= 20
        reasons.append("category_repeated:-20")
    if intent.intent_type == "weak_intro":
        score -= 45
        reasons.append("weak_intro:-45")
    if category == "documents_admin" and intent.intent_type == "family_responsibility" and not any(term in text for term in ("family", "couple", "parents", "home", "mortgage")):
        score -= 25
        reasons.append("cold_documents_for_family:-25")
    if category == "emotional_reassurance" and intent.narrative_function == "client_objection":
        score -= 20
        reasons.append("generic_protection_in_objection:-20")
    if source == "local" and not any(term in text for term in intent.positive_terms):
        score -= 5
        reasons.append("local_unknown_quality:-5")
    if is_image and not (title or tags or query):
        score -= 15
        reasons.append("image_low_metadata:-15")

    for suffix_key, penalty in VPI_ASSET_PENALTIES.items():
        if path_text.endswith(suffix_key):
            score += penalty
            reasons.append(f"asset_penalty:{suffix_key}:{penalty}")
            break

    for avoid in intent.avoid_terms:
        avoid_norm = avoid.lower()
        if avoid_norm and avoid_norm in text:
            score -= 35
            reasons.append(f"avoid:{avoid_norm}:-35")

    # ── Log selected candidate ──────────────────────────────────────────────
    logger.info(
        "EDITORIAL_BROLL_SELECTED category=%s asset=%s confidence=%.2f "
        "timing_anchor=%s score=%.2f reason=%s",
        category, path_text, intent.confidence,
        intent.primary_cue or "none", score,
        ",".join(reasons),
    )

    return score, reasons



def _visual_type_for_category(category: str, text: str) -> str:
    if category == "documents_admin" or any(term in text for term in ("document", "paperwork", "contract", "policy", "close up", "signing")):
        return "documents_paper_closeup"
    if category in {"family_protection", "emotional_reassurance", "home_responsibility"}:
        return "human_family_home"
    if category in {"advisor_consultation", "financial_planning"} or "advisor" in text:
        return "advisor_planning"
    if category == "risk_warning":
        return "risk_context"
    return category or "unknown"


def score_theme_fit(
    category: str,
    candidate_text: str,
    intent: VisualIntent,
    theme: ClipTheme | Dict[str, Any],
    selected_categories: Sequence[str],
    selected_visual_types: Sequence[str],
) -> Tuple[float, List[str]]:
    get = theme.get if isinstance(theme, dict) else lambda key, default=None: getattr(theme, key, default)
    central_topic = str(get("central_topic", ""))
    preferred_mix = list(get("preferred_visual_mix", []) or [])
    emotional_frame = str(get("emotional_frame", ""))
    reasons: List[str] = []
    delta = 0.0
    visual_type = _visual_type_for_category(category, candidate_text)

    if category in preferred_mix or visual_type in preferred_mix:
        delta += 25
        reasons.append("theme_central_fit:+25")
    if any(term in candidate_text for term in ("family", "parents", "couple", "home", "advisor", "planning", "future")):
        delta += 20
        reasons.append("theme_emotional_frame:+20")
    if category == "advisor_consultation" and "insurance_finance" in str(get("domain", "")):
        delta += 25
        reasons.append("advisor_insurance_explanation:+25")
    if central_topic == "life_insurance_family_protection" and (
        category in {"family_protection", "home_responsibility"} or any(term in candidate_text for term in ("family", "parents", "couple", "home", "protection"))
    ):
        delta += 25
        reasons.append("life_insurance_human_context:+25")
    if category == "financial_planning" and any(term in candidate_text for term in ("family", "home", "couple", "advisor", "mortgage", "budget", "planning")):
        delta += 20
        reasons.append("financial_human_context:+20")
    if category == "documents_admin":
        delta += 10
        reasons.append("documents_secondary_support:+10")

    documents_count = sum(1 for cat in selected_categories if cat == "documents_admin")
    if category == "documents_admin" and documents_count >= 1:
        delta -= 45
        reasons.append("documents_twice_same_clip:-45")
    if category == "documents_admin" and documents_count >= 1 and not any(cat in selected_categories for cat in ("advisor_consultation", "financial_planning", "family_protection")):
        delta -= 60
        reasons.append("documents_without_variety:-60")
    if central_topic == "life_insurance_family_protection" and visual_type == "documents_paper_closeup":
        delta -= 25
        reasons.append("cold_paperwork_life_insurance:-25")
    if central_topic == "life_insurance_family_protection" and category == "documents_admin" and intent.intent_type in {"myth_debunk_age", "client_objection"}:
        delta -= 35
        reasons.append("myth_debunk_only_paperwork_risk:-35")
    if category in selected_categories:
        delta -= 30
        reasons.append("same_category_second_overlay:-30")
    if visual_type in selected_visual_types:
        delta -= 25
        reasons.append("repeated_visual_texture:-25")
    if category == "documents_admin" and not any(term in candidate_text for term in ("advisor", "couple", "family", "home", "young")):
        delta -= 30
        reasons.append("weak_commercial_emotional_fit:-30")

    if len(set(selected_categories) | {category}) > len(set(selected_categories)):
        delta += 20
        reasons.append("visual_variety:+20")

    logger.info(
        "[theme-score] asset=%s score_delta=%.1f reasons=%s",
        candidate_text.split()[0] if candidate_text else category,
        delta,
        ",".join(reasons),
    )
    return delta, reasons


def score_broll_candidate_legacy(
    cue_type: str,
    asset_path: Optional[Path],
    intent: VisualIntent,
    editorial_type: Optional[str],
    suggested_broll_cue_type: Optional[str],
    text: str,
    is_image: bool = False,
    used_in_task: bool = False,
    used_recently: bool = False,
    category_repeated: bool = False,
) -> Tuple[float, List[str]]:
    del editorial_type, text, used_recently
    return score_broll_candidate(
        {
            "source": "local",
            "path": asset_path or "",
            "category": cue_type,
            "is_image": is_image,
            "is_video": not is_image,
            "used_in_task": used_in_task,
            "category_repeated": category_repeated,
        },
        intent,
        {"suggested_broll_cue_type": suggested_broll_cue_type},
    )


def assess_broll_relevance(
    phrase: str,
    category: str,
    intent_type: str,
    central_topic: str,
) -> Tuple[bool, float, str]:
    """
    Assess whether a B-roll candidate phrase is relevant to the current editorial intent.

    Returns (is_relevant, score, reason) where score is a heuristic relevance
    score (0-100) and reason is a short human-readable explanation.
    """
    if not phrase or not phrase.strip():
        return False, 0.0, "empty_phrase"

    phrase_lower = phrase.lower()
    score = 0.0
    reasons: List[str] = []

    # Category match against central topic
    if central_topic and category:
        topic_lower = central_topic.lower()
        if category in topic_lower or topic_lower in category:
            score += 30
            reasons.append("category_topic_match:+30")

    # Intent-specific boosts
    if intent_type == "family_responsibility" and any(
        term in phrase_lower for term in ("family", "parents", "child", "home", "couple", "protection")
    ):
        score += 35
        reasons.append("family_phrase:+35")
    elif intent_type in ("myth_debunk_age", "client_objection") and any(
        term in phrase_lower for term in ("advisor", "consultation", "documents", "contract", "young", "couple")
    ):
        score += 30
        reasons.append("objection_phrase:+30")
    elif intent_type == "risk_warning_family" and any(
        term in phrase_lower for term in ("worried", "serious", "protection", "family", "finances")
    ):
        score += 30
        reasons.append("risk_phrase:+30")
    elif intent_type == "financial_planning" and any(
        term in phrase_lower for term in ("mortgage", "budget", "planning", "family", "home", "advisor")
    ):
        score += 25
        reasons.append("financial_phrase:+25")
    elif intent_type == "insurance_documents" and any(
        term in phrase_lower for term in ("insurance", "policy", "documents", "signing", "contract")
    ):
        score += 25
        reasons.append("insurance_phrase:+25")

    # Generic positive signal: phrase has concrete visual terms
    if any(
        term in phrase_lower
        for term in ("family", "home", "office", "advisor", "documents", "planning", "consultation", "contract", "couple", "parents", "child")
    ):
        score += 15
        reasons.append("concrete_visual:+15")

    # Penalty for generic/abstract phrases with no visual hook
    if not any(
        term in phrase_lower
        for term in ("family", "home", "office", "advisor", "documents", "planning", "consultation", "contract", "couple", "parents", "child", "money", "protection", "risk", "insurance", "mortgage", "budget", "future", "health", "travel", "hospital", "patient", "doctor", "clinic", "luggage", "airport", "destination", "hotel")
    ):
        score -= 20
        reasons.append("abstract_no_visual:-20")

    # Strong penalty for wellness/meditation mismatches in finance context
    if any(term in phrase_lower for term in ("tea", "coffee", "meditation", "yoga", "wellness", "spa", "zen")):
        score -= 40
        reasons.append("wellness_mismatch:-40")

    is_relevant = score >= 20.0
    reason_str = ",".join(reasons) if reasons else "neutral"
    return is_relevant, score, reason_str


def is_broll_asset_forbidden(
    asset: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, List[str]]:
    """
    Determine whether a B-roll asset is forbidden for use based on its metadata
    and the current editorial context.

    Returns (is_forbidden, reasons) where reasons is a list of human-readable
    strings explaining why the asset is forbidden (empty if not forbidden).
    """
    if not asset:
        return False, []

    reasons: List[str] = []
    context = context or {}

    path = str(asset.get("path") or asset.get("url") or "").lower()
    category = str(asset.get("category") or "").lower()
    query = str(asset.get("query") or "").lower()
    title = str(asset.get("title") or "").lower()
    tags = " ".join(str(t) for t in (asset.get("tags") or [])).lower()
    metadata = str(asset.get("metadata") or "").lower()
    text = " ".join([path, category, query, title, tags, metadata])

    # Explicit forbidden flag
    if asset.get("forbidden"):
        reason = str(asset.get("forbidden_reason") or "explicit_forbidden_flag")
        reasons.append(reason)
        return True, reasons

    # Wellness/meditation mismatches for insurance/finance context
    ctx_category = str(context.get("category") or "").lower()
    ctx_intent = str(context.get("intent_type") or "").lower()
    is_finance_context = any(
        term in ctx_category or term in ctx_intent
        for term in ("insurance", "finance", "financial", "mortgage", "risk")
    )
    if is_finance_context and any(
        term in text for term in ("tea", "coffee", "meditation", "yoga", "wellness", "spa", "zen")
    ):
        reasons.append("wellness_mismatch_in_finance_context")
        return True, reasons

    # Severe risk imagery not appropriate for non-risk contexts
    if "risk" not in ctx_intent and any(
        term in text for term in ("funeral", "hospital bed", "nursing home", "ambulance", "violence")
    ):
        reasons.append("severe_risk_imagery_in_non_risk_context")
        return True, reasons

    # Sad/alone imagery not appropriate for most contexts
    if "sad alone" in text and "risk" not in ctx_intent:
        reasons.append("sad_alone_imagery")
        return True, reasons

    # Finance cliches
    if any(term in text for term in ("stock market", "trading", "luxury cash", "skyscraper")):
        reasons.append("finance_cliche")
        return True, reasons

    # Generic office cliches
    if any(term in text for term in ("random office", "business handshake")):
        reasons.append("generic_office_cliche")
        return True, reasons

    return False, reasons


def score_broll_phrase_fit(
    asset: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
    theme: Optional[ClipTheme | Dict[str, Any]] = None,
    intent_type: str = "",
) -> Dict[str, Any]:
    """
    Score how well a B-roll asset's phrase/description fits the current editorial context.

    Returns a dict with keys:
        phrase_fit_score (float, 0-100)
        phrase_fit_label (str)
        phrase_fit_reason (str)
        allowed_as_primary (bool)
        allowed_as_support (bool)
    """
    if not asset:
        return {
            "phrase_fit_score": 0.0,
            "phrase_fit_label": "no_asset",
            "phrase_fit_reason": "empty_asset",
            "allowed_as_primary": False,
            "allowed_as_support": False,
        }

    context = context or {}
    path = str(asset.get("path") or "").lower()
    category = str(asset.get("category") or "").lower()
    cue_type = str(asset.get("cue_type") or "").lower()
    query = str(asset.get("query") or "").lower()
    is_image = bool(asset.get("is_image"))
    title = str(asset.get("title") or "").lower()
    tags = " ".join(str(t) for t in (asset.get("tags") or [])).lower()
    text = " ".join([path, category, cue_type, query, title, tags])

    score = 50.0  # baseline neutral
    reasons: List[str] = []

    # Category match with context
    ctx_category = str(context.get("category") or "").lower()
    ctx_cue_type = str(context.get("cue_type") or "").lower()
    if category and (category == ctx_category or category == ctx_cue_type):
        score += 20
        reasons.append("category_match:+20")

    # Query match
    ctx_query = str(context.get("query") or "").lower()
    if ctx_query and (ctx_query in text or any(word in text for word in ctx_query.split() if len(word) > 3)):
        score += 15
        reasons.append("query_match:+15")

    # Intent-type specific boosts
    if intent_type == "family_responsibility" and any(
        term in text for term in ("family", "parents", "child", "home", "couple", "protection")
    ):
        score += 20
        reasons.append("family_phrase:+20")
    elif intent_type in ("myth_debunk_age", "client_objection") and any(
        term in text for term in ("advisor", "consultation", "documents", "contract", "young", "couple")
    ):
        score += 15
        reasons.append("objection_phrase:+15")
    elif intent_type == "risk_warning_family" and any(
        term in text for term in ("worried", "serious", "protection", "family", "finances")
    ):
        score += 15
        reasons.append("risk_phrase:+15")
    elif intent_type == "financial_planning" and any(
        term in text for term in ("mortgage", "budget", "planning", "family", "home", "advisor")
    ):
        score += 15
        reasons.append("financial_phrase:+15")

    # Concrete visual terms bonus
    if any(
        term in text
        for term in ("family", "home", "office", "advisor", "documents", "planning", "consultation", "contract", "couple", "parents", "child")
    ):
        score += 10
        reasons.append("concrete_visual:+10")

    # Penalties for mismatches
    if any(term in text for term in ("tea", "coffee", "meditation", "yoga", "wellness", "spa", "zen")):
        score -= 30
        reasons.append("wellness_mismatch:-30")
    if any(term in text for term in ("funeral", "hospital bed", "nursing home", "ambulance")):
        score -= 40
        reasons.append("severe_imagery:-40")
    if any(term in text for term in ("stock market", "trading", "luxury cash", "skyscraper")):
        score -= 25
        reasons.append("finance_cliche:-25")
    if any(term in text for term in ("random office", "business handshake")):
        score -= 20
        reasons.append("generic_office:-20")

    # Static image penalty
    if is_image:
        score -= 15
        reasons.append("static_image:-15")

    # Clamp score
    score = max(0.0, min(100.0, score))

    # Determine labels
    if score >= 75:
        label = "strong_fit"
        reason = ",".join(reasons) if reasons else "strong_phrase_fit"
        primary = True
        support = True
    elif score >= 50:
        label = "moderate_fit"
        reason = ",".join(reasons) if reasons else "moderate_phrase_fit"
        primary = True
        support = True
    elif score >= 30:
        label = "weak_fit"
        reason = ",".join(reasons) if reasons else "weak_phrase_fit"
        primary = False
        support = True
    else:
        label = "poor_fit"
        reason = ",".join(reasons) if reasons else "poor_phrase_fit"
        primary = False
        support = False

    return {
        "phrase_fit_score": score,
        "phrase_fit_label": label,
        "phrase_fit_reason": reason,
        "allowed_as_primary": primary,
        "allowed_as_support": support,
    }


def select_best_candidates(
    candidates: List[Tuple[str, Optional[Path], float, List[str]]],
    intent: VisualIntent,
    max_overlays: Optional[int] = None,
) -> List[Tuple[str, Optional[Path], float, List[str]]]:
    allowed = max(0, min(max_overlays if max_overlays is not None else intent.max_overlays, intent.max_overlays))
    if allowed <= 0:
        logger.info("[broll-select] skipped reason=intent_disallows_broll intent=%s", intent.intent_type)
        return []
    passing = [item for item in candidates if item[2] >= intent.min_candidate_score]
    passing.sort(key=lambda item: item[2], reverse=True)
    selected: List[Tuple[str, Optional[Path], float, List[str]]] = []
    seen_categories: set[str] = set()
    for cue, asset, score, reasons in passing:
        if cue in seen_categories and len(selected) >= 1:
            continue
        selected.append((cue, asset, score, reasons))
        seen_categories.add(cue)
        if len(selected) >= allowed:
            break
    logger.info("[broll-select] final_count=%d intent=%s", len(selected), intent.intent_type)
    return selected


def _decesos_sensitive(text: str, editorial_type: str) -> bool:
    normalized = normalize_text(" ".join([text or "", editorial_type or ""]))
    return any(
        token in normalized
        for token in (
            "decesos",
            "funeral",
            "fallecimiento",
            "muerte",
            "mourning",
            "cemetery",
        )
    )


def _resolve_local_asset_candidates(
    available_local_assets: Optional[Any],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    if available_local_assets is None:
        try:
            from .vpi_asset_library_service import build_asset_index as _build_asset_index

            index = _build_asset_index()
            verified_broll = list((index.get("verified") or {}).get("broll") or [])
            for item in verified_broll:
                if isinstance(item, dict):
                    candidates.append(dict(item))
                elif item:
                    candidates.append({"path": str(item), "type": "broll", "source_name": "local"})
        except Exception as exc:
            logger.debug("[broll-decision] asset discovery skipped: %s", exc)
        return candidates

    for item in list(available_local_assets or []):
        if isinstance(item, dict):
            candidates.append(dict(item))
        elif isinstance(item, Path):
            candidates.append({"path": str(item), "type": "broll", "source_name": "local"})
        elif isinstance(item, str) and item.strip():
            candidates.append({"path": item, "type": "broll", "source_name": "local"})
    return candidates


def choose_broll_editorial_decision(
    *,
    segment_text: str,
    editorial_type: str = "",
    vpi_score: Optional[float] = None,
    suggested_broll_cue_type: Optional[str] = None,
    words_with_timestamps: Optional[Sequence[Dict[str, Any]]] = None,
    clip_duration: float = 0.0,
    hook_strategy_final: str = "",
    hook_visual_applied: bool = False,
    visual_layer_budget: Optional[Dict[str, Any]] = None,
    visual_support_layer_selected: str = "",
    visual_reinforcement_applied: bool = False,
    captions_active: bool = False,
    face_bbox: Optional[Dict[str, Any]] = None,
    speaker_bbox: Optional[Dict[str, Any]] = None,
    available_local_assets: Optional[Any] = None,
    provider_diagnostics: Optional[Dict[str, Any]] = None,
    hook_text_redundant_with_captions: bool = False,
) -> Dict[str, Any]:
    """Single source of truth for editorial B-roll decisioning."""
    del words_with_timestamps
    normalized_text = normalize_text(" ".join([segment_text or "", editorial_type or "", suggested_broll_cue_type or ""]))
    intent = detect_intent(
        segment_text,
        editorial_type=editorial_type,
        suggested_broll_cue_type=suggested_broll_cue_type,
        vpi_score=vpi_score,
        segment_duration=clip_duration,
    )
    theme = detect_clip_theme(
        segment_text,
        editorial_type=editorial_type,
        suggested_broll_cue_type=suggested_broll_cue_type,
        vpi_score=vpi_score,
    )
    clip_duration = max(0.0, float(clip_duration or 0.0))
    safe_edit = False
    try:
        from .vpi_production_safe_edit import production_safe_edit_enabled as _production_safe_edit_enabled

        safe_edit = _production_safe_edit_enabled()
    except Exception:
        safe_edit = True

    death_sensitive = _decesos_sensitive(segment_text, editorial_type)
    death_sober_family_context = death_sensitive and _contains(
        normalized_text,
        [
            "familia", "acompanamiento", "acompañamiento", "cuidado",
            "menos peso", "serenidad", "organizacion", "organización",
            "tranquilidad",
        ],
    )
    threshold = 0.78 if death_sober_family_context else (0.85 if death_sensitive else (0.72 if safe_edit else 0.62))
    confidence = float(max(intent.confidence or 0.0, (float(vpi_score or 0.0) / 100.0) if vpi_score is not None else 0.0))
    confidence = round(min(1.0, confidence), 3)

    budget = visual_layer_budget if isinstance(visual_layer_budget, dict) else {}
    visual_layers_allowed = list(budget.get("visual_layers_allowed") or budget.get("allowed_layers") or [])
    visual_layers_dropped = list(budget.get("visual_layers_dropped") or budget.get("dropped_layers") or [])
    temporal_density_budget_applied = bool(budget.get("temporal_density_budget_applied"))
    collision_guard_applied = bool(budget.get("collision_guard_applied"))
    visual_density = float(budget.get("visual_density") or 0.0)
    support_selected = str(visual_support_layer_selected or budget.get("visual_support_layer_selected") or "")
    support_reason = str(budget.get("visual_support_layer_reason") or "")
    budget_reason = ""
    budget_allowed = True
    if temporal_density_budget_applied or collision_guard_applied:
        if captions_active or hook_visual_applied or visual_reinforcement_applied or visual_density >= 8.0:
            budget_allowed = False
            budget_reason = "visual_density_budget_blocked"
    if captions_active and hook_visual_applied and support_selected in {"semantic_card", "motion_overlay", "branding", "cta"} and clip_duration < 12.0:
        budget_allowed = False
        budget_reason = "screen_already_loaded"
    if hook_strategy_final == "text_hook" and captions_active and support_selected in {"semantic_card", "lower_third"}:
        budget_allowed = False
        budget_reason = "hook_caption_collision"
    if death_sensitive and not budget_reason:
        budget_reason = "decesos_sobrio"

    local_assets = _resolve_local_asset_candidates(available_local_assets)
    local_only = True
    provider_preference = "local_only" if safe_edit else "local_preferred"

    # Determine a conservative editorial mode.
    intent_type = str(intent.intent_type or "").lower()
    if death_sober_family_context:
        broll_mode = "cutaway_fullscreen"
        mode_reason = "decesos_sober_family_relief"
    elif death_sensitive:
        broll_mode = "no_broll"
        mode_reason = "death_sensitive_requires_sobriety"
    elif intent_type in {"family_responsibility", "emotional_protection"}:
        broll_mode = "cutaway_fullscreen"
        mode_reason = "family_protection_context"
    elif intent_type in {"risk_warning_family", "risk_warning"}:
        broll_mode = "overlay_insert"
        mode_reason = "risk_warning_context"
    elif intent_type in {"insurance_documents", "financial_planning"}:
        broll_mode = "picture_in_picture"
        mode_reason = "coverage_explanation"
    elif intent_type in {"myth_debunk_age", "client_objection"}:
        broll_mode = "picture_in_picture"
        mode_reason = "objection_context"
    elif intent_type == "weak_intro":
        # OUTPUT-QUALITY-7: a presentation opener no longer disables b-roll for the
        # WHOLE clip — the timing strategy already keeps the cutaway out of the
        # first seconds. High-confidence content with local assets gets the daily
        # full-frame cutaway; everything else stays protected.
        if confidence >= 0.75 and safe_edit and local_assets:
            broll_mode = "daily_fullframe_cutaway"
            mode_reason = "weak_intro_with_clear_content_match"
        else:
            broll_mode = "no_broll"
            mode_reason = "weak_intro_protected"
    elif intent_type in {"generic", "speaker_focus", "generic_context"}:
        broll_mode = "no_broll"
        mode_reason = "generic_context_unstable"
    else:
        broll_mode = "background_soft"
        mode_reason = "editorial_contextual_support"

    if visual_reinforcement_applied and support_selected in {"semantic_card", "motion_overlay"}:
        mode_reason = "reinforcement_present"
        if broll_mode in {"cutaway_fullscreen", "overlay_insert"}:
            broll_mode = "picture_in_picture"

    if clip_duration < 3.0:
        broll_mode = "no_broll"
        mode_reason = "clip_too_short"

    if confidence < threshold:
        broll_mode = "no_broll"
        mode_reason = "low_confidence"

    # Hook-first opening protection.
    hook_protected = clip_duration >= 3.0 and (
        hook_visual_applied
        or hook_strategy_final in {"text_hook", "non_text_push_hook", "silence_tension_hook"}
        or captions_active
    )
    if safe_edit and broll_mode == "picture_in_picture":
        # OUTPUT-QUALITY-3: PiP boxes conflict with captions, but a FULL-FRAME cutaway
        # does not — captions are burned after the b-roll step and render on top.
        # High-confidence matches with local assets become a sober full-frame cutaway;
        # PiP itself stays forbidden in daily mode.
        if confidence >= 0.75 and local_assets:
            broll_mode = "daily_fullframe_cutaway"
            mode_reason = "daily_fullframe_cutaway_high_confidence"
            logger.info(
                "VPI_OUTPUT_QUALITY_BROLL_FULLFRAME_ELIGIBLE intent=%s confidence=%.2f local_assets=%d",
                intent_type, confidence, len(local_assets),
            )
        elif captions_active or hook_protected:
            broll_mode = "no_broll"
            mode_reason = "daily_mode_no_picture_in_picture"
        else:
            broll_mode = "cutaway_fullscreen"
            mode_reason = "daily_mode_fullscreen_cutaway_only"
    if safe_edit and broll_mode == "cutaway_fullscreen" and confidence >= 0.75 and local_assets:
        # OUTPUT-BROLL-11: "cutaway_fullscreen" is the same sober full-frame
        # insert under its legacy name — but the composition resolver (Rule 9)
        # only exempts "daily_fullframe_cutaway" in minimal_safe, so the legacy
        # name died as composition_conflict. High-confidence + local assets gets
        # the canonical daily route, identical render path.
        broll_mode = "daily_fullframe_cutaway"
        mode_reason = "daily_fullframe_cutaway_high_confidence"
        logger.info(
            "VPI_OUTPUT_QUALITY_BROLL_FULLFRAME_ELIGIBLE intent=%s confidence=%.2f local_assets=%d reason=legacy_cutaway_promoted",
            intent_type, confidence, len(local_assets),
        )
    start_time = 3.0 if hook_protected else max(0.0, min(clip_duration, 0.75))
    if hook_protected and start_time < 3.0:
        start_time = 3.0
    if start_time < 3.0:
        if confidence >= 0.90 and not hook_text_redundant_with_captions and not captions_active:
            start_time = 3.0
            mode_reason = "hook_protected_first3"
        else:
            broll_mode = "no_broll"
            mode_reason = "hook_protected_first3"
    duration = 1.2 if clip_duration < 12.0 else 1.8
    duration = min(2.8, max(1.2, duration))
    if broll_mode == "daily_fullframe_cutaway":
        duration = 2.0
    max_insertions = 1 if clip_duration < 20.0 else 2
    if visual_reinforcement_applied or support_selected in {"semantic_card", "motion_overlay"}:
        max_insertions = min(max_insertions, 1)
    if death_sensitive:
        max_insertions = 1

    face_safe = True
    if isinstance(face_bbox, dict):
        try:
            face_y = float(face_bbox.get("y") or face_bbox.get("top") or 0.0)
            face_safe = face_y >= 0.42 or broll_mode != "cutaway_fullscreen"
        except Exception:
            face_safe = True
    if isinstance(speaker_bbox, dict):
        try:
            speaker_y = float(speaker_bbox.get("y") or speaker_bbox.get("top") or 0.0)
            if speaker_y < 0.42 and broll_mode in {"cutaway_fullscreen", "daily_fullframe_cutaway", "overlay_insert"}:
                face_safe = False
        except Exception:
            pass
    caption_safe = bool(captions_active or broll_mode in {"cutaway_fullscreen", "daily_fullframe_cutaway", "background_soft", "picture_in_picture"})

    if not budget_allowed:
        broll_mode = "no_broll"
    if not local_assets:
        broll_mode = "no_broll"
    if death_sensitive and not local_assets:
        broll_mode = "no_broll"
    if not face_safe:
        mode_reason = "face_not_safe"
    if not caption_safe:
        mode_reason = "caption_not_safe"

    asset_query = ""
    if intent.preferred_queries:
        asset_query = str(intent.preferred_queries[0] or "")
    if not asset_query:
        asset_query = build_stock_queries(intent, limit=1)[0] if build_stock_queries(intent, limit=1) else ""
    asset_category = str(intent.primary_cue or (intent.preferred_categories[0] if intent.preferred_categories else "") or "")
    taxonomy_families = _compatible_families_for_intent(intent)
    logger.info(
        "VPI_BROLL_TAXONOMY_ASSET_COVERAGE intent=%s families=%s local_assets=%d",
        intent.intent_type,
        ",".join(taxonomy_families) or "none",
        len(local_assets),
    )

    if provider_diagnostics is not None:
        logger.info(
            "BROLL_PROVIDER_DIAGNOSTICS local_only=%s available=%s",
            str(local_only).lower(),
            ",".join(str(k) for k in sorted((provider_diagnostics or {}).keys())) or "none",
        )

    if broll_mode == "no_broll":
        reason = mode_reason or "no_editorial_gain"
    else:
        reason = mode_reason or "editorial_match"

    decision = {
        "broll_decision": "use_broll" if broll_mode != "no_broll" else "no_broll",
        "broll_mode": broll_mode,
        "intent": intent,
        "intent_type": intent.intent_type,
        "confidence": confidence,
        "reason": reason,
        "start_time": round(float(start_time), 2),
        "duration": round(float(duration), 2),
        "max_insertions": int(max_insertions),
        "asset_query": asset_query,
        "asset_category": asset_category,
        "provider_preference": provider_preference,
        "budget_allowed": bool(budget_allowed),
        "face_safe": bool(face_safe),
        "caption_safe": bool(caption_safe),
        "hook_protected_first3": bool(hook_protected),
        "visual_support_layer_selected": support_selected,
        "visual_support_layer_reason": support_reason,
        "visual_layers_allowed": visual_layers_allowed,
        "visual_layers_dropped": visual_layers_dropped,
        "local_asset_count": len(local_assets),
        "safe_edit": bool(safe_edit),
        "local_only": bool(local_only),
        "provider_diagnostics": provider_diagnostics or {},
        "broll_taxonomy_intent": str(intent.intent_type or ""),
        "broll_taxonomy_asset_family": asset_category,
        "broll_taxonomy_match_confidence": confidence if broll_mode != "no_broll" else 0.0,
        "broll_taxonomy_match_reason": reason if broll_mode != "no_broll" else f"skip:{reason}",
    }
    logger.info(
        "BROLL_EDITORIAL_DECISION decision=%s mode=%s confidence=%.2f reason=%s asset_query=%s start=%.2f dur=%.2f max=%d budget=%s face_safe=%s caption_safe=%s",
        decision["broll_decision"],
        decision["broll_mode"],
        confidence,
        reason,
        asset_query,
        decision["start_time"],
        decision["duration"],
        decision["max_insertions"],
        str(budget_allowed).lower(),
        str(face_safe).lower(),
        str(caption_safe).lower(),
    )
    return decision


def build_broll_editorial_decision(**kwargs: Any) -> Dict[str, Any]:
    # Callers pass a wider context than choose_broll_editorial_decision accepts;
    # filter to its signature so extra keys don't raise TypeError (which used to
    # silently disable the whole editorial b-roll route as "decision_failed").
    import inspect
    _accepted = set(inspect.signature(choose_broll_editorial_decision).parameters)
    decision = choose_broll_editorial_decision(
        **{k: v for k, v in kwargs.items() if k in _accepted}
    )
    should_use_broll = decision.get("broll_decision") == "use_broll"
    result = {
        "should_use_broll": should_use_broll,
        "broll_decision": decision.get("broll_decision"),
        "broll_mode": decision.get("broll_mode"),
        "broll_intent": str(decision.get("intent_type") or ""),
        "confidence": float(decision.get("confidence") or 0.0),
        "reason": str(decision.get("reason") or ""),
        "start_offset": float(decision.get("start_time") or 0.0),
        "duration": float(decision.get("duration") or 0.0),
        "max_insertions": int(decision.get("max_insertions") or 0),
        "asset_query": str(decision.get("asset_query") or ""),
        "asset_category": str(decision.get("asset_category") or ""),
        "provider_preference": str(decision.get("provider_preference") or "local_only"),
        "budget_allowed": bool(decision.get("budget_allowed")),
        "face_safe": bool(decision.get("face_safe")),
        "caption_safe": bool(decision.get("caption_safe")),
        "hook_protected_first3": bool(decision.get("hook_protected_first3")),
        "visual_support_layer_selected": str(decision.get("visual_support_layer_selected") or ""),
        "visual_support_layer_reason": str(decision.get("visual_support_layer_reason") or ""),
        "fallback": "none" if should_use_broll else str(decision.get("reason") or "no_broll"),
        "skip_reason": "" if should_use_broll else str(decision.get("reason") or "no_broll"),
        "route_used": "editorial_local",
        "duplicate_routes_blocked": True,
        "local_only": bool(decision.get("local_only")),
        "broll_taxonomy_intent": str(decision.get("broll_taxonomy_intent") or ""),
        "broll_taxonomy_asset_family": str(decision.get("broll_taxonomy_asset_family") or ""),
        "broll_taxonomy_match_confidence": float(decision.get("broll_taxonomy_match_confidence") or 0.0),
        "broll_taxonomy_match_reason": str(decision.get("broll_taxonomy_match_reason") or ""),
    }
    logger.info(
        "BROLL_SELECTED use_broll=%s mode=%s reason=%s",
        str(should_use_broll).lower(),
        result["broll_mode"],
        result["reason"],
    )
    if not should_use_broll:
        logger.info("BROLL_SKIPPED_REASON reason=%s", result["skip_reason"])
    return result


def match_broll_asset(
    *,
    broll_intent: str,
    topic: str,
    segment_text: str,
    available_local_assets: Optional[Any] = None,
    provider_diagnostics: Optional[Dict[str, Any]] = None,
    decision: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Match an editorial B-roll asset using local/verified assets only."""
    from .broll_asset_memory import asset_id_for

    base_decision = decision or choose_broll_editorial_decision(
        segment_text=segment_text,
        editorial_type=topic or broll_intent,
        suggested_broll_cue_type=broll_intent,
        available_local_assets=available_local_assets,
        provider_diagnostics=provider_diagnostics,
    )
    # ── OUTPUT-BROLL-14: local intake status for the requested family ─────────
    _intake_intent = detect_intent(
        segment_text,
        editorial_type=topic or broll_intent,
        suggested_broll_cue_type=broll_intent,
    )
    _intake_requested = _canonical_broll_family(
        str(_intake_intent.primary_cue or (_intake_intent.preferred_categories[0] if _intake_intent.preferred_categories else "") or broll_intent or "")
    )
    _intake_available = 0
    _intake_status = "unknown_family"
    if _intake_requested:
        for _base in (Path("/app/assets/broll"), Path("assets/broll")):
            _fam_dir = _base / _intake_requested
            if _fam_dir.is_dir():
                _intake_available = sum(
                    1 for _f in _fam_dir.iterdir()
                    if _f.suffix.lower() in VIDEO_EXTS or _f.suffix.lower() in IMAGE_EXTS
                )
                _intake_status = "ready" if _intake_available else "no_local_assets_in_family"
                break
        else:
            _intake_status = "family_folder_missing"
        if _intake_status == "ready":
            logger.info(
                "VPI_BROLL_ASSET_INTAKE_FAMILY_READY family=%s assets=%d",
                _intake_requested, _intake_available,
            )
        elif _intake_status == "no_local_assets_in_family":
            logger.info("VPI_BROLL_ASSET_INTAKE_FAMILY_EMPTY family=%s", _intake_requested)
    _intake_fields = {
        "broll_asset_family_requested": _intake_requested,
        "broll_asset_family_available": _intake_available,
        "broll_asset_intake_status": _intake_status,
    }
    if _intake_requested in {"travel_assistance", "student_abroad"} and _intake_status == "no_local_assets_in_family":
        logger.info("BROLL_SKIPPED_REASON reason=no_local_assets_in_family family=%s", _intake_requested)
        return {
            "matched": False,
            "asset": "",
            "source": "none",
            "score": 0.0,
            "reasons": ["no_local_assets_in_family"],
            "category": "",
            "asset_id": "",
            "provider_video_id": "",
            "route_used": str(base_decision.get("route_used") or "editorial_local"),
            "duplicate_routes_blocked": bool(base_decision.get("duplicate_routes_blocked", True)),
            **_intake_fields,
        }
    if base_decision.get("broll_decision") != "use_broll":
        _early_reasons = (
            ["no_local_assets_in_family"]
            if _intake_status == "no_local_assets_in_family"
            else [str(base_decision.get("reason") or "no_broll")]
        )
        return {
            "matched": False,
            "asset": "",
            "source": "none",
            "score": 0.0,
            "reasons": _early_reasons,
            "category": "",
            "asset_id": "",
            "provider_video_id": "",
            "route_used": str(base_decision.get("route_used") or "editorial_local"),
            "duplicate_routes_blocked": bool(base_decision.get("duplicate_routes_blocked", True)),
            **_intake_fields,
        }

    try:
        from .vpi_asset_library_service import build_asset_index as _build_asset_index
        from .local_broll_asset_bank import list_assets as _list_local_assets
        from .vpi_asset_library_service import _classify_broll_by_filename as _classify_broll_by_filename
    except Exception as exc:
        logger.debug("[broll-match] asset helpers unavailable: %s", exc)
        return {
            "matched": False,
            "asset": "",
            "source": "none",
            "score": 0.0,
            "reasons": ["asset_helpers_unavailable"],
            "category": "",
            "asset_id": "",
            "provider_video_id": "",
            "route_used": str(base_decision.get("route_used") or "editorial_local"),
            "duplicate_routes_blocked": bool(base_decision.get("duplicate_routes_blocked", True)),
            **_intake_fields,
        }

    intent = detect_intent(
        segment_text,
        editorial_type=topic or broll_intent,
        suggested_broll_cue_type=broll_intent,
    )
    theme = detect_clip_theme(
        segment_text,
        editorial_type=topic or broll_intent,
        suggested_broll_cue_type=broll_intent,
    )

    # (intake status computed earlier, right after base_decision)
    local_candidates: List[Dict[str, Any]] = []
    if available_local_assets is not None:
        local_candidates = _resolve_local_asset_candidates(available_local_assets)
    else:
        index = _build_asset_index()
        verified_broll = list((index.get("verified") or {}).get("broll") or [])
        local_candidates = [dict(item) for item in verified_broll if isinstance(item, dict)]
        if not local_candidates:
            # Fall back to the local bank by category
            preferred = []
            for category in intent.preferred_categories or ([intent.primary_cue] if intent.primary_cue else []):
                if not category:
                    continue
                preferred.extend(list(_list_local_assets(category)))
            local_candidates = [{"path": str(path), "type": "broll", "source_name": "local"} for path in preferred]

    if not local_candidates:
        logger.info("BROLL_SKIPPED_REASON reason=no_local_asset_match")
        return {
            "matched": False,
            "asset": "",
            "source": "none",
            "score": 0.0,
            "reasons": ["no_local_assets_in_family"] if _intake_status == "no_local_assets_in_family" else ["no_local_asset_match"],
            "category": "",
            "asset_id": "",
            "provider_video_id": "",
            "route_used": str(base_decision.get("route_used") or "editorial_local"),
            "duplicate_routes_blocked": bool(base_decision.get("duplicate_routes_blocked", True)),
            **_intake_fields,
        }

    decision_threshold = 85.0 if _decesos_sensitive(segment_text, topic) else (72.0 if bool(base_decision.get("safe_edit", True)) else 65.0)
    scored: List[Tuple[str, Optional[Path], float, List[str], str, str]] = []
    for candidate in local_candidates:
        path_str = str(candidate.get("path") or "").strip()
        if not path_str:
            continue
        asset = Path(path_str)
        if not asset.exists():
            continue
        category = _canonical_broll_family(str(candidate.get("category") or candidate.get("taxonomy") or "").strip().lower())
        if not category:
            category, tags = _classify_broll_by_filename(asset)
            candidate["category"] = category
            candidate["taxonomy"] = category
            candidate.setdefault("tags", tags)
        candidate["query"] = base_decision.get("asset_query") or ""
        candidate["cue"] = base_decision.get("asset_category") or broll_intent or ""
        candidate["source"] = str(candidate.get("source_name") or "local")
        candidate["is_video"] = asset.suffix.lower() in VIDEO_EXTS
        candidate["is_image"] = asset.suffix.lower() in IMAGE_EXTS
        score, reasons = score_broll_candidate(
            candidate,
            intent,
            theme,
            {
                "suggested_broll_cue_type": broll_intent,
                "category_seen": {},
                "selected_categories": [],
                "selected_visual_types": [],
            },
        )
        fit = score_broll_phrase_fit(candidate, {"query": base_decision.get("asset_query") or ""}, theme, intent.intent_type)
        score += float(fit.get("phrase_fit_score") or 0.0) * 0.2
        reasons.extend([
            f"phrase_fit_score:{fit.get('phrase_fit_score')}",
            f"phrase_fit_label:{fit.get('phrase_fit_label')}",
            f"phrase_fit_reason:{fit.get('phrase_fit_reason')}",
            f"allowed_as_primary:{str(bool(fit.get('allowed_as_primary'))).lower()}",
            f"allowed_as_support:{str(bool(fit.get('allowed_as_support'))).lower()}",
        ])
        if not fit.get("allowed_as_support") and not fit.get("allowed_as_primary"):
            continue
        if _decesos_sensitive(segment_text, topic) and not any(term in normalize_text(path_str) for term in ("family", "home", "document", "shield", "calm", "peace", "health")):
            continue
        scored.append((str(candidate.get("cue") or broll_intent or ""), asset, score, reasons, category, str(candidate.get("source_name") or "local")))

    selected = select_best_candidates(
        [(cue, asset, score, reasons) for cue, asset, score, reasons, _, _ in scored],
        intent,
        max_overlays=1,
    )
    if not selected:
        # Feed the daily-cutaway text-category fallback below instead of returning:
        # weak_intro-style intents produce zero selectable candidates by design.
        selected = [("", None, 0.0, ["no_scored_selection"])]

    selected_cue, selected_asset, selected_score, selected_reasons = selected[0]
    selected_category = ""
    selected_source = "local"
    for cue, asset, score, reasons, category, source in scored:
        if asset == selected_asset and cue == selected_cue:
            selected_category = category
            selected_source = source
            break

    asset_id = asset_id_for(selected_source, str(selected_asset), None)
    matched = bool(selected_asset and selected_score >= decision_threshold)
    if not matched and str(base_decision.get("broll_mode") or "") in {"daily_fullframe_cutaway", "cutaway_fullscreen"} and float(base_decision.get("confidence") or 0.0) >= 0.75:
        # OUTPUT-QUALITY-7: weak_intro-style intents carry no preferred categories so
        # score_broll_candidate hard-rejects every asset (-999). For the high-confidence
        # daily cutaway path, fall back to a CLEAR text→category mapping over the
        # verified local assets — never generic stock.
        _TEXT_CATEGORY_FALLBACK = (
            # OUTPUT-BROLL-14: travel/student text NEVER falls back to emotional
            # families — first-match-break lands here before the emotional rows.
            (("viaje", "viajar", "pasaje", "aeropuerto", "equipaje", "maleta", "asistencia en viaje"), ("travel_assistance",)),
            (("estudiante", "estudios", "visado", "campus", "universidad", "estancia"), ("student_abroad",)),
            (("familia", "tuyos", "hijos", "pareja", "acompanamiento", "cuidado", "serenidad"), ("family_relief", "family_protection", "emotional_reassurance")),
            (("documento", "documentos", "tramite", "poliza", "contrato", "firmar"), ("documents_admin",)),
            (("precio", "prima", "pago", "pagos", "ahorro", "ahorrar"), ("financial_planning",)),
            (("tranquilidad", "calma", "proteger", "proteccion", "protege", "menos peso"), ("family_relief", "emotional_reassurance", "family_protection")),
            (("salud", "medico", "hospital", "imprevisto", "avisa"), ("health_access", "risk_warning")),
            (("cobertura", "seguro", "seguros", "vida", "contratar", "revisar"), ("practical_explanation", "documents_admin", "financial_planning")),
            (("viaje", "pasaje", "extranjero", "aeropuerto"), ("documents_admin", "financial_planning")),
        )
        _norm_text = normalize_text(segment_text)
        _fallback_categories: Tuple[str, ...] = tuple()
        for _terms, _cats in _TEXT_CATEGORY_FALLBACK:
            if any(term in _norm_text for term in _terms):
                _fallback_categories = _cats
                break
        if _fallback_categories:
            for _cue, _asset, _score, _reasons, _category, _source in scored:
                if _asset is not None and str(_category or "").lower() in _fallback_categories and Path(str(_asset)).exists():
                    selected_asset = _asset
                    selected_score = max(float(decision_threshold), 75.0)
                    selected_reasons = list(_reasons) + [f"text_category_fallback:{_category}"]
                    selected_category = _category
                    selected_source = _source
                    asset_id = asset_id_for(selected_source, str(selected_asset), None)
                    matched = True
                    logger.info(
                        "VPI_OUTPUT_QUALITY_BROLL_TEXT_CATEGORY_FALLBACK category=%s asset=%s",
                        _category, str(_asset),
                    )
                    break
    if not matched:
        if _intake_status == "no_local_assets_in_family":
            logger.info("BROLL_SKIPPED_REASON reason=no_local_assets_in_family family=%s", _intake_requested)
        else:
            logger.info("BROLL_SKIPPED_REASON reason=low_confidence")
    else:
        logger.info(
            "VPI_BROLL_ASSET_INTAKE_SELECTED family_requested=%s family_selected=%s asset=%s intake_status=%s",
            _intake_requested, selected_category or selected_cue, selected_asset, _intake_status,
        )
        taxonomy_confidence = round(min(1.0, max(0.0, float(selected_score or 0.0) / 100.0)), 3)
        logger.info(
            "BROLL_SELECTED asset=%s source=%s score=%.2f category=%s",
            selected_asset,
            selected_source,
            selected_score,
            selected_category or selected_cue,
        )
        logger.info(
            "VPI_BROLL_TAXONOMY_MATCH intent=%s asset_family=%s confidence=%.2f reason=%s",
            intent.intent_type,
            selected_category or selected_cue,
            taxonomy_confidence,
            ",".join(selected_reasons[:4]),
        )
    return {
        "matched": matched,
        "asset": str(selected_asset) if matched else "",
        "source": selected_source if matched else "none",
        "score": float(selected_score if matched else 0.0),
        "reasons": selected_reasons if matched else (
            ["no_local_assets_in_family"] if _intake_status == "no_local_assets_in_family" else ["low_confidence"]
        ),
        "category": selected_category or selected_cue,
        "asset_id": asset_id if matched else "",
        "provider_video_id": "",
        "route_used": str(base_decision.get("route_used") or "editorial_local"),
        "duplicate_routes_blocked": bool(base_decision.get("duplicate_routes_blocked", True)),
        "broll_asset_family_requested": _intake_requested,
        "broll_asset_family_available": _intake_available,
        "broll_asset_intake_status": _intake_status,
        "broll_taxonomy_intent": str(intent.intent_type or broll_intent or ""),
        "broll_taxonomy_asset_family": str(selected_category or selected_cue or ""),
        "broll_taxonomy_match_confidence": round(min(1.0, max(0.0, float(selected_score if matched else 0.0) / 100.0)), 3),
        "broll_taxonomy_match_reason": ",".join(selected_reasons[:6]) if matched else "no_compatible_local_asset",
    }


def choose_vpi_broll_timing_strategy(
    broll_decision: Optional[Dict[str, Any]] = None,
    editorial_type: str = "",
    segment_text: str = "",
    words_with_timestamps: Optional[Sequence[Dict[str, Any]]] = None,
    hook_strategy_final: str = "",
    first_second_strength: float = 0.0,
    caption_density: float = 0.0,
    premium_restraint_mode: str = "",
    motion_profile: str = "",
    clip_duration: float = 0.0,
    sensitive_topic: bool = False,
) -> Dict[str, Any]:
    decision = dict(broll_decision or {})
    normalized_text = normalize_text(segment_text)
    words: List[Dict[str, float]] = []
    for item in words_with_timestamps or []:
        if not isinstance(item, dict):
            continue
        words.append(
            {
                "word": normalize_text(str(item.get("word") or "")),
                "start": float(item.get("start") or 0.0),
                "end": float(item.get("end") or item.get("start") or 0.0),
            }
        )

    # OUTPUT-QUALITY-7: the original 9-term list missed the core insurance vocabulary
    # (seguro/proteccion/poliza/vida...), so the phrase matcher never fired and the
    # relevance gate killed every b-roll on real VPI content.
    _PHRASE_MATCH_TERMS = (
        "familia", "hospital", "tramite", "documento", "documentos", "viaje", "ahorro",
        "riesgo", "cobertura", "tranquilidad", "seguro", "seguros", "proteccion",
        "proteger", "protege", "poliza", "prima", "vida", "salud", "decesos",
        "contratar", "asesor", "prever", "claridad", "calma",
    )
    match_terms = [term for term in _PHRASE_MATCH_TERMS if term in normalized_text]
    match_confidence = 0.0
    timing_strategy = "no_broll"
    start_time = 0.0
    end_time = 0.0
    duration = 0.0
    entry_style = "no_transition"
    exit_style = "no_transition"
    should_return = False
    reason = "default_no_broll"

    restraint = normalize_text(premium_restraint_mode)
    motion = normalize_text(motion_profile)
    hook = normalize_text(hook_strategy_final)
    has_strong_hook = float(first_second_strength or 0.0) >= 72.0 or "strong" in hook or "visual" in hook

    if sensitive_topic or restraint == "sensitive_minimal" or motion == "sensitive_soft":
        reason = "sensitive_or_sensitive_soft"
    elif restraint == "no_extra_visual" and float(decision.get("confidence") or 0.0) < 0.8:
        reason = "suppressed_by_restraint"
    else:
        phrase_match = None
        if words and match_terms:
            # Never land the cutaway inside the first-3s hook window: prefer the first
            # match at >=4.0s; fall back to any match only if none exists later.
            for word in words:
                if float(word.get("start") or 0.0) >= 4.0 and any(term in word["word"] for term in match_terms):
                    phrase_match = word
                    break
            if phrase_match is None:
                for word in words:
                    if any(term in word["word"] for term in match_terms):
                        phrase_match = word
                        break
        if phrase_match:
            phrase_start = max(0.0, float(phrase_match.get("start") or 0.0) - 0.12)
            phrase_end = min(float(clip_duration or 0.0), float(phrase_match.get("end") or phrase_start) + 0.32)
            timing_strategy = "phrase_matched_insert"
            start_time = phrase_start
            end_time = max(phrase_end, start_time + 1.8)
            # Recommended perceptible cutaway length (1.8-2.4s); the daily gate
            # requires >= 1.8s.
            duration = min(2.4, max(1.8, end_time - start_time))
            entry_style = "cut" if motion == "punchy" else "soft_fade"
            exit_style = "cut" if motion == "punchy" else "soft_fade"
            should_return = True
            match_confidence = 0.9
            reason = "matched_phrase_context"
            logger.info("VPI_BROLL_PHRASE_MATCHED terms=%s start=%.2f end=%.2f", "|".join(match_terms), start_time, end_time)
        elif clip_duration <= 15.0 and float(decision.get("confidence") or 0.0) >= 0.8 and not has_strong_hook:
            timing_strategy = "short_cutaway"
            start_time = max(3.0, min(float(clip_duration) * 0.30, float(clip_duration) - 2.0))
            duration = min(1.8, max(1.0, float(clip_duration) * 0.10))
            end_time = min(float(clip_duration), start_time + duration)
            entry_style = "cut"
            exit_style = "cut"
            should_return = True
            match_confidence = 0.55
            reason = "short_clip_conservative_broll"
        elif clip_duration > 15.0 and not has_strong_hook and caption_density < 7.0:
            timing_strategy = "late_context_insert"
            start_time = max(3.2, min(float(clip_duration) * 0.38, float(clip_duration) - 4.0))
            duration = min(3.2, max(1.5, float(clip_duration) * 0.12))
            end_time = min(float(clip_duration), start_time + duration)
            entry_style = "soft_fade"
            exit_style = "soft_fade"
            should_return = True
            match_confidence = 0.45
            reason = "late_context_without_clear_phrase_match"

    broll_relevance_score = round(float(match_confidence or 0.0), 2)
    broll_relevance_gate_passed = bool(timing_strategy != "no_broll" and broll_relevance_score >= 0.65)
    broll_skipped_unrelated = False
    if timing_strategy != "no_broll" and not broll_relevance_gate_passed:
        broll_skipped_unrelated = True
        timing_strategy = "no_broll"
        start_time = 0.0
        end_time = 0.0
        duration = 0.0
        entry_style = "no_transition"
        exit_style = "no_transition"
        should_return = False
        reason = "skipped_unrelated_low_relevance"
        logger.info("VPI_BROLL_RELEVANCE_GATE_FAILED score=%.2f reason=%s", broll_relevance_score, reason)
        logger.info("VPI_BROLL_SKIPPED_UNRELATED score=%.2f reason=%s", broll_relevance_score, reason)

    if timing_strategy != "no_broll" and float(clip_duration or 0.0) > 0.0:
        max_share = 0.35 * float(clip_duration or 0.0)
        if duration > max_share > 0.0:
            duration = max_share
            end_time = min(float(clip_duration), start_time + duration)
            reason = f"{reason}_capped_by_share"
        if start_time < 3.0 and has_strong_hook:
            start_time = max(start_time, 3.0)
            end_time = min(float(clip_duration), start_time + duration)
            if end_time <= start_time:
                timing_strategy = "no_broll"
                duration = 0.0
                should_return = False
                reason = "hook_strong_forced_no_broll"

    if timing_strategy == "no_broll":
        start_time = 0.0
        end_time = 0.0
        duration = 0.0
        should_return = False
        if sensitive_topic or restraint in {"sensitive_minimal", "no_extra_visual"}:
            logger.info("VPI_BROLL_SKIPPED_BY_RESTRAINT reason=%s", reason)
        else:
            logger.info("VPI_BROLL_SKIPPED_NO_PHRASE_MATCH reason=%s", reason)
        logger.info("VPI_BROLL_POLISH_WARNING reason=%s", reason)
    else:
        logger.info("VPI_BROLL_RETURN_TO_SPEAKER reason=%s", "payoff_or_cta_requires_speaker" if should_return else "no_return_needed")

    logger.info(
        "VPI_BROLL_TIMING_SELECTED strategy=%s start=%.2f end=%.2f duration=%.2f reason=%s",
        timing_strategy,
        start_time,
        end_time,
        duration,
        reason,
    )
    return {
        "broll_timing_strategy": timing_strategy,
        "broll_start_time": round(float(start_time or 0.0), 2),
        "broll_end_time": round(float(end_time or 0.0), 2),
        "broll_duration": round(float(duration or 0.0), 2),
        "broll_entry_style": entry_style,
        "broll_exit_style": exit_style,
        "broll_timing_reason": reason,
        "broll_should_return_to_speaker": bool(should_return),
        "broll_phrase_matched": bool(match_terms and timing_strategy != "no_broll"),
        "broll_phrase_match_terms": match_terms,
        "broll_phrase_match_confidence": round(float(match_confidence or 0.0), 2),
        "broll_relevance_gate_passed": bool(broll_relevance_gate_passed),
        "broll_relevance_score": float(broll_relevance_score),
        "broll_skipped_unrelated": bool(broll_skipped_unrelated),
        "broll_transition_sober": entry_style in {"cut", "soft_fade", "subtle_push"} and exit_style in {"cut", "soft_fade"},
        "broll_return_to_speaker": bool(should_return),
        "broll_return_reason": "payoff_or_cta_requires_speaker" if should_return else "no_return_needed",
        "broll_status": "skipped_no_clear_phrase_match" if timing_strategy == "no_broll" and not match_terms else ("skipped_unrelated" if timing_strategy == "no_broll" and broll_skipped_unrelated else timing_strategy),
    }
