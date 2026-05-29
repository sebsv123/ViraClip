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

_LOCAL_BROLL_SEARCH_ROOTS: Tuple[str, ...] = (
    "/app/assets/broll",
    "/app/assets/videos/broll",
    "assets/broll",
    "backend/assets/broll",
    "frontend/public/broll",
)

_BROLL_INTENT_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "family_relief": ("alivio", "familia", "menos carga", "acompanamiento", "acompañamiento", "respaldo"),
    "health_access": ("salud", "especialistas", "pruebas", "acceso rapido", "acceso rápido", "consulta"),
    "autonomous_work_stability": ("autonomo", "autónomo", "motor", "ingresos", "estabilidad", "negocio", "continuidad"),
    "risk_warning_context": ("no siempre avisa", "imprevisto", "riesgo", "si manana", "si mañana"),
    "practical_explanation": ("antes de", "mira tu vida real", "organizacion", "organización", "consejo"),
    "emotional_support": ("cuando mas falta hace", "cuando más falta hace", "apoyo", "tranquilidad", "familia"),
}

_BROLL_FILENAME_TERMS: Dict[str, Tuple[str, ...]] = {
    "family_relief": ("family", "familia", "home", "couple", "parents", "child", "support"),
    "health_access": ("health", "salud", "doctor", "clinic", "medical", "specialist", "consulta"),
    "autonomous_work_stability": ("autonom", "business", "work", "office", "laptop", "entrepreneur", "income"),
    "risk_warning_context": ("risk", "warning", "concern", "worry", "insurance", "planning"),
    "practical_explanation": ("advisor", "consultation", "explaining", "documents", "plan", "strategy"),
    "emotional_support": ("support", "family", "embrace", "care", "home", "calm"),
}

_SENSITIVE_DECESOS_BLOCKLIST: Tuple[str, ...] = (
    "cement",
    "cemeter",
    "grave",
    "coffin",
    "ataud",
    "ataúd",
    "funeral",
    "mortuary",
    "morgue",
)

_LOCAL_BROLL_CACHE: Optional[List[Path]] = None

_FORBIDDEN_BROLL_TERMS: Dict[str, Tuple[str, ...]] = {
    "tea_or_wellness": (
        "tea",
        "té",
        "cup",
        "taza",
        "coffee",
        "cafe",
        "café",
        "mug",
        "meditation",
        "meditacion",
        "meditación",
        "yoga",
        "wellness",
        "bienestar",
        "calm",
        "relaxation",
        "spa",
    ),
    "severe_risk_cliche": (
        "funeral",
        "hospital bed",
        "hospital",
        "ambulance",
        "ambulancia",
    ),
    "finance_cliche": (
        "stock market",
        "stock_market",
        "bolsa",
        "trading",
        "luxury",
        "lujo",
        "luxury money",
    ),
    "generic_office": (
        "handshake only",
        "generic office",
        "random office",
        "business handshake",
        "sad alone person",
        "sad alone",
    ),
}

_KNOWN_FORBIDDEN_LOCAL_ASSETS = {
    "emotional_reassurance/02.mp4": "known_tea_wellness_asset",
}


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
    "emotional_protection": ["advisor_consultation", "family_protection", "financial_planning", "home_responsibility", "documents_admin"],
    "client_objection": ["advisor_consultation", "financial_planning", "family_protection", "documents_admin"],
    "myth_debunk": ["advisor_consultation", "financial_planning", "family_protection", "documents_admin"],
    "coverage_explanation": ["documents_admin", "financial_planning"],
    "risk_warning": ["risk_warning", "family_protection", "financial_planning"],
    "actionable_advice": ["documents_admin", "financial_planning"],
    "example_story": ["family_protection", "financial_planning", "location_context"],
}

CUE_ALIASES: Dict[str, str] = {
    "documents_admin": "documents_admin",
    "emotional_reassurance": "emotional_reassurance",
    "family_protection": "family_protection",
    "financial_planning": "financial_planning",
    "risk_warning": "risk_warning",
    "explain_coverage": "documents_admin",
    "advisor_meeting": "advisor_consultation",
}


def assess_broll_relevance(
    *,
    phrase: str,
    category: str,
    intent_type: str = "",
    central_topic: str = "",
) -> Tuple[bool, float, str]:
    phrase_norm = normalize_text(" ".join(str(item or "") for item in [phrase]))
    category_key = str(category or "").lower()
    intent_key = str(intent_type or "").lower()
    topic = str(central_topic or "").lower()

    def has_any(terms: Tuple[str, ...]) -> bool:
        return any(normalize_text(term) in phrase_norm for term in terms)

    if topic == "life_insurance_family_protection":
        emotional_intent = intent_key in {"emotional_protection", "family_responsibility"} or has_any(
            ("dependen de ti", "hijos", "pareja", "familia", "responsabilidad")
        )
        if emotional_intent and category_key == "documents_admin":
            return False, 18.0, "documents_admin_not_primary_for_emotional_family"

    allowed: Optional[set[str]] = None
    reason = "general_context_match"
    if has_any(("dependen de ti", "hijos", "pareja", "familia")):
        allowed = {"family_protection", "home_responsibility", "advisor_consultation", "financial_planning"}
        reason = "family_phrase_requires_human_or_home_context"
    elif has_any(("hipoteca", "casa")):
        allowed = {"home_responsibility", "financial_planning", "advisor_consultation"}
        reason = "home_financial_phrase"
    elif "responsabilidad" in phrase_norm:
        allowed = {"family_protection", "financial_planning", "advisor_consultation", "home_responsibility"}
        reason = "responsibility_phrase_requires_family_or_advisor"
    elif has_any(("no es solo", "personas mayores", "mayores", "edad")):
        allowed = {"advisor_consultation", "young_family", "financial_planning", "family_protection"}
        reason = "age_myth_phrase_requires_advisor_or_younger_family"
    elif has_any(("cobertura", "póliza", "poliza", "contratar", "contrato")):
        allowed = {"documents_admin", "advisor_consultation", "financial_planning"}
        reason = "coverage_phrase_allows_documents_as_support"

    if allowed is not None and category_key not in allowed:
        return False, 25.0, f"not_related_to_phrase:{reason}"
    if category_key == "documents_admin" and reason != "coverage_phrase_allows_documents_as_support":
        return False, 30.0, "documents_admin_only_support_not_primary"
    if category_key == "documents_admin":
        return True, 68.0, reason
    if category_key in {"family_protection", "home_responsibility", "advisor_consultation"}:
        return True, 92.0, reason
    if category_key in {"financial_planning", "young_family"}:
        return True, 84.0, reason
    return True, 60.0, reason


def score_broll_phrase_fit(
    asset: Any,
    phrase_context: str,
    clip_theme: Optional[ClipTheme] = None,
    intent_type: str = "",
) -> Dict[str, Any]:
    """Score fine-grained editorial fit between active phrase and B-roll asset."""
    phrase_norm = normalize_text(phrase_context)
    if isinstance(clip_theme, dict):
        topic = str(clip_theme.get("central_topic") or "").lower()
    else:
        topic = str(getattr(clip_theme, "central_topic", "") or "").lower()
    intent_key = str(intent_type or "").lower()
    path, raw_text, normalized = _candidate_text_for_guard(asset, {"intent_type": intent_type})
    category = normalize_text(str((asset or {}).get("category") if isinstance(asset, dict) else ""))
    if not category and isinstance(asset, dict):
        category = normalize_text(str(asset.get("cue_type") or ""))
    combined = " ".join([raw_text, normalized, category])

    def has_phrase(terms: Tuple[str, ...]) -> bool:
        return any(normalize_text(term) in phrase_norm for term in terms)

    def has_asset(terms: Tuple[str, ...]) -> bool:
        return any(normalize_text(term) in combined for term in terms)

    family_phrase = has_phrase((
        "personas que dependen de ti",
        "dependen de ti",
        "hijos",
        "pareja",
        "familia",
        "sosteniendo una estructura",
        "proteger",
        "responsabilidad",
    ))
    paper_only = category == "documents_admin" or has_asset(("document", "documents", "papel", "paper", "contract", "contrato", "policy", "poliza"))
    human_home = has_asset(("family", "familia", "home", "hogar", "child", "hijos", "parents", "pareja", "couple"))
    advisor = category == "advisor_consultation" or has_asset(("advisor", "asesor", "consultation", "consulta"))
    financial = category == "financial_planning" or has_asset(("financial", "planning", "budget", "mortgage", "hipoteca"))

    score = 55.0
    reason = "general_support"
    allowed_primary = True
    allowed_support = True

    if topic == "life_insurance_family_protection" and family_phrase:
        if category in {"family_protection", "home_responsibility"} or (human_home and not paper_only):
            score, reason = 92.0, "family_dependency_phrase_matches_family_or_home"
        elif advisor and human_home:
            score, reason = 78.0, "family_dependency_phrase_supported_by_human_advisor_context"
        elif financial and human_home and not paper_only:
            score, reason = 70.0, "family_dependency_phrase_supported_by_family_financial_context"
        elif paper_only:
            score, reason = 35.0, "documents_do_not_express_dependency_or_care"
            allowed_primary = False
            allowed_support = category in {"documents_admin", "advisor_consultation"}
        else:
            score, reason = 45.0, "weak_family_dependency_visual_context"
            allowed_primary = False
    elif has_phrase(("cobertura", "poliza", "póliza", "contratar", "contrato")):
        if category == "documents_admin":
            score, reason = 68.0, "coverage_phrase_allows_documents_support"
            allowed_primary = intent_key in {"coverage_explanation", "actionable_advice"}
        elif advisor:
            score, reason = 82.0, "coverage_phrase_supported_by_advisor_context"
        else:
            score, reason = 58.0, "coverage_phrase_general_support"
    elif has_phrase(("no es solo", "personas mayores", "edad", "mas adelante", "más adelante")):
        if advisor or (financial and not paper_only) or category == "family_protection":
            score, reason = 80.0, "objection_phrase_matches_advisor_or_planning"
        elif paper_only:
            score, reason = 48.0, "objection_phrase_documents_only_support"
            allowed_primary = False
        else:
            score, reason = 52.0, "objection_phrase_weak_context"

    if score >= 85:
        label = "exact"
    elif score >= 70:
        label = "good"
    elif score >= 55:
        label = "support"
    elif score >= 40:
        label = "weak"
    else:
        label = "mismatch"

    if label in {"weak", "mismatch"}:
        allowed_primary = False
    if label == "mismatch":
        allowed_support = False

    return {
        "phrase_fit_score": round(score, 1),
        "phrase_fit_label": label,
        "phrase_fit_reason": reason,
        "allowed_as_primary": bool(allowed_primary),
        "allowed_as_support": bool(allowed_support),
        "asset_path": str(path),
    }


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


def _candidate_text_for_guard(asset: Any, context: Optional[Dict[str, Any]] = None) -> Tuple[str, str, str]:
    context = context or {}
    if isinstance(asset, dict):
        path = asset.get("path") or asset.get("asset_path") or asset.get("url") or ""
        fields = [
            path,
            asset.get("query"),
            asset.get("title"),
            asset.get("category") or asset.get("cue"),
            asset.get("visual_texture"),
            asset.get("visual_fingerprint"),
            asset.get("provider_video_id"),
            " ".join(str(tag) for tag in asset.get("tags", []) or []),
            asset.get("metadata"),
        ]
    else:
        path = str(asset or "")
        fields = [path]

    context_fields = [
        context.get("query"),
        context.get("title"),
        context.get("category"),
        context.get("cue_type"),
        context.get("visual_texture"),
        context.get("visual_fingerprint"),
        context.get("provider_video_id"),
        context.get("asset_id"),
        " ".join(str(term) for term in context.get("tags", []) or []),
        context.get("metadata"),
        context.get("theme_topic"),
        context.get("central_topic"),
    ]
    combined = " ".join(str(item or "") for item in fields + context_fields)
    normalized = normalize_text(combined)
    raw_lower = combined.lower()
    return path, raw_lower, normalized


def _guard_contains(raw_text: str, normalized_text: str, term: str) -> bool:
    term_norm = normalize_text(term)
    if len(term_norm) <= 2:
        return term.lower() in raw_text
    return (term.lower() in raw_text) or (term_norm and term_norm in normalized_text)


def is_broll_asset_forbidden(asset: Any, context: Optional[Dict[str, Any]] = None) -> Tuple[bool, List[str]]:
    """Hard VPI B-roll guard. Forbidden assets must not reach final scoring."""
    context = context or {}
    path, raw_text, normalized = _candidate_text_for_guard(asset, context)
    path_norm = str(path or "").replace("\\", "/").lower()
    reasons: List[str] = []

    for known_path, reason in _KNOWN_FORBIDDEN_LOCAL_ASSETS.items():
        if known_path in path_norm:
            reasons.append(reason)

    for group, terms in _FORBIDDEN_BROLL_TERMS.items():
        for term in terms:
            if _guard_contains(raw_text, normalized, term):
                reasons.append(f"{group}:{normalize_text(term) or term.lower()}")
                break

    central_topic = str(context.get("central_topic") or context.get("theme_topic") or "").lower()
    category = normalize_text(str(context.get("category") or context.get("cue_type") or ""))
    risk_context = any(_guard_contains(raw_text, normalized, term) for term in ("funeral", "hospital", "hospital bed", "ambulance", "ambulancia"))
    explicit_risk = str(context.get("intent_type") or "") in {"risk_warning", "risk_warning_family"} or _guard_contains(
        raw_text,
        normalized,
        "imprevisto",
    )
    if explicit_risk:
        reasons = [reason for reason in reasons if not reason.startswith("severe_risk_cliche:")]
    if central_topic == "life_insurance_family_protection":
        if any(_guard_contains(raw_text, normalized, term) for term in ("wellness", "tea", "té", "meditation", "meditación", "yoga", "coffee", "taza")):
            reasons.append("life_insurance_forbidden_wellness")
        if category == "documents_admin" and context.get("documents_already_used"):
            reasons.append("life_insurance_paper_only_repeated")
        if category == "documents_admin" and not any(
            _guard_contains(raw_text, normalized, term)
            for term in ("advisor", "asesor", "couple", "family", "familia", "parents", "home", "hogar", "young")
        ):
            reasons.append("life_insurance_cold_documents_primary")
        if risk_context and not explicit_risk:
            reasons.append("life_insurance_risk_cliche_without_context")
        if any(_guard_contains(raw_text, normalized, term) for term in ("stock market", "bolsa", "trading", "luxury", "lujo")):
            reasons.append("life_insurance_stock_luxury_money")

    asset_id = str(context.get("asset_id") or "")
    provider_video_id = str(context.get("provider_video_id") or "")
    visual_fingerprint = str(context.get("visual_fingerprint") or "")
    filename_stem = Path(str(path or "")).stem.lower()
    if asset_id and asset_id in set(str(item) for item in context.get("task_seen_asset_ids", []) or []):
        reasons.append("exact_asset_repeat")
    if provider_video_id and provider_video_id in set(str(item) for item in context.get("task_seen_provider_video_ids", []) or []):
        reasons.append("provider_video_repeat")
    if filename_stem and filename_stem in set(str(item).lower() for item in context.get("task_seen_filename_stems", []) or []):
        reasons.append("filename_stem_repeat")
    if context.get("strict_fingerprint_repeat") and visual_fingerprint and visual_fingerprint in set(
        str(item) for item in context.get("task_seen_visual_fingerprints", []) or []
    ):
        reasons.append("visual_fingerprint_repeat")

    unique_reasons = list(dict.fromkeys(reasons))
    return bool(unique_reasons), unique_reasons


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
            preferred_categories=["advisor_consultation", "family_protection", "financial_planning", "home_responsibility", "documents_admin"],
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
            confidence=0.74,
            primary_cue="documents_admin",
            preferred_categories=["documents_admin", "financial_planning"],
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
        return VisualIntent(
            intent_type=str(editorial_type),
            confidence=0.62,
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

    category = str(candidate.get("category") or candidate.get("cue") or "").lower()
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

    if intent.intent_type == "family_responsibility" and category == "family_protection":
        score += 30
        reasons.append("family_responsibility_match:+30")
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

    return score, reasons


def _visual_type_for_category(category: str, text: str) -> str:
    if category in {"family_protection", "emotional_reassurance", "home_responsibility"}:
        return "human_family_home"
    if category in {"advisor_consultation", "financial_planning"} or "advisor" in text:
        return "advisor_planning"
    if category == "documents_admin" or any(term in text for term in ("document", "paperwork", "contract", "policy", "close up", "signing")):
        return "documents_paper_closeup"
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


def _list_local_broll_assets() -> List[Path]:
    global _LOCAL_BROLL_CACHE
    if _LOCAL_BROLL_CACHE is not None:
        return list(_LOCAL_BROLL_CACHE)
    assets: List[Path] = []
    seen: set[str] = set()
    for root_str in _LOCAL_BROLL_SEARCH_ROOTS:
        root = Path(root_str)
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in IMAGE_EXTS.union(VIDEO_EXTS):
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            assets.append(path)
    _LOCAL_BROLL_CACHE = assets
    return list(assets)


def build_broll_editorial_decision(
    *,
    segment_text: str,
    hook_intent: str = "",
    topic: str = "",
    private_premium_status: str = "",
    composition_decision: Optional[Dict[str, Any]] = None,
    first3_visual_contract: Optional[Dict[str, Any]] = None,
    visual_profile: str = "",
) -> Dict[str, Any]:
    text_norm = normalize_text(segment_text or "")
    hook_intent_norm = normalize_text(hook_intent or "")
    topic_norm = normalize_text(topic or "")
    comp_mode = str((composition_decision or {}).get("composition_mode") or "")
    first3_status = str((first3_visual_contract or {}).get("status") or "")

    if str(private_premium_status or "") == "DO_NOT_UPLOAD":
        decision = {
            "should_use_broll": False,
            "broll_intent": "no_broll_needed",
            "moment_type": "none",
            "start_offset": 0.0,
            "duration": 0.0,
            "reason": "private_premium_do_not_upload",
            "confidence": 0.0,
            "fallback": "none",
            "composition_allowed": False,
            "skip_reason": "sensitive_tone",
        }
        logger.info("[broll-editorial] should_use=false intent=no_broll_needed confidence=0.00 reason=private_premium_do_not_upload")
        logger.info("[broll-editorial] skipped reason=sensitive_tone")
        return decision

    broll_intent = "no_broll_needed"
    confidence = 0.2
    reason = "no_editorial_gain"
    moment_type = "none"
    start_offset = 1.8
    duration = 1.4
    fallback = "none"

    _has_family_relief = _contains(text_norm, _BROLL_INTENT_KEYWORDS["family_relief"])
    _has_health_access = _contains(text_norm, _BROLL_INTENT_KEYWORDS["health_access"])
    _has_autonomous = _contains(text_norm, _BROLL_INTENT_KEYWORDS["autonomous_work_stability"])
    _has_risk_context = _contains(text_norm, _BROLL_INTENT_KEYWORDS["risk_warning_context"])
    _has_practical = _contains(text_norm, _BROLL_INTENT_KEYWORDS["practical_explanation"])
    _has_emotional_support = _contains(text_norm, _BROLL_INTENT_KEYWORDS["emotional_support"])

    if hook_intent_norm == "risk_warning" or _has_risk_context:
        broll_intent = "risk_warning_context"
        confidence = 0.76
        reason = "risk_context_support"
        moment_type = "risk_phrase"
        start_offset = 1.6
        duration = 1.2
    elif hook_intent_norm == "autonomous_business_stakes" or _has_autonomous:
        broll_intent = "autonomous_work_stability"
        confidence = 0.82
        reason = "business_stability_context"
        moment_type = "topic_shift"
        start_offset = 1.7
        duration = 1.6
    elif hook_intent_norm == "practical_advice" or _has_practical:
        broll_intent = "practical_explanation"
        confidence = 0.72
        reason = "abstract_explanation_needs_visual_clarity"
        moment_type = "explanation_example"
        start_offset = 2.0
        duration = 1.5
    elif hook_intent_norm == "emotional_closure" or _has_emotional_support:
        broll_intent = "emotional_support"
        confidence = 0.65
        reason = "soft_emotional_support"
        moment_type = "emotional_pause"
        start_offset = 2.4
        duration = 1.0
    elif _has_health_access:
        broll_intent = "health_access"
        confidence = 0.73
        reason = "health_access_example"
        moment_type = "clarity_example"
        start_offset = 1.8
        duration = 1.4
    elif _has_family_relief or (topic_norm == "decesos" and _has_emotional_support):
        broll_intent = "family_relief"
        confidence = 0.7
        reason = "family_relief_metaphor"
        moment_type = "emotional_pause"
        start_offset = 1.9
        duration = 1.3

    should_use = broll_intent != "no_broll_needed" and confidence >= 0.62
    composition_allowed = True
    skip_reason = ""

    if comp_mode == "minimal_safe":
        should_use = False
        composition_allowed = False
        skip_reason = "composition_conflict"
    elif comp_mode == "emotional_soft" and broll_intent not in {"emotional_support", "family_relief"}:
        should_use = False
        composition_allowed = False
        skip_reason = "sensitive_tone"
    elif first3_status in {"review", "fail"} and (first3_visual_contract or {}).get("first3_visual_contract", {}).get("no_layer_overload") is False:
        should_use = False
        composition_allowed = False
        skip_reason = "composition_conflict"

    if should_use and start_offset < 1.5:
        old_start = start_offset
        start_offset = 1.5
        logger.info(
            "[broll-editorial] timing_adjusted=true old=%.2f new=%.2f reason=avoid_hook_or_caption",
            old_start,
            start_offset,
        )

    duration = max(0.8, min(2.2, duration))
    if should_use:
        fallback = "motion_only" if visual_profile else "caption_overlay"
        if comp_mode in {"hook_driven", "business_punch"}:
            fallback = "sweeping_reveal"
    elif skip_reason:
        fallback = "none"

    decision = {
        "should_use_broll": bool(should_use),
        "broll_intent": broll_intent,
        "moment_type": moment_type,
        "start_offset": round(start_offset, 2),
        "duration": round(duration, 2),
        "reason": reason,
        "confidence": round(confidence, 3),
        "fallback": fallback,
        "composition_allowed": bool(composition_allowed),
        "skip_reason": skip_reason or ("no_editorial_gain" if not should_use else ""),
    }

    logger.info(
        "[broll-editorial] should_use=%s intent=%s confidence=%.2f reason=%s",
        str(bool(should_use)).lower(),
        broll_intent,
        confidence,
        reason,
    )
    if not should_use:
        logger.info("[broll-editorial] skipped reason=%s", decision["skip_reason"] or "no_editorial_gain")
    else:
        logger.info(
            "[broll-editorial] timing start_offset=%.2f duration=%.2f reason=%s",
            decision["start_offset"],
            decision["duration"],
            moment_type or "editorial",
        )
    return decision


def match_broll_asset(
    *,
    broll_intent: str,
    topic: str = "",
    segment_text: str = "",
) -> Dict[str, Any]:
    intent = str(broll_intent or "no_broll_needed")
    topic_norm = normalize_text(topic or "")
    text_norm = normalize_text(segment_text or "")
    if intent == "no_broll_needed":
        return {"matched": False, "asset": None, "reason": "no_editorial_gain"}

    try:
        from .vpi_asset_library_service import build_asset_index
        _asset_index = build_asset_index()
    except Exception as exc:
        logger.debug("[broll-asset] asset_library_unavailable reason=%s", exc)
        _asset_index = {}

    _verified_broll = list((_asset_index.get("verified") or {}).get("broll") or [])
    _manifest_found = bool(_asset_index.get("manifest_found"))
    assets = _list_local_broll_assets()
    verified_by_path: Dict[str, Dict[str, Any]] = {
        str(item.get("path") or ""): item for item in _verified_broll if isinstance(item, dict)
    }
    terms = _BROLL_FILENAME_TERMS.get(intent, tuple())
    best_match: Optional[Path] = None
    best_score = -1
    for asset in assets:
        blob = normalize_text(str(asset))
        if topic_norm == "decesos" and any(block in blob for block in _SENSITIVE_DECESOS_BLOCKLIST):
            continue
        score = 0
        for term in terms:
            if normalize_text(term) in blob:
                score += 2
        if topic_norm and topic_norm in blob:
            score += 2
        if any(token in text_norm for token in ("familia", "salud", "autonomo", "autónomo", "riesgo")) and any(token in blob for token in ("family", "health", "autonom", "risk", "support")):
            score += 1
        if score > best_score:
            best_score = score
            best_match = asset

    if not best_match or best_score <= 0:
        logger.info("[broll-asset] intent=%s matched=false asset=", intent)
        logger.info("[broll-asset] skipped reason=no_local_asset")
        return {"matched": False, "asset": None, "reason": "no_local_asset", "score": 0}

    _best_key = str(best_match)
    _verified_entry = verified_by_path.get(_best_key)
    _verified = bool(_verified_entry)
    _source = str((_verified_entry or {}).get("source_name") or ("unverified_local" if not _manifest_found else ""))
    _license = str((_verified_entry or {}).get("license_name") or "")
    _commercial_use_ok = bool((_verified_entry or {}).get("commercial_use_ok"))
    _attribution_required = bool((_verified_entry or {}).get("attribution_required"))
    _tags = list((_verified_entry or {}).get("tags") or [])
    _topics = list((_verified_entry or {}).get("topics") or [])

    if _manifest_found and not _verified:
        logger.info("[broll-asset] verified=false source=unverified_local license=")
        logger.info("[broll-asset] skipped reason=unverified_local")
        return {"matched": False, "asset": None, "reason": "unverified_local", "score": 0}
    if _verified and not _commercial_use_ok:
        logger.info("[broll-asset] verified=false source=%s license=%s", _source, _license)
        logger.info("[broll-asset] skipped reason=commercial_use_not_ok")
        return {"matched": False, "asset": None, "reason": "commercial_use_not_ok", "score": 0}
    if _verified and not _license:
        logger.info("[broll-asset] verified=false source=%s license=", _source)
        logger.info("[broll-asset] skipped reason=license_missing")
        return {"matched": False, "asset": None, "reason": "license_missing", "score": 0}

    logger.info("[broll-asset] intent=%s matched=true asset=%s", intent, str(best_match))
    logger.info("[broll-asset] verified=%s source=%s license=%s", str(_verified).lower(), _source or "unverified_local", _license or "none")
    return {
        "matched": True,
        "asset": str(best_match),
        "asset_path": best_match,
        "score": best_score,
        "reason": "local_asset_match",
        "verified": _verified,
        "broll_asset_verified": _verified,
        "broll_asset_source": _source or "unverified_local",
        "broll_asset_license": _license,
        "broll_asset_tags": _tags,
        "broll_asset_topics": _topics,
        "broll_asset_commercial_use_ok": bool(_commercial_use_ok if _verified else False),
        "broll_asset_attribution_required": _attribution_required,
        "verification_status": "verified_manifest" if _verified else "unverified_local",
    }
