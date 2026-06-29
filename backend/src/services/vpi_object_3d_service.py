"""
vpi_object_3d_service.py — OUTPUT-OBJECTS-3D-53.

Selection logic for a single contextual REAL 3D object per clip. This service does NOT
re-implement semantic classification: it REUSES the contextual intent + phrase-targeted
windowing intelligence already proven in `vpi_object_2d` (VISUALS-42/43/52C) and only adds:

  * the intent → real-3D-family map (4 families),
  * a STRICTER 3D gate (FASE 8: semantic_score >= 0.82, normalized margin >= 0.15, an
    explicit STRONG phrase, and the family must literally represent the concept),
  * phrase-targeted windowing 1.4–2.0s that never lands on the hook or final fade and never
    overlaps strong B-roll / card / punch (FASE 9),
  * safe-area placement (FASE 10) + the reveal variant that matches the chosen side.

Geometry/rendering live entirely offline (Remotion+three.js → alpha cache). This module is
pure decision logic: no file I/O, no rendering. Resolver order (B-roll > 3D > card > 2D) and
the ffmpeg composite are applied by the caller (FASE 7/11).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .vpi_object_2d import classify_visual_intent, place_object_best_phrase

logger = logging.getLogger(__name__)

# ── 53B gate calibration ─────────────────────────────────────────────────────
# Root cause (see checkpoints/output_objects_3d_53b_gate_calibration): the 2D semantic_score
# is min(1, top_score/8); a SINGLE strong literal token caps at 0.5, so the old flat 0.82 gate
# was unreachable by a single literal phrase ("antes de viajar", "proteger a tu familia"). The
# "max possible" is non-deterministic (top ranged 4→22 on real phrases), so normalising by a
# fixed max is impossible — we use an EVIDENCE-TIER policy (FASE 4 Preferencia 2) instead.
#
#   TIER A — LITERAL_STRONG: an explicit phrase from the family's curated literal-object set,
#            strong, no exclusions, margin>=0.30, raw_score>=LITERAL_FLOOR. Accept.
#   TIER B — INFERRED: everything else keeps the strict normalised gate (0.82 / margin 0.15).
#
# This does NOT lower the global gate: inferred/contextual matches still need 0.82. It only adds
# a literal fast-path for explicit object phrases, and EXCLUDES generic emotionals (tranquilidad,
# respaldo, …) that are 2D-strong but are NOT literal 3D objects.
GATE_VERSION = "3d-gate-53b-v1"
MIN_SEMANTIC_SCORE_3D = 0.82       # TIER B (INFERRED) only — unchanged
MIN_MARGIN_NORM_3D = 0.15          # TIER B (INFERRED) only — unchanged
# LITERAL_FLOOR derived from the real distribution (score_distribution.md): a single strong
# literal token = top_score 4 / 8 = 0.5. That is the minimum genuine literal match. NOT hardcoded
# from one observation — it is the structural floor of "exactly one strong literal phrase".
LITERAL_FLOOR = 0.5
LITERAL_MIN_MARGIN_NORM = 0.30
HOOK_SEPARATION_S = 4.0          # FASE 9: window must sit >=4s after the hook
DEFAULT_HOOK_END_S = 3.0
WINDOW_TARGET_MIN_S = 1.4
WINDOW_HARD_MAX_S = 2.0

# ── FASE 3 — exactly 4 families. intent → real 3D asset_id ───────────────────────
_INTENT_TO_3D: Dict[str, str] = {
    "travel_assistance": "travel_suitcase_3d",
    "documents_admin": "document_passport_3d",
    "emotional_protection": "protection_shield_3d",
    "health_access": "health_heart_3d",
}
VALID_3D_ASSETS = frozenset(_INTENT_TO_3D.values())
VALID_VARIANTS = ("reveal_left", "reveal_right")
VALID_PLACEMENTS = ("upper_left", "upper_right", "mid_left", "mid_right")

# ── FASE 3 — TIER A literal-object phrases per family (normalised, accent-free) ──
# Only phrases that LITERALLY denote the object/concept the family renders. Curated from the 2D
# evidence map, with generic emotionals removed. A match here is a literal 3D object cue.
_LITERAL_PHRASES_BY_FAMILY: Dict[str, frozenset] = {
    "travel_suitcase_3d": frozenset({
        "viaje", "viajar", "antes de viajar", "al extranjero", "en el extranjero",
        "equipaje", "maleta", "aeropuerto", "desplazamiento", "asistencia fuera",
    }),
    "document_passport_3d": frozenset({
        "pasaporte", "visado", "documentacion", "residencia", "certificado",
    }),
    "protection_shield_3d": frozenset({
        "proteger a", "protege a", "proteger a tu familia", "tu familia", "a tu familia",
        "los tuyos", "seres queridos", "cuidar de",
    }),
    "health_heart_3d": frozenset({
        "salud no avisa", "la salud no siempre avisa", "atencion sanitaria", "acudir al medico",
        "acceso a especialistas", "consulta medica", "prueba medica", "hospital",
    }),
}
# Generic/abstract tokens that are 2D-strong but must NEVER count as a literal 3D object.
# (FASE 6: tranquilidad / respaldo / por si acaso / problema / importante / seguro / cuidado …)
_NON_LITERAL_STRONG = frozenset({
    "tranquilidad", "respaldo", "calma", "seguridad", "proteccion",
    "por si acaso", "imprevisto", "cuidado con", "problema", "importante", "seguro",
})


@dataclass(frozen=True)
class Object3DDecision:
    intent: str
    asset_id: str
    phrase: str
    phrase_start_s: float
    phrase_end_s: float
    window_start_s: float
    window_end_s: float
    semantic_score: float
    placement: str
    animation_variant: str
    reason: str
    evidence_tier: str = "INFERRED"      # LITERAL_STRONG | INFERRED
    raw_score: float = 0.0
    normalized_score: float = 0.0
    literal_match: bool = False
    gate_reason: str = ""
    gate_version: str = GATE_VERSION


def classify_evidence_tier(asset_id: str, candidate_phrases: List[Dict[str, str]]) -> Dict[str, Any]:
    """FASE 3 — decide the evidence tier for a family + its strong phrases.

    Returns {tier, literal_match, literal_phrase}. TIER A (LITERAL_STRONG) requires a STRONG
    candidate whose normalised phrase is in the family's literal-object set AND is not a generic
    non-literal token. Everything else is TIER B (INFERRED).
    """
    literal_set = _LITERAL_PHRASES_BY_FAMILY.get(asset_id, frozenset())
    for c in candidate_phrases or []:
        if str(c.get("evidence_strength")) != "strong":
            continue
        norm = str(c.get("matched_norm") or "").strip()
        if not norm or norm in _NON_LITERAL_STRONG:
            continue
        if norm in literal_set:
            return {"tier": "LITERAL_STRONG", "literal_match": True, "literal_phrase": c}
    return {"tier": "INFERRED", "literal_match": False, "literal_phrase": None}


def resolve_visual_coverage_choice(
    *,
    broll_strong: bool,
    object_3d_decision: Optional["Object3DDecision"],
    card_available: bool,
    object_2d_available: bool,
) -> str:
    """FASE 7 — single source of truth for the visual-coverage resolver order.

    B-roll (strong) > real 3D object > card > 2D object > none. Exactly ONE wins; 3D and 2D
    are never chosen together. When 3D fails (decision is None) the chain falls through to
    card/2D so the clip never loses its reinforcement.
    """
    if broll_strong:
        return "broll"
    if object_3d_decision is not None:
        return "object_3d"
    if card_available:
        return "card"
    if object_2d_available:
        return "object_2d"
    return "none"


def intent_to_asset_3d(intent: str) -> str:
    """Map a contextual intent to its literal 3D family (or '' if none represents it)."""
    return _INTENT_TO_3D.get((intent or "").strip().lower(), "")


def _words_to_text(words: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for w in words or []:
        tok = str(w.get("word") or w.get("text") or "").strip()
        if tok:
            parts.append(tok)
    return " ".join(parts)


def _has_strong_phrase(candidate_phrases: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    for c in candidate_phrases or []:
        if str(c.get("evidence_strength")) == "strong":
            return c
    return None


def _broll_covers_window(existing_visuals: Dict[str, Any]) -> bool:
    """FASE 7: a strong B-roll in the same window suppresses 3D entirely."""
    ev = existing_visuals or {}
    if ev.get("broll_strong") or ev.get("strong_broll_present"):
        return True
    # explicit list of strong broll spans
    for span in ev.get("broll_spans", []) or []:
        if float(span.get("strength", 0.0) or 0.0) >= 0.7:
            return True
    return False


def _avoid_intervals(existing_visuals: Dict[str, Any]) -> List[Tuple[float, float, float]]:
    """Collision spans the 3D window must not overlap: B-roll / card / 2D object / punch."""
    ev = existing_visuals or {}
    out: List[Tuple[float, float, float]] = []
    for key in ("broll_spans", "card_spans", "object_2d_spans", "punch_spans", "transition_spans"):
        for span in ev.get(key, []) or []:
            try:
                a = float(span.get("start_s"))
                b = float(span.get("end_s"))
            except (TypeError, ValueError):
                continue
            if b > a:
                out.append((a, b, 0.25))
    return out


def _choose_placement_and_variant(existing_visuals: Dict[str, Any]) -> Tuple[str, str]:
    """FASE 10: pick a safe side. Never centre over the face. Place opposite the face when its
    side is known; the reveal variant matches the entry side (reveal_left enters from the left).
    Captions live at the bottom, so prefer the UPPER band."""
    ev = existing_visuals or {}
    face_side = str(ev.get("face_side") or "").lower()       # "left" | "right" | "center" | ""
    captions_band = str(ev.get("captions_band") or "bottom").lower()
    # default: object on the right, entering from the right
    side = "right"
    if face_side == "right":
        side = "left"
    elif face_side == "left":
        side = "right"
    elif face_side == "center":
        side = ev.get("preferred_object_side") or "right"
    band = "upper" if captions_band in ("bottom", "lower", "") else "mid"
    placement = f"{band}_{side}"
    if placement not in VALID_PLACEMENTS:
        placement = "upper_right"
    variant = "reveal_left" if side == "left" else "reveal_right"
    return placement, variant


def select_object_3d(
    words: List[Dict[str, Any]],
    *,
    existing_visuals: Dict[str, Any],
    clip_duration_s: float,
    task_context: Dict[str, Any],
) -> Optional[Object3DDecision]:
    """Decide whether — and where — to place ONE real 3D object on this clip.

    Returns an Object3DDecision when a strong, explicit, collision-free placement exists;
    otherwise None (the caller then falls through to card / 2D per the resolver order).
    Never returns a decision when strong B-roll already covers the window (FASE 7).
    """
    cd = float(clip_duration_s or 0.0)
    if cd <= 8.0:
        logger.info("VPI_OBJECT_3D_SKIPPED reason=clip_too_short dur=%.2f", cd)
        return None

    # FASE 7: strong B-roll wins — no 3D.
    if _broll_covers_window(existing_visuals):
        logger.info("VPI_OBJECT_3D_SKIPPED reason=strong_broll_present")
        return None

    text = _words_to_text(words)
    vi = classify_visual_intent(
        text, editorial_type_prior=str((task_context or {}).get("editorial_type") or "")
    )
    intent = vi.get("intent") or ""
    asset_id = intent_to_asset_3d(intent)
    # FASE 8 refinement: "pasaporte/visado/documentación/residencia/certificado" represent a
    # document literally — prefer the passport family even when the winning intent is travel
    # (vpi_object_2d files "pasaporte" under travel_assistance). The object must LITERALLY match.
    _strong_norm = " ".join(
        str(c.get("matched_norm") or "") for c in (vi.get("candidate_phrases") or [])
        if c.get("evidence_strength") == "strong"
    )
    if asset_id == "travel_suitcase_3d" and any(
        tok in _strong_norm for tok in ("pasaporte", "visado", "documentacion", "residencia", "certificado")
    ):
        asset_id = "document_passport_3d"
    semantic_score = float(vi.get("semantic_score") or 0.0)
    margin_norm = float(vi.get("visual_intent_margin") or 0) / 8.0
    candidate_phrases = vi.get("candidate_phrases") or []
    strong = _has_strong_phrase(candidate_phrases)
    # 53B — evidence tier on the (possibly refined) family.
    tier_info = classify_evidence_tier(asset_id, candidate_phrases) if asset_id else \
        {"tier": "INFERRED", "literal_match": False, "literal_phrase": None}
    evidence_tier = tier_info["tier"]
    literal_match = bool(tier_info["literal_match"])

    logger.info(
        "VPI_OBJECT_3D_CANDIDATE intent=%s asset=%s score=%.3f margin=%.3f strong=%s tier=%s literal=%s",
        intent or "-", asset_id or "-", semantic_score, margin_norm, bool(strong),
        evidence_tier, literal_match,
    )

    # 53B two-tier gate. 3D is reserved for explicit LITERAL object phrases (TIER A) or very
    # strong INFERRED intent (TIER B, unchanged 0.82). Generic emotionals (tranquilidad, …) are
    # excluded from TIER A by classify_evidence_tier, so they fall to TIER B and are rejected.
    gate_reason = ""
    if not asset_id:
        logger.info("VPI_OBJECT_3D_SKIPPED reason=no_literal_3d_family intent=%s", intent or "-")
        return None
    if not strong:
        logger.info("VPI_OBJECT_3D_SKIPPED reason=no_explicit_strong_phrase intent=%s", intent)
        return None
    if evidence_tier == "LITERAL_STRONG":
        if margin_norm < LITERAL_MIN_MARGIN_NORM or semantic_score < LITERAL_FLOOR:
            logger.info(
                "VPI_OBJECT_3D_SKIPPED reason=literal_below_floor score=%.3f(floor=%.2f) margin=%.3f(min=%.2f) tier=%s",
                semantic_score, LITERAL_FLOOR, margin_norm, LITERAL_MIN_MARGIN_NORM, evidence_tier,
            )
            return None
        gate_reason = f"literal_strong:{tier_info['literal_phrase'].get('matched_norm')}"
    else:
        # TIER B INFERRED — strict normalised gate, unchanged.
        if semantic_score < MIN_SEMANTIC_SCORE_3D or margin_norm < MIN_MARGIN_NORM_3D:
            logger.info(
                "VPI_OBJECT_3D_SKIPPED reason=inferred_below_threshold score=%.3f(min=%.2f) margin=%.3f(min=%.2f) tier=%s",
                semantic_score, MIN_SEMANTIC_SCORE_3D, margin_norm, MIN_MARGIN_NORM_3D, evidence_tier,
            )
            return None
        gate_reason = "inferred_above_strict_gate"

    # FASE 9 — phrase-targeted windowing (reuse 52C placement: hook + closure + collisions).
    hook_end = float((task_context or {}).get("hook_end_s") or DEFAULT_HOOK_END_S)
    placement, variant = _choose_placement_and_variant(existing_visuals)
    # restrict to STRONG explicit phrases only for 3D (never a weak keyword); for TIER A put the
    # literal-object phrase first so the window lands on the literal cue.
    strong_phrases = [c for c in candidate_phrases if c.get("evidence_strength") == "strong"]
    if literal_match and tier_info.get("literal_phrase") in strong_phrases:
        lp = tier_info["literal_phrase"]
        strong_phrases = [lp] + [c for c in strong_phrases if c is not lp]
    placed = place_object_best_phrase(
        words, strong_phrases,
        clip_duration=cd,
        hook_end=hook_end + HOOK_SEPARATION_S,   # FASE 9: >=4s separation from the hook
        avoid=_avoid_intervals(existing_visuals),
        closure_tail_s=1.5,
        phrase_fallback_ratio=0.70,
    )
    win = placed.get("window")
    if not win:
        logger.info(
            "VPI_OBJECT_3D_SKIPPED reason=no_clean_window detail=%s",
            placed.get("phrase_window_skip_reason") or "collision",
        )
        return None

    decision = Object3DDecision(
        intent=intent,
        asset_id=asset_id,
        phrase=str(placed.get("chosen_phrase") or win.get("matched_phrase") or ""),
        phrase_start_s=float(win.get("phrase_start_s")),
        phrase_end_s=float(win.get("phrase_end_s")),
        window_start_s=float(win.get("start_s")),
        window_end_s=float(win.get("end_s")),
        semantic_score=round(semantic_score, 3),
        placement=placement,
        animation_variant=variant,
        reason="strong_explicit_literal_3d" if evidence_tier == "LITERAL_STRONG" else "strong_inferred_3d",
        evidence_tier=evidence_tier,
        raw_score=round(semantic_score, 3),
        normalized_score=round(semantic_score, 3),
        literal_match=literal_match,
        gate_reason=gate_reason,
        gate_version=GATE_VERSION,
    )
    logger.info(
        "VPI_OBJECT_3D_SELECTED asset=%s phrase=%r window=%.2f-%.2f placement=%s variant=%s score=%.3f tier=%s gate=%s",
        decision.asset_id, decision.phrase, decision.window_start_s, decision.window_end_s,
        decision.placement, decision.animation_variant, decision.semantic_score,
        decision.evidence_tier, decision.gate_reason,
    )
    return decision
