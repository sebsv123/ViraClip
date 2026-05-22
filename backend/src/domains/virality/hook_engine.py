"""
Hook Engine — Phase 9 Creative Engine

Identifies the most impactful hook moment and flags whether the clip
already starts with it or needs reordering.
"""

import logging
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)

# ── Insurance trigger words ─────────────────────────────────────────────────────
_INSURANCE_TRIGGER_WORDS: List[str] = [
    "seguro", "seguros", "aseguradora", "póliza", "cobertura",
    "prima", "siniestro", "indemnización", "reclamación",
    "vida", "coche", "hogar", "mutua", "protección",
    "ahorro", "tranquilidad", "contrato", "fallecimiento",
    "accidente", "precio", "presupuesto", "asegurado",
    "beneficiario", "deducible", "franquicia", "renovación",
    "cancelación", "asistencia", "defensa jurídica",
    "responsabilidad civil", "todo riesgo", "daños",
    "robo", "incendio", "inundación", "desempleo",
    "enfermedad", "hospitalización", "cirugía",
    "medicamentos", "reembolso", "copago",
    "pensión", "jubilación", "inversión",
    "hipoteca", "préstamo", "crédito",
]

# ── Insurance-native hook signals ───────────────────────────────────────────────
# Preferred hooks for insurance content: concrete, Spanish, insurance-domain.
_INSURANCE_HOOK_SIGNALS: List[tuple[str, float]] = [
    ("protección", 0.95),
    ("ahorro", 0.93),
    ("familia", 0.90),
    ("reclamación", 0.92),
    ("cobertura", 0.92),
    ("responsabilidad", 0.90),
    ("urgencia", 0.88),
    ("urgente", 0.88),
    ("siniestro", 0.90),
    ("indemnización", 0.90),
    ("póliza", 0.92),
    ("contrato", 0.85),
    ("beneficiario", 0.88),
    ("deducible", 0.85),
    ("franquicia", 0.85),
    ("renovación", 0.85),
    ("cancelación", 0.85),
    ("asistencia", 0.85),
    ("defensa jurídica", 0.90),
    ("responsabilidad civil", 0.92),
    ("todo riesgo", 0.88),
    ("daños", 0.85),
    ("robo", 0.85),
    ("incendio", 0.85),
    ("inundación", 0.85),
    ("desempleo", 0.85),
    ("enfermedad", 0.85),
    ("hospitalización", 0.88),
    ("cirugía", 0.85),
    ("medicamentos", 0.85),
    ("reembolso", 0.88),
    ("copago", 0.85),
    ("pensión", 0.85),
    ("jubilación", 0.85),
    ("inversión", 0.85),
    ("hipoteca", 0.85),
    ("préstamo", 0.85),
    ("crédito", 0.85),
    ("aprobación", 0.85),
    ("documentos", 0.80),
    ("firma", 0.82),
    ("asesor", 0.85),
    ("consulta", 0.82),
    ("llamada", 0.78),
    ("presupuesto", 0.85),
    ("ahorrar", 0.88),
    ("proteger", 0.92),
    ("asegurado", 0.88),
    ("siniestrado", 0.85),
    ("peritaje", 0.85),
    ("tramitación", 0.85),
]

# ── Generic hook signals REJECTED for insurance content ─────────────────────────
_GENERIC_REJECTED_HOOK_SIGNALS: List[str] = [
    "increíble", "impresionante", "amazing", "unbelievable",
    "shocking", "secreto", "secret", "descubre", "discover",
    "truco", "mira", "espera", "wait", "listen",
    "nunca", "never", "siempre",
]

HOOK_SIGNALS: "list[tuple[str, float]]" = [
    # Spanish hooks (high priority)
    ("¿", 0.90),
    ("?", 0.90),
    ("te voy a contar", 0.92),
    ("te voy a decir", 0.92),
    ("lo que nadie te dice", 0.95),
    ("la verdad sobre", 0.90),
    ("nadie te lo dice", 0.92),
    ("esto es lo que", 0.85),
    ("esto cambia", 0.88),
    ("el secreto", 0.88),
    ("la clave", 0.85),
    ("3 cosas", 0.88),
    ("5 cosas", 0.88),
    ("10 cosas", 0.88),
    ("número", 0.80),
    ("truco", 0.82),
    ("error", 0.80),
    ("nunca", 0.88),
    ("siempre", 0.75),
    ("secreto", 0.85),
    ("descubre", 0.80),
    ("increíble", 0.82),
    ("impresionante", 0.78),
    ("espera", 0.75),
    ("mira", 0.72),
    ("escucha", 0.72),
    ("para", 0.70),
    ("stop", 0.75),
    ("atención", 0.80),
    ("importante", 0.82),
    ("urgente", 0.85),
    ("cuidado", 0.78),
    ("alerta", 0.80),
    # English hooks (existing)
    ("never", 0.88),
    ("secret", 0.85),
    ("discover", 0.80),
    ("amazing", 0.78),
    ("wait", 0.75),
    ("listen", 0.72),
    ("shocking", 0.85),
    ("unbelievable", 0.85),
]


def _is_insurance_content(words: "list[dict]") -> bool:
    """Detect if the transcript is about insurance content using trigger words."""
    transcript = " ".join(w.get("word", "") for w in words).lower()
    for trigger in _INSURANCE_TRIGGER_WORDS:
        if trigger.lower() in transcript:
            logger.info("[HookEngine] Insurance content detected via trigger word '%s'", trigger)
            return True
    return False


HOOK_WINDOW_S = 3.0  # candidate must appear in first 3s to be "already optimized"


@dataclass
class HookResult:
    hook_start: float       # seconds into segment
    hook_end: float
    hook_text: str
    hook_score: float       # 0–1
    reorder: bool           # True → hook is not in first 3s, suggest reordering
    already_optimized: bool


class HookEngine:
    """
    Scans word-level transcript for the strongest hook candidate
    and returns positioning metadata.
    """

    def find_best_hook(
        self,
        words: "list[dict]",
        segment_duration: float,
    ) -> HookResult:
        """
        Args:
            words:              Word dicts relative to segment (t=0 at clip start).
            segment_duration:   Total clip duration in seconds.
        """
        if not words:
            return HookResult(0.0, 0.0, "", 0.0, False, True)

        # Detect insurance content to select appropriate hook signals
        is_insurance = _is_insurance_content(words)
        if is_insurance:
            logger.info("[HookEngine] Using insurance-native hook signals, rejecting generic hooks")

        best_score = 0.0
        best_idx = 0

        for i, w in enumerate(words):
            word = w.get("word", "").lower().strip(".,!?¡¿\"'")
            raw = w.get("word", "")
            t = float(w.get("start", 0.0))

            # Determine which signals to scan based on content type
            signals_to_check: "list[tuple[str, float]]" = list(HOOK_SIGNALS)

            if is_insurance:
                # For insurance content: prefer insurance-native signals,
                # reject generic viral hooks
                signals_to_check = list(_INSURANCE_HOOK_SIGNALS)
                # Also keep question marks and urgency signals
                signals_to_check.extend([
                    ("¿", 0.90), ("?", 0.90),
                    ("urgente", 0.88), ("urgencia", 0.88),
                    ("importante", 0.85), ("atención", 0.85),
                    ("cuidado", 0.85), ("alerta", 0.85),
                    ("stop", 0.80), ("para", 0.80),
                    ("error", 0.85), ("nunca", 0.85),
                    ("te voy a contar", 0.92), ("te voy a decir", 0.92),
                    ("lo que nadie te dice", 0.95), ("la verdad sobre", 0.90),
                    ("nadie te lo dice", 0.92), ("esto es lo que", 0.85),
                    ("esto cambia", 0.88), ("la clave", 0.85),
                    ("3 cosas", 0.88), ("5 cosas", 0.88), ("10 cosas", 0.88),
                    ("número", 0.80),
                ])

            for signal, base_score in signals_to_check:
                if signal in word or signal in raw:
                    # Penalise late appearances slightly
                    pos_factor = 1.0 if t <= segment_duration * 0.25 else 0.85
                    # Bonus if followed by emphasis punctuation
                    next_raw = words[i + 1].get("word", "") if i + 1 < len(words) else ""
                    emphasis = 1.1 if ("!" in next_raw or "?" in next_raw) else 1.0
                    effective = base_score * pos_factor * emphasis
                    if effective > best_score:
                        best_score = effective
                        best_idx = i

        if best_score == 0.0:
            logger.info("[HookEngine] No hook signal found (score=0)")
            return HookResult(0.0, 0.0, "", 0.0, False, True)

        bw = words[best_idx]
        snippet_words = words[max(0, best_idx - 2): best_idx + 5]
        hook_text = " ".join(x.get("word", "") for x in snippet_words).strip()
        hook_start = float(bw.get("start", 0.0))
        hook_end = float(bw.get("end", hook_start + 0.5))

        already_optimized = hook_start <= HOOK_WINDOW_S
        reorder = not already_optimized and best_score >= 0.6

        logger.info(
            "[HookEngine] Selected hook: score=%.3f text='%s' start=%.3fs reorder=%s",
            best_score, hook_text, hook_start, reorder,
        )

        return HookResult(
            hook_start=round(hook_start, 3),
            hook_end=round(hook_end, 3),
            hook_text=hook_text,
            hook_score=round(best_score, 3),
            reorder=reorder,
            already_optimized=already_optimized,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: "HookEngine | None" = None


def get_hook_engine() -> HookEngine:
    global _engine
    if _engine is None:
        _engine = HookEngine()
    return _engine
