"""OUTPUT-VISUALS-40B — live 2D semantic object overlay (daily-mode narrow override).

A sober, single 2D semantic object: a rasterized local SVG icon composited on a solid rounded
card, overlaid on the video with opacity fade-in/out motion in an upper safe corner. Direct
icon-on-card (PIL card + ffmpeg overlay) — NOT the nested-SVG badge that loses the icon under
librsvg. Bypasses the gated render_visual_reinforcement; eligibility is decided by the caller.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_ASSETS_ICON_ROOTS = [
    Path("/app/assets/icons"),
    Path(__file__).resolve().parents[3] / "assets" / "icons",
]

# intent -> ordered local icon candidates.
# shield_check.svg is intentionally excluded (empty/unusable per the audit).
_OBJECT_2D_ICON_MAP: Dict[str, List[str]] = {
    "emotional_protection": ["vpi/family_shield.svg", "vpi/shield_life.svg", "vpi/family_home.svg", "vpi/heart_shield.svg"],
    "family_protection":    ["vpi/family_shield.svg", "vpi/family_home.svg", "vpi/shield_life.svg", "family/contact.svg"],
    "health_access":        ["vpi/medical_cross.svg", "vpi/health_card.svg", "hospital/hospital.svg"],
    "documents_admin":      ["vpi/folder_paperwork.svg", "vpi/signature_form.svg", "document/file-search-corner.svg"],
    "financial_planning":   ["vpi/budget_document.svg", "vpi/capital_stack.svg", "vpi/coverage_umbrella.svg", "euro/badge-euro.svg"],
    "risk_warning":         ["vpi/risk_marker.svg", "vpi/storm_cloud_risk.svg", "warning/octagon-alert.svg"],
    "advisor_explanation":  ["vpi/advisor_chat.svg", "vpi/checklist_advice.svg", "vpi/magnifying_glass.svg", "vpi/key_insight.svg"],
    "practical_explanation": ["vpi/checklist_advice.svg", "vpi/key_insight.svg", "vpi/magnifying_glass.svg"],
    "travel_assistance":    ["vpi/travel_suitcase.svg", "vpi/travel_passport.svg"],
}
# student_abroad remains intentionally unmapped until real task demand appears.


# task-level anti-repetition (within one task render loop).
_USED_ICONS_BY_TASK: Dict[str, set] = {}


def track_used_icon(task_id: str, asset_key: str) -> None:
    _USED_ICONS_BY_TASK.setdefault(str(task_id or ""), set()).add(asset_key)


def get_used_icons(task_id: str) -> Tuple[str, ...]:
    return tuple(_USED_ICONS_BY_TASK.get(str(task_id or ""), set()))


def choose_object_2d_window(
    clip_duration: float,
    *,
    hook_end: float = 2.5,
    avoid: Optional[List[Tuple[float, float, float]]] = None,
    win: float = 1.5,
) -> Optional[Tuple[float, float]]:
    """Pick a clean [start,end] window for the object: after the hook, off the closure tail,
    and not within the margin of any avoid interval (punch ±3s, micro-repair ±0.5s).

    `avoid` items are (start, end, margin). Returns None if no clean window exists.
    """
    cd = float(clip_duration or 0.0)
    if cd <= 0:
        return None
    lo = max(float(hook_end) + 1.0, cd * 0.30)
    hi = cd - 2.5 - float(win)  # keep the closure/fade tail (last 2.5s) free
    if hi <= lo:
        return None
    av = list(avoid or [])
    for frac in (0.45, 0.55, 0.35, 0.62, 0.40, 0.50):
        st = round(min(hi, max(lo, cd * frac)), 2)
        en = round(st + float(win), 2)
        clean = True
        for a, b, m in av:
            if not (en < float(a) - float(m) or st > float(b) + float(m)):
                clean = False
                break
        if clean:
            return (st, en)
    return None


def evaluate_object_2d_eligibility(
    *,
    daily_mode_active: bool,
    no_broll_rendered: bool,
    semantic_score: float,
    icon_valid: bool,
    other_reinforcement_present: bool,
    clean_window: bool,
    clip_duration: float,
    flagged: bool = False,
    threshold: float = 0.78,
) -> Dict[str, Any]:
    """Narrow daily-mode override policy for one semantic 2D object.

    This is intentionally stricter than the old visual_reinforcement route: it only allows a
    direct icon-on-card object when the clip has no B-roll/card/reinforcement already and the
    semantic/icon/window signals are strong enough.
    """
    reasons: List[str] = []
    if flagged:
        reasons.append("flagged_clip")
    if not daily_mode_active:
        reasons.append("daily_mode_inactive")
    if not no_broll_rendered:
        reasons.append("broll_rendered")
    if other_reinforcement_present:
        reasons.append("reinforcement_already_present")
    if float(clip_duration or 0.0) <= 8.0:
        reasons.append("clip_too_short")
    if float(semantic_score or 0.0) < float(threshold):
        reasons.append("weak_semantic_match")
    if not icon_valid:
        reasons.append("invalid_icon")
    if not clean_window:
        reasons.append("no_clean_window")
    return {
        "allowed": not reasons,
        "reason": "daily_mode_no_broll_strong_intent_clean_window" if not reasons else reasons[0],
        "reasons": reasons,
        "daily_2d_object_override": bool(not reasons),
        "semantic_score": round(float(semantic_score or 0.0), 3),
        "threshold": round(float(threshold), 3),
    }


def _icons_root() -> Optional[Path]:
    for r in _ASSETS_ICON_ROOTS:
        if r.exists():
            return r
    return None


def normalize_intent(intent: str) -> str:
    s = (intent or "").strip().lower()
    if s in _OBJECT_2D_ICON_MAP:
        return s
    # light aliasing onto the known intents (no taxonomy expansion)
    if "health" in s or "salud" in s or "medic" in s:
        return "health_access"
    if "document" in s or "tramite" in s or "admin" in s:
        return "documents_admin"
    if "financ" in s or "ahorro" in s or "money" in s or "saving" in s:
        return "financial_planning"
    if "risk" in s or "riesgo" in s or "warning" in s:
        return "risk_warning"
    if "advisor" in s or "asesor" in s or "explanation" in s:
        return "advisor_explanation"
    if "travel" in s or "viaje" in s or "pasaje" in s or "airport" in s or "aeropuerto" in s or "passport" in s or "pasaporte" in s:
        return "travel_assistance"
    if "protect" in s or "family" in s or "familia" in s or "emotional" in s:
        return "emotional_protection"
    return ""


# VISUALS-42: contextual intent evidence. Mapping is by full-phrase evidence, not a single
# keyword. `strong` = exact-phrase / dominant concept (+4); `weak` = secondary signal (+1);
# `exclude` = if present, this intent is strongly penalised (-4). travel requires explicit travel.
_INTENT_EVIDENCE: Dict[str, Dict[str, Any]] = {
    "emotional_protection": {
        "strong": ["proteger a", "protege a", "los tuyos", "tranquilidad", "respaldo", "cuidar de",
                   "tu familia", "a tu familia", "seres queridos", "proteger a tu familia"],
        "weak": ["familia", "calma", "seguridad", "proteccion", "proteger"],
        "exclude": ["pagar mas", "pagar de mas", "presupuesto", "comparar precio", "comparar precios",
                    "ahorro", "ahorrar", "cuanto cuesta"],
    },
    "financial_planning": {
        "strong": ["presupuesto", "pagar mas", "no pagar de mas", "comparar precio", "comparar precios",
                   "comparar coste", "ahorro", "ahorrar", "capital", "planificacion economica",
                   "cuanto cuesta", "comparar opciones"],
        "weak": ["dinero", "euros", "coste", "precio", "barato", "caro"],
        "exclude": ["familia", "salud", "medico", "tramite", "viaje"],
    },
    "advisor_explanation": {
        "strong": ["revisar coberturas", "revisar las coberturas", "asesoramiento", "te explico",
                   "conviene revisar", "comparar condiciones", "revisar condiciones", "analizar"],
        "weak": ["revisar", "revisa", "explicar", "condiciones", "opciones", "contexto", "asesor"],
        "exclude": [],
    },
    "health_access": {
        "strong": ["acudir al medico", "atencion sanitaria", "acceso a especialistas", "salud no avisa",
                   "consulta medica", "prueba medica", "hospital"],
        "weak": ["medico", "sanitari", "salud", "especialista", "consulta", "cita"],
        "exclude": [],
    },
    "documents_admin": {
        "strong": ["documentacion", "visado", "residencia", "poliza", "certificado", "tramite", "tramites"],
        "weak": ["documento", "papeles", "firma", "formulario", "condiciones del contrato"],
        "exclude": [],
    },
    "risk_warning": {
        "strong": ["por si acaso", "imprevisto", "cuidado con", "error frecuente", "peligro de"],
        "weak": ["riesgo", "problema", "imprevistos"],
        "exclude": ["viaje", "extranjero"],
    },
    "travel_assistance": {
        "strong": ["viaje", "viajar", "en el extranjero", "al extranjero", "desplazamiento",
                   "equipaje", "maleta", "pasaporte", "asistencia fuera", "aeropuerto"],
        "weak": [],
        "exclude": [],
        "require_explicit": True,  # never activate without an explicit travel reference
    },
}


def _norm_text(text: str) -> str:
    s = (text or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        s = s.replace(a, b)
    return s


_MATCH_PUNCT = " ,.;:!?¿¡\"'()[]-—…«»"


def _tokenize_norm(text: str) -> List[str]:
    """Normalize + tokenize on whitespace, stripping edge punctuation (conservative)."""
    return [tok for tok in (t.strip(_MATCH_PUNCT) for t in _norm_text(text).split()) if tok]


def _phrase_in_tokens(norm_phrase: str, tokens: List[str]) -> bool:
    """VISUALS-43B: word-boundary match — the phrase's token sequence must appear as a
    consecutive run in `tokens`. Avoids substring false positives ('capital' in 'capitalismo',
    'familia' in 'familiar'). Same evidence weights; only the detection changes from substring.
    """
    ptoks = [tok for tok in norm_phrase.split() if tok]
    if not ptoks:
        return False
    m = len(ptoks)
    n = len(tokens)
    for i in range(0, n - m + 1):
        if tokens[i:i + m] == ptoks:
            return True
    return False


def classify_visual_intent(
    text: str,
    *,
    editorial_type_prior: str = "",
    min_score: int = 4,
    min_margin: int = 2,
) -> Dict[str, Any]:
    """VISUALS-42 FASE 3: contextual visual intent from the full phrase, not a keyword.

    Scores each intent by evidence (strong +4 / weak +1 / exclude -4), adds a small prior for
    the clip's editorial_type, and requires the winner to clear `min_score` AND beat the
    runner-up by `min_margin`. Ambiguous / weak / excluded -> intent="" (honest skip). travel
    never fires without an explicit travel reference.
    """
    t = _norm_text(text)
    text_tokens = _tokenize_norm(text)
    prior = normalize_intent(editorial_type_prior)
    scores: Dict[str, int] = {}
    # VISUALS-43: keep the matched evidence per intent so the object can be placed on the exact
    # winning phrase. VISUALS-43B: evidence is matched by TOKEN BOUNDARY (not substring), so a
    # keyword never fires inside a larger word. _norm_text preserves length, so char offsets in
    # the normalized text equal char offsets in the original text.
    matched_by_intent: Dict[str, List[Tuple[str, str, str]]] = {}
    for intent, ev in _INTENT_EVIDENCE.items():
        sc = 0
        has_strong = False
        matches: List[Tuple[str, str, str]] = []
        for ph in ev.get("strong", []):
            np_ = _norm_text(ph)
            if _phrase_in_tokens(np_, text_tokens):
                sc += 4
                has_strong = True
                matches.append((ph, np_, "strong"))
        for ph in ev.get("weak", []):
            np_ = _norm_text(ph)
            if _phrase_in_tokens(np_, text_tokens):
                sc += 1
                matches.append((ph, np_, "weak"))
        for ph in ev.get("exclude", []):
            if _phrase_in_tokens(_norm_text(ph), text_tokens):
                sc -= 4
        if ev.get("require_explicit") and not has_strong:
            sc = -99  # travel: no explicit travel reference -> never
        if intent == prior and sc > 0:
            sc += 1  # gentle prior nudge, not a hijack
        scores[intent] = sc
        matched_by_intent[intent] = matches
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_intent, top_score = ranked[0]
    runner_score = ranked[1][1] if len(ranked) > 1 else -99
    margin = top_score - runner_score
    competing = [i for i, s in ranked[1:] if s >= top_score - 1 and s > 0]
    if top_score < min_score or margin < min_margin:
        reason = "weak_or_ambiguous"
        final = ""
    else:
        reason = "strong_unambiguous"
        final = top_intent
    # best evidence for the winner: prefer the longest STRONG phrase, else longest weak.
    matched_phrase = ""
    matched_norm = ""
    matched_char_start = -1
    matched_char_end = -1
    evidence_strength = ""
    competing_evidence: List[str] = []
    matched_tokens: List[str] = []
    if final and matched_by_intent.get(final):
        pool = [m for m in matched_by_intent[final] if m[2] == "strong"] or matched_by_intent[final]
        # FASE 3: prefer the longest STRONG multi-token phrase (more tokens first, then chars),
        # never a single keyword when a fuller phrase matched.
        best = max(pool, key=lambda m: (len(m[1].split()), len(m[1])))
        _ph, matched_norm, evidence_strength = best
        matched_tokens = matched_norm.split()
        pos = t.find(matched_norm)
        if pos >= 0:
            matched_char_start = pos
            matched_char_end = pos + len(matched_norm)
            matched_phrase = text[matched_char_start:matched_char_end]
        else:
            matched_phrase = _ph
        competing_evidence = [m[0] for m in matched_by_intent[final] if m[1] != matched_norm]
    # VISUALS-52C FASE 5: expose ALL winning-intent evidence phrases (ranked: strong first,
    # then more tokens, then longer) so placement can try the next explicit phrase when the
    # best one collides with the hook/closure/punch — instead of skipping the object entirely.
    candidate_phrases: List[Dict[str, str]] = []
    if final and matched_by_intent.get(final):
        ranked_ev = sorted(
            matched_by_intent[final],
            key=lambda m: (1 if m[2] == "strong" else 0, len(m[1].split()), len(m[1])),
            reverse=True,
        )
        seen_norm: set = set()
        for _ph, _norm, _streng in ranked_ev:
            if _norm in seen_norm:
                continue
            seen_norm.add(_norm)
            _pos = t.find(_norm)
            _phrase_text = text[_pos:_pos + len(_norm)] if _pos >= 0 else _ph
            candidate_phrases.append({
                "matched_phrase": _phrase_text,
                "matched_norm": _norm,
                "evidence_strength": _streng,
            })
    return {
        "intent": final,
        "candidate_phrases": candidate_phrases,
        "visual_intent_scores": scores,
        "visual_intent_margin": margin,
        "visual_intent_competing": competing,
        "visual_intent_top_score": top_score,
        "visual_intent_final_reason": reason,
        # VISUALS-43 evidence span (for phrase-targeted windowing)
        "matched_phrase": matched_phrase,
        "matched_norm": matched_norm,
        "matched_char_start": matched_char_start,
        "matched_char_end": matched_char_end,
        "evidence_strength": evidence_strength,
        "competing_evidence": competing_evidence,
        # VISUALS-43B word-boundary metadata
        "visual_intent_match_method": "token_boundary",
        "visual_intent_matched_tokens": matched_tokens,
        "visual_intent_match_count": len(matched_tokens),
        # 0..1 confidence for the eligibility gate (>=0.78 when strong+clear)
        "semantic_score": round(min(1.0, max(0.0, (top_score / 8.0) * (1.0 if final else 0.5))), 3),
    }


def locate_phrase_time_span(
    words: List[Dict[str, Any]],
    matched_phrase: str,
    *,
    matched_norm: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """VISUALS-43 FASE 3: map the winning phrase text to final word timestamps.

    1) exact normalized token sequence; 2) bounded token match (all phrase tokens within a
    short consecutive run, tolerating one differing transcription token); else None (skip).
    No wide fuzzy search. Returns {start_s, end_s, matched_words, confidence, match_method}.
    """
    if not words or not matched_phrase:
        return None
    _TGT_PUNCT = " ,.;:!?¿¡\"'()[]-—…«»"
    target = [tok.strip(_TGT_PUNCT) for tok in (matched_norm or _norm_text(matched_phrase)).split()]
    target = [tok for tok in target if tok]
    if not target:
        return None
    _PUNCT = " ,.;:!?¿¡\"'()[]-—…«»"
    toks = []
    for w in words:
        if not isinstance(w, dict):
            continue
        nw = _norm_text(str(w.get("text") or "")).strip(_PUNCT).strip()
        if not nw:
            continue
        try:
            toks.append((nw, float(w.get("start") or 0.0), float(w.get("end") or 0.0), float(w.get("confidence") or w.get("score") or 1.0)))
        except (TypeError, ValueError):
            continue
    n, m = len(toks), len(target)
    if n == 0:
        return None

    def _span(i: int, j: int, method: str) -> Dict[str, Any]:
        run = toks[i:j]
        return {
            "start_s": round(run[0][1], 3),
            "end_s": round(run[-1][2], 3),
            "matched_words": [r[0] for r in run],
            "confidence": round(sum(r[3] for r in run) / max(1, len(run)), 3),
            "match_method": method,
        }

    # 1) exact normalized sequence
    seq = [tk[0] for tk in toks]
    for i in range(0, n - m + 1):
        if seq[i:i + m] == target:
            return _span(i, i + m, "exact")
    # 2) bounded token match: a window of length m (±1) containing >= m-1 of the target tokens
    tgt_set = set(target)
    win = m + 1
    best = None
    for i in range(0, max(1, n - m + 2)):
        j = min(n, i + win)
        window = seq[i:j]
        hits = sum(1 for tok in window if tok in tgt_set)
        if hits >= m - 1 and hits >= max(2, m - 1):
            # tighten to the first..last hit inside the window
            idxs = [i + k for k, tok in enumerate(window) if tok in tgt_set]
            if idxs:
                cand = (idxs[0], idxs[-1] + 1, hits)
                if best is None or cand[2] > best[2]:
                    best = cand
    if best is not None:
        return _span(best[0], best[1], "bounded_token")
    return None


def build_phrase_window(
    phrase_start_s: float,
    phrase_end_s: float,
    *,
    clip_duration: float,
    target_min: float = 1.2,
    target_max: float = 1.8,
    hard_max: float = 2.0,
) -> Optional[Dict[str, Any]]:
    """VISUALS-43 FASE 4: build the object window over the phrase span.

    Starts ~0.10s before the first word, ends ~0.40s after the last; short phrases extend the
    hold after; long phrases center on the core and cap at 2.0s. Returns the window + offsets.
    """
    ps = float(phrase_start_s)
    pe = float(phrase_end_s)
    cd = float(clip_duration or 0.0)
    if cd <= 0 or pe <= ps:
        return None
    off_before = 0.10
    off_after = 0.40
    st = ps - off_before
    en = pe + off_after
    dur = en - st
    if dur < target_min:
        en = st + target_min  # extend hold after (short phrase)
    elif dur > hard_max:
        # long phrase: center on the core, cap at hard_max
        core = (ps + pe) / 2.0
        st = core - hard_max / 2.0
        en = core + hard_max / 2.0
    st = max(0.0, round(st, 3))
    en = round(min(cd - 0.05, en), 3)
    if en - st < 0.8:
        return None
    return {
        "start_s": st,
        "end_s": en,
        "phrase_start_s": round(ps, 3),
        "phrase_end_s": round(pe, 3),
        "offset_before_s": round(ps - st, 3),
        "offset_after_s": round(en - pe, 3),
        "window_source": "matched_phrase",
    }


def place_object_on_phrase(
    words: List[Dict[str, Any]],
    matched_phrase: str,
    matched_norm: str,
    *,
    clip_duration: float,
    hook_end: float,
    avoid: Optional[List[Tuple[float, float, float]]] = None,
    closure_tail_s: float = 1.5,
    phrase_fallback_ratio: float = 0.70,
) -> Dict[str, Any]:
    """VISUALS-43 FASE 3-6: place the object on the exact winning phrase, with guards.

    Locate the phrase in the final words -> build the window over it -> resolve collisions
    (hook/punch/cut/closure) only by a small shift that still covers the phrase. If it cannot
    appear on the phrase, SKIP (never relocate to a clean zone that no longer matches the
    phrase) — unless the phrase spans >70% of the clip, where a clean window is still on-phrase.
    """
    span = locate_phrase_time_span(words, matched_phrase, matched_norm=matched_norm)
    base = {"window": None, "phrase_window_found": False, "phrase_window_collision": False,
            "phrase_window_fallback_used": False, "phrase_window_skip_reason": "", "phrase_span": span}
    if not span:
        base["phrase_window_skip_reason"] = "phrase_not_located"
        return base
    base["phrase_window_found"] = True
    ps, pe = float(span["start_s"]), float(span["end_s"])
    cd = float(clip_duration or 0.0)
    avoid = list(avoid or [])

    def _collides(a: float, b: float):
        for ca, cb, m in avoid:
            if not (b < float(ca) - float(m) or a > float(cb) + float(m)):
                return (ca, cb, m)
        return None

    # hook / closure hard guards (phrase entirely inside hook, or window in closure tail)
    if pe <= float(hook_end):
        base["phrase_window_skip_reason"] = "phrase_in_hook"
        return base
    win = build_phrase_window(ps, pe, clip_duration=cd)
    if not win:
        base["phrase_window_skip_reason"] = "phrase_window_invalid"
        return base
    st, en = float(win["start_s"]), float(win["end_s"])
    if en > cd - float(closure_tail_s):
        base["phrase_window_skip_reason"] = "phrase_in_closure"
        return base
    col = _collides(st, en)
    if col:
        base["phrase_window_collision"] = True
        shifted = None
        for dx in (0.4, -0.4, 0.25, -0.25):
            ns, ne = st + dx, en + dx
            ov = min(ne, pe) - max(ns, ps)  # overlap with the phrase span
            if ns >= 0 and ne <= cd - float(closure_tail_s) and ov >= 0.6 * (pe - ps) and not _collides(ns, ne):
                shifted = (round(ns, 3), round(ne, 3))
                break
        if not shifted:
            # FASE 6 controlled fallback: only if the phrase spans most of the clip.
            if (pe - ps) >= phrase_fallback_ratio * cd:
                base["phrase_window_fallback_used"] = True
            else:
                base["phrase_window_skip_reason"] = "semantic_window_collision"
                return base
        else:
            st, en = shifted
    base["window"] = {
        "start_s": round(st, 3), "end_s": round(en, 3),
        "phrase_start_s": round(ps, 3), "phrase_end_s": round(pe, 3),
        "offset_before_s": round(max(0.0, ps - st), 3), "offset_after_s": round(max(0.0, en - pe), 3),
        "window_source": "matched_phrase", "match_method": span.get("match_method"),
    }
    return base


def place_object_best_phrase(
    words: List[Dict[str, Any]],
    candidate_phrases: List[Dict[str, str]],
    *,
    clip_duration: float,
    hook_end: float,
    avoid: Optional[List[Tuple[float, float, float]]] = None,
    closure_tail_s: float = 1.5,
    phrase_fallback_ratio: float = 0.70,
) -> Dict[str, Any]:
    """VISUALS-52C FASE 5: try each winning-intent evidence phrase in priority order and
    return the first that yields a clean, collision-free window. Only when EVERY explicit
    phrase fails do we skip — never relocate to an unrelated zone. Returns the placement
    result (with the chosen phrase) plus `attempted_phrases` for the audit.
    """
    attempts: List[Dict[str, Any]] = []
    last: Dict[str, Any] = {"window": None, "phrase_window_found": False,
                            "phrase_window_skip_reason": "no_candidate_phrase"}
    for cand in (candidate_phrases or []):
        res = place_object_on_phrase(
            words, str(cand.get("matched_phrase") or ""), str(cand.get("matched_norm") or ""),
            clip_duration=clip_duration, hook_end=hook_end, avoid=avoid,
            closure_tail_s=closure_tail_s, phrase_fallback_ratio=phrase_fallback_ratio,
        )
        attempts.append({
            "phrase": cand.get("matched_phrase"),
            "found": bool(res.get("phrase_window_found")),
            "skip_reason": res.get("phrase_window_skip_reason") or "",
            "has_window": bool(res.get("window")),
        })
        last = res
        if res.get("window"):
            res["chosen_phrase"] = cand.get("matched_phrase")
            res["chosen_norm"] = cand.get("matched_norm")
            res["attempted_phrases"] = attempts
            return res
    last["attempted_phrases"] = attempts
    return last


def select_object_2d_icon(
    intent: str,
    *,
    used_icons: Tuple[str, ...] = (),
) -> Optional[Dict[str, str]]:
    """Pick one local icon for the intent, skipping already-used icons (anti-repetition)."""
    root = _icons_root()
    if root is None:
        return None
    norm = normalize_intent(intent)
    if not norm:
        return None
    used = set(used_icons or ())
    for rel in _OBJECT_2D_ICON_MAP.get(norm, []):
        p = root / rel
        if p.exists() and p.is_file() and p.stat().st_size > 0 and rel not in used:
            return {"asset_key": rel, "asset_path": str(p), "intent": norm}
    return None


def _build_object_2d_card(icon_svg_path: Path, card_png_path: Path, *, card_size: int = 380) -> bool:
    """Rasterize the icon (ffmpeg/librsvg) and composite it on a solid rounded card (PIL)."""
    try:
        from PIL import Image, ImageDraw
        icon_png = card_png_path.with_name("obj_icon_raw.png")
        ic = int(card_size * 0.56)
        r = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(icon_svg_path),
             "-vf", f"scale={ic}:{ic}:force_original_aspect_ratio=decrease", "-frames:v", "1", str(icon_png)],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0 or not icon_png.exists():
            return False
        card = Image.new("RGBA", (card_size, card_size), (0, 0, 0, 0))
        d = ImageDraw.Draw(card)
        rad = int(card_size * 0.18)
        d.rounded_rectangle([6, 6, card_size - 6, card_size - 6], radius=rad,
                            fill=(20, 30, 56, 232), outline=(150, 180, 225, 200), width=5)
        icon = Image.open(icon_png).convert("RGBA")
        iw, ih = icon.size
        card.paste(icon, ((card_size - iw) // 2, (card_size - ih) // 2), icon)
        card.save(card_png_path)
        return card_png_path.exists() and card_png_path.stat().st_size > 0
    except Exception as exc:
        logger.warning("VPI_OBJECT_2D_CARD_FAILED reason=%s", exc)
        return False


def render_object_2d_overlay(
    input_video_path: str | Path,
    output_video_path: str | Path,
    *,
    icon_svg_path: str | Path,
    start_s: float,
    end_s: float,
    position: str = "upper_left",
    frame_w: int = 1080,
    frame_h: int = 1920,
    card_frac: float = 0.20,
    work_dir: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Overlay one sober 2D object on [start_s, end_s] with opacity fade-in/out motion.

    Returns metadata with object_2d_render_applied (ffmpeg rc=0 + valid output). Pixel
    visibility is verified separately by the caller.
    """
    out: Dict[str, Any] = {
        "object_2d_render_applied": False,
        "object_2d_output_path": str(input_video_path),
        "object_2d_start_s": round(float(start_s), 3),
        "object_2d_end_s": round(float(end_s), 3),
        "object_2d_position": position,
        "object_2d_card_width": 0,
        "object_2d_reason": "",
    }
    try:
        win = max(0.0, float(end_s) - float(start_s))
        if win < 0.8:
            out["object_2d_reason"] = "window_too_short"
            return out
        card_w = int(max(0.16, min(0.22, float(card_frac))) * float(frame_w))  # 16-22% of width
        wd = Path(work_dir) if work_dir else Path("/tmp/viraclip_object_2d")
        wd.mkdir(parents=True, exist_ok=True)
        card_png = wd / f"obj_card_{Path(icon_svg_path).stem}_{int(start_s*100)}.png"
        if not _build_object_2d_card(Path(icon_svg_path), card_png, card_size=card_w):
            out["object_2d_reason"] = "card_build_failed"
            return out
        # safe-zone position (margins ~6% of frame); opposite side handled by caller.
        mx = int(0.06 * frame_w)
        my = int(0.075 * frame_h)
        x = mx if position == "upper_left" else f"W-w-{mx}"
        y = my
        # opacity fade-in (0.28s) -> hold -> fade-out (0.28s), aligned to the window start.
        fo_st = max(0.0, win - 0.28)
        vf = (
            f"[1:v]format=rgba,fade=t=in:st=0:d=0.28:alpha=1,fade=t=out:st={fo_st:.3f}:d=0.28:alpha=1,"
            f"setpts=PTS-STARTPTS+{float(start_s):.3f}/TB[obj];"
            f"[0:v][obj]overlay=x={x}:y={y}:enable='between(t,{float(start_s):.3f},{float(end_s):.3f})'[v]"
        )
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(input_video_path),
            "-loop", "1", "-t", f"{win:.3f}", "-i", str(card_png),
            "-filter_complex", vf,
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-c:a", "copy",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(output_video_path),
        ]
        logger.info("VPI_OBJECT_2D_RENDER_START icon=%s start=%.2f end=%.2f pos=%s card_w=%d",
                    Path(icon_svg_path).name, start_s, end_s, position, card_w)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode == 0 and Path(output_video_path).exists() and Path(output_video_path).stat().st_size > 0:
            out["object_2d_render_applied"] = True
            out["object_2d_output_path"] = str(output_video_path)
            out["object_2d_card_width"] = card_w
            out["object_2d_reason"] = "rendered"
            logger.info("VPI_OBJECT_2D_RENDER_APPLIED icon=%s output=%s", Path(icon_svg_path).name, str(output_video_path))
            return out
        out["object_2d_reason"] = "ffmpeg_failed"
        logger.warning("VPI_OBJECT_2D_RENDER_FAILED detail=%s", (r.stderr or "")[-200:])
    except Exception as exc:
        out["object_2d_reason"] = f"exception:{exc}"
        logger.warning("VPI_OBJECT_2D_RENDER_FAILED reason=%s", exc)
    return out
