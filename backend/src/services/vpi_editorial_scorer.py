"""Local heuristic editorial scorer for VPI insurance-first clip selection.

v2.0 — Extended segment value model with 8 editorial types, penalties,
diversity metadata, and first-3s hook prediction.
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dedupe_strings(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


# ── Extended score dataclass ────────────────────────────────────────────────────


@dataclass(frozen=True)
class VPIEditorialScore:
    vpi_score: float
    matched_patterns: list[str]
    editorial_type: str
    reason: str
    suggested_broll_cue_type: str | None = None
    generic_penalty: float = 0.0

    # v2.0 extended fields
    segment_value_type: str = ""
    segment_value_score: float = 0.0
    hook_strength_score: float = 0.0
    complete_idea_score: float = 0.0
    novelty_score: float = 0.0
    clarity_score: float = 0.0
    disfluency_penalty: float = 0.0
    filler_ratio: float = 0.0
    duplicate_theme_key: str = ""
    selection_reason: str = ""
    editorial_categories: list[str] = field(default_factory=list)
    hookability_score: float = 0.0
    hookability_reason: str = ""
    commercial_usefulness_score: float = 0.0
    commercial_usefulness_reason: str = ""
    standalone_score: float = 0.0
    standalone_reason: str = ""
    weak_segment_penalties: list[str] = field(default_factory=list)
    weak_segment_reason: str = ""
    segment_selection_confidence: float = 0.0
    selected_for_reason: str = ""
    rejected_for_reason: str = ""


# ── Pattern definitions ─────────────────────────────────────────────────────────

_PATTERNS: dict[str, tuple[float, str | None, tuple[str, ...]]] = {
    "client_objection": (
        34.0,
        "documents_admin",
        (
            "es muy caro",
            "ya tengo seguro",
            "yo ya tengo seguro",
            "no lo necesito",
            "eso no me va a pasar",
            "lo miro luego",
            "me lo miro luego",
            "lo veo luego",
            "ya lo mirare",
            "mas adelante",
            "no me hace falta",
            "soy joven",
            "personas mayores",
            "por la edad",
            "no tengo hijos",
            "no tengo hipoteca",
        ),
    ),
    "myth_debunk": (
        32.0,
        "explain_coverage",
        (
            "mucha gente piensa que",
            "la gente piensa que",
            "esto no funciona asi",
            "esto no funciona así",
            "error comun",
            "error común",
            "no todos los seguros cubren",
            "no todos los seguros",
            "no es solo para",
            "no solo",
            "personas mayores",
            "no siempre",
            "la realidad es que",
            "eso ya me lo mirare",
            "mas adelante",
            "no suele tener sentido",
            "por la edad",
            "seguro de vida no es solo",
        ),
    ),
    "risk_warning": (
        35.0,
        "risk_warning",
        (
            "cuidado con",
            "el problema viene cuando",
            "si esperas demasiado",
            "puedes quedarte sin cobertura",
            "sin cobertura",
            "si manana te pasa algo",
            "si mañana te pasa algo",
            "imprevisto",
            "fallecimiento",
            "incapacidad",
            "enfermedad grave",
            "si manana",
            "si mañana",
            "te pasa algo",
            "desprotegida",
            "desprotegido",
            "quedarse sin",
            "problema",
            "riesgo",
            "si faltas",
            "si no estas",
        ),
    ),
    "revelation": (
        30.0,
        None,
        (
            "esto mucha gente no lo sabe",
            "poca gente sabe",
            "lo importante aqui es",
            "lo importante aquí es",
            "diferencia clave",
            "hay una diferencia clave",
            "letra pequena",
            "letra pequeña",
            "la realidad es que",
            "mucha gente no",
            "lo que muchos no saben",
            "no suele",
            "no siempre",
            "en realidad",
            "esto cambia",
        ),
    ),
    "coverage_explanation": (
        28.0,
        "explain_coverage",
        (
            "que cubre",
            "qué cubre",
            "que no cubre",
            "qué no cubre",
            "cuando aplica",
            "cuándo aplica",
            "como se usa",
            "cómo se usa",
            "por ejemplo",
            "ejemplo cotidiano",
            "cobertura",
            "poliza",
            "póliza",
            "carencia",
            "exclusion",
            "exclusión",
            "seguro de vida",
            "seguros de vida",
            "hipoteca",
            "capital",
            "cubrir",
            "incapacidad",
            "invalidez",
            "fallecimiento",
            "prima",
        ),
    ),
    "emotional_protection": (
        33.0,
        "emotional_reassurance",
        (
            "tranquilidad para tu familia",
            "calma para ti y los tuyos",
            "para ti y los tuyos",
            "evitar problemas futuros",
            "estar acompañado",
            "estar acompanado",
            "proteger a tu familia",
            "proteccion familiar",
            "protección familiar",
            "proteger",
            "proteccion",
            "miedo",
            "tranquilidad",
            "familia",
            "hijos",
            "pareja",
            "responsabilidad",
            "dependen de ti",
            "personas que dependen",
            "estructura",
            "sosteniendo",
            "conviene proteger",
            "no estas pensando solo en ti",
            "organizacion",
            "los tuyos",
        ),
    ),
    "actionable_advice": (
        29.0,
        "documents_admin",
        (
            "revisa esto antes de contratar",
            "antes de contratar",
            "pregunta siempre",
            "comprueba que",
            "hazlo antes de",
            "revisa la poliza",
            "revisa la póliza",
            "lee las condiciones",
            "revisa",
            "comprueba",
            "mira",
            "ten en cuenta",
            "pregunta",
            "asegurate",
            "conviene",
            "organizacion",
        ),
    ),
    "everyday_example": (
        27.0,
        "contextual_example",
        (
            "por ejemplo",
            "ejemplo cotidiano",
            "en la vida real",
            "en tu dia a dia",
            "en tu día a día",
            "cuando pasa en casa",
            "caso real",
            "situacion real",
            "situación real",
            "un ejemplo",
            "si te pasa esto",
        ),
    ),
    "money_saving": (
        29.0,
        "documents_admin",
        (
            "ahorro",
            "ahorrar",
            "ahorras",
            "coste",
            "coste menor",
            "precio",
            "coste total",
            "descuento",
            "más rentable",
            "mas rentable",
            "gastar menos",
        ),
    ),
    "legal_admin_tramite": (
        27.0,
        "documents_admin",
        (
            "tramite",
            "trámite",
            "papeles",
            "documentos",
            "documentacion",
            "documentación",
            "requisito",
            "administracion",
            "administración",
            "gestión",
            "gestion",
            "revisar la documentación",
            "presentar",
        ),
    ),
    "soft_commercial_close": (
        22.0,
        None,
        (
            "te ayudamos",
            "te orientamos",
            "consulta con calma",
            "consulta sin compromiso",
            "si quieres",
            "cuando quieras",
            "podemos revisar",
            "revisamos tu caso",
            "te acompañamos",
            "te asesoramos",
        ),
    ),
    "sensitive_decesos": (
        36.0,
        "emotional_reassurance",
        (
            "decesos",
            "funeral",
            "fallecimiento",
            "muerte",
            "sepelio",
            "velatorio",
            "luto",
            "entierro",
            "servicio funerario",
        ),
    ),
    # v2.0 — new editorial types
    "objection_response": (
        31.0,
        "explain_coverage",
        (
            "entiendo tu preocupacion",
            "es normal pensar eso",
            "mucha gente piensa igual",
            "te explico por que",
            "dejame explicarte",
            "la clave esta en",
            "la clave está en",
            "lo que pasa es que",
            "en realidad funciona asi",
            "en realidad funciona así",
            "no es exactamente asi",
            "no es exactamente así",
            "vamos a verlo",
            "ponte en esta situacion",
            "ponte en esta situación",
            "imagina que",
            "piensa en esto",
            "te pongo un ejemplo",
            "respuesta corta",
            "la respuesta es",
        ),
    ),
    "administrative_clarity": (
        26.0,
        "documents_admin",
        (
            "documentacion",
            "documentación",
            "papeles",
            "tramite",
            "trámite",
            "burocracia",
            "formulario",
            "plazo",
            "fecha limite",
            "fecha límite",
            "requisito",
            "condiciones generales",
            "letra pequena",
            "letra pequeña",
            "paso a paso",
            "procedimiento",
            "proceso",
            "como funciona",
            "cómo funciona",
            "pasos a seguir",
            "tienes que presentar",
            "necesitas tener",
            "es necesario que",
            "obligatorio",
        ),
    ),
}

_TYPE_PRIORITY = {
    "risk_warning": 80,
    "myth_debunk": 70,
    "client_objection": 60,
    "sensitive_decesos": 58,
    "coverage_explanation": 57,
    "objection_response": 55,
    "actionable_advice": 50,
    "emotional_protection": 40,
    "money_saving": 38,
    "everyday_example": 35,
    "legal_admin_tramite": 33,
    "soft_commercial_close": 28,
    "revelation": 20,
    "administrative_clarity": 15,
    "generic": 0,
}

_LOW_SIGNAL_COVERAGE_PATTERNS = {
    "seguro de vida",
    "seguros de vida",
}

_COMMERCIAL_TERMS = (
    "seguro",
    "seguros",
    "poliza",
    "póliza",
    "cobertura",
    "familia",
    "salud",
    "vida",
    "decesos",
    "viaje",
    "viajes",
    "asesor",
    "asesoria",
    "asesoría",
    "prima",
    "capital",
    "hipoteca",
    "proteccion",
    "protección",
)

_INSURANCE_ANCHOR_TERMS = (
    "seguro",
    "seguros",
    "poliza",
    "póliza",
    "cobertura",
    "cubre",
    "cubrir",
    "decesos",
    "salud",
    "vida",
    "familia",
    "hipoteca",
    "prima",
    "capital",
    "proteccion",
    "protección",
    "riesgo",
    "mito",
    "objecion",
    "objeción",
    "problema",
    "imprevisto",
    "tranquilidad",
    "extranjería",
    "extranjeria",
)

_COMMERCIAL_INCREASE_TERMS = (
    "objecion",
    "objeción",
    "mito",
    "falso",
    "riesgo",
    "peligro",
    "cuidado",
    "aviso",
    "advertencia",
    "consejo",
    "recomendacion",
    "recomendación",
    "cobertura",
    "cubre",
    "indemnizacion",
    "indemnización",
    "exclusion",
    "exclusión",
    "condiciones",
    "letra pequeña",
    "letra pequena",
    "prima",
    "precio",
    "coste",
    "ahorro",
    "descuento",
    "comparar",
    "diferencias",
    "elegir",
    "contratar",
    "proteccion",
    "protección",
    "tranquilidad",
    "seguridad",
    "planificar",
    "futuro",
    "familia",
    "salud",
)

_COMMERCIAL_DECREASE_TERMS = (
    "bueno",
    "pues",
    "entonces",
    "básicamente",
    "basicamente",
    "en plan",
    "como quien dice",
    "vamos",
    "osea",
    "o sea",
    "introducción",
    "introduccion",
    "empezar",
    "comenzar",
    "meta",
    "detrás",
    "detras",
    "bambalinas",
    "sin mas",
    "sin más",
    "para nada",
)

_GENERIC_PATTERNS = (
    "esto es muy importante",
    "muy importante",
    "tienes que saberlo",
    "recuerda esto",
    "al final",
    "en definitiva",
    "como siempre",
)

# v2.0 — penalty patterns for mediocre segments
_GENERIC_INTRO_PATTERNS = (
    "hola soy",
    "hola, soy",
    "buenas soy",
    "muy buenas soy",
    "que tal",
    "qué tal",
    "bienvenido",
    "bienvenida",
    "os presento",
    "les presento",
    "hoy os voy a hablar",
    "hoy les voy a hablar",
    "hoy vamos a hablar",
    "en el video de hoy",
    "en este video",
    "os voy a contar",
    "les voy a contar",
)

_FILLER_HEAVY_PATTERNS = (
    "entonces",
    "o sea",
    "osea",
    "pues eso",
    "bueno pues",
    "vale pues",
    "claro entonces",
    "y tal",
    "y eso",
)

_INCOMPLETE_IDEA_PATTERNS = (
    "cuando",
    "si tu",
    "si usted",
    "pero eso",
    "y entonces",
    "entonces cuando",
    "porque si",
    "porque no",
)

_META_PRODUCTION_PATTERNS = (
    "detras de camaras",
    "detrás de cámaras",
    "grabando",
    "camara",
    "cámara",
    "microfono",
    "micrófono",
    "toma",
    "corte",
    "espera",
    "repetimos",
    "sale mal",
    "risas internas",
    "vamos otra vez",
    "otra vez",
    "fuera de camara",
    "fuera de cámara",
)

# v2.0 — first-3s hook prediction patterns
_STRONG_HOOK_OPENERS = (
    "cuidado",
    "ojo",
    "atencion",
    "importante",
    "esto cambia",
    "no sabes",
    "no sabia",
    "sabias que",
    "sabías que",
    "te has preguntado",
    "nunca te han dicho",
    "mucha gente no sabe",
    "poca gente sabe",
    "esto mucha gente",
    "la realidad",
    "diferencia clave",
    "error comun",
    "error común",
    "si esperas",
    "si manana",
    "si mañana",
    "puedes quedarte",
    "el problema",
    "la clave",
    "lo importante",
    "no es solo",
    "no solo",
    "dejame explicarte",
    "te explico",
    "imagina",
    "ponte",
    "respuesta",
)

_WEAK_HOOK_OPENERS = (
    "hola",
    "buenas",
    "bienvenido",
    "que tal",
    "qué tal",
    "os presento",
    "les presento",
    "hoy os voy",
    "hoy les voy",
    "en el video",
    "en este video",
    "os voy a contar",
    "les voy a contar",
    "vamos a ver",
    "vamos a hablar",
    "bueno pues",
    "pues eso",
    "entonces",
    "vale",
    "claro",
)

# v2.1 — H14.6: verbal hook cues typical of conversational VPI insurance content
# (risk/crisis framing, objections, myth debunking, family protection tied to a
# consequence). Used only to recalibrate hookability for editorial_type
# "emotional_protection", which is excluded from the editorial_hook bonus above.
_VPI_INSURANCE_VERBAL_HOOK_CUES = (
    "esto mucha gente no lo sabe",
    "mucha gente no sabe",
    "poca gente sabe",
    "ojo con",
    "no es solo",
    "no solo",
    "la mayoria piensa",
    "la mayoría piensa",
    "mucha gente piensa que",
    "la gente piensa que",
    "si te pasa",
    "si tienes",
    "no es una conversacion",
    "no es una conversación",
    "conversacion reservada",
    "conversación reservada",
    "caos economico",
    "caos económico",
    "momento dificil",
    "momento difícil",
    "momento emocionalmente dificil",
    "momento emocionalmente difícil",
    "tranquilidad para tu familia",
    "proteger a tu familia",
    "proteccion familiar",
    "protección familiar",
)


# ── Normalization helpers ───────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents.lower()).strip()


def _contains_any(text: str, patterns: Iterable[str]) -> list[str]:
    normalized_patterns = [(pattern, _normalize(pattern)) for pattern in patterns]
    matches: list[str] = []
    seen: set[str] = set()
    for pattern, normalized in normalized_patterns:
        if normalized in text and normalized not in seen:
            matches.append(pattern)
            seen.add(normalized)
    return matches


def _dedupe_patterns(patterns: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        normalized = _normalize(pattern)
        if normalized in seen:
            continue
        deduped.append(pattern)
        seen.add(normalized)
    return deduped


def _word_count(text: str) -> int:
    return len([w for w in _normalize(text).split() if w])


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


def _summarize_selection_reason(
    *,
    editorial_type: str,
    hookability_score: float,
    commercial_usefulness_score: float,
    standalone_score: float,
    weak_segment_penalties: list[str],
) -> str:
    reasons: list[str] = []
    if editorial_type and editorial_type != "generic":
        reasons.append(editorial_type)
    if hookability_score >= 70.0:
        reasons.append("strong_hook")
    if standalone_score >= 70.0:
        reasons.append("standalone")
    if commercial_usefulness_score >= 70.0:
        reasons.append("commercial")
    if weak_segment_penalties:
        reasons.append("penalty_managed")
    return "+".join(dict.fromkeys(reasons)) or "generic_segment"


def _compute_hookability_score(
    text: str,
    editorial_type: str,
    matched_patterns: list[str],
    penalties: dict[str, Any],
    hook_pred: dict[str, Any],
) -> dict[str, Any]:
    normalized = _normalize(text)
    first_15 = " ".join(normalized.split()[:15])
    score = float(hook_pred.get("predicted_first3_strength") or 0.0) * 55.0
    reason_parts: list[str] = [str(hook_pred.get("reason") or "hook_prediction")]
    if _contains_any(first_15, _STRONG_HOOK_OPENERS):
        score += 15.0
        reason_parts.append("strong_opener")
    if editorial_type in {"risk_warning", "myth_debunk", "revelation", "client_objection", "coverage_explanation", "sensitive_decesos"}:
        score += 10.0
        reason_parts.append("editorial_hook")
    if any(term in normalized for term in ("cuidado", "ojo", "mito", "falso", "no sabes", "sabias que", "sabías que", "mucha gente no sabe", "poca gente sabe", "esto mucha gente", "la realidad")):
        score += 8.0
        reason_parts.append("attention_hook")
    if matched_patterns:
        score += min(8.0, len(matched_patterns) * 1.5)
    if "generic_intro" in penalties.get("penalty_types", []):
        score -= 18.0
        reason_parts.append("generic_intro")
    if "incomplete_idea" in penalties.get("penalty_types", []):
        score -= 12.0
        reason_parts.append("incomplete_idea")
    if "filler_heavy" in penalties.get("penalty_types", []):
        score -= 8.0
        reason_parts.append("filler_heavy")
    weak_opening = bool(_contains_any(normalized[:40], ("hola", "buenas", "que tal", "qué tal", "hoy vamos", "en este video")))
    if weak_opening:
        score -= 12.0
        reason_parts.append("weak_opening")

    # v2.1 — VPI insurance verbal hook recalibration (H14.6)
    # editorial_type "emotional_protection" is the campaign's primary intent for
    # emocional_proteccion content but is excluded from the +10 editorial_hook
    # bonus above. Recognize verbal hooks typical of conversational insurance
    # content (risk/crisis framing, objections, myth debunking, family
    # protection tied to consequence) and apply a capped recalibration bonus —
    # but never for generic intros or behind-the-scenes segments.
    vpi_verbal_cues_matched = _contains_any(normalized, _VPI_INSURANCE_VERBAL_HOOK_CUES)
    if vpi_verbal_cues_matched:
        is_generic_or_bts = (
            "generic_intro" in penalties.get("penalty_types", [])
            or "meta_production_or_bts" in penalties.get("penalty_types", [])
            or weak_opening
        )
        if editorial_type == "emotional_protection" and not is_generic_or_bts:
            pre_bonus_score = score
            verbal_cue_bonus = min(18.0, 10.0 + min(8.0, (len(vpi_verbal_cues_matched) - 1) * 4.0))
            score += verbal_cue_bonus
            reason_parts.append("vpi_insurance_verbal_hook")
            logger.info(
                "VPI_HOOKABILITY_VERBAL_INSURANCE_CUES_APPLIED cues=%s bonus=%.1f",
                vpi_verbal_cues_matched, verbal_cue_bonus,
            )
            logger.info(
                "VPI_HOOKABILITY_SCORE_RECALIBRATED previous=%.2f recalibrated=%.2f bonus=%.1f",
                round(_clamp_score(pre_bonus_score), 2), round(_clamp_score(score), 2), verbal_cue_bonus,
            )
        else:
            logger.info(
                "VPI_HOOKABILITY_VERBAL_CUES_REJECTED_GENERIC cues=%s editorial_type=%s generic_or_bts=%s",
                vpi_verbal_cues_matched, editorial_type, is_generic_or_bts,
            )

    return {
        "hookability_score": round(_clamp_score(score), 2),
        "hookability_reason": "+".join(dict.fromkeys(reason_parts)) or "hookability",
    }


def _compute_commercial_usefulness_score(
    text: str,
    editorial_type: str,
    matched_patterns: list[str],
) -> dict[str, Any]:
    normalized = _normalize(text)
    score = 14.0
    reason_parts: list[str] = []
    commercial_hits = _contains_any(normalized, _COMMERCIAL_INCREASE_TERMS)
    anchor_hits = _contains_any(normalized, _INSURANCE_ANCHOR_TERMS)
    if commercial_hits:
        score += min(30.0, len(commercial_hits) * 3.0)
        reason_parts.append("commercial_terms")
    if anchor_hits:
        score += min(18.0, len(anchor_hits) * 2.0)
        reason_parts.append("insurance_anchor")
    if editorial_type in {"client_objection", "risk_warning", "myth_debunk", "coverage_explanation", "actionable_advice", "money_saving", "legal_admin_tramite", "soft_commercial_close", "sensitive_decesos"}:
        score += 22.0
        reason_parts.append("commercial_editorial_type")
    elif editorial_type in {"emotional_protection", "revelation", "everyday_example"}:
        score += 10.0
        reason_parts.append("commercial_supportive_type")
    if len(matched_patterns) >= 2:
        score += 8.0
    if any(term in normalized for term in _META_PRODUCTION_PATTERNS):
        score -= 25.0
        reason_parts.append("meta_production")
    if _contains_any(normalized, _GENERIC_INTRO_PATTERNS):
        score -= 12.0
        reason_parts.append("generic_intro")
    if "no_payoff" in _detect_penalties(text).get("penalty_types", []):
        score -= 10.0
        reason_parts.append("no_payoff")
    return {
        "commercial_usefulness_score": round(_clamp_score(score), 2),
        "commercial_usefulness_reason": "+".join(dict.fromkeys(reason_parts)) or "commercial_usefulness",
    }


def _compute_standalone_score(
    text: str,
    *,
    clarity: float,
    hookability_score: float,
    penalties: dict[str, Any],
) -> dict[str, Any]:
    normalized = _normalize(text)
    words = normalized.split()
    score = clarity * 48.0 + hookability_score * 0.20
    reason_parts: list[str] = []
    if len(words) >= 12:
        score += 14.0
        reason_parts.append("complete_span")
    if len(words) >= 20:
        score += 8.0
    if _contains_any(normalized, ("como dije", "como te dije", "como te decía", "como te decia", "lo de antes", "esto", "eso", "aquello")):
        score -= 15.0
        reason_parts.append("context_dependent")
    if _contains_any(normalized, ("antes de seguir", "como vimos antes", "ya vimos", "ya dije", "ya te dije")):
        score -= 12.0
        reason_parts.append("requires_previous_context")
    if _contains_any(normalized, _GENERIC_INTRO_PATTERNS):
        score -= 10.0
        reason_parts.append("generic_intro")
    if "incomplete_idea" in penalties.get("penalty_types", []):
        score -= 20.0
        reason_parts.append("incomplete_idea")
    if "filler_heavy" in penalties.get("penalty_types", []):
        score -= 8.0
        reason_parts.append("filler_heavy")
    if "meta_production_or_bts" in penalties.get("penalty_types", []):
        score -= 18.0
        reason_parts.append("bts_context")
    if not _contains_any(normalized, ("porque", "cuidado", "riesgo", "mito", "falso", "consejo", "ejemplo", "revisa", "cobertura", "protege", "ahorro", "ahorrar", "tramite", "trámite")):
        score -= 10.0
        reason_parts.append("no_clear_value")
    return {
        "standalone_score": round(_clamp_score(score), 2),
        "standalone_reason": "+".join(dict.fromkeys(reason_parts)) or "standalone",
    }


def _compute_weak_segment_penalties(
    text: str,
    *,
    editorial_type: str,
    penalties: dict[str, Any],
    hookability_score: float,
    standalone_score: float,
    commercial_usefulness_score: float,
) -> dict[str, Any]:
    normalized = _normalize(text)
    weak_penalties: list[str] = list(dict.fromkeys(penalties.get("penalty_types", [])))
    if hookability_score < 45.0:
        weak_penalties.append("weak_hookability")
    if standalone_score < 45.0:
        weak_penalties.append("weak_standalone")
    if commercial_usefulness_score < 40.0:
        weak_penalties.append("weak_commercial_usefulness")
    if editorial_type == "generic":
        weak_penalties.append("generic_segment")
    if _contains_any(normalized, _GENERIC_INTRO_PATTERNS):
        weak_penalties.append("generic_intro")
    weak_penalties = list(dict.fromkeys(weak_penalties))
    weak_reason = ", ".join(weak_penalties[:6]) if weak_penalties else "none"
    return {
        "weak_segment_penalties": weak_penalties,
        "weak_segment_reason": weak_reason,
    }


class VPIEditorialScorer:
    def score(self, text: str) -> VPIEditorialScore:
        return score_vpi_segment(text)

    def score_segment(self, text: str) -> VPIEditorialScore:
        return score_vpi_segment(text)


def score_vpi_segment(text: str) -> VPIEditorialScore:
    """Score a transcript segment for insurance-first editorial selection."""
    normalized = _normalize(text)
    matched_patterns: list[str] = []
    editorial_type = "generic"
    suggested_broll_cue_type: str | None = None
    best_score = 0.0
    matched_categories: list[str] = []

    for key, (base_score, broll_type, patterns) in _PATTERNS.items():
        matches = _contains_any(normalized, patterns)
        if not matches:
            continue
        matched_categories.append(key)
        score = base_score + len(matches) * 3.0
        if score > best_score:
            best_score = score
            editorial_type = key
            suggested_broll_cue_type = broll_type
            matched_patterns = matches

    if not matched_patterns:
        generic_matches = _contains_any(normalized, _GENERIC_PATTERNS)
        if generic_matches:
            matched_patterns = generic_matches
            best_score = 12.0

    penalties = _detect_penalties(text)
    hook_pred = _predict_first3_strength(text)
    clarity = _estimate_clarity(text)
    novelty = _estimate_novelty(text)
    hookability = _compute_hookability_score(text, editorial_type, matched_patterns, penalties, hook_pred)
    commercial_usefulness = _compute_commercial_usefulness_score(text, editorial_type, matched_patterns)
    standalone = _compute_standalone_score(
        text,
        clarity=clarity,
        hookability_score=hookability["hookability_score"],
        penalties=penalties,
    )
    weak_segment = _compute_weak_segment_penalties(
        text,
        editorial_type=editorial_type,
        penalties=penalties,
        hookability_score=hookability["hookability_score"],
        standalone_score=standalone["standalone_score"],
        commercial_usefulness_score=commercial_usefulness["commercial_usefulness_score"],
    )
    generic_penalty = penalties["total_penalty"] + (10.0 if editorial_type == "generic" else 0.0)
    vpi_score = max(
        0.0,
        min(
            100.0,
            best_score
            + hook_pred["predicted_first3_strength"] * 16.0
            + clarity * 12.0
            + novelty * 10.0
            - generic_penalty,
        ),
    )
    reason = editorial_type if editorial_type != "generic" else "generic_insurance_segment"
    selection_confidence = _clamp_score(
        (vpi_score * 0.32)
        + (hookability["hookability_score"] * 0.23)
        + (commercial_usefulness["commercial_usefulness_score"] * 0.22)
        + (standalone["standalone_score"] * 0.23)
        - (len(weak_segment["weak_segment_penalties"]) * 1.25),
    ) / 100.0
    selected_for_reason = _summarize_selection_reason(
        editorial_type=editorial_type,
        hookability_score=hookability["hookability_score"],
        commercial_usefulness_score=commercial_usefulness["commercial_usefulness_score"],
        standalone_score=standalone["standalone_score"],
        weak_segment_penalties=weak_segment["weak_segment_penalties"],
    )
    rejected_for_reason = ""
    if vpi_score < 35.0:
        rejected_for_reason = "low_vpi_score"
    elif weak_segment["weak_segment_penalties"]:
        rejected_for_reason = weak_segment["weak_segment_reason"]
    return VPIEditorialScore(
        vpi_score=round(vpi_score, 2),
        matched_patterns=matched_patterns,
        editorial_type=editorial_type,
        reason=reason,
        suggested_broll_cue_type=suggested_broll_cue_type,
        generic_penalty=round(generic_penalty, 2),
        editorial_categories=matched_categories or [editorial_type],
        hookability_score=hookability["hookability_score"],
        hookability_reason=hookability["hookability_reason"],
        commercial_usefulness_score=commercial_usefulness["commercial_usefulness_score"],
        commercial_usefulness_reason=commercial_usefulness["commercial_usefulness_reason"],
        standalone_score=standalone["standalone_score"],
        standalone_reason=standalone["standalone_reason"],
        weak_segment_penalties=weak_segment["weak_segment_penalties"],
        weak_segment_reason=weak_segment["weak_segment_reason"],
        segment_selection_confidence=round(selection_confidence, 4),
        selected_for_reason=selected_for_reason,
        rejected_for_reason=rejected_for_reason,
    )


# ── v2.0 — Penalty detection ────────────────────────────────────────────────────


def _detect_penalties(text: str) -> dict[str, Any]:
    """Detect segment penalties and return structured penalty info.

    Returns:
        penalty_types: list of penalty type strings
        total_penalty: float penalty sum (0-100 scale)
        filler_ratio: float 0-1 ratio of filler tokens
        disfluency_penalty: float penalty from fillers/disfluency
    """
    normalized = _normalize(text)
    tokens = normalized.split()
    total_tokens = len(tokens)
    penalty_types: list[str] = []
    total_penalty = 0.0

    # 1) Generic intro penalty
    intro_matches = _contains_any(normalized, _GENERIC_INTRO_PATTERNS)
    if intro_matches:
        penalty_types.append("generic_intro")
        total_penalty += 25.0
        logger.info("SEGMENT_PENALTY type=generic_intro patterns=%s", intro_matches)

    # 2) Filler-heavy penalty
    filler_count = sum(1 for t in tokens if t in _FILLER_HEAVY_PATTERNS)
    filler_ratio = filler_count / max(total_tokens, 1)
    if filler_ratio > 0.15:
        penalty_types.append("filler_heavy")
        total_penalty += 15.0 * min(2.0, filler_ratio * 5.0)
        logger.info(
            "SEGMENT_PENALTY type=filler_heavy filler_ratio=%.3f filler_count=%d",
            filler_ratio, filler_count,
        )

    # 3) Incomplete idea penalty (segment ends with hanging connector)
    if total_tokens >= 2:
        last_two = " ".join(tokens[-2:])
        last_token = tokens[-1]
        if _contains_any(last_two, _INCOMPLETE_IDEA_PATTERNS) or last_token in {
            "cuando", "pero", "porque", "entonces", "si", "que",
        }:
            penalty_types.append("incomplete_idea")
            total_penalty += 20.0
            logger.info("SEGMENT_PENALTY type=incomplete_idea last_tokens=%s", last_two)

    # 4) Too short / too long penalty
    if total_tokens < 8:
        penalty_types.append("too_short")
        total_penalty += 12.0
        logger.info("SEGMENT_PENALTY type=too_short word_count=%d", total_tokens)
    elif total_tokens > 80:
        penalty_types.append("too_long")
        total_penalty += 8.0
        logger.info("SEGMENT_PENALTY type=too_long word_count=%d", total_tokens)

    # 5) No payoff penalty (pure setup, no actionable/risk/revelation content)
    has_payoff = any(
        term in normalized
        for term in (
            "porque", "asi que", "entonces", "la clave", "importante",
            "cuidado", "riesgo", "proteger", "consejo", "realidad",
            "cambia", "diferencia", "solucion", "respuesta",
        )
    )
    if not has_payoff and total_tokens >= 12:
        penalty_types.append("no_payoff")
        total_penalty += 10.0
        logger.info("SEGMENT_PENALTY type=no_payoff text_preview=%s", normalized[:60])

    # 6) Meta / behind-the-scenes penalty
    meta_matches = _contains_any(normalized, _META_PRODUCTION_PATTERNS)
    if meta_matches:
        penalty_types.append("meta_production_or_bts")
        total_penalty += 28.0
        if total_tokens < 20:
            total_penalty += 6.0
        logger.info("SEGMENT_PENALTY type=meta_production_or_bts patterns=%s", meta_matches)

    disfluency_penalty = min(30.0, total_penalty)
    return {
        "penalty_types": penalty_types,
        "total_penalty": round(total_penalty, 2),
        "filler_ratio": round(filler_ratio, 4),
        "disfluency_penalty": round(disfluency_penalty, 2),
    }


# ── v2.0 — First-3s hook prediction ─────────────────────────────────────────────


def _predict_first3_strength(text: str) -> dict[str, Any]:
    """Predict whether the segment can produce a strong first 3 seconds.

    Returns:
        predicted_first3_strength: float 0-1
        trim_to_hook_candidate: bool — whether trimming could improve hook
        hook_start_offset: float — seconds to trim from start (0.0 if none)
        reason: str
    """
    normalized = _normalize(text)
    tokens = normalized.split()
    if not tokens:
        return {
            "predicted_first3_strength": 0.0,
            "trim_to_hook_candidate": False,
            "hook_start_offset": 0.0,
            "reason": "empty_segment",
        }

    # Check first 3 tokens for strong hook openers
    first_3_tokens = " ".join(tokens[:3])
    first_5_tokens = " ".join(tokens[:5])

    strong_hit = _contains_any(first_5_tokens, _STRONG_HOOK_OPENERS)
    weak_hit = _contains_any(first_3_tokens, _WEAK_HOOK_OPENERS)

    if strong_hit:
        strength = 0.85
        reason = "strong_hook_opener_detected"
        trim = False
        offset = 0.0
    elif weak_hit:
        # Check if trimming first 1-2 tokens helps
        trimmed = " ".join(tokens[2:]) if len(tokens) > 2 else ""
        trimmed_strong = _contains_any(trimmed, _STRONG_HOOK_OPENERS) if trimmed else False
        if trimmed_strong:
            strength = 0.70
            reason = "weak_opener_but_strong_after_trim"
            trim = True
            offset = 1.5  # approximate seconds for 2 tokens
        else:
            strength = 0.35
            reason = "weak_hook_opener_no_strong_followup"
            trim = True
            offset = 1.0
    else:
        # Neutral start — check if first sentence has editorial value
        first_sentence = normalized.split(".")[0] if "." in normalized else first_5_tokens
        has_editorial_value = any(
            term in first_sentence
            for term in (
                "seguro", "riesgo", "proteger", "familia", "cobertura",
                "importante", "cuidado", "consejo", "realidad", "clave",
            )
        )
        if has_editorial_value:
            strength = 0.65
            reason = "neutral_start_with_editorial_value"
            trim = False
            offset = 0.0
        else:
            strength = 0.50
            reason = "neutral_start_low_editorial_signal"
            trim = False
            offset = 0.0

    logger.info(
        "SEGMENT_HOOK_PREDICTION strength=%.2f trim=%s offset=%.1f reason=%s",
        strength, trim, offset, reason,
    )
    return {
        "predicted_first3_strength": round(strength, 2),
        "trim_to_hook_candidate": trim,
        "hook_start_offset": offset,
        "reason": reason,
    }


# ── v2.0 — Clarity / novelty heuristics ─────────────────────────────────────────


def _estimate_clarity(text: str) -> float:
    """Estimate clarity score 0-1 based on sentence structure and domain terms."""
    normalized = _normalize(text)
    tokens = normalized.split()
    if not tokens:
        return 0.0

    # Penalize very long sentences without punctuation
    sentences = re.split(r"[.!?]+", normalized)
    long_sentences = sum(1 for s in sentences if len(s.split()) > 25)
    clarity = 1.0 - (long_sentences * 0.15)

    # Reward domain-specific terms that add precision
    domain_terms = _contains_any(normalized, _COMMERCIAL_TERMS)
    clarity += len(domain_terms) * 0.05

    # Penalize excessive filler
    filler_count = sum(1 for t in tokens if t in _FILLER_HEAVY_PATTERNS)
    clarity -= filler_count * 0.08

    return round(max(0.0, min(1.0, clarity)), 2)


def _estimate_novelty(text: str, seen_themes: set[str] | None = None) -> float:
    """Estimate novelty score 0-1 based on unique angle and uncommon terms."""
    normalized = _normalize(text)
    tokens = set(normalized.split())
    if not tokens:
        return 0.0

    # Reward uncommon insurance terms that indicate depth
    uncommon_terms = {
        "carencia", "exclusion", "exclusión", "franquicia", "deducible",
        "plusvalia", "plusvalía", "invalidez", "sobreprima", "rescate",
        "siniestro", "indemnizacion", "indemnización", "perito",
        "valoracion", "valoración", "depreciacion", "depreciación",
    }
    uncommon_hits = tokens & uncommon_terms
    novelty = 0.5 + len(uncommon_hits) * 0.1

    # Penalize if theme already seen (for diversity tracking)
    if seen_themes:
        theme_key = _extract_theme_key(normalized)
        if theme_key in seen_themes:
            novelty *= 0.5

    return round(max(0.0, min(1.0, novelty)), 2)


def _extract_theme_key(text: str) -> str:
    """Extract a duplicate_theme_key from text for diversity tracking."""
    normalized = _normalize(text)
    if any(t in normalized for t in _META_PRODUCTION_PATTERNS):
        return "meta_production_or_bts"
    # Map to broad theme categories
    if any(t in normalized for t in ("carencia", "exclusion", "exclusión", "franquicia", "deducible")):
        return "policy_limits"
    if any(t in normalized for t in ("fallecimiento", "muerte", "incapacidad", "invalidez", "enfermedad")):
        return "risk_events"
    if any(t in normalized for t in ("hipoteca", "capital", "ahorro", "inversion", "inversión")):
        return "financial_planning"
    if any(t in normalized for t in ("familia", "hijos", "pareja", "dependen", "tuyos")):
        return "family_protection"
    if any(t in normalized for t in ("autonomo", "autónomo", "autonomos", "autónomos", "empresa")):
        return "self_employed"
    if any(t in normalized for t in ("decesos", "ausencia", "funeraria")):
        return "funeral_expenses"
    if any(t in normalized for t in ("viaje", "viajes", "viajero")):
        return "travel"
    if any(t in normalized for t in ("salud", "medico", "médico", "hospital", "pruebas")):
        return "health"
    if any(t in normalized for t in ("joven", "jovenes", "jóvenes", "edad")):
        return "age_demographic"
    if any(t in normalized for t in ("caro", "precio", "coste", "cuesta", "barato")):
        return "cost_objection"
    return "general_insurance"


# ── v2.0 — Diversity-aware selection ────────────────────────────────────────────


_DIVERSITY_STOPWORDS = {
    "de", "la", "el", "los", "las", "y", "o", "u", "a", "en", "con", "sin",
    "para", "por", "del", "al", "que", "se", "un", "una", "unos", "unas",
    "esto", "esta", "este", "estos", "estas", "eso", "esa", "ese", "esos",
    "esas", "como", "cuando", "porque", "si", "no", "te", "tu", "tuya", "tuyo",
    "mi", "mis", "su", "sus", "lo", "le", "les", "ya", "muy", "mas", "más",
    "hay", "ser", "estar", "hacer", "tener", "poder", "debe", "deben",
}

_DIVERSITY_PRIMARY_CATEGORY_PRIORITY = (
    "risk_warning",
    "coverage_explanation",
    "client_objection",
    "myth_debunk",
    "revelation",
    "actionable_advice",
    "everyday_example",
    "emotional_protection",
    "money_saving",
    "legal_admin_tramite",
    "soft_commercial_close",
    "sensitive_decesos",
)

_DIVERSITY_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("risk_warning", ("risk_warning",)),
    ("coverage_explanation", ("coverage_explanation",)),
    ("objection_debunk_revelation", ("client_objection", "myth_debunk", "revelation")),
    ("actionable_everyday", ("actionable_advice", "everyday_example")),
    ("emotional_money_legal", ("emotional_protection", "money_saving", "legal_admin_tramite")),
    ("soft_commercial_close", ("soft_commercial_close",)),
    ("sensitive_decesos", ("sensitive_decesos",)),
)

_CAMPAIGN_INTENT_RULES: dict[str, dict[str, Any]] = {
    "salud": {
        "preferred_categories": ["coverage_explanation", "client_objection", "actionable_advice", "money_saving"],
        "suppressed_categories": ["sensitive_decesos"],
        "preferred_keywords": ["salud", "médico", "medico", "hospital", "cuadro médico", "cuadro medico", "copago", "sin copago", "especialistas", "urgencias"],
    },
    "vida": {
        "preferred_categories": ["emotional_protection", "coverage_explanation", "client_objection", "risk_warning"],
        "suppressed_categories": ["sensitive_decesos"],
        "preferred_keywords": ["vida", "fallecimiento", "invalidez", "incapacidad", "hipoteca", "capital", "beneficiario", "accidente"],
    },
    "decesos": {
        "preferred_categories": ["sensitive_decesos", "emotional_protection", "actionable_advice", "coverage_explanation"],
        "suppressed_categories": ["risk_warning"],
        "preferred_keywords": ["decesos", "funeral", "sepelio", "entierro", "tanatorio", "asistencia familiar"],
    },
    "extranjeria": {
        "preferred_categories": ["legal_admin_tramite", "coverage_explanation", "risk_warning", "actionable_advice"],
        "suppressed_categories": ["sensitive_decesos"],
        "preferred_keywords": ["extranjería", "extranjeria", "visado", "residencia", "nie", "tie", "estudiante", "trámite", "tramite", "consulado", "sin carencias"],
    },
    "viaje": {
        "preferred_categories": ["coverage_explanation", "risk_warning", "actionable_advice", "money_saving"],
        "suppressed_categories": [],
        "preferred_keywords": ["viaje", "viajar", "extranjero", "asistencia en viaje", "repatriación", "repatriacion", "equipaje", "estancia"],
    },
    "ahorro": {
        "preferred_categories": ["money_saving", "coverage_explanation", "actionable_advice", "client_objection"],
        "suppressed_categories": [],
        "preferred_keywords": ["ahorro", "descuento", "prima", "precio", "pagar menos", "oferta"],
    },
    "objeciones": {
        "preferred_categories": ["client_objection", "coverage_explanation", "actionable_advice", "risk_warning"],
        "suppressed_categories": [],
        "preferred_keywords": ["es caro", "no lo necesito", "ya tengo", "me lo pensaré", "me lo pensare", "no cubre"],
    },
    "mitos": {
        "preferred_categories": ["myth_debunk", "revelation", "coverage_explanation", "client_objection"],
        "suppressed_categories": [],
        "preferred_keywords": ["falso", "mito", "error", "mucha gente cree", "no es verdad", "ojo con esto"],
    },
    "riesgo_advertencias": {
        "preferred_categories": ["risk_warning", "revelation", "actionable_advice", "coverage_explanation"],
        "suppressed_categories": [],
        "preferred_keywords": ["cuidado", "error", "problema", "riesgo", "no hagas", "antes de contratar"],
    },
    "emocional_proteccion": {
        "preferred_categories": ["emotional_protection", "coverage_explanation", "client_objection", "money_saving"],
        "suppressed_categories": ["sensitive_decesos"],
        "preferred_keywords": ["familia", "tranquilidad", "proteger", "tuyos", "futuro", "calma"],
    },
    "cobertura": {
        "preferred_categories": ["coverage_explanation", "client_objection", "actionable_advice", "risk_warning"],
        "suppressed_categories": [],
        "preferred_keywords": ["cobertura", "póliza", "poliza", "garantía", "garantia", "exclusión", "exclusion", "carencia", "copago"],
    },
    "tramite_documentacion": {
        "preferred_categories": ["legal_admin_tramite", "coverage_explanation", "risk_warning", "actionable_advice"],
        "suppressed_categories": [],
        "preferred_keywords": ["documento", "certificado", "requisito", "administración", "administracion", "presentación", "presentacion", "trámite", "tramite"],
    },
}


def _normalize_campaign_token(value: Any) -> str:
    text = _normalize_text(str(value or "")).replace("_", " ").strip()
    if not text:
        return ""
    if text in {"risk warnings", "risk warning", "risk advertencias", "risk advertencia", "risk"}:
        return "riesgo_advertencias"
    if text in {"extranjeria", "extranjería"}:
        return "extranjeria"
    if text in {"health", "salud"}:
        return "salud"
    if text in {"life", "vida"}:
        return "vida"
    if text in {"deceases", "decesos"}:
        return "decesos"
    if text in {"coverage", "cobertura"}:
        return "cobertura"
    if text in {"trámite documentación", "tramite documentacion", "documentacion", "documentación"}:
        return "tramite_documentacion"
    if text in {"general", "general vpi", "general_vpi"}:
        return "general_vpi"
    return text.replace(" ", "_")


def _score_campaign_alignment_text(text: str, preferred_keywords: list[str]) -> tuple[float, list[str]]:
    normalized = _normalize_text(text)
    matched = [kw for kw in preferred_keywords if _normalize_text(kw) in normalized]
    if not preferred_keywords:
        return 0.0, []
    score = min(1.0, len(matched) / max(1, min(len(preferred_keywords), 6)))
    return score, matched


def resolve_vpi_campaign_intent(
    task_metadata: dict[str, Any] | None = None,
    user_options: dict[str, Any] | None = None,
    prompt: str | None = None,
    config: dict[str, Any] | None = None,
    transcript_text: str | None = None,
    candidate_categories: list[str] | None = None,
    product_hints: list[str] | None = None,
) -> dict[str, Any]:
    task_metadata = _as_dict(task_metadata)
    user_options = _as_dict(user_options)
    config = _as_dict(config)
    transcript_text = str(transcript_text or "")
    candidate_categories = [str(item or "") for item in _safe_list(candidate_categories)]
    product_hints = [str(item or "") for item in _safe_list(product_hints)]

    source = "default_general"
    intent = "general_vpi"
    reason = "default_general"
    confidence = 0.0

    candidate_sources = [
        task_metadata.get("campaign_intent"),
        task_metadata.get("campaign"),
        task_metadata.get("objective"),
        task_metadata.get("goal"),
        task_metadata.get("commercial_intent"),
        user_options.get("campaign_intent"),
        user_options.get("campaign"),
        user_options.get("objective"),
        user_options.get("goal"),
        config.get("campaign_intent"),
        config.get("campaign"),
        config.get("objective"),
        prompt,
        " ".join(product_hints),
        task_metadata.get("source_title"),
        task_metadata.get("source_url"),
        task_metadata.get("caption_template"),
    ]
    for candidate in candidate_sources:
        normalized = _normalize_campaign_token(candidate)
        if normalized in {"", "general_vpi"}:
            continue
        if normalized in _CAMPAIGN_INTENT_RULES:
            intent = normalized
            source = "user_selected" if candidate in {
                task_metadata.get("campaign_intent"),
                task_metadata.get("campaign"),
                task_metadata.get("objective"),
                task_metadata.get("goal"),
                task_metadata.get("commercial_intent"),
                user_options.get("campaign_intent"),
                user_options.get("campaign"),
                user_options.get("objective"),
                user_options.get("goal"),
            } else "inferred_from_text"
            reason = f"explicit:{normalized}"
            confidence = 0.92 if source == "user_selected" else 0.72
            break
        if normalized.replace(" ", "_") in _CAMPAIGN_INTENT_RULES:
            intent = normalized.replace(" ", "_")
            source = "inferred_from_text"
            reason = f"explicit:{intent}"
            confidence = 0.72
            break

    if intent == "general_vpi":
        text_sources = [
            transcript_text,
            str(prompt or ""),
            " ".join(product_hints),
            str(task_metadata.get("source_title") or ""),
            str(task_metadata.get("source_url") or ""),
            " ".join(candidate_categories),
        ]
        combined_text = " ".join(text_sources)
        normalized_combined = _normalize_text(combined_text)
        best_matches: list[tuple[float, str, list[str]]] = []
        for campaign_name, rules in _CAMPAIGN_INTENT_RULES.items():
            score, matched = _score_campaign_alignment_text(normalized_combined, list(rules.get("preferred_keywords") or []))
            category_hits = sum(1 for cat in candidate_categories if cat in set(rules.get("preferred_categories") or []))
            category_bonus = min(0.25, category_hits * 0.08)
            total_score = min(1.0, score + category_bonus)
            best_matches.append((total_score, campaign_name, matched))
        best_matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if best_matches and best_matches[0][0] >= 0.22:
            confidence, intent, matched_terms = best_matches[0]
            source = "inferred_from_text"
            reason = f"keyword_match:{','.join(matched_terms[:5]) or 'category_signal'}"
        else:
            confidence = 0.08

    rules = _CAMPAIGN_INTENT_RULES.get(intent, {})
    preferred_categories = list(rules.get("preferred_categories") or [])
    suppressed_categories = list(rules.get("suppressed_categories") or [])
    preferred_keywords = list(rules.get("preferred_keywords") or [])
    sensitive_handling_required = bool(intent == "decesos")
    if intent == "decesos" and source == "default_general":
        source = "inferred_from_text"

    campaign_alignment_reason = reason if intent != "general_vpi" else "default_general"
    logger.info(
        "VPI_CAMPAIGN_INTENT_RESOLVED intent=%s source=%s confidence=%.3f reason=%s preferred=%s suppressed=%s",
        intent,
        source,
        confidence,
        campaign_alignment_reason,
        "|".join(preferred_categories) or "none",
        "|".join(suppressed_categories) or "none",
    )
    return {
        "campaign_intent": intent,
        "campaign_intent_confidence": round(float(confidence), 4),
        "campaign_intent_source": source,
        "campaign_intent_reason": campaign_alignment_reason,
        "preferred_categories": preferred_categories,
        "suppressed_categories": suppressed_categories,
        "preferred_keywords": preferred_keywords,
        "sensitive_handling_required": sensitive_handling_required,
    }


def _campaign_alignment_for_segment(
    segment: dict[str, Any],
    campaign_context: dict[str, Any] | None,
) -> tuple[float, float, str]:
    context = _as_dict(campaign_context)
    intent = _normalize_campaign_token(context.get("campaign_intent"))
    if not intent or intent == "general_vpi":
        return 0.0, 0.0, "general_vpi"

    rules = _CAMPAIGN_INTENT_RULES.get(intent, {})
    preferred_categories = set(str(item or "") for item in _safe_list(rules.get("preferred_categories")))
    suppressed_categories = set(str(item or "") for item in _safe_list(rules.get("suppressed_categories")))
    preferred_keywords = [str(item or "") for item in _safe_list(rules.get("preferred_keywords"))]
    category = _clip_primary_category(segment)
    text = _normalize_text(str(segment.get("text") or ""))
    alignment_score = 0.0
    boost_score = 0.0
    reasons: list[str] = []

    if category in preferred_categories:
        alignment_score += 0.45
        boost_score += 2.0
        reasons.append(f"category:{category}")
    elif category in suppressed_categories:
        alignment_score -= 0.12
        boost_score -= 1.0
        reasons.append(f"suppressed_category:{category}")
    else:
        # H14.2 Fix A: secondary category bonus when primary doesn't match but preferred
        # categories appear in the full vpi_editorial_categories list. Covers multi-category
        # content (e.g. revelation/coverage_explanation/emotional_protection) where the
        # primary editorial type differs from the campaign's preferred categories.
        _all_cats = [str(x or "").strip() for x in _safe_list(segment.get("vpi_editorial_categories") or []) if str(x or "").strip()]
        _secondary_preferred = [cat for cat in _all_cats[1:] if cat in preferred_categories]
        if _secondary_preferred:
            _secondary_bonus = min(0.22, 0.12 * len(_secondary_preferred))
            alignment_score += _secondary_bonus
            boost_score += min(1.2, 0.5 * len(_secondary_preferred))
            reasons.append(f"secondary_category:{','.join(_secondary_preferred[:2])}")
            logger.info(
                "VPI_CAMPAIGN_ALIGNMENT_VPI_SIGNALS_APPLIED intent=%s primary=%s secondary=%s bonus=%.2f",
                intent, category, "|".join(_secondary_preferred[:3]), _secondary_bonus,
            )

    matched_keywords = [kw for kw in preferred_keywords if _normalize_text(kw) in text]
    if matched_keywords:
        keyword_bonus = min(0.35, 0.08 * len(matched_keywords))
        alignment_score += keyword_bonus
        boost_score += min(2.5, 0.7 * len(matched_keywords))
        reasons.append(f"keywords:{','.join(matched_keywords[:4])}")

    if bool(context.get("sensitive_handling_required")) and intent == "decesos":
        if category == "sensitive_decesos":
            alignment_score += 0.18
            boost_score += 1.2
            reasons.append("sensitive_alignment")
        elif category in {"risk_warning"}:
            alignment_score -= 0.05
            boost_score -= 0.4
            reasons.append("risk_softened")

    alignment_score = max(0.0, min(1.0, alignment_score))
    boost_score = max(-2.0, min(3.5, boost_score))
    if alignment_score >= 0.35 and any(r.startswith("secondary_category:") for r in reasons):
        logger.info(
            "VPI_CAMPAIGN_ALIGNMENT_SCORE_RECALIBRATED intent=%s score=%.4f reasons=%s",
            intent, alignment_score, "|".join(reasons),
        )
    elif alignment_score < 0.35 and reasons:
        logger.info(
            "VPI_CAMPAIGN_ALIGNMENT_LOW_CONFIDENCE_RETAINED intent=%s score=%.4f reasons=%s",
            intent, alignment_score, "|".join(reasons),
        )
    return round(alignment_score, 4), round(boost_score, 4), "|".join(reasons) or "general_vpi"


def _normalize_diversity_tokens(text: str) -> list[str]:
    normalized = _normalize(text)
    tokens = []
    for token in normalized.split():
        token = token.strip()
        if len(token) < 3 or token in _DIVERSITY_STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _text_overlap_metrics(a_text: str, b_text: str) -> tuple[float, float]:
    a_tokens = set(_normalize_diversity_tokens(a_text))
    b_tokens = set(_normalize_diversity_tokens(b_text))
    if not a_tokens or not b_tokens:
        return 0.0, 0.0
    inter = a_tokens & b_tokens
    union = a_tokens | b_tokens
    jaccard = len(inter) / max(1, len(union))
    coverage = len(inter) / max(1, min(len(a_tokens), len(b_tokens)))
    return round(jaccard, 4), round(coverage, 4)


def _clip_primary_category(seg: dict[str, Any]) -> str:
    categories = [str(x or "").strip() for x in (seg.get("vpi_editorial_categories") or []) if str(x or "").strip()]
    if categories:
        return categories[0]
    editorial_type = str(seg.get("editorial_type") or "").strip()
    return editorial_type or "generic"


def _package_rank_score(seg: dict[str, Any]) -> float:
    final_rank = float(seg.get("final_rank_score") or seg.get("segment_value_score") or seg.get("vpi_score") or 0.0)
    hookability = float(seg.get("hookability_score") or 0.0)
    commercial = float(seg.get("commercial_usefulness_score") or 0.0)
    standalone = float(seg.get("standalone_score") or 0.0)
    boundary_confidence = float(seg.get("boundary_confidence") or 0.0)
    campaign_boost = float(seg.get("campaign_boost_score") or seg.get("campaign_alignment_score") or 0.0)
    weak_penalties = len(_safe_list(seg.get("weak_segment_penalties")))
    duration = float(seg.get("duration") or 0.0)
    duration_bonus = 2.5 if 18.0 <= duration <= 35.0 else 1.0 if 10.0 <= duration <= 45.0 else 0.0
    similarity_penalty = float(seg.get("diversity_similarity_penalty") or 0.0)
    complete_idea_score = float(seg.get("complete_idea_score") or 0.0)
    setup_context_shift_seconds = float(seg.get("setup_context_shift_seconds") or 0.0)
    trailing_low_value_seconds = float(seg.get("trailing_low_value_seconds") or 0.0)
    incomplete_viral_window_detected = bool(seg.get("incomplete_viral_window_detected"))
    bts_tail_detected = bool(seg.get("bts_tail_detected"))
    weak_penalty = min(18.0, weak_penalties * 2.0)
    score = (
        final_rank * 0.52
        + hookability * 0.14
        + commercial * 0.12
        + standalone * 0.14
        + boundary_confidence * 8.0
        + campaign_boost * 1.2
        + duration_bonus
        - weak_penalty
        - similarity_penalty
    )
    if boundary_confidence <= 0.0:
        score -= 8.0
    elif boundary_confidence < 0.35:
        score -= 3.5
    if complete_idea_score and complete_idea_score < 0.70:
        score -= 12.0
    if boundary_confidence >= 0.75 and complete_idea_score and complete_idea_score < 0.80:
        score -= 8.0
    if incomplete_viral_window_detected:
        score -= 12.5
    if bts_tail_detected:
        score -= 5.0
    if setup_context_shift_seconds > 0.0:
        score += min(1.5, setup_context_shift_seconds * 0.12)
    if trailing_low_value_seconds > 0.0:
        score -= min(3.0, trailing_low_value_seconds * 0.35)
    if bool(seg.get("weak_editorial_segment")):
        score -= 4.0
    return round(_clamp_score(score), 3)


def _viral_window_audit(seg: dict[str, Any]) -> dict[str, Any]:
    original_start_time = str(seg.get("original_start_time") or seg.get("start_time") or "")
    original_end_time = str(seg.get("original_end_time") or seg.get("end_time") or "")
    refined_start_time = str(seg.get("refined_start_time") or seg.get("start_time") or original_start_time or "")
    refined_end_time = str(seg.get("refined_end_time") or seg.get("end_time") or original_end_time or "")
    setup_context_shift_seconds = float(seg.get("setup_context_shift_seconds") or seg.get("start_extend_seconds") or 0.0)
    trailing_low_value_seconds = float(seg.get("trailing_low_value_seconds") or seg.get("end_trim_seconds") or seg.get("bts_tail_trimmed_seconds") or 0.0)
    complete_idea_score = float(seg.get("complete_idea_score") or 0.0)
    boundary_confidence = float(seg.get("boundary_confidence") or 0.0)
    starts_cleanly = bool(seg.get("starts_cleanly", True))
    ends_cleanly = bool(seg.get("ends_cleanly", True))
    payoff_preserved = bool(seg.get("payoff_preserved", True))
    bts_tail_detected = bool(seg.get("bts_tail_detected"))
    forced_shift_back_applied = bool(seg.get("forced_shift_back_applied"))
    selected_alternative_for_complete_idea = bool(seg.get("selected_alternative_for_complete_idea"))
    incomplete_window_uncorrectable = bool(seg.get("incomplete_window_uncorrectable"))
    incomplete_viral_window_detected = bool(
        bts_tail_detected
        or not ends_cleanly
        or not payoff_preserved
        or complete_idea_score < 0.70
        or (boundary_confidence >= 0.75 and complete_idea_score < 0.80)
        or (not starts_cleanly and boundary_confidence >= 0.75)
    )
    if incomplete_viral_window_detected and setup_context_shift_seconds <= 0.0:
        if trailing_low_value_seconds > 0.0:
            setup_context_shift_seconds = min(12.0, max(8.0, trailing_low_value_seconds))
        elif boundary_confidence >= 0.80 and complete_idea_score < 0.80:
            setup_context_shift_seconds = min(12.0, max(8.0, boundary_confidence * 12.0))
        elif complete_idea_score < 0.70:
            setup_context_shift_seconds = 8.0
        else:
            setup_context_shift_seconds = min(12.0, max(6.0, boundary_confidence * 10.0 if boundary_confidence > 0.0 else 6.0))
    if incomplete_viral_window_detected and setup_context_shift_seconds > 0.0:
        try:
            original_start_s = _parse_timestamp_to_seconds(original_start_time or refined_start_time or "00:00")
            original_end_s = _parse_timestamp_to_seconds(original_end_time or refined_end_time or "00:00")
            new_start_s = max(0.0, original_start_s - setup_context_shift_seconds)
            tail_trim_s = min(6.0, max(0.0, setup_context_shift_seconds / 2.0))
            new_end_s = max(new_start_s + 0.5, original_end_s - tail_trim_s)
            if new_end_s > new_start_s:
                refined_start_time = _fmt_timestamp(new_start_s)
                refined_end_time = _fmt_timestamp(new_end_s)
                selected_window_after = f"{refined_start_time} -> {refined_end_time}".strip()
                trailing_low_value_seconds = max(trailing_low_value_seconds, round(max(0.0, original_end_s - new_end_s), 3))
                setup_context_shift_seconds = round(max(setup_context_shift_seconds, min(12.0, original_start_s - new_start_s)), 3)
                forced_shift_back_applied = True
                segment["forced_shift_back_applied"] = True
                segment["viral_window_shift_reason"] = "incomplete_idea_shift_back_forced"
            else:
                incomplete_window_uncorrectable = True
        except Exception:
            incomplete_window_uncorrectable = True
    elif incomplete_viral_window_detected and setup_context_shift_seconds <= 0.0:
        incomplete_window_uncorrectable = True
    selected_window_before = f"{original_start_time} -> {original_end_time}".strip()
    selected_window_after = f"{refined_start_time} -> {refined_end_time}".strip()
    return {
        "selected_window_before": selected_window_before,
        "selected_window_after": selected_window_after,
        "setup_context_shift_seconds": round(setup_context_shift_seconds, 3),
        "trailing_low_value_seconds": round(trailing_low_value_seconds, 3),
        "complete_idea_score": round(complete_idea_score, 4),
        "incomplete_viral_window_detected": bool(incomplete_viral_window_detected),
        "forced_shift_back_applied": bool(forced_shift_back_applied),
        "selected_alternative_for_complete_idea": bool(selected_alternative_for_complete_idea),
        "incomplete_window_uncorrectable": bool(incomplete_window_uncorrectable),
        "viral_window_shifted_back": bool(seg.get("viral_window_shifted_back") or setup_context_shift_seconds > 0.0 or bts_tail_detected or forced_shift_back_applied),
        "viral_window_shift_reason": str(seg.get("viral_window_shift_reason") or ("incomplete_idea_shift_back_forced" if forced_shift_back_applied else ("incomplete_idea_shift_back" if setup_context_shift_seconds > 0.0 else ""))),
    }


def _category_group_for(primary_category: str) -> str:
    normalized = str(primary_category or "").strip()
    for group_name, members in _DIVERSITY_GROUPS:
        if normalized in members:
            return group_name
    return normalized or "generic"


def _compute_package_diversity_score(selected_segments: list[dict[str, Any]]) -> dict[str, Any]:
    if not selected_segments:
        return {
            "package_diversity_score": 0.0,
            "package_diversity_reason": "no_selected_segments",
            "package_category_distribution": {},
            "package_theme_distribution": {},
            "package_duration_balance_ok": False,
            "package_duration_warnings": ["no_selected_segments"],
            "package_diversity_warnings": ["no_selected_segments"],
        }
    category_counts: dict[str, int] = {}
    theme_counts: dict[str, int] = {}
    durations: list[float] = []
    hook_buckets: set[str] = set()
    weak_count = 0
    similar_theme_duplicates = 0
    for seg in selected_segments:
        category = _clip_primary_category(seg)
        theme = str(seg.get("duplicate_theme_key") or "general_insurance")
        category_counts[category] = category_counts.get(category, 0) + 1
        theme_counts[theme] = theme_counts.get(theme, 0) + 1
        durations.append(float(seg.get("duration") or 0.0))
        hookability = float(seg.get("hookability_score") or 0.0)
        hook_buckets.add("high" if hookability >= 70.0 else "mid" if hookability >= 45.0 else "low")
        weak_count += int(bool(seg.get("weak_editorial_segment")))
        if theme_counts[theme] > 1:
            similar_theme_duplicates += 1

    unique_categories = len(category_counts)
    unique_themes = len(theme_counts)
    total = max(1, len(selected_segments))
    mean_duration = sum(durations) / total
    variance = sum((dur - mean_duration) ** 2 for dur in durations) / total
    stddev = variance ** 0.5
    duration_ratio = stddev / max(1.0, mean_duration)
    duration_balance_score = max(0.0, min(1.0, duration_ratio / 0.30))
    category_score = unique_categories / total
    theme_score = unique_themes / total
    hook_score = len(hook_buckets) / 3.0
    weak_penalty = min(1.0, weak_count / max(1, total * 1.5))
    duplicate_penalty = min(1.0, similar_theme_duplicates / max(1, total))
    package_diversity_score = (
        category_score * 0.38
        + theme_score * 0.28
        + hook_score * 0.14
        + duration_balance_score * 0.12
        + (1.0 - weak_penalty) * 0.08
        - duplicate_penalty * 0.12
    )
    package_diversity_score = max(0.0, min(1.0, package_diversity_score))
    duration_warnings: list[str] = []
    if duration_ratio < 0.15:
        duration_warnings.append("duration_pattern_too_uniform")
    elif duration_ratio > 0.60:
        duration_warnings.append("duration_pattern_too_spread")
    if weak_count:
        duration_warnings.append("weak_editorial_segments_present")
    diversity_warnings: list[str] = []
    if len(category_counts) == 1 and total >= 3:
        diversity_warnings.append("single_category_package")
    if similar_theme_duplicates > 2:
        diversity_warnings.append("duplicate_theme_concentration")
    if package_diversity_score < 0.35:
        diversity_warnings.append("low_package_diversity")
    return {
        "package_diversity_score": round(package_diversity_score, 4),
        "package_diversity_reason": (
            f"{unique_categories} categories/{unique_themes} themes/{len(hook_buckets)} hook_bins "
            f"std={round(duration_ratio, 3)} weak={weak_count}"
        ),
        "package_category_distribution": dict(sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))),
        "package_theme_distribution": dict(sorted(theme_counts.items(), key=lambda item: (-item[1], item[0]))),
        "package_duration_balance_ok": bool(duration_ratio >= 0.15 and len(duration_warnings) == 0),
        "package_duration_warnings": duration_warnings,
        "package_diversity_warnings": diversity_warnings,
    }


def select_diverse_vpi_clip_package(
    candidate_segments: list[dict[str, Any]],
    *,
    max_clips: int,
    min_clips: int = 1,
    editorial_categories: list[str] | None = None,
    duplicate_theme_key: str | None = None,
    final_rank_score: str = "final_rank_score",
    hookability_score: str = "hookability_score",
    commercial_usefulness_score: str = "commercial_usefulness_score",
    standalone_score: str = "standalone_score",
    boundary_confidence: str = "boundary_confidence",
    clip_duration: str = "duration",
    weak_segment_penalties: str = "weak_segment_penalties",
    campaign_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select a diverse VPI clip package from ranked candidates."""

    del editorial_categories, duplicate_theme_key  # selector reads per-segment fields directly
    campaign_context = _as_dict(campaign_context)
    campaign_intent = _normalize_campaign_token(campaign_context.get("campaign_intent"))
    campaign_rules = _CAMPAIGN_INTENT_RULES.get(campaign_intent, {})
    campaign_preferred_categories = list(campaign_rules.get("preferred_categories") or [])
    campaign_suppressed_categories = list(campaign_rules.get("suppressed_categories") or [])
    campaign_preferred_keywords = list(campaign_rules.get("preferred_keywords") or [])
    campaign_sensitive = bool(campaign_context.get("sensitive_handling_required"))
    logger.info(
        "VPI_PACKAGE_DIVERSITY_STARTED candidates=%d max_clips=%d min_clips=%d",
        len(candidate_segments or []),
        int(max_clips),
        int(min_clips),
    )

    if not candidate_segments:
        summary = _compute_package_diversity_score([])
        summary.update(
            {
                "selected_segments": [],
                "rejected_segments": [],
                "package_rejection_reasons": [],
                "package_duration_balance_ok": False,
            }
        )
        logger.info("VPI_PACKAGE_DIVERSITY_SCORE_COMPUTED score=0.000 reason=no_candidates")
        return summary

    max_clips = max(1, int(max_clips))
    min_clips = max(1, min(int(min_clips or 1), max_clips))
    small_lot = max_clips <= 3
    same_category_limit = max_clips if small_lot else 2
    same_theme_limit = max_clips if small_lot else 1
    absolute_top = max(candidate_segments, key=lambda seg: float(seg.get(final_rank_score) or seg.get("final_rank_score") or seg.get("vpi_score") or 0.0))
    absolute_top_score = float(absolute_top.get(final_rank_score) or absolute_top.get("final_rank_score") or absolute_top.get("vpi_score") or 0.0)
    second_best = sorted(
        [float(seg.get(final_rank_score) or seg.get("final_rank_score") or seg.get("vpi_score") or 0.0) for seg in candidate_segments],
        reverse=True,
    )[1] if len(candidate_segments) > 1 else 0.0
    preserve_absolute_top = (absolute_top_score - second_best) >= 18.0

    prepared: list[dict[str, Any]] = []
    for _idx, seg in enumerate(candidate_segments):
        item = dict(seg)
        item.setdefault("candidate_id", str(item.get("segment_id") or item.get("id") or f"candidate_{_idx + 1}"))
        text = str(item.get("text") or "")
        primary_category = _clip_primary_category(item)
        theme_key = str(item.get("duplicate_theme_key") or _extract_theme_key(text) or "general_insurance")
        campaign_alignment_score, campaign_boost_score, campaign_alignment_reason = _campaign_alignment_for_segment(item, campaign_context)
        item["campaign_intent"] = campaign_intent or "general_vpi"
        item["campaign_alignment_score"] = round(float(campaign_alignment_score), 4)
        item["campaign_boost_score"] = round(float(campaign_boost_score), 4)
        item["campaign_alignment_reason"] = campaign_alignment_reason
        item["campaign_boost_applied"] = bool(campaign_intent in _CAMPAIGN_INTENT_RULES and (campaign_alignment_score > 0.0 or campaign_boost_score > 0.0))
        item.update(_viral_window_audit(item))
        score = _package_rank_score(item)
        item["primary_category"] = primary_category
        item["category_group"] = _category_group_for(primary_category)
        item["package_rank_score"] = score
        item.setdefault("selected_for_reason", str(item.get("selected_for_reason") or ""))
        item.setdefault("rejected_for_reason", str(item.get("rejected_for_reason") or ""))
        item["similar_theme_key"] = theme_key
        item["similar_text_overlap"] = 0.0
        item["diversity_similarity_penalty"] = 0.0
        if campaign_intent in _CAMPAIGN_INTENT_RULES and primary_category in campaign_suppressed_categories:
            item["campaign_boost_score"] = min(float(item.get("campaign_boost_score") or 0.0), 0.0)
        if campaign_intent == "decesos" and primary_category not in {"sensitive_decesos", "emotional_protection", "actionable_advice", "coverage_explanation"}:
            item["campaign_alignment_score"] = min(float(item.get("campaign_alignment_score") or 0.0), 0.35)
        if item["campaign_boost_applied"]:
            item["package_rank_score"] = round(min(100.0, score + max(0.0, float(item.get("campaign_boost_score") or 0.0))), 3)
        prepared.append(item)

    prepared.sort(key=lambda seg: float(seg.get("package_rank_score") or 0.0), reverse=True)

    rejected: list[dict[str, Any]] = []

    # H14.7 Fix C — dedupe near-identical overlapping windows when max_clips>1.
    # `_similarity_penalty` only applies a soft score penalty during diversity
    # fill, which is not enough to stop two near-duplicate windows (same text,
    # windows overlapping >65%) from both being selected when max_clips<=3
    # (same_theme_limit==max_clips for "small_lot"). Hard-reject the weaker one
    # up front, unless the windows actually carry distinct payoffs.
    if max_clips > 1 and len(prepared) > 1:
        def _dedupe_ts_seconds(value: str) -> float:
            parts = str(value or "0").strip().split(":")
            try:
                if len(parts) == 3:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                if len(parts) == 2:
                    return int(parts[0]) * 60 + float(parts[1])
                return float(parts[0])
            except (TypeError, ValueError):
                return 0.0

        _duplicate_found = False
        _dropped_ids: set[str] = set()
        _kept_list = list(prepared)
        for _i in range(len(_kept_list)):
            for _j in range(_i + 1, len(_kept_list)):
                a = _kept_list[_i]
                b = _kept_list[_j]
                a_id = str(a.get("candidate_id") or "")
                b_id = str(b.get("candidate_id") or "")
                if a_id in _dropped_ids or b_id in _dropped_ids:
                    continue
                a_start = _dedupe_ts_seconds(str(a.get("start_time") or "00:00"))
                a_end = _dedupe_ts_seconds(str(a.get("end_time") or "00:00"))
                b_start = _dedupe_ts_seconds(str(b.get("start_time") or "00:00"))
                b_end = _dedupe_ts_seconds(str(b.get("end_time") or "00:00"))
                inter = max(0.0, min(a_end, b_end) - max(a_start, b_start))
                union = max(a_end, b_end) - min(a_start, b_start)
                if union <= 0.0 or inter <= 0.0:
                    continue
                temporal_overlap_ratio = round(inter / union, 4)
                if temporal_overlap_ratio <= 0.65:
                    continue
                jaccard, coverage = _text_overlap_metrics(str(a.get("text") or ""), str(b.get("text") or ""))
                text_overlap = max(jaccard, coverage)
                if text_overlap < 0.50:
                    logger.info(
                        "VPI_MULTICLIP_DUPLICATE_WINDOW_KEPT_DISTINCT_PAYOFF candidate_a=%s candidate_b=%s temporal_overlap_ratio=%.3f text_overlap=%.3f",
                        a_id,
                        b_id,
                        temporal_overlap_ratio,
                        text_overlap,
                    )
                    continue
                _duplicate_found = True

                def _candidate_quality(seg: dict[str, Any]) -> tuple[float, float, float]:
                    return (
                        0.0 if bool(seg.get("incomplete_viral_window_detected")) else 1.0,
                        float(seg.get("complete_idea_score") or 0.0),
                        float(seg.get("package_rank_score") or 0.0),
                    )

                if _candidate_quality(b) > _candidate_quality(a):
                    keep, drop = b, a
                else:
                    keep, drop = a, b
                drop_id = str(drop.get("candidate_id") or "")
                keep_id = str(keep.get("candidate_id") or "")
                drop["rejected_for_reason"] = "duplicate_window_overlap"
                drop["duplicate_of_candidate_id"] = keep_id
                drop["temporal_overlap_ratio"] = temporal_overlap_ratio
                _dropped_ids.add(drop_id)
                logger.info(
                    "VPI_MULTICLIP_DUPLICATE_WINDOW_REJECTED dropped=%s kept=%s temporal_overlap_ratio=%.3f text_overlap=%.3f",
                    drop_id,
                    keep_id,
                    temporal_overlap_ratio,
                    text_overlap,
                )
        if _dropped_ids:
            for _seg in list(prepared):
                if str(_seg.get("candidate_id") or "") in _dropped_ids:
                    prepared.remove(_seg)
                    rejected.append(_seg)
            logger.info(
                "VPI_MULTICLIP_OVERLAP_DIVERSITY_ENFORCED dropped=%d remaining=%d",
                len(_dropped_ids),
                len(prepared),
            )
        elif _duplicate_found:
            logger.info("VPI_MULTICLIP_OVERLAP_DIVERSITY_ENFORCED dropped=0 remaining=%d", len(prepared))

    def _category_count(selected: list[dict[str, Any]], category: str) -> int:
        return sum(1 for seg in selected if str(seg.get("primary_category") or "") == category)

    def _theme_count(selected: list[dict[str, Any]], theme: str) -> int:
        return sum(1 for seg in selected if str(seg.get("duplicate_theme_key") or seg.get("similar_theme_key") or "") == theme)

    def _best_candidate_for_categories(categories: tuple[str, ...], pool: list[dict[str, Any]]) -> dict[str, Any] | None:
        chosen = None
        chosen_score = -1.0
        for seg in pool:
            if str(seg.get("primary_category") or "") not in categories:
                continue
            score = float(seg.get("package_rank_score") or 0.0)
            if score > chosen_score:
                chosen = seg
                chosen_score = score
        return chosen

    def _similarity_penalty(candidate: dict[str, Any], selected: list[dict[str, Any]]) -> tuple[float, str, str]:
        if not selected:
            return 0.0, "", ""
        best_penalty = 0.0
        best_theme = ""
        best_overlap = 0.0
        candidate_text = str(candidate.get("text") or "")
        candidate_theme = str(candidate.get("similar_theme_key") or candidate.get("duplicate_theme_key") or "general_insurance")
        for sel in selected:
            overlap_jaccard, overlap_coverage = _text_overlap_metrics(candidate_text, str(sel.get("text") or ""))
            overlap = max(overlap_jaccard, overlap_coverage)
            if candidate_theme and candidate_theme == str(sel.get("duplicate_theme_key") or sel.get("similar_theme_key") or ""):
                overlap = max(overlap, 0.75)
            if overlap > best_penalty:
                best_penalty = overlap
                best_theme = str(sel.get("duplicate_theme_key") or sel.get("similar_theme_key") or "general_insurance")
                best_overlap = overlap
        return best_penalty, best_theme, f"{best_theme}:{best_overlap:.2f}" if best_theme else ""

    selected: list[dict[str, Any]] = []
    selected_categories: dict[str, int] = {}
    selected_themes: dict[str, int] = {}
    package_rejection_reasons: list[str] = []

    priority_groups = list(_DIVERSITY_GROUPS)
    if campaign_intent in _CAMPAIGN_INTENT_RULES:
        prioritized_groups: list[tuple[str, tuple[str, ...]]] = []
        preferred_categories_set = set(campaign_preferred_categories)
        for group_name, members in _DIVERSITY_GROUPS:
            if preferred_categories_set.intersection(members):
                prioritized_groups.append((group_name, members))
        for group in _DIVERSITY_GROUPS:
            if group not in prioritized_groups:
                prioritized_groups.append(group)
        priority_groups = prioritized_groups
    if small_lot:
        priority_groups = []

    def _take(seg: dict[str, Any], reason: str, *, replace: dict[str, Any] | None = None) -> None:
        seg = dict(seg)
        seg["selected_for_reason"] = reason
        seg["rejected_for_reason"] = ""
        if replace is not None:
            replace["rejected_for_reason"] = "diversity_replacement"
            replace["selected_for_reason"] = replace.get("selected_for_reason") or ""
            rejected.append(replace)
            logger.info(
                "VPI_PACKAGE_DIVERSITY_REPLACEMENT replaced_theme=%s replaced_category=%s new_theme=%s new_category=%s",
                str(replace.get("duplicate_theme_key") or replace.get("similar_theme_key") or "general_insurance"),
                str(replace.get("primary_category") or ""),
                str(seg.get("duplicate_theme_key") or seg.get("similar_theme_key") or "general_insurance"),
                str(seg.get("primary_category") or ""),
            )
        selected.append(seg)
        selected_categories[str(seg.get("primary_category") or "")] = selected_categories.get(str(seg.get("primary_category") or ""), 0) + 1
        theme_key = str(seg.get("duplicate_theme_key") or seg.get("similar_theme_key") or "general_insurance")
        selected_themes[theme_key] = selected_themes.get(theme_key, 0) + 1
        logger.info(
            "VPI_PACKAGE_DIVERSITY_SELECTED category=%s theme=%s score=%.3f reason=%s",
            str(seg.get("primary_category") or ""),
            theme_key,
            float(seg.get("package_rank_score") or 0.0),
            reason,
        )

    # Anchor one strong clip per editorial group if possible.
    for _, group_members in priority_groups:
        if len(selected) >= min_clips:
            break
        anchor = _best_candidate_for_categories(group_members, prepared)
        if anchor is None:
            continue
        if float(anchor.get("package_rank_score") or 0.0) < 40.0:
            continue
        if _theme_count(selected, str(anchor.get("duplicate_theme_key") or anchor.get("similar_theme_key") or "")) >= same_theme_limit and len(selected) >= min_clips:
            continue
        prepared.remove(anchor)
        _take(anchor, "category_anchor")

    # Ensure the absolute top stays if it is clearly ahead.
    if preserve_absolute_top and absolute_top in prepared:
        prepared.remove(absolute_top)
        if selected:
            weakest = min(selected, key=lambda seg: float(seg.get("package_rank_score") or 0.0))
            if float(absolute_top.get("package_rank_score") or 0.0) >= float(weakest.get("package_rank_score") or 0.0):
                selected.remove(weakest)
                _take(absolute_top, "top_absolute_preserved", replace=weakest)
            else:
                _take(absolute_top, "top_absolute_preserved")
        else:
            _take(absolute_top, "top_absolute_preserved")

    # Fill remaining slots with diversity-aware ranking.
    while prepared and len(selected) < max_clips:
        best_choice: dict[str, Any] | None = None
        best_choice_score = -9999.0
        best_choice_reason = ""
        best_choice_overlap = 0.0
        best_choice_theme = ""
        for seg in list(prepared):
            # OUTPUT-CUTS-8 hard-ban: never let diversity/backfill rescue a
            # candidate already marked as backstage-contaminated.
            _bts_reason = str(seg.get("content_quality_reason") or "")
            if bool(seg.get("backstage_pure")) or (
                str(seg.get("content_quality_label") or "") == "reject"
                and _bts_reason in {
                    "bts_contamination_too_high",
                    "behind_the_scenes_low_speech",
                    "meta_production_or_bts",
                }
            ):
                seg["backstage_rescue_blocked"] = True
                seg["backstage_placeholder"] = True
                logger.info(
                    "VPI_OUTPUT_CUTS_BACKSTAGE_RESCUE_BLOCKED start=%s end=%s reason=%s",
                    seg.get("start_time"),
                    seg.get("end_time"),
                    _bts_reason or "backstage_pure",
                )
                prepared.remove(seg)
                continue
            category = str(seg.get("primary_category") or "")
            theme_key = str(seg.get("duplicate_theme_key") or seg.get("similar_theme_key") or "general_insurance")
            category_count = _category_count(selected, category)
            theme_count = _theme_count(selected, theme_key)
            overlap_penalty, overlap_theme, overlap_reason = _similarity_penalty(seg, selected)
            seg["diversity_similarity_penalty"] = round(overlap_penalty * 35.0, 3)
            seg["similar_theme_key"] = overlap_theme or theme_key
            seg["similar_text_overlap"] = round(overlap_penalty, 4)
            adjusted_score = float(seg.get("package_rank_score") or 0.0) - seg["diversity_similarity_penalty"]
            can_take = True
            if category_count >= same_category_limit and max_clips > 3:
                can_take = False
            if theme_count >= same_theme_limit:
                has_alternatives = any(
                    str(rem.get("primary_category") or "") != category or float(rem.get("package_rank_score") or 0.0) >= adjusted_score - 10.0
                    for rem in prepared
                    if rem is not seg
                )
                if has_alternatives and len(selected) >= min_clips:
                    can_take = False
            if not can_take and len(selected) < min_clips:
                can_take = True
            if not can_take:
                reason = []
                if category_count >= same_category_limit and max_clips > 3:
                    reason.append(f"same_category_limit:{category}")
                if theme_count >= same_theme_limit:
                    reason.append(f"same_theme_limit:{theme_key}")
                package_rejection_reasons.append("|".join(reason) or "diversity_limit")
                continue
            if adjusted_score > best_choice_score:
                best_choice = seg
                best_choice_score = adjusted_score
                if max_clips <= 1:
                    logger.info(
                        "VPI_SELECTION_DIVERSITY_FILL_BLOCKED_FOR_TOP1 candidates=%d",
                        len(candidate_segments or []),
                    )
                    best_choice_reason = "top_rank_primary"
                else:
                    best_choice_reason = "diversity_fill"
                best_choice_overlap = overlap_penalty
                best_choice_theme = overlap_reason
        if best_choice is None:
            break
        if max_clips <= 1 and best_choice is not None:
            best_complete_idea = float(best_choice.get("complete_idea_score") or 0.0)
            best_incomplete = bool(best_choice.get("incomplete_viral_window_detected"))
            if best_incomplete or best_complete_idea < 0.70:
                logger.info(
                    "VPI_SELECTION_COMPLETE_IDEA_RESCUE_TRIGGERED window=%s->%s complete_idea=%.3f incomplete=%s current_reason=%s",
                    str(best_choice.get("start_time") or ""),
                    str(best_choice.get("end_time") or ""),
                    best_complete_idea,
                    str(best_incomplete).lower(),
                    str(best_choice_reason or ""),
                )
                _rescue_best_rank = float(best_choice.get("final_rank_score") or best_choice.get("package_rank_score") or 0.0)
                _rescue_min_rank = max(0.0, _rescue_best_rank * 0.5)
                complete_candidates = [
                    seg for seg in prepared
                    if seg is not best_choice
                    and float(seg.get("complete_idea_score") or 0.0) >= 0.70
                    and not bool(seg.get("incomplete_viral_window_detected"))
                    and not bool(seg.get("bts_tail_detected"))
                    and float(seg.get("final_rank_score") or seg.get("package_rank_score") or 0.0) >= _rescue_min_rank
                ]
                if complete_candidates:
                    alt_choice = max(
                        complete_candidates,
                        key=lambda seg: float(seg.get("package_rank_score") or 0.0) - float(seg.get("diversity_similarity_penalty") or 0.0),
                    )
                    if alt_choice is not best_choice:
                        _rescue_previous_reason = str(best_choice.get("selected_for_reason") or best_choice_reason or "")
                        _rescue_previous_window = f"{best_choice.get('start_time') or ''} -> {best_choice.get('end_time') or ''}"
                        logger.info(
                            "VPI_SELECTION_COMPLETE_IDEA_ALTERNATIVE_SELECTED candidates=%d best=%.3f alt=%.3f alt_window=%s->%s",
                            len(complete_candidates),
                            best_complete_idea,
                            float(alt_choice.get("complete_idea_score") or 0.0),
                            str(alt_choice.get("start_time") or ""),
                            str(alt_choice.get("end_time") or ""),
                        )
                        alt_choice["previous_selected_for_reason"] = _rescue_previous_reason
                        alt_choice["previous_selected_window"] = _rescue_previous_window
                        alt_choice["selected_alternative_for_complete_idea"] = True
                        best_choice = alt_choice
                        best_choice_reason = "complete_idea_rescue"
                else:
                    logger.info(
                        "VPI_SELECTION_COMPLETE_IDEA_RESCUE_SKIPPED_NO_CANDIDATE candidates_checked=%d complete_idea=%.3f boundary=%.3f min_rank=%.3f",
                        len(prepared),
                        best_complete_idea,
                        float(best_choice.get("boundary_confidence") or 0.0),
                        _rescue_min_rank,
                    )
                    # H13.2 Fix C — no qualifying complete alternative existed in the
                    # pool: persist that finding onto the selected candidate itself
                    # (not just a log line) so downstream consumers (manifest, gate,
                    # snapshot) can see the clip is genuinely uncorrectable rather
                    # than silently re-selecting the incomplete top candidate.
                    # `selected_for_reason` is intentionally left as-is (it stays
                    # "top_rank_primary" — it WAS the only option) but the new
                    # `incomplete_window_uncorrectable_reason` field clearly states
                    # that no alternative existed.
                    best_choice["incomplete_window_uncorrectable"] = True
                    best_choice["incomplete_window_uncorrectable_reason"] = "no_qualifying_complete_alternative_in_candidate_pool"
                    logger.info(
                        "VPI_SELECTION_INCOMPLETE_WINDOW_UNCORRECTABLE candidates=%d complete_idea=%.3f boundary=%.3f selected_for_reason=%s reason=%s",
                        len(prepared) + len(selected) + 1,
                        best_complete_idea,
                        float(best_choice.get("boundary_confidence") or 0.0),
                        str(best_choice.get("selected_for_reason") or best_choice_reason or ""),
                        best_choice["incomplete_window_uncorrectable_reason"],
                    )
        prepared.remove(best_choice)
        if best_choice_overlap > 0.45:
            logger.info(
                "VPI_PACKAGE_THEME_DUPLICATE_DETECTED theme=%s overlap=%.3f category=%s",
                best_choice_theme or str(best_choice.get("similar_theme_key") or best_choice.get("duplicate_theme_key") or "general_insurance"),
                best_choice_overlap,
                str(best_choice.get("primary_category") or ""),
            )
        _take(best_choice, best_choice_reason)

    # If we still need clips, allow duplicates rather than returning too few.
    while prepared and len(selected) < min_clips:
        seg = prepared.pop(0)
        overlap_penalty, overlap_theme, overlap_reason = _similarity_penalty(seg, selected)
        seg["diversity_similarity_penalty"] = round(overlap_penalty * 35.0, 3)
        seg["similar_theme_key"] = overlap_theme or str(seg.get("similar_theme_key") or seg.get("duplicate_theme_key") or "general_insurance")
        seg["similar_text_overlap"] = round(overlap_penalty, 4)
        if overlap_reason:
            logger.info(
                "VPI_PACKAGE_THEME_DUPLICATE_DETECTED theme=%s overlap=%.3f category=%s",
                overlap_reason,
                overlap_penalty,
                str(seg.get("primary_category") or ""),
            )
        _take(seg, "fill_minimum_package")

    # Attach package metadata.
    package_meta = _compute_package_diversity_score(selected)
    package_meta["package_rejection_reasons"] = list(package_rejection_reasons)
    package_meta["selected_segments"] = selected
    package_meta["rejected_segments"] = rejected + prepared
    package_meta["package_diversity_context"] = {
        "package_diversity_score": package_meta["package_diversity_score"],
        "package_diversity_reason": package_meta["package_diversity_reason"],
        "package_category_distribution": package_meta["package_category_distribution"],
        "package_theme_distribution": package_meta["package_theme_distribution"],
        "package_duration_balance_ok": package_meta["package_duration_balance_ok"],
        "package_duration_warnings": package_meta["package_duration_warnings"],
        "package_diversity_warnings": package_meta["package_diversity_warnings"],
    }
    package_meta["selected_clip_package_summary"] = {
        "selected_count": len(selected),
        "rejected_count": len(rejected) + len(prepared),
        "package_diversity_score": package_meta["package_diversity_score"],
        "package_category_distribution": package_meta["package_category_distribution"],
        "package_theme_distribution": package_meta["package_theme_distribution"],
        "package_duration_balance_ok": package_meta["package_duration_balance_ok"],
        "package_diversity_warnings": package_meta["package_diversity_warnings"],
    }
    if campaign_intent in _CAMPAIGN_INTENT_RULES:
        selected_campaign_mix: dict[str, int] = {}
        alignment_scores = [float(seg.get("campaign_alignment_score") or 0.0) for seg in selected]
        boost_scores = [float(seg.get("campaign_boost_score") or 0.0) for seg in selected]
        for seg in selected:
            cat = str(seg.get("primary_category") or _clip_primary_category(seg) or "generic")
            selected_campaign_mix[cat] = selected_campaign_mix.get(cat, 0) + 1
        package_meta["campaign_intent"] = campaign_intent
        package_meta["campaign_intent_confidence"] = round(float(campaign_context.get("campaign_intent_confidence") or 0.0), 4)
        package_meta["campaign_intent_source"] = str(campaign_context.get("campaign_intent_source") or "default_general")
        package_meta["campaign_intent_reason"] = str(campaign_context.get("campaign_intent_reason") or "")
        package_meta["preferred_categories"] = list(campaign_preferred_categories)
        package_meta["suppressed_categories"] = list(campaign_suppressed_categories)
        package_meta["preferred_keywords"] = list(campaign_preferred_keywords)
        package_meta["sensitive_handling_required"] = bool(campaign_sensitive)
        package_meta["campaign_boost_applied"] = bool(any(bool(seg.get("campaign_boost_applied")) for seg in selected))
        package_meta["campaign_boost_score"] = round(max(boost_scores) if boost_scores else 0.0, 4)
        package_meta["campaign_alignment_score"] = round(sum(alignment_scores) / max(1, len(alignment_scores)), 4) if alignment_scores else 0.0
        package_meta["campaign_alignment_reason"] = str(campaign_context.get("campaign_intent_reason") or "")
        package_meta["selected_campaign_mix"] = selected_campaign_mix
        package_meta["campaign_alignment_summary"] = {
            "campaign_intent": campaign_intent,
            "selected_categories": selected_campaign_mix,
            "average_alignment_score": package_meta["campaign_alignment_score"],
            "boost_applied_count": sum(1 for seg in selected if bool(seg.get("campaign_boost_applied"))),
            "sensitive_handling_required": bool(campaign_sensitive),
        }
        package_meta["package_diversity_context"].update(
            {
                "campaign_intent": package_meta.get("campaign_intent", campaign_intent),
                "campaign_intent_confidence": package_meta.get("campaign_intent_confidence", 0.0),
                "campaign_intent_source": package_meta.get("campaign_intent_source", "default_general"),
                "campaign_intent_reason": package_meta.get("campaign_intent_reason", ""),
                "preferred_categories": package_meta.get("preferred_categories", []),
                "suppressed_categories": package_meta.get("suppressed_categories", []),
                "preferred_keywords": package_meta.get("preferred_keywords", []),
                "sensitive_handling_required": package_meta.get("sensitive_handling_required", False),
                "selected_campaign_mix": package_meta.get("selected_campaign_mix", {}),
                "campaign_alignment_score": package_meta.get("campaign_alignment_score", 0.0),
                "campaign_boost_score": package_meta.get("campaign_boost_score", 0.0),
            }
        )
        if campaign_intent == "decesos" and not bool(campaign_sensitive):
            package_meta["package_diversity_warnings"] = list(dict.fromkeys(package_meta["package_diversity_warnings"] + ["decesos_without_sensitive_handling"]))
        logger.info(
            "VPI_CAMPAIGN_PACKAGE_SELECTED intent=%s selected=%d alignment=%.3f boost=%.3f",
            campaign_intent,
            len(selected),
            float(package_meta["campaign_alignment_score"] or 0.0),
            float(package_meta["campaign_boost_score"] or 0.0),
        )
        logger.info(
            "VPI_CAMPAIGN_ALIGNMENT_SCORED intent=%s avg=%.3f preferred=%s suppressed=%s",
            campaign_intent,
            float(package_meta["campaign_alignment_score"] or 0.0),
            "|".join(campaign_preferred_categories) or "none",
            "|".join(campaign_suppressed_categories) or "none",
        )
        if package_meta["campaign_alignment_score"] < 0.35 or not any(bool(seg.get("campaign_boost_applied")) for seg in selected):
            logger.warning(
                "VPI_CAMPAIGN_WARNING intent=%s reason=%s selected=%d alignment=%.3f",
                campaign_intent,
                "no_aligned_strong_clips" if not any(bool(seg.get("campaign_boost_applied")) for seg in selected) else "low_alignment",
                len(selected),
                float(package_meta["campaign_alignment_score"] or 0.0),
            )
    category_distribution = package_meta["package_category_distribution"]
    theme_distribution = package_meta["package_theme_distribution"]
    logger.info(
        "VPI_PACKAGE_DIVERSITY_SCORE_COMPUTED score=%.4f selected=%d rejected=%d reason=%s",
        float(package_meta["package_diversity_score"] or 0.0),
        len(selected),
        len(rejected) + len(prepared),
        str(package_meta["package_diversity_reason"] or ""),
    )
    logger.info(
        "VPI_PACKAGE_CATEGORY_DISTRIBUTION %s",
        "|".join(f"{k}:{v}" for k, v in category_distribution.items()) or "none",
    )
    if any(v > 1 for v in theme_distribution.values()):
        logger.info(
            "VPI_PACKAGE_THEME_DUPLICATE_DETECTED %s",
            "|".join(f"{k}:{v}" for k, v in theme_distribution.items() if v > 1) or "none",
        )
    if package_meta["package_diversity_score"] < 0.35 or len(category_distribution) == 1 or any(v > 2 for v in theme_distribution.values()):
        logger.warning(
            "VPI_PACKAGE_DIVERSITY_WARNING score=%.4f categories=%d duplicate_themes=%d",
            float(package_meta["package_diversity_score"] or 0.0),
            len(category_distribution),
            sum(1 for v in theme_distribution.values() if v > 1),
        )
        package_meta["package_diversity_warnings"] = list(dict.fromkeys(package_meta["package_diversity_warnings"] + ["package_diversity_needs_review"]))
    return package_meta


def select_diverse_segments(
    segments: list[dict[str, Any]],
    *,
    requested: int = 3,
    max_same_theme: int = 1,
) -> list[dict[str, Any]]:
    """Select segments with diversity awareness.

    Prefers diversity across segment types. Allows same theme only if one
    segment is much stronger (score difference > 15 points).

    Returns:
        Selected segments (mutated in-place with diversity metadata).
    """
    package = select_diverse_vpi_clip_package(
        segments,
        max_clips=requested,
        min_clips=min(requested, max(1, requested if requested <= 3 else 3)),
    )
    selected = list(package.get("selected_segments") or [])
    selection_diversity_score = float(package.get("package_diversity_score") or 0.0)
    unique_themes = len(set(str(s.get("duplicate_theme_key") or "general_insurance") for s in selected))
    logger.info(
        "SEGMENT_DIVERSITY_SUMMARY selected=%d unique_themes=%d diversity_score=%.2f",
        len(selected), unique_themes, selection_diversity_score,
    )
    for seg in selected:
        seg["selection_diversity_score"] = selection_diversity_score
        seg["diversity_reason"] = str(package.get("package_diversity_reason") or "")
    return selected


# ── v2.0 — Clip brief contract ─────────────────────────────────────────────────


def build_vpi_clip_editorial_brief(
    *,
    segment_text: str,
    vpi_editorial_categories: list[str] | None = None,
    primary_category: str | None = None,
    editorial_score: float | None = None,
    hookability_score: float | None = None,
    commercial_usefulness_score: float | None = None,
    standalone_score: float | None = None,
    boundary_confidence: float | None = None,
    package_diversity_context: dict[str, Any] | None = None,
    campaign_intent: str | None = None,
    campaign_alignment_score: float | None = None,
    selected_for_reason: str | None = None,
    weak_segment_penalties: list[str] | None = None,
    sensitive_handling_required: bool = False,
    cta_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = str(segment_text or "")
    categories = [str(item or "").strip() for item in _safe_list(vpi_editorial_categories) if str(item or "").strip()]
    primary = str(primary_category or (categories[0] if categories else "") or "generic")
    editorial_score_f = float(editorial_score or 0.0)
    hookability_score_f = float(hookability_score or 0.0)
    commercial_usefulness_score_f = float(commercial_usefulness_score or 0.0)
    standalone_score_f = float(standalone_score or 0.0)
    boundary_confidence_f = float(boundary_confidence or 0.0)
    campaign_intent_n = _normalize_campaign_token(campaign_intent or "general_vpi")
    campaign_alignment_score_f = float(campaign_alignment_score or 0.0)
    weak_penalties = [str(item or "") for item in _safe_list(weak_segment_penalties) if str(item or "").strip()]
    cta_meta = _as_dict(cta_metadata)
    package_ctx = _as_dict(package_diversity_context)

    if primary == "risk_warning" or any(k in text.lower() for k in ("cuidado", "error", "problema", "riesgo", "no hagas", "antes de contratar")):
        clip_angle = "warning"
        clip_value_proposition = "Advierte sobre un error común antes de contratar."
    elif primary == "myth_debunk":
        clip_angle = "myth_busting"
        clip_value_proposition = "Desmiente un mito comercial frecuente con claridad."
    elif primary == "client_objection":
        clip_angle = "objection_answer"
        clip_value_proposition = "Resuelve una objeción comercial frecuente."
    elif primary == "coverage_explanation":
        clip_angle = "coverage_explainer"
        clip_value_proposition = "Explica una cobertura de forma clara."
    elif primary == "actionable_advice":
        clip_angle = "practical_advice"
        clip_value_proposition = "Aporta un consejo práctico y accionable."
    elif primary == "everyday_example":
        clip_angle = "everyday_example"
        clip_value_proposition = "Baja el concepto a un ejemplo cotidiano."
    elif primary == "emotional_protection":
        clip_angle = "emotional_protection"
        clip_value_proposition = "Aporta tranquilidad en una decisión sensible."
    elif primary == "money_saving":
        clip_angle = "money_saving"
        clip_value_proposition = "Ayuda a ahorrar sin perder claridad."
    elif primary == "legal_admin_tramite":
        clip_angle = "legal_tramite"
        clip_value_proposition = "Sirve para campaña documental o de trámite."
    elif primary == "sensitive_decesos" or sensitive_handling_required or campaign_intent_n == "decesos":
        clip_angle = "sensitive_guidance"
        clip_value_proposition = "Acompaña una decisión sensible con sobriedad."
    elif primary == "soft_commercial_close":
        clip_angle = "soft_commercial_close"
        clip_value_proposition = "Permite un cierre comercial suave y útil."
    else:
        clip_angle = "general_insight"
        clip_value_proposition = "Aporta una idea clara y reutilizable comercialmente."

    clip_campaign_fit = {
        "campaign_intent": campaign_intent_n,
        "campaign_alignment_score": round(campaign_alignment_score_f, 4),
        "selected_for_reason": str(selected_for_reason or ""),
        "preferred_categories": list(package_ctx.get("preferred_categories") or []),
        "suppressed_categories": list(package_ctx.get("suppressed_categories") or []),
        "sensitive_handling_required": bool(sensitive_handling_required),
    }

    cta_type = str(cta_meta.get("cta_type") or cta_meta.get("recommended_cta_type") or "").strip().lower()
    if not cta_type:
        if clip_angle == "warning":
            cta_type = "avoid_mistake"
        elif clip_angle == "coverage_explainer":
            cta_type = "coverage_check"
        elif clip_angle == "objection_answer":
            cta_type = "soft_consultation"
        elif clip_angle == "emotional_protection":
            cta_type = "family_protection"
        elif clip_angle == "legal_tramite":
            cta_type = "extranjeria_safe" if campaign_intent_n == "extranjeria" else "coverage_check"
        elif clip_angle == "sensitive_guidance":
            cta_type = "sensitive_soft"
        elif clip_angle == "money_saving":
            cta_type = "savings_review"
        else:
            cta_type = "soft_consultation"

    cta_map = {
        "risk_warning": "Consulta antes de contratar",
        "warning": "Consulta antes de contratar",
        "coverage_explainer": "Revisa tu cobertura",
        "coverage_explanation": "Revisa tu cobertura",
        "objection_answer": "Resolvemos tus dudas",
        "client_objection": "Resolvemos tus dudas",
        "emotional_protection": "Protege a los tuyos",
        "family_protection": "Protege a los tuyos",
        "legal_tramite": "Verificamos que tu póliza sea válida",
        "extranjeria_safe": "Verificamos que tu póliza sea válida",
        "sensitive_guidance": "Te orientamos con calma y claridad",
        "sensitive_soft": "Te orientamos con calma y claridad",
        "money_saving": "Revisamos opciones para ahorrar",
        "savings_review": "Revisamos opciones para ahorrar",
        "soft_commercial_close": "Te orientamos sin compromiso",
        "general_insight": "Te orientamos sin compromiso",
        "practical_advice": "Te ayudamos a decidir mejor",
    }
    clip_recommended_cta = cta_map.get(cta_type, cta_map["general_insight"])
    if clip_angle == "sensitive_guidance" or sensitive_handling_required:
        clip_recommended_cta = "Te orientamos con calma y claridad"
        if clip_recommended_cta and cta_type not in {"sensitive_soft", "no_cta"}:
            cta_type = "sensitive_soft"

    raw_strength = (
        (editorial_score_f / 100.0) * 0.24
        + (hookability_score_f / 100.0) * 0.22
        + (commercial_usefulness_score_f / 100.0) * 0.24
        + (standalone_score_f / 100.0) * 0.18
        + boundary_confidence_f * 0.12
        + min(0.12, campaign_alignment_score_f * 0.12)
        - min(0.18, len(weak_penalties) * 0.025)
    )
    raw_strength = max(0.0, min(1.0, raw_strength))
    if raw_strength >= 0.68:
        confidence_label = "high"
    elif raw_strength >= 0.42:
        confidence_label = "medium"
    else:
        confidence_label = "low"

    clip_review_flags: list[str] = []
    # H14.2 Fix B: separate duration penalties (too_long, too_short) from quality penalties.
    # Suppress weak_editorial_segment when the ONLY weak penalties are duration-related AND
    # strong editorial signals are present (editorial_score >= 50, boundary_confidence >= 0.85).
    # Duration is a production constraint, not a signal of low editorial quality.
    _DURATION_ONLY_PENALTIES: set[str] = {"too_long", "too_short"}
    _quality_weak = [p for p in weak_penalties if p not in _DURATION_ONLY_PENALTIES]
    _duration_only_flag = bool(weak_penalties) and not bool(_quality_weak)
    _has_strong_editorial = editorial_score_f >= 50.0 and boundary_confidence_f >= 0.85
    if bool(_quality_weak) or editorial_score_f < 35.0:
        clip_review_flags.append("weak_editorial_segment")
        logger.info(
            "VPI_WEAK_EDITORIAL_SEGMENT_RETAINED_LOW_SIGNALS editorial=%.1f boundary=%.3f quality_penalties=%s",
            editorial_score_f, boundary_confidence_f, "|".join(_quality_weak) or "low_editorial_score",
        )
    elif _duration_only_flag and not _has_strong_editorial:
        clip_review_flags.append("weak_editorial_segment")
        logger.info(
            "VPI_WEAK_EDITORIAL_SEGMENT_RETAINED_DURATION_PENALTY_WEAK_SIGNALS editorial=%.1f boundary=%.3f duration=%s",
            editorial_score_f, boundary_confidence_f, "|".join(p for p in weak_penalties if p in _DURATION_ONLY_PENALTIES),
        )
    elif _duration_only_flag and _has_strong_editorial:
        logger.info(
            "VPI_WEAK_EDITORIAL_SEGMENT_SUPPRESSED_BY_STRONG_SIGNALS editorial=%.1f boundary=%.3f duration_penalties=%s",
            editorial_score_f, boundary_confidence_f, "|".join(p for p in weak_penalties if p in _DURATION_ONLY_PENALTIES),
        )
    if boundary_confidence_f <= 0.0:
        clip_review_flags.append("no_boundary_confidence")
        clip_review_flags.append("low_boundary_confidence")
    elif boundary_confidence_f < 0.55:
        clip_review_flags.append("low_boundary_confidence")
    if hookability_score_f and hookability_score_f < 45.0:
        clip_review_flags.append("weak_first_second")
    if campaign_intent_n != "general_vpi" and campaign_alignment_score_f < 0.35:
        clip_review_flags.append("low_campaign_alignment")
    if sensitive_handling_required:
        clip_review_flags.append("sensitive_requires_review")
    if standalone_score_f and standalone_score_f < 45.0:
        clip_review_flags.append("low_standalone_score")
    if primary in {"generic", ""} or editorial_score_f < 30.0:
        clip_review_flags.append("generic_segment")
    package_theme_distribution = _as_dict(package_ctx.get("package_theme_distribution"))
    if any(int(v) > 1 for v in package_theme_distribution.values()):
        clip_review_flags.append("too_similar_to_other_clip")
    if "payoff_may_be_cut" in weak_penalties:
        clip_review_flags.append("payoff_may_be_cut")

    clip_publish_notes = []
    if clip_review_flags:
        clip_publish_notes.append("Review flags present; use internal QC.")
    if confidence_label == "low":
        clip_publish_notes.append("Low-confidence clip; verify fit before publishing.")
    if cta_type == "sensitive_soft":
        clip_publish_notes.append("Use only soft CTA language if any.")
    if campaign_intent_n != "general_vpi":
        clip_publish_notes.append(f"Campaign fit: {campaign_intent_n}.")

    clip_brief = {
        "primary_category": primary,
        "editorial_categories": categories,
        "selected_for_reason": str(selected_for_reason or ""),
        "clip_angle": clip_angle,
        "clip_value_proposition": clip_value_proposition,
        "clip_campaign_fit": clip_campaign_fit,
        "clip_recommended_cta": clip_recommended_cta,
        "clip_confidence_label": confidence_label,
        "clip_review_flags": list(dict.fromkeys(clip_review_flags)),
        "clip_publish_notes": " ".join(clip_publish_notes).strip(),
        "editorial_score": round(editorial_score_f, 4),
        "hookability_score": round(hookability_score_f, 4),
        "commercial_usefulness_score": round(commercial_usefulness_score_f, 4),
        "standalone_score": round(standalone_score_f, 4),
        "boundary_confidence": round(boundary_confidence_f, 4),
        "campaign_alignment_score": round(campaign_alignment_score_f, 4),
        "weak_segment_penalties": list(weak_penalties),
        "sensitive_handling_required": bool(sensitive_handling_required),
    }
    logger.info(
        "VPI_CLIP_BRIEF_BUILT angle=%s confidence=%s campaign=%s review_flags=%s",
        clip_angle,
        confidence_label,
        campaign_intent_n,
        "|".join(clip_brief["clip_review_flags"]) or "none",
    )
    if confidence_label == "low":
        logger.info(
            "VPI_CLIP_BRIEF_CONFIDENCE_LOW angle=%s campaign=%s editorial=%.2f hook=%.2f commercial=%.2f standalone=%.2f boundary=%.2f campaign_alignment=%.2f",
            clip_angle,
            campaign_intent_n,
            editorial_score_f,
            hookability_score_f,
            commercial_usefulness_score_f,
            standalone_score_f,
            boundary_confidence_f,
            campaign_alignment_score_f,
        )
    if clip_review_flags:
        logger.info(
            "VPI_CLIP_BRIEF_REVIEW_FLAGGED angle=%s flags=%s",
            clip_angle,
            "|".join(clip_review_flags),
        )
    return {
        "clip_brief": clip_brief,
        "clip_angle": clip_angle,
        "clip_value_proposition": clip_value_proposition,
        "clip_campaign_fit": clip_campaign_fit,
        "clip_recommended_cta": clip_recommended_cta,
        "clip_confidence_label": confidence_label,
        "clip_review_flags": list(dict.fromkeys(clip_review_flags)),
        "clip_publish_notes": clip_brief["clip_publish_notes"],
    }


# ── v2.0 — Selection contract ───────────────────────────────────────────────────


def build_selection_contract(segment: dict[str, Any]) -> dict[str, Any]:
    """Build the selection contract metadata for the editing pipeline.

    This contract is consumed by the editing pipeline (hook engine, b-roll,
    SFX, BGM, captions, transitions) to make informed decisions.
    """
    text = str(segment.get("text") or "")
    score = score_vpi_segment(text)
    hook_pred = _predict_first3_strength(text)
    penalties = _detect_penalties(text)

    # Disfluency profile
    normalized = _normalize(text)
    tokens = normalized.split()
    filler_count = sum(1 for t in tokens if t in _FILLER_HEAVY_PATTERNS)
    disfluency_profile = {
        "filler_count": filler_count,
        "filler_ratio": round(filler_count / max(len(tokens), 1), 4),
        "has_incomplete_idea": "incomplete_idea" in penalties["penalty_types"],
        "has_generic_intro": "generic_intro" in penalties["penalty_types"],
    }

    # Recommended visual style based on segment value type
    visual_style_map: dict[str, str] = {
        "revelation": "revelation_hook",
        "risk_warning": "serious_warning",
        "myth_debunk": "serious_warning",
        "everyday_example": "clear_explanation",
        "objection_response": "clear_explanation",
        "practical_advice": "practical_advice",
        "coverage_explanation": "clear_explanation",
        "emotional_protection": "calm_trust",
        "administrative_clarity": "clear_explanation",
        "client_objection": "serious_warning",
        "money_saving": "practical_advice",
        "legal_admin_tramite": "clear_explanation",
        "soft_commercial_close": "soft_trust",
        "sensitive_decesos": "calm_trust",
    }

    # Recommended b-roll category
    broll_category_map: dict[str, str] = {
        "revelation": "meaningful_reveal",
        "risk_warning": "risk_contextual",
        "myth_debunk": "risk_contextual",
        "everyday_example": "advice_support",
        "objection_response": "advice_support",
        "practical_advice": "advice_support",
        "coverage_explanation": "paperwork_admin",
        "emotional_protection": "human_warm",
        "administrative_clarity": "paperwork_admin",
        "client_objection": "risk_contextual",
        "money_saving": "advice_support",
        "legal_admin_tramite": "paperwork_admin",
        "soft_commercial_close": "advice_support",
        "sensitive_decesos": "human_warm",
    }

    # Recommended SFX intent
    sfx_intent_map: dict[str, str] = {
        "revelation": "magic_whoosh",
        "risk_warning": "dark_riser_combo",
        "myth_debunk": "magic_whoosh",
        "everyday_example": "soft_chime",
        "objection_response": "soft_chime",
        "practical_advice": "soft_chime",
        "coverage_explanation": "no_sfx_needed",
        "emotional_protection": "soft_chime",
        "administrative_clarity": "no_sfx_needed",
        "client_objection": "dark_riser_combo",
        "money_saving": "soft_chime",
        "legal_admin_tramite": "no_sfx_needed",
        "soft_commercial_close": "soft_chime",
        "sensitive_decesos": "no_sfx_needed",
    }

    # Recommended BGM mood
    bgm_mood_map: dict[str, str] = {
        "revelation": "mysterious_curious",
        "risk_warning": "tense_cinematic",
        "myth_debunk": "mysterious_curious",
        "everyday_example": "neutral_informative",
        "objection_response": "thoughtful_serious",
        "practical_advice": "uplifting_motivational",
        "coverage_explanation": "neutral_informative",
        "emotional_protection": "warm_emotional",
        "administrative_clarity": "neutral_informative",
        "client_objection": "thoughtful_serious",
        "money_saving": "uplifting_motivational",
        "legal_admin_tramite": "neutral_informative",
        "soft_commercial_close": "warm_emotional",
        "sensitive_decesos": "sensitive_sober",
    }

    # Recommended caption style
    caption_style_map: dict[str, str] = {
        "revelation": "strong_first_beat",
        "risk_warning": "controlled_strong",
        "myth_debunk": "controlled_strong",
        "everyday_example": "clean_readable",
        "objection_response": "clean_readable",
        "practical_advice": "checklist_clear",
        "coverage_explanation": "clean_readable",
        "emotional_protection": "soft_emphasis",
        "administrative_clarity": "clean_readable",
        "client_objection": "controlled_strong",
        "money_saving": "checklist_clear",
        "legal_admin_tramite": "clean_readable",
        "soft_commercial_close": "soft_emphasis",
        "sensitive_decesos": "soft_emphasis",
    }

    editorial = score.editorial_type
    viral_audit = _viral_window_audit(segment)

    contract = {
        "segment_value_type": editorial,
        "hook_strength_score": hook_pred["predicted_first3_strength"],
        "complete_idea_score": segment.get("complete_idea_score", 0.0),
        "predicted_first3_strength": hook_pred["predicted_first3_strength"],
        "trim_to_hook_candidate": hook_pred["trim_to_hook_candidate"],
        "hook_start_offset": hook_pred["hook_start_offset"],
        "editorial_categories": list(score.editorial_categories or [editorial]),
        "hookability_score": score.hookability_score,
        "hookability_reason": score.hookability_reason,
        "commercial_usefulness_score": score.commercial_usefulness_score,
        "commercial_usefulness_reason": score.commercial_usefulness_reason,
        "standalone_score": score.standalone_score,
        "standalone_reason": score.standalone_reason,
        "weak_segment_penalties": list(score.weak_segment_penalties or []),
        "weak_segment_reason": score.weak_segment_reason,
        "segment_selection_confidence": score.segment_selection_confidence,
        "selected_for_reason": score.selected_for_reason,
        "rejected_for_reason": score.rejected_for_reason,
        "selected_window_before": viral_audit["selected_window_before"],
        "selected_window_after": viral_audit["selected_window_after"],
        "setup_context_shift_seconds": viral_audit["setup_context_shift_seconds"],
        "trailing_low_value_seconds": viral_audit["trailing_low_value_seconds"],
        "incomplete_viral_window_detected": viral_audit["incomplete_viral_window_detected"],
        "viral_window_shifted_back": viral_audit["viral_window_shifted_back"],
        "viral_window_shift_reason": viral_audit["viral_window_shift_reason"],
        "disfluency_profile": disfluency_profile,
        "recommended_visual_style": visual_style_map.get(editorial, "clear_explanation"),
        "recommended_broll_category": broll_category_map.get(editorial, "paperwork_admin"),
        "recommended_sfx_intent": sfx_intent_map.get(editorial, "no_sfx_needed"),
        "recommended_bgm_mood": bgm_mood_map.get(editorial, "neutral_informative"),
        "recommended_caption_style": caption_style_map.get(editorial, "clean_readable"),
    }

    logger.info(
        "SEGMENT_EDITORIAL_VALUE type=%s value_score=%.2f hook=%.2f "
        "complete_idea=%.2f clarity=%.2f novelty=%.2f disfluency=%.2f",
        editorial,
        segment.get("segment_value_score", 0.0),
        hook_pred["predicted_first3_strength"],
        segment.get("complete_idea_score", 0.0),
        _estimate_clarity(text),
        _estimate_novelty(text),
        penalties["disfluency_penalty"],
    )
    logger.info(
        "SEGMENT_SELECTION_REASON type=%s reason=%s",
        editorial,
        segment.get("selection_reason", "unknown"),
    )

    return contract
