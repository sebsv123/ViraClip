"""Local heuristic editorial scorer for VPI insurance-first clip selection."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
import unicodedata
from typing import Iterable


@dataclass(frozen=True)
class VPIEditorialScore:
    vpi_score: float
    matched_patterns: list[str]
    editorial_type: str
    reason: str
    suggested_broll_cue_type: str | None = None
    generic_penalty: float = 0.0


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
}

_TYPE_PRIORITY = {
    "risk_warning": 80,
    "myth_debunk": 70,
    "client_objection": 60,
    "actionable_advice": 50,
    "emotional_protection": 40,
    "coverage_explanation": 30,
    "revelation": 20,
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

_GENERIC_PATTERNS = (
    "esto es muy importante",
    "muy importante",
    "tienes que saberlo",
    "recuerda esto",
    "al final",
    "en definitiva",
    "como siempre",
)


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


def score_vpi_segment(text: str) -> VPIEditorialScore:
    """Score a Spanish transcript segment for VPI editorial/commercial value."""
    normalized = _normalize(text)
    _debug = os.environ.get("VIRACLIP_DEBUG_VPI_SCORER", "false").lower() == "true"
    if _debug:
        import logging as _log
        _log.getLogger(__name__).info(
            "[vpi-scorer-debug] raw_preview=%s... normalized_preview=%s... "
            "text_len=%d normalized_len=%d",
            (text or "")[:220], normalized[:220],
            len(text or ""), len(normalized),
        )
    if not normalized:
        return VPIEditorialScore(
            vpi_score=0.0,
            matched_patterns=[],
            editorial_type="generic",
            reason="empty segment",
            generic_penalty=18.0,
        )

    type_scores: dict[str, float] = {}
    type_matches: dict[str, list[str]] = {}
    broll_by_type: dict[str, str | None] = {}
    for editorial_type, (weight, broll_cue, patterns) in _PATTERNS.items():
        matches = _contains_any(normalized, patterns)
        if _debug:
            _log.getLogger(__name__).info(
                "[vpi-scorer-debug] type=%s patterns=%d matches=%d first_pattern=%s",
                editorial_type, len(patterns), len(matches),
                patterns[0] if patterns else "-",
            )
        if not matches:
            continue
        # Reward multiple matches, but cap per type to avoid keyword stuffing.
        effective_weight = weight
        if (
            editorial_type == "coverage_explanation"
            and set(_normalize(match) for match in matches).issubset(_LOW_SIGNAL_COVERAGE_PATTERNS)
        ):
            effective_weight = 10.0
        type_scores[editorial_type] = min(
            effective_weight + (len(matches) - 1) * 6.0,
            effective_weight + 12.0,
        )
        type_matches[editorial_type] = matches
        broll_by_type[editorial_type] = broll_cue

    generic_penalty = 0.0
    generic_matches = _contains_any(normalized, _GENERIC_PATTERNS)
    if generic_matches:
        generic_penalty += 14.0
    if len(normalized.split()) < 7:
        generic_penalty += 8.0
    if not _contains_any(normalized, _COMMERCIAL_TERMS):
        generic_penalty += 8.0

    if not type_scores:
        return VPIEditorialScore(
            vpi_score=max(0.0, 18.0 - generic_penalty),
            matched_patterns=generic_matches,
            editorial_type="generic",
            reason="Intro genérica sin patrones editoriales fuertes.",
            generic_penalty=generic_penalty,
        )

    editorial_type = max(
        type_scores,
        key=lambda key: (type_scores[key], _TYPE_PRIORITY.get(key, 0)),
    )
    raw_score = 40.0 + sum(type_scores.values()) * 0.75
    if len(type_scores) >= 2:
        raw_score += 8.0
    vpi_score = max(0.0, min(100.0, raw_score - generic_penalty))
    primary_patterns = type_matches.get(editorial_type, [])[:5]
    supporting_patterns = [
        pattern
        for key, patterns in type_matches.items()
        if key != editorial_type
        for pattern in patterns
    ]
    ordered_patterns = _dedupe_patterns([*type_matches.get(editorial_type, []), *supporting_patterns])
    reason_by_type = {
        "client_objection": "Detecta objeción comercial del cliente",
        "myth_debunk": "Desmonta mito u objeción frecuente",
        "risk_warning": "Detecta advertencia de riesgo o posible desprotección",
        "revelation": "Detecta momento de revelación o cambio de perspectiva",
        "coverage_explanation": "Explica cobertura o contexto asegurador",
        "emotional_protection": "Detecta protección familiar/responsabilidad",
        "actionable_advice": "Detecta consejo accionable para contratar o revisar",
    }
    reason = reason_by_type.get(editorial_type, f"Detecta {editorial_type}")
    if primary_patterns:
        reason += f": {', '.join(primary_patterns)}."
    else:
        reason += "."
    supporting = [key for key in type_scores if key != editorial_type]
    if supporting:
        reason += f" Refuerzo: {', '.join(supporting)}."

    return VPIEditorialScore(
        vpi_score=round(vpi_score, 2),
        matched_patterns=ordered_patterns[:8],
        editorial_type=editorial_type,
        reason=reason,
        suggested_broll_cue_type=broll_by_type.get(editorial_type),
        generic_penalty=round(generic_penalty, 2),
    )


class VPIEditorialScorer:
    """Small wrapper for call sites that prefer a service-style object."""

    def score(self, text: str) -> VPIEditorialScore:
        return score_vpi_segment(text)
