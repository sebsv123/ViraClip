"""
VPI Editorial Fluency Layer — pre-render editorial intelligence.

Resolves 4 problems from human feedback:
  1. Clips cut mid-idea (incomplete ideas)
  2. Speaker disfluency (Rosa stumbles, repeats, corrects herself)
  3. Generic hooks (same hook style for all clips regardless of content)
  4. False "rich/good" quality scores (hook weak, highlights=0, broll=0)

Core principle:
  "Si un recurso visual o sonoro no mejora claridad, retención o ritmo, no se usa."

All logic is deterministic, local-only, no LLM runtime, no external APIs.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# FASE 1 — Complete Idea Boundary
# ──────────────────────────────────────────────────────────────────────

# Closure signals — phrases that indicate a complete thought
_CLOSURE_SIGNALS = [
    "por eso",
    "en realidad",
    "la clave es",
    "esto significa",
    "en definitiva",
    "es organizacion",
    "para vivir más tranquilo",
    "para vivir mas tranquilo",
    "cuando más falta hace",
    "cuando mas falta hace",
    "es estrategia",
    "es una estrategia",
    "es organizarte con cabeza",
    "existe para facilitar un momento dificil",
    "facilitar un momento dificil",
    "mejor ayuda",
    "menos carga",
    "sentido comun",
    "claridad y respaldo",
    "no es dramatizar",
    "es dejar de improvisar",
    "conviene mirar tu vida real",
    "qué tranquilidad estás buscando",
    "que tranquilidad estas buscando",
    "qué tranquilidad estáis buscando",
    "que tranquilidad estais buscando",
    "al final del día",
    "al final del dia",
    "en el fondo",
    "dicho de otra forma",
    "dicho de otro modo",
    "en otras palabras",
    "es decir",
    "o sea",
    "con esto quiero decir",
    "al final",
    "total",
    "en resumen",
    "resumiendo",
    "para que te hagas una idea",
    "para que te hagas una idea",
    "ahí está la clave",
    "ahi esta la clave",
    "ahí está",
    "ahi esta",
]

# H14.7 Fix B — conversational closure / payoff signals typical of VPI insurance
# content (cierre emocional/protección). These only count as closure when the
# transcript also carries insurance/protection/family/health/life context —
# otherwise they are too generic (e.g. "la idea es" alone) and would inflate
# complete_idea_score for unrelated content.
_VPI_CLOSURE_CONTEXT_SIGNALS = [
    "dejar las cosas bien cuidadas",
    "dejarlo bien cuidado",
    "dejarlo todo bien cuidado",
    "quedarse tranquilo",
    "quedarte tranquilo",
    "estar tranquilo",
    "para que los tuyos",
    "para proteger a tu familia",
    "para proteger a los tuyos",
    "eso es proteccion",
    "eso es protección",
    "eso es tranquilidad",
    "la idea es",
    "por eso es importante",
]

# Context terms that must be present somewhere in the transcript for
# `_VPI_CLOSURE_CONTEXT_SIGNALS` to count as a real closure/payoff.
_VPI_PROTECTION_CONTEXT_TERMS = [
    "seguro",
    "seguros",
    "proteccion",
    "protección",
    "proteger",
    "familia",
    "salud",
    "vida",
    "deceso",
    "decesos",
    "cobertura",
    "tranquilidad",
    "hipoteca",
    "ahorro",
    "responsabilidad",
    "dependen",
]

# Bad cut signals — clip ends mid-thought if it ends with these
_BAD_CUT_END_SIGNALS = [
    "cuando",
    "porque",
    "pero",
    "y ",
    "para",
    "si ",
    "aunque",
    "mientras",
    "entonces",
    "también",
    "tambien",
    "además",
    "ademas",
    "sin embargo",
    "no obstante",
    "por lo tanto",
    "por lo cual",
    "ya que",
    "puesto que",
    "debido a",
    "a causa de",
    "con tal de",
    "en caso de",
    "siempre que",
    "siempre y cuando",
    "así que",
    "asi que",
    "de modo que",
    "de manera que",
]

# Bad start signals — clip starts mid-thought if it starts with these
_BAD_START_SIGNALS = [
    "y ",
    "pero ",
    "porque ",
    "entonces ",
    "también ",
    "tambien ",
    "además ",
    "ademas ",
    "sin embargo ",
    "no obstante ",
    "por lo tanto ",
    "por lo cual ",
    "ya que ",
    "puesto que ",
    "debido a ",
    "a causa de ",
    "con tal de ",
    "en caso de ",
    "siempre que ",
    "siempre y cuando ",
    "así que ",
    "asi que ",
    "de modo que ",
    "de manera que ",
    "o sea ",
    "es decir ",
    "en otras palabras ",
]

# Development signals — phrases that indicate the speaker is developing an idea
_DEVELOPMENT_SIGNALS = [
    "por ejemplo",
    "porque",
    "así puedes",
    "asi puedes",
    "existe para",
    "para facilitar",
    "proteger",
    "protegerte",
    "ayuda",
    "tranquilidad",
    "cuando todo depende",
    "depende de ti",
    "imagínate",
    "imaginate",
    "piensa en",
    "pongamos",
    "supongamos",
    "te pongo un ejemplo",
    "te voy a poner un ejemplo",
    "porque mira",
    "verás",
    "veras",
    "fíjate",
    "fijate",
    "mira",
    "es como",
    "es decir",
    "o sea",
    "quiero decir",
    "lo que pasa es",
    "resulta que",
    "el caso es",
    "la cuestión es",
    "lo importante es",
    "lo que quiero decir",
]

# Opening signals — phrases that indicate the start of a new idea
_OPENING_SIGNALS = [
    "mira",
    "verás",
    "veras",
    "fíjate",
    "fijate",
    "piensa",
    "imagínate",
    "imaginate",
    "te voy a contar",
    "hoy vengo",
    "hoy vengo a hablarte",
    "tener un seguro",
    "la salud",
    "si eres autonomo",
    "si eres autónomo",
    "a veces",
    "te cuento",
    "sabes qué",
    "sabes que",
    "a ver",
    "vamos a ver",
    "déjame explicarte",
    "dejame explicarte",
    "déjame decirte",
    "dejame decirte",
    "lo primero",
    "lo primero que",
    "la clave es",
    "empecemos",
    "para empezar",
    "una cosa",
    "una cosa que",
    "hay algo",
    "hay algo que",
    "te explico",
    "vamos allá",
    "vamos alla",
]


def _normalize(text: str) -> str:
    """Normalize text for matching: lowercase, no accents, no punctuation."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def _word_count(text: str) -> int:
    return len([w for w in _normalize(text).split() if w])


def _contains_signal(normalized_text: str, signal: str) -> bool:
    """Check if a normalized signal appears as a whole phrase in normalized text."""
    if not normalized_text or not signal:
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(signal)}(?![a-z0-9])", normalized_text))


def _parse_transcript_lines(transcript: str) -> List[Dict[str, Any]]:
    """Parse [HH:MM:SS - HH:MM:SS] text format into structured lines."""
    pattern = re.compile(r"\[(\d{2}:\d{2}(?::\d{2})?)\s*-\s*(\d{2}:\d{2}(?::\d{2})?)\]\s*([^\[]+)")

    def parse_ts(value: str) -> float:
        parts = str(value or "0").split(":")
        try:
            if len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            return float(value)
        except Exception:
            return 0.0

    lines: List[Dict[str, Any]] = []
    for match in pattern.finditer(transcript or ""):
        text = match.group(3).strip()
        if not text:
            continue
        start = parse_ts(match.group(1))
        end = max(start, parse_ts(match.group(2)))
        normalized = _normalize(text)
        lines.append({
            "start": start,
            "end": end,
            "text": text,
            "normalized": normalized,
            "word_count": _word_count(text),
        })
    return lines


def score_complete_idea(candidate_transcript: str) -> Dict[str, Any]:
    """Score how complete an idea is in a candidate transcript.

    Returns a dict with:
      - complete_idea_score (0.0-1.0)
      - has_opening (bool)
      - has_development (bool)
      - has_closure (bool)
      - opening_signals_found (list)
      - development_signals_found (list)
      - closure_signals_found (list)
      - ends_badly (bool)
      - starts_badly (bool)
      - bad_end_signal (str)
      - bad_start_signal (str)
    """
    normalized = _normalize(candidate_transcript)
    if not normalized:
        return {
            "complete_idea_score": 0.0,
            "has_opening": False,
            "has_development": False,
            "has_closure": False,
            "opening_signals_found": [],
            "development_signals_found": [],
            "closure_signals_found": [],
            "ends_badly": False,
            "starts_badly": False,
            "bad_end_signal": "",
            "bad_start_signal": "",
        }

    # Detect opening signals
    opening_found = []
    for signal in _OPENING_SIGNALS:
        if _contains_signal(normalized, signal):
            opening_found.append(signal)

    # Detect development signals
    development_found = []
    for signal in _DEVELOPMENT_SIGNALS:
        if _contains_signal(normalized, signal):
            development_found.append(signal)

    # Detect closure signals
    closure_found = []
    for signal in _CLOSURE_SIGNALS:
        if _contains_signal(normalized, signal):
            closure_found.append(signal)

    # H14.7 Fix B — VPI conversational closure/payoff signals, gated by
    # insurance/protection/family context so generic phrases (e.g. "la idea
    # es") don't inflate complete_idea_score for unrelated content.
    has_protection_context = any(
        _contains_signal(normalized, term) for term in _VPI_PROTECTION_CONTEXT_TERMS
    )
    had_closure_before_vpi_signals = bool(closure_found)
    for signal in _VPI_CLOSURE_CONTEXT_SIGNALS:
        if not _contains_signal(normalized, signal):
            continue
        if has_protection_context:
            if signal not in closure_found:
                closure_found.append(signal)
            logger.info(
                "VPI_COMPLETE_IDEA_VPI_CLOSURE_SIGNAL_DETECTED signal=%r context=insurance_protection",
                signal,
            )
        else:
            logger.info(
                "VPI_COMPLETE_IDEA_VPI_CLOSURE_REJECTED_NO_CONTEXT signal=%r",
                signal,
            )
    if closure_found and not had_closure_before_vpi_signals and has_protection_context:
        logger.info(
            "VPI_COMPLETE_IDEA_SCORE_RECALIBRATED_VPI_CLOSURE closure_signals=%s",
            closure_found,
        )

    # Detect bad end
    bad_end = ""
    words = normalized.split()
    if words:
        last_word = words[-1]
        # Check if last word is a bad cut signal (exact match)
        for signal in _BAD_CUT_END_SIGNALS:
            sig_clean = signal.strip()
            if last_word == sig_clean:
                bad_end = signal
                break
        # Also check if the last 2-3 words form a bad cut signal
        for signal in _BAD_CUT_END_SIGNALS:
            sig_clean = signal.strip()
            if len(sig_clean.split()) > 1 and normalized.endswith(sig_clean):
                bad_end = signal
                break

    # Detect bad start
    bad_start = ""
    for signal in _BAD_START_SIGNALS:
        sig_clean = signal.strip()
        if normalized.startswith(sig_clean):
            bad_start = signal
            break

    # Compute score
    has_opening = len(opening_found) > 0
    has_development = len(development_found) > 0
    has_closure = len(closure_found) > 0
    ends_badly = bool(bad_end)
    starts_badly = bool(bad_start)

    score = 0.0
    if has_opening:
        score += 0.25
    if has_development:
        score += 0.25
    if has_closure:
        score += 0.35
    if not ends_badly:
        score += 0.10
    if not starts_badly:
        score += 0.05

    # Bonus for multiple signals in same category
    if len(opening_found) >= 2 and not starts_badly and not ends_badly:
        score = min(1.0, score + 0.05)
    if len(development_found) >= 2 and not starts_badly and not ends_badly:
        score = min(1.0, score + 0.05)
    if len(closure_found) >= 2 and not starts_badly and not ends_badly:
        score = min(1.0, score + 0.05)

    # Penalty for bad end/start
    if ends_badly:
        score = max(0.0, score - 0.20)
    if starts_badly:
        score = max(0.0, score - 0.10)

    score = max(0.0, min(1.0, score))

    return {
        "complete_idea_score": round(score, 3),
        "has_opening": has_opening,
        "has_development": has_development,
        "has_closure": has_closure,
        "opening_signals_found": opening_found,
        "development_signals_found": development_found,
        "closure_signals_found": closure_found,
        "ends_badly": ends_badly,
        "starts_badly": starts_badly,
        "bad_end_signal": bad_end,
        "bad_start_signal": bad_start,
    }


def expand_to_nearest_complete_idea(
    candidate_start_s: float,
    candidate_end_s: float,
    transcript_lines: List[Dict[str, Any]],
    *,
    max_end_expansion_s: float = 12.0,
    max_start_expansion_s: float = 5.0,
) -> Dict[str, Any]:
    """Expand clip boundaries to nearest complete idea boundary.

    Args:
        candidate_start_s: Current clip start time in seconds.
        candidate_end_s: Current clip end time in seconds.
        transcript_lines: Parsed transcript lines (from _parse_transcript_lines).
        max_end_expansion_s: Maximum seconds to extend the end.
        max_start_expansion_s: Maximum seconds to extend the start.

    Returns:
        Dict with:
          - adjusted_start_s (float)
          - adjusted_end_s (float)
          - boundary_adjustment_reason (str)
          - expanded_end_s (float or None)
          - expanded_start_s (float or None)
          - complete_idea_score (float)
    """
    if not transcript_lines:
        return {
            "adjusted_start_s": candidate_start_s,
            "adjusted_end_s": candidate_end_s,
            "boundary_adjustment_reason": "no_transcript_lines",
            "expanded_end_s": None,
            "expanded_start_s": None,
            "complete_idea_score": 0.0,
        }

    # Find lines that overlap with the candidate range
    overlapping_lines = [
        line for line in transcript_lines
        if line["start"] < candidate_end_s and line["end"] > candidate_start_s
    ]

    if not overlapping_lines:
        return {
            "adjusted_start_s": candidate_start_s,
            "adjusted_end_s": candidate_end_s,
            "boundary_adjustment_reason": "no_overlapping_lines",
            "expanded_end_s": None,
            "expanded_start_s": None,
            "complete_idea_score": 0.0,
        }

    # Build candidate transcript from overlapping lines
    candidate_text = " ".join(line["text"] for line in overlapping_lines)
    score_result = score_complete_idea(candidate_text)

    # If already complete, no expansion needed
    if score_result["complete_idea_score"] >= 0.75 and not score_result["ends_badly"]:
        return {
            "adjusted_start_s": candidate_start_s,
            "adjusted_end_s": candidate_end_s,
            "boundary_adjustment_reason": "already_complete",
            "expanded_end_s": None,
            "expanded_start_s": None,
            "complete_idea_score": score_result["complete_idea_score"],
        }

    # Try expanding end first (most common fix)
    expanded_end = None
    last_line_end = overlapping_lines[-1]["end"]
    end_expansion_used = 0.0

    if score_result["ends_badly"] or score_result["complete_idea_score"] < 0.75:
        # Look for next lines after the candidate that could complete the idea
        candidate_end_idx = -1
        for i, line in enumerate(transcript_lines):
            if line["start"] >= candidate_end_s:
                candidate_end_idx = i
                break

        if candidate_end_idx >= 0:
            # Try adding lines one by one until we find a closure or hit max expansion
            for i in range(candidate_end_idx, len(transcript_lines)):
                line = transcript_lines[i]
                additional_end = line["end"] - last_line_end
                if end_expansion_used + additional_end > max_end_expansion_s:
                    break

                # Add this line and re-evaluate
                expanded_text = candidate_text + " " + line["text"]
                expanded_score = score_complete_idea(expanded_text)

                if expanded_score["complete_idea_score"] >= 0.75 and not expanded_score["ends_badly"]:
                    expanded_end = line["end"]
                    end_expansion_used += additional_end
                    candidate_text = expanded_text
                    score_result = expanded_score
                    break
                elif expanded_score["has_closure"]:
                    # Found closure signal, accept this expansion
                    expanded_end = line["end"]
                    end_expansion_used += additional_end
                    candidate_text = expanded_text
                    score_result = expanded_score
                    break
                else:
                    # Keep expanding
                    expanded_end = line["end"]
                    end_expansion_used += additional_end
                    candidate_text = expanded_text
                    score_result = expanded_score

    # Try expanding start if still incomplete or starts badly
    expanded_start = None
    start_expansion_used = 0.0

    if score_result["complete_idea_score"] < 0.75 or score_result["starts_badly"]:
        first_line_start = overlapping_lines[0]["start"]
        candidate_start_idx = -1
        for i, line in enumerate(transcript_lines):
            if line["end"] <= candidate_start_s:
                candidate_start_idx = i

        if candidate_start_idx >= 0:
            # Try adding preceding lines one by one
            for i in range(candidate_start_idx, -1, -1):
                line = transcript_lines[i]
                additional_start = first_line_start - line["start"]
                if start_expansion_used + additional_start > max_start_expansion_s:
                    break

                expanded_text = line["text"] + " " + candidate_text
                expanded_score = score_complete_idea(expanded_text)

                if expanded_score["complete_idea_score"] >= 0.75 and not expanded_score["starts_badly"]:
                    expanded_start = line["start"]
                    start_expansion_used += additional_start
                    candidate_text = expanded_text
                    score_result = expanded_score
                    break
                elif expanded_score["has_opening"]:
                    expanded_start = line["start"]
                    start_expansion_used += additional_start
                    candidate_text = expanded_text
                    score_result = expanded_score
                    break
                else:
                    expanded_start = line["start"]
                    start_expansion_used += additional_start
                    candidate_text = expanded_text
                    score_result = expanded_score

    # Determine final boundaries
    adjusted_start = expanded_start if expanded_start is not None else candidate_start_s
    adjusted_end = expanded_end if expanded_end is not None else candidate_end_s

    # Determine reason
    if expanded_end is not None and expanded_start is not None:
        reason = "expanded_both"
    elif expanded_end is not None:
        reason = "expanded_end"
    elif expanded_start is not None:
        reason = "expanded_start"
    else:
        reason = "could_not_expand"

    return {
        "adjusted_start_s": adjusted_start,
        "adjusted_end_s": adjusted_end,
        "boundary_adjustment_reason": reason,
        "expanded_end_s": expanded_end,
        "expanded_start_s": expanded_start,
        "complete_idea_score": score_result["complete_idea_score"],
    }


# ──────────────────────────────────────────────────────────────────────
# FASE 2 — Fluency Editing
# ──────────────────────────────────────────────────────────────────────

# Filler words and BTS terms to remove
_FILLER_TERMS = {
    "ok", "vale", "bien", "aja", "ajá", "no", "eh", "este", "mmm",
    "mmh", "emmm", "ah", "oh", "uy", "uf", "bah", "puf",
}

# BTS / behind-the-scenes markers
_BTS_MARKERS = {
    "dale de nuevo", "repite", "vamos de nuevo", "otra vez",
    "se escuchó muy leído", "se escucho muy leido",
    "esa parte de nuevo", "no me gustó", "no me gusto",
    "cortamos", "vamos otra vez", "desde el principio",
    "desde ahí", "desde ahi", "desde la parte",
    "prueba", "espera", "cámara", "camara", "graba",
    "listo", "empezamos", "perfecto", "dame", "vamos",
    "ruido", "se escucha", "mira", "vamos aquí", "vamos aqui",
    "como se sube", "no lo puedo subir", "voy a leer",
    "cambio", "outfit", "hazlo de nuevo", "hazlo otra vez",
    "corta", "silencio",
}

# Auto-correction markers — speaker corrects herself mid-sentence
_AUTO_CORRECTION_MARKERS = {
    "no", "bueno", "digo", "quiero decir", "o sea",
    "mejor dicho", "es más", "es mas", "rectifico",
    "corrijo", "perdón", "perdon", "disculpa",
}


@dataclass
class FluencyEdit:
    """A single fluency edit operation."""
    type: str  # "remove_repetition", "remove_filler", "remove_bts", "remove_auto_correction"
    start_s: float
    end_s: float
    original_text: str
    reason: str
    confidence: float = 1.0


@dataclass
class FluencyEditPlan:
    """Complete fluency editing plan for a clip."""
    enabled: bool
    fluency_score_before: float
    fluency_score_after: float
    disfluency_count: int
    false_start_count: int
    repetition_groups: List[Dict[str, Any]] = field(default_factory=list)
    edits: List[Dict[str, Any]] = field(default_factory=list)
    fluency_edit_applied: bool = False
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _compute_fluency_score(text: str) -> float:
    """Compute a fluency score (0.0-1.0) for a text.

    Higher is more fluent. Penalizes:
      - Filler words
      - BTS markers
      - Auto-correction patterns
      - Immediate repetitions
    """
    normalized = _normalize(text)
    if not normalized:
        return 0.0

    words = normalized.split()
    if not words:
        return 0.0

    total_words = len(words)
    penalty = 0.0

    # Penalize filler words
    filler_count = sum(1 for w in words if w in _FILLER_TERMS)
    penalty += filler_count * 0.15

    # Penalize BTS markers
    for marker in _BTS_MARKERS:
        if _contains_signal(normalized, marker):
            penalty += 0.25

    # Penalize auto-correction markers
    for marker in _AUTO_CORRECTION_MARKERS:
        if _contains_signal(normalized, marker):
            penalty += 0.20

    # Penalize immediate repetitions (same word repeated consecutively)
    for i in range(1, len(words)):
        if words[i] == words[i - 1]:
            penalty += 0.10

    # Penalize very short utterances (likely disfluent)
    if total_words <= 3:
        penalty += 0.30

    score = max(0.0, min(1.0, 1.0 - penalty))
    return round(score, 3)


def _detect_repetition_groups(
    transcript_lines: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Detect groups of repeated/similar content in transcript lines.

    Returns list of dicts with:
      - indices: list of line indices that form a repetition group
      - text: the repeated text
      - best_index: index of the best/last version to keep
      - type: "exact_repeat" or "near_repeat"
    """
    groups: List[Dict[str, Any]] = []
    if len(transcript_lines) < 2:
        return groups

    # Look for consecutive lines with similar normalized text
    i = 0
    while i < len(transcript_lines):
        current_norm = transcript_lines[i]["normalized"]
        if not current_norm:
            i += 1
            continue

        # Look ahead for similar lines
        similar_indices = [i]
        for j in range(i + 1, len(transcript_lines)):
            next_norm = transcript_lines[j]["normalized"]
            if not next_norm:
                continue

            # Check if they share significant word overlap
            current_words = set(current_norm.split())
            next_words = set(next_norm.split())
            if len(current_words) > 0 and len(next_words) > 0:
                overlap = len(current_words & next_words)
                smaller = min(len(current_words), len(next_words))
                if smaller > 0 and overlap / smaller >= 0.6:
                    similar_indices.append(j)

        if len(similar_indices) >= 2:
            # Found a repetition group
            group_text = transcript_lines[similar_indices[0]]["text"]
            groups.append({
                "indices": similar_indices,
                "text": group_text,
                "best_index": similar_indices[-1],  # Keep the last version
                "type": "exact_repeat" if len(similar_indices) >= 2 else "near_repeat",
            })
            i = similar_indices[-1] + 1
        else:
            i += 1

    return groups


def _detect_false_starts(
    transcript_lines: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Detect false starts in transcript lines.

    A false start is a short utterance followed by a longer one on the same topic,
    or an utterance that starts with auto-correction markers.

    Returns list of dicts with:
      - index: line index of the false start
      - text: the false start text
      - reason: why it's considered a false start
    """
    false_starts: List[Dict[str, Any]] = []
    if len(transcript_lines) < 2:
        return false_starts

    for i in range(len(transcript_lines) - 1):
        current = transcript_lines[i]
        next_line = transcript_lines[i + 1]
        current_norm = current["normalized"]
        next_norm = next_line["normalized"]

        if not current_norm or not next_norm:
            continue

        # Check if current line starts with auto-correction marker
        for marker in _AUTO_CORRECTION_MARKERS:
            if current_norm.startswith(marker):
                false_starts.append({
                    "index": i,
                    "text": current["text"],
                    "reason": f"starts_with_auto_correction_{marker}",
                })
                break

        # Check if current is very short and next is much longer (abandoned start)
        current_words = len(current_norm.split())
        next_words = len(next_norm.split())
        if current_words <= 5 and next_words >= current_words * 2:
            # Check if they share topic words
            current_set = set(current_norm.split())
            next_set = set(next_norm.split())
            overlap = len(current_set & next_set)
            if overlap >= 1:
                false_starts.append({
                    "index": i,
                    "text": current["text"],
                    "reason": f"short_abandoned_start_words={current_words}_vs_{next_words}",
                })

    return false_starts


def _detect_bts_lines(
    transcript_lines: List[Dict[str, Any]],
) -> List[int]:
    """Detect lines that are behind-the-scenes / production talk.

    Returns list of line indices to remove.
    """
    bts_indices: List[int] = []
    for i, line in enumerate(transcript_lines):
        normalized = line["normalized"]
        if not normalized:
            continue

        # Check for BTS markers
        for marker in _BTS_MARKERS:
            if _contains_signal(normalized, marker):
                bts_indices.append(i)
                break

        # Check if all words are filler
        words = normalized.split()
        if words and all(w in _FILLER_TERMS for w in words):
            if i not in bts_indices:
                bts_indices.append(i)

    return bts_indices


def build_fluency_edit_plan(
    transcript_lines: List[Dict[str, Any]],
) -> FluencyEditPlan:
    """Build a fluency editing plan for a set of transcript lines.

    Detects and plans removal of:
      - Immediate repetitions
      - Auto-corrections / false starts
      - Filler words and BTS talk
      - Abandoned sentence starts

    Returns FluencyEditPlan with all detected issues and planned edits.
    """
    if not transcript_lines:
        return FluencyEditPlan(
            enabled=True,
            fluency_score_before=1.0,
            fluency_score_after=1.0,
            disfluency_count=0,
            false_start_count=0,
            fluency_edit_applied=False,
        )

    # Compute fluency before
    full_text_before = " ".join(line["text"] for line in transcript_lines)
    fluency_before = _compute_fluency_score(full_text_before)

    # Detect issues
    repetition_groups = _detect_repetition_groups(transcript_lines)
    false_starts = _detect_false_starts(transcript_lines)
    bts_indices = _detect_bts_lines(transcript_lines)

    # Build edit list
    edits: List[Dict[str, Any]] = []
    removed_indices: set[int] = set()

    # 1. Remove BTS lines
    for idx in bts_indices:
        if idx not in removed_indices:
            edits.append({
                "type": "remove_bts",
                "start_s": transcript_lines[idx]["start"],
                "end_s": transcript_lines[idx]["end"],
                "original_text": transcript_lines[idx]["text"],
                "reason": "behind_the_scenes_talk",
                "confidence": 1.0,
            })
            removed_indices.add(idx)

    # 2. Remove repetition groups (keep best/last version)
    for group in repetition_groups:
        for idx in group["indices"]:
            if idx != group["best_index"] and idx not in removed_indices:
                edits.append({
                    "type": "remove_repetition",
                    "start_s": transcript_lines[idx]["start"],
                    "end_s": transcript_lines[idx]["end"],
                    "original_text": transcript_lines[idx]["text"],
                    "reason": f"repetition_group_type={group['type']}",
                    "confidence": 0.9,
                })
                removed_indices.add(idx)

    # 3. Remove false starts
    for fs in false_starts:
        idx = fs["index"]
        if idx not in removed_indices:
            edits.append({
                "type": "remove_false_start",
                "start_s": transcript_lines[idx]["start"],
                "end_s": transcript_lines[idx]["end"],
                "original_text": transcript_lines[idx]["text"],
                "reason": fs["reason"],
                "confidence": 0.85,
            })
            removed_indices.add(idx)

    # 4. Remove filler-only lines
    for i, line in enumerate(transcript_lines):
        if i in removed_indices:
            continue
        words = line["normalized"].split()
        if words and all(w in _FILLER_TERMS for w in words):
            edits.append({
                "type": "remove_filler",
                "start_s": line["start"],
                "end_s": line["end"],
                "original_text": line["text"],
                "reason": "filler_only_line",
                "confidence": 0.95,
            })
            removed_indices.add(i)

    # Compute fluency after (simulate by removing edited lines)
    remaining_lines = [
        line for i, line in enumerate(transcript_lines) if i not in removed_indices
    ]
    full_text_after = " ".join(line["text"] for line in remaining_lines) if remaining_lines else full_text_before
    fluency_after = _compute_fluency_score(full_text_after)

    # Sort edits by start time
    edits.sort(key=lambda e: e["start_s"])

    return FluencyEditPlan(
        enabled=True,
        fluency_score_before=fluency_before,
        fluency_score_after=fluency_after,
        disfluency_count=len(edits),
        false_start_count=len(false_starts),
        repetition_groups=[{
            "text": g["text"],
            "best_index": g["best_index"],
            "type": g["type"],
            "count": len(g["indices"]),
        } for g in repetition_groups],
        edits=edits,
        fluency_edit_applied=len(edits) > 0,
        warnings=[],
    )


# ──────────────────────────────────────────────────────────────────────
# FASE 3 — Hook Fit
# ──────────────────────────────────────────────────────────────────────

# Hook intent classification patterns
_HOOK_INTENT_PATTERNS = {
    "myth_reframing": [
        "no es solo", "no es verdad", "no es cierto", "no es así",
        "no es como", "no es lo que", "no es un", "no es lujo",
        "postureo", "mito", "creencia",
        "te han dicho", "te han contado", "seguro que crees",
        "todo el mundo piensa", "la gente cree",
        "en realidad no", "realmente no",
        "eso de que", "eso es mentira",
        "déjame decirte", "dejame decirte",
    ],
    "warning_risk": [
        "cuidado", "atención", "alerta", "peligro", "riesgo",
        "ojo", "importante", "grave", "problema",
        "te puede pasar", "puede pasar", "puede ocurrir",
        "no te confíes", "no te confies",
        "esto es serio", "va en serio",
        "más vale", "mas vale",
        "antes de que", "antes de",
        "si no tienes", "si no contratas",
    ],
    "advice_practical": [
        "te voy a contar", "te voy a explicar", "te voy a decir",
        "te cuento", "te explico", "te enseño",
        "consejo", "recomendación", "recomendacion",
        "clave", "secreto", "truco",
        "paso a paso", "pasos",
        "lo que tienes que", "lo que debes",
        "aprende", "descubre",
        "mira esto", "fíjate", "fijate",
    ],
    "autonomous_business": [
        "autónomo", "autonomo", "autónomos", "autonomos",
        "emprendedor", "negocio", "profesional",
        "factura", "ingresos", "clientes",
        "trabajas por", "trabaja por",
        "por cuenta propia",
        "si eres autónomo", "si eres autonomo",
        "para autónomos", "para autonomos",
    ],
    "emotional_closure": [
        "tranquilidad", "paz", "seguridad", "protección", "proteccion",
        "familia", "hijos", "pareja", "ser querido",
        "dormir tranquilo", "dormir tranquila",
        "vivir tranquilo", "vivir tranquila",
        "estar tranquilo", "estar tranquila",
        "sin preocupaciones", "sin estrés", "sin estres",
        "lo más importante", "lo importante",
        "al final del día", "al final del dia",
        "mereces", "necesitas",
        "no te preocupes", "no te preocupes",
        "confía", "confia",
        "estar protegido", "estar protegida",
        "sentir seguro", "sentir segura",
    ],
}

# Hook intent classification thresholds
_HOOK_INTENT_MIN_MATCHES = 2
_HOOK_INTENT_MIN_CONFIDENCE = 0.30


def classify_hook_intent(
    text: str,
    *,
    editorial_type: str = "",
) -> Dict[str, Any]:
    """Classify the hook intent of a text segment.

    Returns dict with:
        - intent: str — one of the 5 intent keys or "generic"
        - confidence: float — 0.0 to 1.0
        - matched_patterns: List[str] — which patterns matched
        - match_count: int
        - total_patterns_checked: int
    """
    if not text:
        return {
            "intent": "generic",
            "confidence": 0.0,
            "matched_patterns": [],
            "match_count": 0,
            "total_patterns_checked": 0,
        }

    normalized = _normalize(text)
    best_intent = "generic"
    best_matches: List[str] = []
    best_count = 0
    best_total = 0

    for intent, patterns in _HOOK_INTENT_PATTERNS.items():
        matches = [p for p in patterns if _contains_signal(normalized, p)]
        count = len(matches)
        total = len(patterns)
        if count > best_count:
            best_intent = intent
            best_matches = matches
            best_count = count
            best_total = total

    # Confidence is editorial usefulness, not percentage of a long dictionary.
    # Two strong local signals are enough to treat an intent as clear.
    confidence = min(1.0, best_count / max(_HOOK_INTENT_MIN_MATCHES, 1)) if best_total > 0 else 0.0

    # Editorial type override: if editorial_type is known, boost confidence
    editorial_hint_map = {
        "myth_debunk": "myth_reframing",
        "risk_warning": "warning_risk",
        "client_objection": "myth_reframing",
        "objection_breaker": "myth_reframing",
        "advice": "advice_practical",
        "tutorial": "advice_practical",
        "autonomous": "autonomous_business",
        "emotional": "emotional_closure",
        "storytelling": "emotional_closure",
    }
    hint = editorial_hint_map.get(editorial_type)
    if hint and hint == best_intent:
        confidence = min(1.0, confidence + 0.15)
    elif hint and best_count == 0:
        # Editorial type suggests an intent but no patterns matched — weak signal
        best_intent = hint
        confidence = 0.15

    if best_count < _HOOK_INTENT_MIN_MATCHES and confidence < _HOOK_INTENT_MIN_CONFIDENCE:
        best_intent = "generic"
        confidence = 0.0

    return {
        "intent": best_intent,
        "confidence": round(confidence, 3),
        "matched_patterns": best_matches,
        "match_count": best_count,
        "total_patterns_checked": best_total,
    }


# Hook style mapping per intent
_HOOK_STYLE_MAP: Dict[str, List[Dict[str, Any]]] = {
    "myth_reframing": [
        {"style": "myth_buster", "template": "¿Crees que {myth}? La realidad es otra.", "weight": 1.0},
        {"style": "reframe", "template": "No es {common_belief}, es {truth}.", "weight": 0.8},
        {"style": "reveal", "template": "Te han dicho que {myth}, pero {truth}.", "weight": 0.7},
    ],
    "warning_risk": [
        {"style": "alert", "template": "Cuidado con {risk}. Esto es serio.", "weight": 1.0},
        {"style": "consequence", "template": "Si no {action}, {consequence}.", "weight": 0.9},
        {"style": "urgency", "template": "Antes de que {bad_thing}, haz esto.", "weight": 0.8},
    ],
    "advice_practical": [
        {"style": "how_to", "template": "Te voy a contar {topic}.", "weight": 1.0},
        {"style": "tip", "template": "El truco de {topic} que nadie te cuenta.", "weight": 0.9},
        {"style": "step", "template": "Paso a paso: {action}.", "weight": 0.7},
    ],
    "autonomous_business": [
        {"style": "autonomy", "template": "Si eres autónomo, {advice}.", "weight": 1.0},
        {"style": "business_tip", "template": "Esto te interesa si {condition}.", "weight": 0.8},
        {"style": "professional", "template": "Todo profesional necesita {thing}.", "weight": 0.7},
    ],
    "emotional_closure": [
        {"style": "peace", "template": "Lo que realmente importa es {value}.", "weight": 1.0},
        {"style": "reassurance", "template": "Mereces {good_thing}.", "weight": 0.9},
        {"style": "family", "template": "Tu {family_member} merece {value}.", "weight": 0.8},
    ],
    "generic": [
        {"style": "direct", "template": "{topic}.", "weight": 0.6},
        {"style": "question", "template": "¿Sabes qué? {topic}.", "weight": 0.5},
    ],
}


def choose_hook_style(
    intent: str,
    *,
    text: str = "",
    editorial_type: str = "",
) -> Dict[str, Any]:
    """Choose the best hook style for a given intent.

    Returns dict with:
        - style: str — the chosen style name
        - template: str — the template string
        - intent: str — the intent used
        - confidence: float
    """
    styles = _HOOK_STYLE_MAP.get(intent, _HOOK_STYLE_MAP["generic"])
    if not styles:
        styles = _HOOK_STYLE_MAP["generic"]

    # Pick the highest-weight style
    best = max(styles, key=lambda s: s["weight"])

    return {
        "style": best["style"],
        "template": best["template"],
        "intent": intent,
        "confidence": best["weight"],
    }


def adjust_hook_start_for_intent(
    hook_start_s: float,
    intent: str,
    *,
    duration_s: float = 0.0,
) -> float:
    """Adjust hook start time based on intent.

    - myth_reframing: start slightly earlier to grab attention
    - warning_risk: start immediately
    - advice_practical: standard start
    - autonomous_business: standard start
    - emotional_closure: allow a tiny breath before hook
    - generic: no adjustment
    """
    adjustments = {
        "myth_reframing": -0.15,
        "warning_risk": 0.0,
        "advice_practical": 0.0,
        "autonomous_business": 0.0,
        "emotional_closure": 0.10,
    }
    delta = adjustments.get(intent, 0.0)
    adjusted = max(0.0, hook_start_s + delta)
    return round(adjusted, 2)


def assess_hook_fit(
    text: str,
    *,
    editorial_type: str = "",
    hook_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assess whether the hook style fits the content.

    Returns dict with:
        - hook_fit_acceptable: bool
        - hook_fit_score: float (0.0 to 1.0)
        - hook_fit_reason: str
        - intent_classification: Dict
        - chosen_style: Dict
        - hook_start_adjustment_s: float
    """
    classification = classify_hook_intent(text, editorial_type=editorial_type)
    intent = classification["intent"]
    confidence = classification["confidence"]

    chosen = choose_hook_style(intent, text=text, editorial_type=editorial_type)

    hook_plan = hook_plan or {}
    hook_type = str(hook_plan.get("hook_type") or "").lower()

    # Acceptability rules
    if intent == "generic" and confidence < 0.2:
        acceptable = False
        reason = "no_clear_intent_detected"
        score = 0.0
    elif intent == "generic":
        acceptable = True
        reason = "generic_intent_fallback"
        score = 0.4
    elif confidence >= 0.5:
        acceptable = True
        reason = f"strong_{intent}_match"
        score = confidence
    elif confidence >= 0.3:
        acceptable = True
        reason = f"moderate_{intent}_match"
        score = confidence
    else:
        acceptable = False
        reason = f"weak_{intent}_match_confidence_{confidence}"
        score = confidence

    # If hook_type is weak_intro, always unacceptable
    if hook_type == "weak_intro":
        acceptable = False
        reason = "weak_intro_no_fit"
        score = 0.0

    start_adjustment = adjust_hook_start_for_intent(
        hook_plan.get("start_s", 0.0),
        intent,
        duration_s=hook_plan.get("duration_s", 0.0),
    )

    return {
        "hook_fit_acceptable": acceptable,
        "hook_fit_score": round(score, 3),
        "hook_fit_reason": reason,
        "intent_classification": classification,
        "chosen_style": chosen,
        "hook_start_adjustment_s": start_adjustment,
    }


# ──────────────────────────────────────────────────────────────────────
# FASE 4 — Editorial Rhythm
# ──────────────────────────────────────────────────────────────────────

@dataclass
class EditorialDecision:
    """A single editorial decision in the edit decision list."""
    action: str  # "keep", "cut", "trim", "jump_cut", "emphasis"
    start_s: float
    end_s: float
    reason: str
    source: str = ""  # "silence", "disfluency", "repetition", "pause", "emphasis"


@dataclass
class EditDecisionList:
    """Full edit decision list for a clip before final render."""
    enabled: bool
    decisions: List[EditorialDecision] = field(default_factory=list)
    total_duration_s: float = 0.0
    edited_duration_s: float = 0.0
    cuts_count: int = 0
    jump_cuts_count: int = 0
    emphasis_count: int = 0
    too_fragmented: bool = False
    fragmentation_warning: str = ""


# Minimum segment duration to keep (seconds) — shorter segments get merged
_MIN_KEEP_DURATION = 0.8

# Maximum number of cuts before clip is considered too fragmented
_MAX_CUTS_BEFORE_FRAGMENTED = 8

# Minimum pause duration to consider cutting (seconds)
_MIN_PAUSE_CUT_DURATION = 0.35

# Maximum pause duration to keep for natural rhythm (seconds)
_MAX_PAUSE_KEEP_DURATION = 0.50


def _parse_timestamp(ts: str) -> float:
    """Parse [HH:MM:SS] or [MM:SS] or float string to seconds."""
    ts = ts.strip().strip("[]")
    try:
        return float(ts)
    except ValueError:
        pass
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return 0.0


def build_edit_decision_list(
    transcript_lines: List[Dict[str, Any]],
    *,
    fluency_plan: Optional[FluencyEditPlan] = None,
    silence_plan: Optional[Dict[str, Any]] = None,
    duration_s: float = 0.0,
) -> EditDecisionList:
    """Build an edit decision list before final render.

    Decides which pauses to cut/keep, which repetitions to remove,
    micro jump cuts, and visual emphasis points.

    Args:
        transcript_lines: List of dicts with start_s, end_s, text
        fluency_plan: Optional FluencyEditPlan from FASE 2
        silence_plan: Optional silence edit plan
        duration_s: Total clip duration in seconds

    Returns:
        EditDecisionList with all editorial decisions.
    """
    decisions: List[EditorialDecision] = []
    fluency_plan = fluency_plan or FluencyEditPlan(
        enabled=False,
        fluency_score_before=1.0,
        fluency_score_after=1.0,
        disfluency_count=0,
        false_start_count=0,
    )
    silence_plan = silence_plan or {}

    if not transcript_lines:
        return EditDecisionList(
            enabled=True,
            decisions=[],
            total_duration_s=duration_s,
            edited_duration_s=duration_s,
            too_fragmented=False,
        )

    # ── 1. Process fluency edits (repetitions, false starts, BTS) ──────
    if fluency_plan.enabled and fluency_plan.edits:
        for edit in fluency_plan.edits:
            edit_type = str(edit.get("type") if isinstance(edit, dict) else getattr(edit, "type", ""))
            edit_action = "cut" if edit_type.startswith("remove_") else str(getattr(edit, "action", ""))
            edit_start = float(edit.get("start_s", 0.0) if isinstance(edit, dict) else getattr(edit, "start_s", 0.0))
            edit_end = float(edit.get("end_s", edit_start) if isinstance(edit, dict) else getattr(edit, "end_s", edit_start))
            edit_reason = str(edit.get("reason", edit_type) if isinstance(edit, dict) else getattr(edit, "reason", edit_type))
            if edit_action == "cut":
                decisions.append(EditorialDecision(
                    action="cut",
                    start_s=edit_start,
                    end_s=edit_end,
                    reason=edit_reason,
                    source="disfluency",
                ))

    # ── 2. Process silence/pause decisions ─────────────────────────────
    silence_intervals = silence_plan.get("silence_intervals") or []
    if silence_intervals:
        for interval in silence_intervals:
            sil_start = float(interval.get("start_s", 0))
            sil_end = float(interval.get("end_s", 0))
            sil_dur = sil_end - sil_start

            if sil_dur >= _MIN_PAUSE_CUT_DURATION:
                if sil_dur <= _MAX_PAUSE_KEEP_DURATION:
                    # Short pause — keep for natural rhythm
                    logger.info("[fluency-edit] preserved_pause reason=emphasis_before_closure")
                    decisions.append(EditorialDecision(
                        action="keep",
                        start_s=sil_start,
                        end_s=sil_end,
                        reason=f"natural_pause_{sil_dur:.2f}s",
                        source="pause",
                    ))
                else:
                    # Long pause — cut
                    decisions.append(EditorialDecision(
                        action="cut",
                        start_s=sil_start,
                        end_s=sil_end,
                        reason=f"long_pause_{sil_dur:.2f}s",
                        source="silence",
                    ))

    # ── 3. Detect micro jump cuts ─────────────────────────────────────
    # If two adjacent lines have very similar content, suggest jump cut
    for i in range(1, len(transcript_lines)):
        prev_text = _normalize(transcript_lines[i - 1].get("text", ""))
        curr_text = _normalize(transcript_lines[i].get("text", ""))
        if prev_text and curr_text:
            # Check word overlap
            prev_words = set(prev_text.split())
            curr_words = set(curr_text.split())
            if prev_words and curr_words:
                overlap = len(prev_words & curr_words) / max(len(prev_words | curr_words), 1)
                if overlap >= 0.60:
                    # Suggest jump cut — keep the better version
                    prev_end = transcript_lines[i - 1].get("end_s", transcript_lines[i - 1].get("end", 0))
                    curr_start = transcript_lines[i].get("start_s", transcript_lines[i].get("start", 0))
                    if curr_start > prev_end:
                        decisions.append(EditorialDecision(
                            action="jump_cut",
                            start_s=prev_end,
                            end_s=curr_start,
                            reason=f"repetitive_content_overlap_{overlap:.2f}",
                            source="repetition",
                        ))

    # ── 4. Plan visual emphasis points ────────────────────────────────
    # Mark key moments where visual emphasis could help
    for line in transcript_lines:
        text = line.get("text", "")
        normalized = _normalize(text)
        # Check for emphasis-worthy content
        emphasis_signals = [
            "importante", "clave", "secreto", "truco",
            "cuidado", "atención", "alerta",
            "nunca", "siempre", "obligatorio",
            "prohibido", "permitido",
        ]
        if any(sig in normalized for sig in emphasis_signals):
            decisions.append(EditorialDecision(
                action="emphasis",
                start_s=line.get("start_s", line.get("start", 0)),
                end_s=line.get("end_s", line.get("end", 0)),
                reason=f"emphasis_signal_{next((s for s in emphasis_signals if s in normalized), 'unknown')}",
                source="emphasis",
            ))

    # ── 5. Sort decisions by start time ───────────────────────────────
    decisions.sort(key=lambda d: d.start_s)

    # ── 6. Merge overlapping decisions ────────────────────────────────
    merged: List[EditorialDecision] = []
    for decision in decisions:
        if merged and decision.start_s < merged[-1].end_s:
            # Overlapping — keep the more important action
            prev = merged[-1]
            if decision.action == "cut" and prev.action != "cut":
                # Cut takes priority
                prev.action = "cut"
                prev.end_s = max(prev.end_s, decision.end_s)
                prev.reason = f"merged_{prev.reason}_{decision.reason}"
            elif decision.action == "emphasis" and prev.action != "cut":
                prev.end_s = max(prev.end_s, decision.end_s)
                prev.reason = f"merged_{prev.reason}_{decision.reason}"
            else:
                # Extend the existing decision
                prev.end_s = max(prev.end_s, decision.end_s)
        else:
            merged.append(decision)

    # ── 7. Check for fragmentation ────────────────────────────────────
    cuts_count = sum(1 for d in merged if d.action == "cut")
    jump_cuts_count = sum(1 for d in merged if d.action == "jump_cut")
    emphasis_count = sum(1 for d in merged if d.action == "emphasis")
    total_cuts = cuts_count + jump_cuts_count

    too_fragmented = total_cuts > _MAX_CUTS_BEFORE_FRAGMENTED
    fragmentation_warning = ""
    if too_fragmented:
        fragmentation_warning = (
            f"clip_has_{total_cuts}_cuts_exceeds_max_{_MAX_CUTS_BEFORE_FRAGMENTED}"
        )

    # Compute edited duration
    total_cut_duration = sum(
        d.end_s - d.start_s
        for d in merged
        if d.action in ("cut", "jump_cut")
    )
    edited_duration = max(0.0, duration_s - total_cut_duration)

    return EditDecisionList(
        enabled=True,
        decisions=merged,
        total_duration_s=round(duration_s, 2),
        edited_duration_s=round(edited_duration, 2),
        cuts_count=cuts_count,
        jump_cuts_count=jump_cuts_count,
        emphasis_count=emphasis_count,
        too_fragmented=too_fragmented,
        fragmentation_warning=fragmentation_warning,
    )


# ──────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────


def assess_editorial_fluency(
    text: str,
    transcript: str = "",
    *,
    editorial_type: str = "",
    hook_plan: Optional[Dict[str, Any]] = None,
    silence_plan: Optional[Dict[str, Any]] = None,
    duration_s: float = 0.0,
) -> Dict[str, Any]:
    """Main entry point for the Editorial Fluency Layer.

    Runs all FASEs in sequence and returns a combined result dict.

    Args:
        text: The clip text content
        transcript: Raw transcript string (for FASE 1 boundary detection)
        editorial_type: Editorial type hint
        hook_plan: Existing hook plan dict
        silence_plan: Existing silence edit plan dict
        duration_s: Clip duration in seconds

    Returns:
        Dict with all fluency assessment results.
    """
    result: Dict[str, Any] = {
        "editorial_fluency_enabled": True,
    }

    # ── FASE 1: Complete Idea Boundary ────────────────────────────────
    transcript_lines = _parse_transcript_lines(transcript) if transcript else []
    if not transcript_lines and text:
        # Gate calls often have plain clip text but no timestamped transcript.
        # Split into synthetic sentence lines so fluency/rhythm checks still run
        # deterministically instead of silently assuming the clip is complete.
        sentence_parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
        if not sentence_parts:
            sentence_parts = [text.strip()]
        step = (float(duration_s) / max(len(sentence_parts), 1)) if duration_s else 1.0
        transcript_lines = [
            {
                "start": round(i * step, 2),
                "end": round((i + 1) * step, 2),
                "text": part,
                "normalized": _normalize(part),
                "word_count": _word_count(part),
            }
            for i, part in enumerate(sentence_parts)
        ]

    idea_source = transcript if transcript else text
    score_result = score_complete_idea(idea_source)
    idea_score = float(score_result.get("complete_idea_score", 0.0))
    result.update(score_result)
    result["complete_idea_assessment"] = (
        "complete" if idea_score >= 0.75
        else "partial" if idea_score >= 0.50
        else "incomplete"
    )
    if transcript_lines and (idea_score < 0.75 or score_result.get("ends_badly") or score_result.get("starts_badly")):
        expansion = expand_to_nearest_complete_idea(0, duration_s, transcript_lines)
        result["complete_idea_expansion"] = expansion
        if expansion.get("complete_idea_score", 0.0) > idea_score:
            result["complete_idea_score"] = float(expansion.get("complete_idea_score", idea_score))
            result["complete_idea_assessment"] = (
                "complete" if result["complete_idea_score"] >= 0.75
                else "partial" if result["complete_idea_score"] >= 0.50
                else "incomplete"
            )

    # ── FASE 2: Fluency Editing ───────────────────────────────────────
    fluency_plan = build_fluency_edit_plan(transcript_lines) if transcript_lines else FluencyEditPlan(enabled=False)
    result["fluency_plan"] = asdict(fluency_plan)
    result["fluency_score_before"] = fluency_plan.fluency_score_before
    result["fluency_score_after"] = fluency_plan.fluency_score_after
    result["disfluency_count"] = fluency_plan.disfluency_count
    result["false_start_count"] = fluency_plan.false_start_count
    result["repetition_groups"] = fluency_plan.repetition_groups
    result["fluency_edit_applied"] = fluency_plan.fluency_edit_applied

    # ── FASE 3: Hook Fit ──────────────────────────────────────────────
    hook_fit = assess_hook_fit(text, editorial_type=editorial_type, hook_plan=hook_plan)
    result["hook_fit"] = hook_fit

    # ── FASE 4: Editorial Rhythm ──────────────────────────────────────
    edit_list = build_edit_decision_list(
        transcript_lines,
        fluency_plan=fluency_plan,
        silence_plan=silence_plan,
        duration_s=duration_s,
    )
    result["edit_decision_list"] = asdict(edit_list)

    # ── Summary ───────────────────────────────────────────────────────
    fluency_score_before = fluency_plan.fluency_score_before
    fluency_score_after = fluency_plan.fluency_score_after
    hook_fit_acceptable = hook_fit.get("hook_fit_acceptable", False)
    idea_complete = result["complete_idea_assessment"] == "complete"

    # Overall editorial fluency score (0-1)
    overall = 0.0
    components = 0
    if idea_complete:
        overall += 0.25
    components += 1
    overall += fluency_score_after * 0.35
    overall += (1.0 if hook_fit_acceptable else 0.3) * 0.25
    if not edit_list.too_fragmented:
        overall += 0.15
    overall = min(1.0, overall)

    result["editorial_fluency_score"] = round(overall, 3)
    result["editorial_fluency_warnings"] = []
    if not idea_complete:
        result["editorial_fluency_warnings"].append("incomplete_idea")
    if fluency_score_after < 0.70:
        result["editorial_fluency_warnings"].append("low_fluency")
    if not hook_fit_acceptable:
        result["editorial_fluency_warnings"].append("hook_fit_unacceptable")
    if edit_list.too_fragmented:
        result["editorial_fluency_warnings"].append("too_fragmented")

    return result
