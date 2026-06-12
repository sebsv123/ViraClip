"""
VPI Retention Editing System v4.0 — RetentionEditingPlan generator.

Generates a per-clip RetentionEditingPlan that orchestrates all retention
layers: hook, silence, SFX, music, visual effects, transitions, captions,
frame rhythm, and pattern interruptions.

Core principle:
  "Si un recurso visual o sonoro no mejora claridad, retención o ritmo, no se usa."
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .vpi_editorial_scorer import (
    build_selection_contract,
    select_diverse_segments,
    _predict_first3_strength,
)

logger = logging.getLogger(__name__)

_BTS_TERMS = {
    "claro", "vale", "ok", "chevere", "cheverisima", "cheverisimo",
    "ahi esta", "ya si", "papa", "espera", "prueba", "camara", "graba",
    "listo", "empezamos", "otra vez", "perfecto", "dame", "vamos",
    "ruido", "se escucha", "mira", "vamos aqui", "dale de nuevo",
    "repite", "joder", "cono", "coño", "como se sube", "no lo puedo subir",
    "voy a leer", "cambio", "outfit", "hazlo de nuevo", "bien",
    "detras de camaras", "detrás de cámaras", "grabando", "camara", "cámara",
    "microfono", "micrófono", "toma", "corte", "repetimos", "sale mal",
    "risas internas", "fuera de camara", "fuera de cámara",
}
_CONTENT_VALUE_TERMS = {
    "seguro", "vida", "salud", "decesos", "proteccion", "proteger",
    "cobertura", "familia", "tranquilidad", "responsabilidad", "consejo",
    "objecion", "mito", "advertencia", "riesgo", "hipoteca", "pareja",
    "hijos", "contratar", "poliza", "cliente", "autonomo", "autonomos",
    "estabilidad", "acompanamiento", "imprevisto", "organizar", "economia",
    "cuidar", "especialista", "pruebas",
}
_INSURANCE_ANCHOR_TERMS = {
    "seguro", "seguros", "poliza", "póliza", "cobertura", "cubre", "cubrir",
    "decesos", "salud", "vida", "familia", "hipoteca", "prima", "capital",
    "proteccion", "protección", "riesgo", "mito", "objecion", "objeción",
    "problema", "imprevisto", "tranquilidad", "extranjería", "extranjeria",
}
_SHORT_INTERJECTIONS = {
    "claro", "vale", "ok", "chevere", "cheverisima", "cheverisimo",
    "ahi", "esta", "ya", "si", "papa", "listo", "perfecto",
}
_DISFLUENCY_FILLERS = {
    "eee", "eh", "aaa", "mmm", "um", "uh", "pues", "bueno", "vale", "sabes", "entonces",
}
_CAPTION_FILLERS = _DISFLUENCY_FILLERS | {"o", "sea", "o sea"}
_HIGHLIGHT_PHRASES = {
    "riesgo", "problema", "imprevisto", "miedo", "error",
    "proteger", "familia", "tranquilidad", "tuyos",
    "seguro de vida", "poliza", "póliza", "cobertura", "prima",
    "revisa", "fijate", "fíjate", "consejo", "importante",
    "no lo sabe", "clave", "realidad", "ojo",
}


def _normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def _word_count(text: str) -> int:
    return len([word for word in _normalize_text(text).split() if word])


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _build_visual_coherence_plan(editorial_type: str, text: str) -> Dict[str, Any]:
    text_l = _normalize_text(text or "")
    styles: List[str] = []
    if editorial_type in {"emotional_protection"} or any(t in text_l for t in ("familia", "calma", "tranquilidad", "proteger")):
        styles.append("calm_trust")
    if editorial_type in {"risk_warning", "myth_debunk", "client_objection"} or any(t in text_l for t in ("riesgo", "miedo", "error", "mito", "objecion")):
        styles.append("serious_warning")
    if editorial_type in {"coverage_explanation", "actionable_advice"} or any(t in text_l for t in ("cobertura", "papeleo", "poliza", "documento", "tramite")):
        styles.append("clear_explanation")
    if any(t in text_l for t in ("esto mucha gente no lo sabe", "la realidad es", "lo importante")):
        styles.append("revelation_hook")
    if editorial_type in {"actionable_advice"} or any(t in text_l for t in ("consejo", "revisa", "haz esto", "paso")):
        styles.append("practical_advice")

    primary = styles[0] if styles else "clear_explanation"
    dropped = styles[1:]
    if dropped:
        logger.info(
            "VISUAL_COHERENCE_CONFLICT resolved_primary=%s dropped=%s reason=first_strong_editorial_intent",
            primary,
            ",".join(dropped),
        )

    presets: Dict[str, Dict[str, Any]] = {
        "calm_trust": {
            "transition_family": "soft",
            "motion_intensity": "low",
            "object_style": "warm_subtle",
            "caption_energy": "calm",
            "broll_style": "human_warm",
            "avoid": ["dark_push", "quick_impact_cut", "playful_icons"],
        },
        "serious_warning": {
            "transition_family": "controlled_tension",
            "motion_intensity": "medium",
            "object_style": "serious_minimal",
            "caption_energy": "firm",
            "broll_style": "risk_contextual",
            "avoid": ["playful_icons", "warm_reveal"],
        },
        "clear_explanation": {
            "transition_family": "clean_structured",
            "motion_intensity": "low",
            "object_style": "documental_clean",
            "caption_energy": "clear",
            "broll_style": "paperwork_admin",
            "avoid": ["dark_push", "flashy_reveals"],
        },
        "revelation_hook": {
            "transition_family": "reveal_emphasis",
            "motion_intensity": "medium",
            "object_style": "focused_symbolic",
            "caption_energy": "high_first3",
            "broll_style": "meaningful_reveal",
            "avoid": ["random_icons", "constant_flash"],
        },
        "practical_advice": {
            "transition_family": "clean_actionable",
            "motion_intensity": "low_medium",
            "object_style": "checklist_guided",
            "caption_energy": "step_clarity",
            "broll_style": "advice_support",
            "avoid": ["dark_push", "playful_icons"],
        },
    }
    plan = {"visual_style": primary, **presets.get(primary, presets["clear_explanation"]), "reason": "primary_editorial_intent"}
    logger.info(
        "VISUAL_COHERENCE_PLAN style=%s transition_family=%s motion_intensity=%s object_style=%s reason=%s",
        plan["visual_style"], plan["transition_family"], plan["motion_intensity"], plan["object_style"], plan["reason"],
    )
    return plan


def _build_disfluency_plan(
    text: str,
    clip_duration_s: float,
    *,
    word_timestamps: Optional[List[Dict[str, Any]]] = None,
    editorial_type: str = "generic",
) -> Dict[str, Any]:
    events: List[Dict[str, Any]] = []
    words = [w for w in (word_timestamps or []) if isinstance(w, dict)]
    normalized_text = _normalize_text(text or "")
    tokens = [t for t in normalized_text.split() if t]

    def _add_event(event: Dict[str, Any]) -> None:
        events.append(event)
        logger.info(
            "DISFLUENCY_DETECTED type=%s severity=%s recommendation=%s text=%s",
            event.get("type"), event.get("severity"), event.get("recommendation"), event.get("text") or "",
        )

    # 1) Filler tokens and start fillers
    for idx, token in enumerate(tokens):
        if token in _DISFLUENCY_FILLERS:
            sev = "high" if idx < 2 else "medium"
            rec = "cut" if idx < 2 else "compress"
            if editorial_type == "emotional_protection" and token in {"bueno", "entonces"}:
                rec = "ignore"
                sev = "low"
            _add_event(
                {
                    "type": "filler",
                    "start": float(idx) * 0.2,
                    "end": float(idx) * 0.2 + 0.2,
                    "text": token,
                    "severity": sev,
                    "recommendation": rec,
                    "reason": "filler_token_detected",
                }
            )

    # 2) Repetition / false starts on token stream
    for idx in range(len(tokens) - 1):
        if tokens[idx] == tokens[idx + 1] and len(tokens[idx]) > 1:
            _add_event(
                {
                    "type": "repetition",
                    "start": float(idx) * 0.2,
                    "end": float(idx + 1) * 0.2 + 0.2,
                    "text": f"{tokens[idx]} {tokens[idx + 1]}",
                    "severity": "high",
                    "recommendation": "cut",
                    "reason": "immediate_word_repetition",
                }
            )
        if idx < len(tokens) - 2 and tokens[idx] in {"yo", "que", "el"} and tokens[idx + 1] == tokens[idx] and len(tokens[idx + 2]) > 2:
            _add_event(
                {
                    "type": "false_start",
                    "start": float(idx) * 0.2,
                    "end": float(idx + 1) * 0.2 + 0.2,
                    "text": f"{tokens[idx]} {tokens[idx + 1]}",
                    "severity": "high",
                    "recommendation": "cut",
                    "reason": "false_start_restart",
                }
            )

    # 3) Pause-based hesitation when timestamps are present
    for i in range(len(words) - 1):
        try:
            end = float(words[i].get("end") or words[i].get("stop") or words[i].get("start") or 0.0)
            nxt = float(words[i + 1].get("start") or words[i + 1].get("begin") or 0.0)
        except Exception:
            continue
        gap = max(0.0, nxt - end)
        if gap > 0.8:
            rec = "preserve_for_emphasis" if any(k in normalized_text for k in ("riesgo", "importante", "no lo sabe")) else "compress"
            typ = "emphasis_pause" if rec == "preserve_for_emphasis" else "long_pause"
            _add_event(
                {
                    "type": typ,
                    "start": round(end, 3),
                    "end": round(nxt, 3),
                    "text": "",
                    "severity": "medium",
                    "recommendation": rec,
                    "reason": "pause_gt_0_8_between_ideas",
                }
            )
        elif gap > 0.45:
            _add_event(
                {
                    "type": "long_pause",
                    "start": round(end, 3),
                    "end": round(nxt, 3),
                    "text": "",
                    "severity": "low",
                    "recommendation": "compress",
                    "reason": "pause_gt_0_45_inside_sentence",
                }
            )

    max_hard_cuts = 2 if clip_duration_s <= 20.0 else (3 if clip_duration_s <= 40.0 else 4)
    hard_cut_count = 0
    covered_count = 0
    preserved_count = 0
    selected: List[Dict[str, Any]] = []
    for event in events:
        action = str(event.get("recommendation") or "ignore")
        if action in {"cut", "compress"} and hard_cut_count >= max_hard_cuts:
            event["recommendation"] = "cover_with_transition"
            action = "cover_with_transition"
            logger.info("DISFLUENCY_EDIT_SKIPPED reason=cut_budget_cap")
        cover = "none"
        if action in {"cover_with_broll", "cover_with_transition"}:
            covered_count += 1
            cover = "soft_push"
            logger.info("DISFLUENCY_TRANSITION_SELECTED type=soft_push event=%s reason=cover_visible_jump", event.get("type"))
        elif action == "preserve_for_emphasis":
            preserved_count += 1
            logger.info("DISFLUENCY_TRANSITION_SKIPPED reason=emphasis_pause_preserved")
        elif action in {"cut", "compress"}:
            hard_cut_count += 1
            if event.get("type") == "filler":
                cover = "clean_cut"
            if event.get("type") in {"long_pause", "false_start"}:
                cover = "soft_push"
                covered_count += 1
                logger.info("DISFLUENCY_TRANSITION_SELECTED type=%s event=%s reason=disfluency_cleanup", cover, event.get("type"))
        selected.append({**event, "applied_action": action, "cover": cover})
        logger.info("DISFLUENCY_EDIT_SELECTED event=%s action=%s cover=%s reason=%s", event.get("type"), action, cover, event.get("reason"))

    high_unhandled = sum(1 for e in selected if e.get("severity") == "high" and e.get("applied_action") == "ignore")
    quality = "good" if high_unhandled == 0 and hard_cut_count <= max_hard_cuts else "needs_review"
    logger.info(
        "DISFLUENCY_PLAN events=%d cuts=%d covers=%d preserves=%d",
        len(selected), hard_cut_count, covered_count, preserved_count,
    )
    return {
        "events": selected,
        "disfluency_cleanup_count": hard_cut_count,
        "covered_disfluency_count": covered_count,
        "preserved_emphasis_pause_count": preserved_count,
        "max_hard_cuts": max_hard_cuts,
        "high_severity_unhandled_count": high_unhandled,
        "disfluency_edit_quality": quality,
        "has_disfluency_cleanup": bool(hard_cut_count or covered_count),
    }


def _build_caption_overlay_coherence_plan(
    *,
    text: str,
    clip_duration_s: float,
    visual_coherence_plan: Dict[str, Any],
    disfluency_plan: Dict[str, Any],
    semantic_objects: List[Dict[str, Any]],
    has_broll_active: bool,
    has_hook_card_active: bool,
) -> Dict[str, Any]:
    normalized = _normalize_text(text or "")
    tokens = [t for t in normalized.split() if t]
    removed_fillers = 0
    removed_repetitions = 0
    timing_adjusted = False
    cleaned_tokens: List[str] = []

    # Remove filler-only tokens unless explicitly preserved.
    for idx, tok in enumerate(tokens):
        if tok in _CAPTION_FILLERS:
            removed_fillers += 1
            continue
        if idx > 0 and tokens[idx - 1] == tok:
            removed_repetitions += 1
            continue
        cleaned_tokens.append(tok)

    # Remove first-try false starts if detected.
    for ev in disfluency_plan.get("events") or []:
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "false_start" and str(ev.get("applied_action") or "") in {"cut", "compress", "cover_with_transition"}:
            ev_text = _normalize_text(str(ev.get("text") or ""))
            if ev_text:
                for word in ev_text.split():
                    if word in cleaned_tokens:
                        cleaned_tokens.remove(word)
                        removed_repetitions += 1
            timing_adjusted = True
        if ev.get("type") in {"long_pause", "emphasis_pause"} and str(ev.get("applied_action") or "") == "preserve_for_emphasis":
            timing_adjusted = True

    logger.info(
        "CAPTION_DISFLUENCY_CLEANUP removed_fillers=%d removed_repetitions=%d timing_adjusted=%s",
        removed_fillers, removed_repetitions, str(bool(timing_adjusted)).lower(),
    )

    style = str(visual_coherence_plan.get("visual_style") or "clear_explanation")
    caption_style_map = {
        "calm_trust": "soft_emphasis",
        "serious_warning": "controlled_strong",
        "clear_explanation": "clean_readable",
        "revelation_hook": "strong_first_beat",
        "practical_advice": "checklist_clear",
    }
    caption_style = caption_style_map.get(style, "clean_readable")
    caption_energy = str(visual_coherence_plan.get("caption_energy") or "clear")
    logger.info(
        "CAPTION_STYLE_SELECTED visual_style=%s caption_energy=%s reason=visual_coherence_alignment",
        style, caption_energy,
    )

    # Highlight discipline.
    text_for_phrases = " ".join(cleaned_tokens)
    cap = 3 if clip_duration_s <= 20.0 else (5 if clip_duration_s <= 40.0 else 7)
    if has_broll_active and has_hook_card_active:
        cap = max(1, cap - 2)
    highlights: List[str] = []
    for phrase in _HIGHLIGHT_PHRASES:
        p = _normalize_text(phrase)
        if p in _CAPTION_FILLERS:
            logger.info("CAPTION_HIGHLIGHT_SKIPPED phrase=%s reason=filler_word", phrase)
            continue
        if p and p in text_for_phrases and p not in highlights:
            if len(highlights) >= cap:
                logger.info("CAPTION_HIGHLIGHT_SKIPPED phrase=%s reason=highlight_budget", phrase)
                continue
            highlights.append(phrase)
            logger.info("CAPTION_HIGHLIGHT_SELECTED phrase=%s reason=clarity_retention", phrase)

    overlay_duplication_warning = False
    safe_area_conflicts: List[str] = []
    overlay_actions: List[Dict[str, Any]] = []

    # Hook card duplication guard.
    if has_hook_card_active:
        if any(p in text_for_phrases for p in ("seguro de vida", "cobertura", "familia")):
            overlay_actions.append({"type": "hook_card", "action": "skip", "reason": "duplicates_caption_or_object"})
            overlay_duplication_warning = True
            logger.info("OVERLAY_DUPLICATION_GUARD action=skip reason=duplicates_caption_or_object")
            logger.info("OVERLAY_COHERENCE_SKIPPED type=hook_card reason=duplicates_caption_or_object")
        else:
            overlay_actions.append({"type": "hook_card", "action": "allow", "reason": "first3_strength"})
            logger.info("OVERLAY_COHERENCE_SELECTED type=hook_card reason=first3_strength")

    # Lower third safety with caption/object/broll stack.
    stack = 1 + (1 if has_broll_active else 0) + (1 if semantic_objects else 0) + (1 if has_hook_card_active else 0)
    if stack >= 4:
        safe_area_conflicts.append("lower_third_conflict_caption_object_broll")
        overlay_actions.append({"type": "lower_third", "action": "skip", "reason": "safe_area_conflict"})
        logger.info("SAFE_AREA_GUARD action=skip_or_reposition layer=lower_third reason=caption_object_broll_conflict")
    else:
        overlay_actions.append({"type": "lower_third", "action": "allow", "reason": "safe_area_ok"})
        logger.info("OVERLAY_COHERENCE_SELECTED type=lower_third reason=safe_area_ok")

    # Semantic object face/caption protection.
    if semantic_objects and has_broll_active and stack >= 4:
        safe_area_conflicts.append("semantic_object_conflict")
        logger.info("SAFE_AREA_GUARD action=skip_or_reposition layer=semantic_object reason=face_caption_protection")

    caption_readability_score = 0.92
    if has_broll_active and stack >= 4:
        caption_readability_score = 0.72
        logger.info("CAPTION_READABILITY_GUARD action=add_backing_or_reduce_broll reason=complex_background")
    elif has_broll_active:
        caption_readability_score = 0.84

    overlay_coherence_score = round(max(0.0, 1.0 - (0.25 if overlay_duplication_warning else 0.0) - (0.15 * len(safe_area_conflicts))), 2)

    timing_conflict = bool(timing_adjusted and removed_fillers == 0 and removed_repetitions == 0 and disfluency_plan.get("has_disfluency_cleanup"))
    if timing_conflict:
        logger.info("CAPTION_TIMING_WARNING reason=audio_cleanup_caption_timing_mismatch")

    return {
        "caption_clean_text": " ".join(cleaned_tokens).strip(),
        "has_clean_captions": removed_fillers > 0 or removed_repetitions > 0,
        "caption_disfluency_cleanup": {
            "removed_fillers": removed_fillers,
            "removed_repetitions": removed_repetitions,
            "timing_adjusted": bool(timing_adjusted),
        },
        "caption_timing_conflict": timing_conflict,
        "caption_style": caption_style,
        "caption_energy": caption_energy,
        "highlight_phrases": highlights,
        "highlight_count": len(highlights),
        "overlay_actions": overlay_actions,
        "overlay_coherence_score": overlay_coherence_score,
        "overlay_duplication_warning": overlay_duplication_warning,
        "safe_area_conflicts": safe_area_conflicts,
        "caption_readability_score": round(caption_readability_score, 2),
    }


def _contains_term(normalized_text: str, term: str) -> bool:
    normalized_term = _normalize_text(term)
    if not normalized_term:
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])", normalized_text))


def _segment_duration_s(segment: Dict[str, Any]) -> float:
    def parse(value: Any) -> float:
        raw = str(value or "0").strip()
        try:
            parts = raw.split(":")
            if len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            return float(raw)
        except Exception:
            return 0.0

    start = parse(segment.get("start_time") or segment.get("start") or segment.get("start_s"))
    end = parse(segment.get("end_time") or segment.get("end") or segment.get("end_s"))
    return max(0.0, end - start)


def _format_ts(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


def _parse_transcript_lines(transcript: str) -> List[Dict[str, Any]]:
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
        normalized = _normalize_text(text)
        bts = any(_contains_term(normalized, term) for term in _BTS_TERMS)
        useful_terms = [term for term in _CONTENT_VALUE_TERMS if _contains_term(normalized, term)]
        topic = detect_clean_take_topic(text)
        lines.append({
            "start": start,
            "end": end,
            "text": text,
            "normalized": normalized,
            "bts": bts,
            "useful": bool(useful_terms),
            "useful_terms": useful_terms,
            "topic": topic,
        })
    return lines


def _build_pseudo_timestamp_lines(transcript: str, duration_s: float) -> List[Dict[str, Any]]:
    """Build approximate timestamped lines from plain transcript text."""
    text = (transcript or "").strip()
    if not text or duration_s <= 0:
        return []

    chunks = [chunk.strip() for chunk in re.split(r"[.!?\n]+", text) if chunk.strip()]
    if not chunks:
        chunks = [text]

    line_words = [max(1, _word_count(chunk)) for chunk in chunks]
    total_words = max(1, sum(line_words))

    lines: List[Dict[str, Any]] = []
    cursor = 0.0
    for idx, chunk in enumerate(chunks):
        alloc = max(1.5, duration_s * (line_words[idx] / total_words))
        end = min(duration_s, cursor + alloc)
        normalized = _normalize_text(chunk)
        bts = any(_contains_term(normalized, term) for term in _BTS_TERMS)
        useful_terms = [term for term in _CONTENT_VALUE_TERMS if _contains_term(normalized, term)]
        lines.append(
            {
                "start": cursor,
                "end": max(cursor, end),
                "text": chunk,
                "normalized": normalized,
                "bts": bts,
                "useful": bool(useful_terms),
                "useful_terms": useful_terms,
                "topic": detect_clean_take_topic(chunk),
            }
        )
        cursor = end
        if cursor >= duration_s:
            break
    return lines


def detect_clean_take_topic(text: str) -> str:
    normalized = _normalize_text(text)
    if any(_contains_term(normalized, term) for term in ("decesos", "ausencia", "momento dificil")):
        return "decesos"
    if any(_contains_term(normalized, term) for term in ("salud", "especialista", "pruebas", "cita previa")):
        return "salud"
    if any(_contains_term(normalized, term) for term in ("autonomo", "autonomos", "factura", "cliente", "estabilidad", "bolsillo")):
        return "autonomos"
    if any(_contains_term(normalized, term) for term in ("familia", "proteccion", "proteger", "responsabilidad")):
        return "proteccion"
    return "generic"


def _candidate_from_lines(lines: List[Dict[str, Any]], *, reason: str) -> Optional[Dict[str, Any]]:
    if not lines:
        return None
    start = float(lines[0]["start"])
    end = float(lines[-1]["end"])
    duration = end - start
    if duration < 18.0 or duration > 48.0:
        return None
    text = " ".join(str(line.get("text") or "") for line in lines).strip()
    if not text:
        return None
    bts_lines = sum(1 for line in lines if line.get("bts"))
    useful_lines = sum(1 for line in lines if line.get("useful"))
    bts_ratio = bts_lines / max(1, len(lines))
    useful_ratio = useful_lines / max(1, len(lines))
    topic_votes: Dict[str, int] = {}
    for line in lines:
        topic = str(line.get("topic") or "generic")
        if topic != "generic":
            topic_votes[topic] = topic_votes.get(topic, 0) + 1
    topic = max(topic_votes, key=topic_votes.get) if topic_votes else detect_clean_take_topic(text)
    segment = {
        "start_time": _format_ts(start),
        "end_time": _format_ts(end),
        "text": text,
        "relevance_score": 0.72,
        "reasoning": reason,
        "virality_score": 62 if topic != "generic" else 45,
        "hook_score": 16,
        "engagement_score": 15,
        "value_score": 18,
        "shareability_score": 13,
        "hook_strength": "Medium",
        "hook_type": "content",
        "suggested_title": topic.replace("_", " ").title(),
        "suggested_hashtags": [],
        "clean_take_topic": topic,
        "clean_take_score": round((useful_ratio * 0.75) + ((1.0 - bts_ratio) * 0.25), 3),
        "bts_contamination_ratio": round(bts_ratio, 3),
        "useful_content_ratio": round(useful_ratio, 3),
        "clean_take_useful_lines": useful_lines,
        "clean_take_bts_lines": bts_lines,
        "duplicate_theme_key": f"{topic}:{int(start // 20)}",
    }
    logger.info(
        "[clean-take] start=%s end=%s useful_lines=%d bts_lines=%d topic=%s",
        segment["start_time"],
        segment["end_time"],
        useful_lines,
        bts_lines,
        topic,
    )
    if bts_ratio > 0.25:
        logger.info("[clean-take] reject start=%s end=%s reason=bts_contaminated", segment["start_time"], segment["end_time"])
    return segment


def build_clean_take_candidates(
    transcript: str,
    *,
    transcript_duration_s: float = 0.0,
    num_clips: int = 3,
) -> Dict[str, Any]:
    lines = _parse_transcript_lines(transcript)
    word_count = _word_count(transcript)
    duration_from_input = float(transcript_duration_s or 0.0)
    duration_from_lines = max((float(line["end"]) for line in lines), default=0.0)
    duration = duration_from_input
    duration_source = "video_duration_input"
    transcript_duration_fallback_used = False

    if duration <= 0.0:
        if duration_from_lines > 0.0:
            duration = duration_from_lines
            duration_source = "transcript_timestamps"
            transcript_duration_fallback_used = True
        elif word_count > 0:
            # Conservative Spanish speech estimate: ~2.2 words/s.
            duration = max(24.0, min(180.0, word_count / 2.2))
            duration_source = "word_count_estimate"
            transcript_duration_fallback_used = True
        else:
            duration = 0.0
            duration_source = "unavailable"
            transcript_duration_fallback_used = True

    if not lines and duration > 0.0 and word_count > 0:
        lines = _build_pseudo_timestamp_lines(transcript, duration)
        if lines:
            logger.info("[candidate-pool-source] pseudo_timestamp_lines=%d", len(lines))

    min_candidates = min(12, max(num_clips + 5, 8))
    logger.info(
        "[candidate-pool-source] transcript_duration=%.2f word_count=%d transcript_duration_source=%s transcript_duration_fallback_used=%s",
        duration,
        word_count,
        duration_source,
        str(transcript_duration_fallback_used).lower(),
    )
    logger.info(
        "[candidate-pool-source] transcript_duration_final=%.2f",
        duration,
    )

    sliding: List[Dict[str, Any]] = []
    if duration > 90.0:
        step = 12.0
        window = 30.0
        cursor = 0.0
        while cursor + 20.0 <= duration:
            win_lines = [line for line in lines if float(line["end"]) >= cursor and float(line["start"]) <= cursor + window]
            candidate = _candidate_from_lines(win_lines, reason="sliding_transcript_window")
            if candidate:
                sliding.append(candidate)
            cursor += step
    logger.info("[candidate-pool-source] sliding_windows=%d", len(sliding))
    logger.info("[candidate-pool-source] sliding_windows_count=%d", len(sliding))

    hook_windows: List[Dict[str, Any]] = []
    for line in lines:
        if not line.get("useful") or line.get("bts"):
            continue
        anchor = float(line["start"])
        for offset in (0.0, -4.0):
            start = max(0.0, anchor + offset)
            end = min(duration or start + 32.0, start + 32.0)
            win_lines = [item for item in lines if float(item["end"]) >= start and float(item["start"]) <= end]
            candidate = _candidate_from_lines(win_lines, reason="hook_anchored_clean_take")
            if candidate:
                hook_windows.append(candidate)
    logger.info("[candidate-pool-source] hook_windows=%d", len(hook_windows))
    logger.info("[candidate-pool-source] hook_windows_count=%d", len(hook_windows))

    clean_takes: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []
    for line in lines:
        gap = float(line["start"]) - float(current[-1]["end"]) if current else 0.0
        if line.get("bts") or gap > 4.0:
            if current:
                clean_takes.extend(_split_clean_block(current))
            current = []
            continue
        current.append(line)
    if current:
        clean_takes.extend(_split_clean_block(current))
    logger.info("[clean-take] generated=%d", len(clean_takes))
    logger.info("[candidate-pool-source] clean_take_count=%d", len(clean_takes))

    all_candidates = sliding + hook_windows + clean_takes
    logger.info("[candidate-pool-source] generated_before_filter=%d", len(all_candidates))
    # Stable dedupe by approximate boundary and topic; keep higher clean score.
    best: Dict[str, Dict[str, Any]] = {}
    for candidate in all_candidates:
        key = f"{candidate.get('clean_take_topic')}:{candidate.get('start_time')}:{candidate.get('end_time')}"
        current_best = best.get(key)
        if current_best is None or float(candidate.get("clean_take_score") or 0.0) > float(current_best.get("clean_take_score") or 0.0):
            best[key] = candidate
    candidates = sorted(
        best.values(),
        key=lambda item: (
            {"decesos": 4, "salud": 3, "autonomos": 2, "proteccion": 1}.get(str(item.get("clean_take_topic")), 0),
            float(item.get("clean_take_score") or 0.0),
            float(item.get("virality_score") or 0.0),
        ),
        reverse=True,
    )
    return {
        "segments": candidates[:max(min_candidates, len(candidates))],
        "generated_before_filter": len(all_candidates),
        "sliding_windows": len(sliding),
        "hook_windows": len(hook_windows),
        "clean_takes": len(clean_takes),
        "topics": sorted({str(item.get("clean_take_topic")) for item in candidates if item.get("clean_take_topic")}),
        "transcript_duration": duration,
        "word_count": word_count,
        "transcript_duration_source": duration_source,
        "transcript_duration_fallback_used": transcript_duration_fallback_used,
    }


def _split_clean_block(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not lines:
        return []
    block_start = float(lines[0]["start"])
    block_end = float(lines[-1]["end"])
    duration = block_end - block_start
    chunks: List[Dict[str, Any]] = []
    if duration <= 45.0:
        candidate = _candidate_from_lines(lines, reason="continuous_clean_take")
        return [candidate] if candidate else []
    cursor = block_start
    while cursor + 20.0 <= block_end:
        end = min(cursor + 35.0, block_end)
        win_lines = [line for line in lines if float(line["end"]) >= cursor and float(line["start"]) <= end]
        candidate = _candidate_from_lines(win_lines, reason="split_long_clean_take")
        if candidate:
            chunks.append(candidate)
        cursor += 28.0
    return chunks


def evaluate_content_quality(segment: Dict[str, Any]) -> Dict[str, Any]:
    text = str(segment.get("text") or "")
    normalized = _normalize_text(text)
    words = normalized.split()
    duration = _segment_duration_s(segment)
    total_words = len(words)
    bts_ratio_meta = segment.get("bts_contamination_ratio")
    useful_ratio_meta = segment.get("useful_content_ratio")
    useful_words = [
        word for word in words
        if len(word) >= 4 and word not in _SHORT_INTERJECTIONS
    ]
    bts_hits = [term for term in sorted(_BTS_TERMS, key=len, reverse=True) if _contains_term(normalized, term)]
    value_hits = [term for term in sorted(_CONTENT_VALUE_TERMS) if _contains_term(normalized, term)]
    insurance_anchor_hits = [term for term in sorted(_INSURANCE_ANCHOR_TERMS) if _contains_term(normalized, term)]
    words_per_second = total_words / max(duration, 1.0)
    useful_ratio = len(useful_words) / max(total_words, 1)
    speech_density = max(0.0, min(1.0, (words_per_second / 2.0) * 0.65 + useful_ratio * 0.35))
    behind_scenes = max(0.0, min(1.0, (len(bts_hits) / 4.0) + (0.35 if total_words < 18 and bts_hits else 0.0)))
    content_value = max(0.0, min(1.0, len(value_hits) / 5.0 + len(insurance_anchor_hits) / 8.0 + (0.20 if total_words >= 35 else 0.0)))
    bts_contamination_ratio = (
        float(bts_ratio_meta)
        if bts_ratio_meta is not None
        else max(behind_scenes, min(1.0, len(bts_hits) / max(1, len(value_hits) + len(bts_hits))))
    )
    useful_content_ratio = (
        float(useful_ratio_meta)
        if useful_ratio_meta is not None
        else min(1.0, (len(value_hits) / max(1, len(value_hits) + len(bts_hits))) if value_hits else 0.0)
    )
    speech_density_ratio = min(1.0, words_per_second / 2.5)

    meta_or_bts = bool(bts_hits)
    if meta_or_bts and len(insurance_anchor_hits) == 0 and (speech_density < 0.55 or content_value < 0.40 or total_words < 20):
        label = "reject"
        reason = "meta_production_or_bts"
    elif bts_contamination_ratio > 0.25:
        label = "reject"
        reason = "bts_contamination_too_high" if content_value >= 0.35 else "behind_the_scenes_low_speech"
        logger.info(
            "[content-quality] bts_reject_score=%.3f reason=%s",
            round(bts_contamination_ratio, 3),
            reason,
        )
        if content_value >= 0.35:
            logger.info("[content-quality] split reason=mixed_bts_and_content")
    elif behind_scenes >= 0.55 and (speech_density < 0.45 or content_value < 0.35):
        label = "reject"
        reason = "behind_the_scenes_low_speech"
    elif len(useful_words) < 10 and content_value < 0.4:
        label = "reject"
        reason = "too_few_useful_words"
    elif (
        useful_content_ratio >= 0.65
        and bts_contamination_ratio <= 0.20
        and len(useful_words) >= 35
        and speech_density_ratio >= 0.45
        and content_value >= 0.35
    ):
        label = "accept"
        reason = "clean_insurance_take"
    else:
        label = "review"
        reason = "content_quality_marginal"

    result = {
        "speech_density_score": round(speech_density, 3),
        "behind_the_scenes_score": round(behind_scenes, 3),
        "content_value_score": round(content_value, 3),
        "content_quality_label": label,
        "content_quality_reason": reason,
        "useful_word_count": len(useful_words),
        "speech_density_ratio": round(speech_density_ratio, 3),
        "bts_contamination_ratio": round(bts_contamination_ratio, 3),
        "useful_content_ratio": round(useful_content_ratio, 3),
        "bts_terms": bts_hits,
        "content_value_terms": value_hits,
        "insurance_anchor_terms": insurance_anchor_hits,
    }
    logger.info(
        "[content-quality] speech_density=%.3f behind_scenes=%.3f content_value=%.3f",
        result["speech_density_score"],
        result["behind_the_scenes_score"],
        result["content_value_score"],
    )
    if label == "reject":
        logger.info("[content-quality] reject reason=%s", reason)
    elif label == "accept":
        logger.info("[content-quality] accept reason=%s", reason)
    return result


def apply_content_quality(segment: Dict[str, Any]) -> Dict[str, Any]:
    quality = evaluate_content_quality(segment)
    segment.update(quality)
    penalty = 0.45 if quality["content_quality_label"] == "reject" else (0.18 if quality["content_quality_label"] == "review" else 0.0)
    bonus = quality["content_value_score"] * 0.10
    current = float(segment.get("final_rank_score") or 0.0)
    segment["final_rank_score"] = round(max(0.0, min(1.0, current + bonus - penalty)), 4)
    return segment


def filter_content_quality_candidates(segments: List[Dict[str, Any]], *, requested: int) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    override_candidates: List[Dict[str, Any]] = []
    dialogue_fallback_candidates: List[Dict[str, Any]] = []

    def _is_strong_vpi_insurance_candidate(seg: Dict[str, Any]) -> bool:
        vpi_score = float(seg.get("vpi_score") or 0.0)
        editorial_score = float(seg.get("editorial_score") or 0.0)
        matched = " ".join(str(x or "") for x in (seg.get("matched_patterns") or [])).lower()
        text = _normalize_text(str(seg.get("text") or ""))
        meta_hits = any(term in text for term in ("detras de camaras", "detrás de cámaras", "grabando", "cámara", "camara", "microfono", "micrófono", "toma", "corte", "repetimos", "sale mal", "risas internas"))
        keyword_hit = any(
            term in text or term in matched
            for term in ("seguro", "decesos", "proteccion", "cobertura", "familia", "poliza", "salud")
        )
        useful_word_count = int(seg.get("useful_word_count") or 0)
        speech_density_ratio = float(seg.get("speech_density_ratio") or 0.0)
        return (
            keyword_hit
            and not meta_hits
            and (vpi_score >= 65.0 or editorial_score >= 0.65)
            and useful_word_count >= 10
            and speech_density_ratio >= 0.25
        )

    _BACKSTAGE_BAN_REASONS = {
        "meta_production_or_bts",
        "bts_contamination_too_high",
        "behind_the_scenes_low_speech",
    }

    def _is_dialogue_fallback_candidate(seg: Dict[str, Any]) -> bool:
        reason = str(seg.get("content_quality_reason") or "")
        if reason in _BACKSTAGE_BAN_REASONS or bool(seg.get("backstage_pure")):
            return False
        text = _normalize_text(str(seg.get("text") or ""))
        if any(term in text for term in _META_PRODUCTION_PATTERNS):
            return False
        if any(term in text for term in _BTS_TERMS):
            return False
        useful_word_count = int(seg.get("useful_word_count") or 0)
        speech_density_score = float(seg.get("speech_density_score") or 0.0)
        content_value_score = float(seg.get("content_value_score") or 0.0)
        useful_ratio = float(seg.get("useful_content_ratio") or 0.0)
        anchor_terms = seg.get("insurance_anchor_terms") or []
        return (
            useful_word_count >= 10
            and speech_density_score >= 0.30
            and content_value_score >= 0.20
            and (
                bool(anchor_terms)
                or useful_ratio >= 0.35
                or str(seg.get("clean_take_topic") or "") not in {"", "generic"}
            )
        )

    def _is_generic_speech_fallback_candidate(seg: Dict[str, Any]) -> bool:
        reason = str(seg.get("content_quality_reason") or "")
        if reason in _BACKSTAGE_BAN_REASONS or bool(seg.get("backstage_pure")):
            return False
        text = _normalize_text(str(seg.get("text") or ""))
        if any(term in text for term in _META_PRODUCTION_PATTERNS):
            return False
        if any(term in text for term in _BTS_TERMS):
            return False
        useful_word_count = int(seg.get("useful_word_count") or 0)
        speech_density_score = float(seg.get("speech_density_score") or 0.0)
        content_value_score = float(seg.get("content_value_score") or 0.0)
        return useful_word_count >= 12 and speech_density_score >= 0.25 and content_value_score >= 0.15

    for idx, segment in enumerate(segments):
        apply_content_quality(segment)
        if segment.get("content_quality_label") == "reject":
            reason = str(segment.get("content_quality_reason") or "")
            if reason in {"meta_production_or_bts", "bts_contamination_too_high", "behind_the_scenes_low_speech"}:
                logger.info(
                    "CLIP_SELECTION_BTS_REJECTED start=%s end=%s reason=%s",
                    segment.get("start_time"),
                    segment.get("end_time"),
                    reason,
                )
            if (
                reason == "bts_contamination_too_high"
                and _is_strong_vpi_insurance_candidate(segment)
            ):
                override_candidates.append(segment)
            rejected.append({
                "index": idx,
                "reason": reason,
                "start_time": segment.get("start_time"),
                "end_time": segment.get("end_time"),
            })
            logger.info("[clip-count] rejected index=%d reason=%s", idx, reason)
            continue
        accepted.append(segment)

    if len(accepted) < requested and override_candidates:
        # OUTPUT-CUTS-8 hard-ban: a candidate marked bts_contamination_too_high
        # can never be rescued into the final package; it stays a rejected
        # placeholder with its reason instead of becoming a final MP4.
        for blocked in override_candidates:
            blocked["backstage_rescue_blocked"] = True
            blocked["backstage_placeholder"] = True
            logger.info(
                "VPI_OUTPUT_CUTS_BACKSTAGE_RESCUE_BLOCKED start=%s end=%s reason=%s",
                blocked.get("start_time"),
                blocked.get("end_time"),
                blocked.get("content_quality_reason"),
            )
            logger.info(
                "VPI_OUTPUT_CUTS_BACKSTAGE_PLACEHOLDER_CREATED start=%s end=%s",
                blocked.get("start_time"),
                blocked.get("end_time"),
            )

    if len(accepted) < requested:
        review_fallbacks = [
            seg for seg in segments
            if seg not in accepted
            and str(seg.get("content_quality_label") or "") in {"review", "accept"}
            and _is_strong_vpi_insurance_candidate(seg)
            and str(seg.get("content_quality_reason") or "") != "meta_production_or_bts"
        ]
        if review_fallbacks:
            review_fallbacks.sort(
                key=lambda item: (
                    float(item.get("final_rank_score") or 0.0),
                    float(item.get("content_value_score") or 0.0),
                    float(item.get("speech_density_score") or 0.0),
                ),
                reverse=True,
            )
            while len(accepted) < requested and review_fallbacks:
                best = review_fallbacks.pop(0)
                if best in accepted:
                    continue
                best["content_quality_label"] = "review"
                best["content_quality_reason"] = "review_fallback_vpi_main_dialogue"
                best["fallback_candidate_selected"] = True
                accepted.append(best)
                logger.info(
                    "CLIP_SELECTION_FILLER_USED reason=review_fallback_vpi_main_dialogue start=%s end=%s score=%.2f",
                    best.get("start_time"),
                    best.get("end_time"),
                    float(best.get("final_rank_score") or 0.0),
                )

    if len(accepted) < requested:
        dialogue_fallbacks = [
            seg for seg in segments
            if seg not in accepted
            and _is_dialogue_fallback_candidate(seg)
            and str(seg.get("content_quality_reason") or "") != "meta_production_or_bts"
        ]
        if dialogue_fallbacks:
            logger.info(
                "CLIP_SELECTION_DIALOGUE_FALLBACK_TRIGGERED reason=insufficient_primary_candidates requested=%d accepted=%d dialogue_candidates=%d",
                requested,
                len(accepted),
                len(dialogue_fallbacks),
            )
            dialogue_fallbacks.sort(
                key=lambda item: (
                    float(item.get("final_rank_score") or 0.0),
                    float(item.get("content_value_score") or 0.0),
                    float(item.get("speech_density_score") or 0.0),
                ),
                reverse=True,
            )
            while len(accepted) < requested and dialogue_fallbacks:
                best = dialogue_fallbacks.pop(0)
                if best in accepted:
                    continue
                best["content_quality_label"] = "review"
                best["content_quality_reason"] = "dialogue_fallback_vpi_main_dialogue"
                best["fallback_candidate_selected"] = True
                best["fallback_candidate_reason"] = "strong_dialogue_no_bts"
                accepted.append(best)
                dialogue_fallback_candidates.append(best)
                logger.info(
                    "CLIP_SELECTION_DIALOGUE_FALLBACK_SELECTED start=%s end=%s anchors=%s",
                    best.get("start_time"),
                    best.get("end_time"),
                    ",".join(best.get("insurance_anchor_terms") or best.get("content_value_terms") or [str(best.get("clean_take_topic") or "generic")]),
                )

    if len(accepted) < requested and not accepted:
        generic_fallbacks = [
            seg for seg in segments
            if seg not in accepted
            and _is_generic_speech_fallback_candidate(seg)
            and str(seg.get("content_quality_reason") or "") != "meta_production_or_bts"
        ]
        if generic_fallbacks:
            logger.info(
                "CLIP_SELECTION_DIALOGUE_FALLBACK_TRIGGERED reason=generic_coherent_speech requested=%d accepted=%d generic_candidates=%d",
                requested,
                len(accepted),
                len(generic_fallbacks),
            )
            generic_fallbacks.sort(
                key=lambda item: (
                    float(item.get("final_rank_score") or 0.0),
                    float(item.get("content_value_score") or 0.0),
                    float(item.get("speech_density_score") or 0.0),
                ),
                reverse=True,
            )
            while len(accepted) < requested and generic_fallbacks:
                best = generic_fallbacks.pop(0)
                if best in accepted:
                    continue
                best["content_quality_label"] = "review"
                best["content_quality_reason"] = "generic_speech_fallback"
                best["fallback_candidate_selected"] = True
                best["fallback_candidate_reason"] = "generic_coherent_speech_no_bts"
                accepted.append(best)
                dialogue_fallback_candidates.append(best)
                logger.info(
                    "CLIP_SELECTION_DIALOGUE_FALLBACK_SELECTED start=%s end=%s anchors=%s",
                    best.get("start_time"),
                    best.get("end_time"),
                    ",".join(best.get("content_value_terms") or [str(best.get("clean_take_topic") or "generic")]),
                )

    if len(accepted) < requested:
        logger.info(
            "CLIP_SELECTION_REQUESTED_VS_SELECTED requested=%d selected=%d reason=%s",
            requested,
            len(accepted),
            "insufficient_valid_dialogue" if accepted else "all_candidates_rejected",
        )
    if segments:
        bts_rejected_count = sum(
            1
            for item in rejected
            if str(item.get("reason") or "") in {"meta_production_or_bts", "bts_contamination_too_high", "behind_the_scenes_low_speech"}
        )
        logger.info(
            "CLIP_SELECTION_POOL_SUMMARY requested=%d initial=%d bts_rejected=%d dialogue_candidates=%d selected=%d",
            requested,
            len(segments),
            bts_rejected_count,
            len(dialogue_fallback_candidates),
            len(accepted),
        )
        logger.info("[clip-count] shortage reason=content_quality_filter accepted=%d requested=%d", len(accepted), requested)

    # ── v2.0 — Diversity-aware selection ──────────────────────────────────────
    # Apply diversity-aware selection to accepted segments using the VPI
    # editorial scorer's select_diverse_segments() function.
    if accepted:
        diverse = select_diverse_segments(accepted, requested=requested)
        # Log which segments were dropped by diversity
        accepted_ids = {id(s) for s in diverse}
        for seg in accepted:
            if id(seg) not in accepted_ids:
                logger.info(
                    "SEGMENT_DIVERSITY_DROPPED start=%s end=%s theme=%s reason=diversity_filter",
                    seg.get("start_time"), seg.get("end_time"),
                    seg.get("duplicate_theme_key", "unknown"),
                )
        accepted = diverse

    # ── v2.0 — First-3s prediction & selection contract ───────────────────────
    # Add first-3s hook prediction and build selection contract for each
    # accepted segment. The contract is consumed by the editing pipeline.
    for seg in accepted:
        text = str(seg.get("text") or "")
        hook_pred = _predict_first3_strength(text)
        seg["predicted_first3_strength"] = hook_pred["predicted_first3_strength"]
        seg["trim_to_hook_candidate"] = hook_pred["trim_to_hook_candidate"]
        seg["hook_start_offset"] = hook_pred["hook_start_offset"]
        seg["selection_contract"] = build_selection_contract(seg)
        logger.info(
            "SEGMENT_HOOK_PREDICTION start=%s end=%s first3=%.2f trim=%s offset=%.2f",
            seg.get("start_time"), seg.get("end_time"),
            hook_pred["predicted_first3_strength"],
            hook_pred["trim_to_hook_candidate"],
            hook_pred["hook_start_offset"],
        )

    return accepted, rejected


def build_delivery_contract(*, requested: int, delivered: int, rejected_reasons: List[Dict[str, Any]]) -> Dict[str, Any]:
    if delivered < requested:
        reason = "insufficient_valid_candidates"
        logger.info("[delivery-contract] requested=%d delivered=%d status=shortage reason=%s", requested, delivered, reason)
    else:
        reason = ""
        logger.info("[delivery-contract] requested=%d delivered=%d status=ok", requested, delivered)
    return {
        "requested_num_clips": requested,
        "delivered_num_clips": delivered,
        "shortage_reason": reason,
        "rejected_candidate_reasons": rejected_reasons,
    }


# ── Retention Editing Plan ─────────────────────────────────────────────────────

@dataclass
class RetentionEditingPlan:
    """Complete retention editing plan for one clip.

    Each sub-plan is a dict with at minimum an 'enabled' bool and strategy
    details.  The retention_score is a 0-20 heuristic; retention_warnings
    list any concerns.
    """
    enabled: bool
    clip_index: int = 0
    clip_duration_s: float = 0.0
    editorial_type: str = ""

    # Sub-plans
    hook_strategy: Dict[str, Any] = field(default_factory=dict)
    silence_strategy: Dict[str, Any] = field(default_factory=dict)
    pattern_interruptions: List[Dict[str, Any]] = field(default_factory=list)
    sfx_plan: Dict[str, Any] = field(default_factory=dict)
    music_plan: Dict[str, Any] = field(default_factory=dict)
    visual_effects_plan: Dict[str, Any] = field(default_factory=dict)
    transition_plan: Dict[str, Any] = field(default_factory=dict)
    caption_visual_support_plan: Dict[str, Any] = field(default_factory=dict)
    frame_rhythm_plan: Dict[str, Any] = field(default_factory=dict)

    # Overall assessment
    retention_score: int = 0       # 0-20 heuristic
    retention_warnings: List[str] = field(default_factory=list)
    retention_missing_layers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Hook strategy ──────────────────────────────────────────────────────────────

def _is_vpi_productive_minimum() -> bool:
    """Check if VPI productive minimum mode is active (env or config)."""
    val = os.environ.get("VPI_PRODUCTIVE_MINIMUM", "")
    if val:
        return val.lower() in ("1", "true", "yes")
    beta = os.environ.get("VIRACLIP_BETA_CLEAN", "")
    if beta.lower() in ("1", "true", "yes"):
        return True
    return False


def _build_hook_strategy(
    hook_plan: Optional[Dict[str, Any]],
    editorial_type: str,
) -> Dict[str, Any]:
    """Derive hook strategy from existing hook_plan.

    FASE 7: Includes hook_intent and hook_style from v1.7 Hook Fit layer.
    When hook_intent is available, strengthening suggestions are informed
    by the detected intent rather than editorial_type alone.

    [vpi-productive-minimum] When productive minimum is active and the hook
    needs strengthening, ensures at least one visible mitigation is applied:
    motion push-in, hook_card, semantic_card, or subtitle highlight.
    """
    if not hook_plan:
        return {"enabled": False, "reason": "no_hook_plan"}
    hook_type = str(hook_plan.get("hook_type") or "")
    if hook_type == "weak_intro":
        return {"enabled": False, "reason": "weak_intro", "hook_type": hook_type}

    first3_score = int(hook_plan.get("hook_first3_score") or 0)
    first3_perceptible = bool(hook_plan.get("hook_first3_perceptible"))
    first4_score = int(hook_plan.get("hook_first_4s_score") or 0)

    # ── FASE 7: Extract hook intent & style from v1.7 Hook Fit ──────────────
    hook_intent = str(hook_plan.get("hook_intent") or "")
    hook_style = str(hook_plan.get("hook_style") or "")
    hook_fit_confidence = int(hook_plan.get("hook_fit_confidence") or 0)
    hook_fit_acceptable = bool(hook_plan.get("hook_fit_acceptable"))
    hook_start_adjusted = bool(hook_plan.get("hook_start_adjusted"))
    hook_start_adjustment_reason = str(hook_plan.get("hook_start_adjustment_reason") or "")

    needs_strengthening = first3_score < 5 or not first3_perceptible

    strategy: Dict[str, Any] = {
        "enabled": True,
        "hook_type": hook_type,
        "hook_first3_score": first3_score,
        "hook_first3_perceptible": first3_perceptible,
        "hook_first_4s_score": first4_score,
        "needs_strengthening": needs_strengthening,
        "editorial_type": editorial_type,
        # FASE 7: Hook Fit contextual fields
        "hook_intent": hook_intent,
        "hook_style": hook_style,
        "hook_fit_confidence": hook_fit_confidence,
        "hook_fit_acceptable": hook_fit_acceptable,
        "hook_start_adjusted": hook_start_adjusted,
        "hook_start_adjustment_reason": hook_start_adjustment_reason,
    }

    if first3_score < 5:
        # FASE 7: Use hook_intent to inform strengthening when available
        if hook_intent:
            strategy["strengthen_suggestions"] = _suggest_hook_strengthening_via_intent(
                hook_intent, hook_style, editorial_type, hook_type
            )
        else:
            strategy["strengthen_suggestions"] = _suggest_hook_strengthening(editorial_type, hook_type)

    # [vpi-productive-minimum] When hook needs strengthening and productive minimum
    # is active, ensure at least one visible mitigation is applied so the hook
    # can pass strict QC review. The mitigation is recorded in the strategy so
    # downstream rendering (hook_card, motion, subtitle highlight) can act on it.
    if needs_strengthening and _is_vpi_productive_minimum():
        strategy["vpi_productive_minimum_mitigation"] = True
        strategy["vpi_productive_minimum_mitigation_type"] = "motion_push_in"
        logger.info(
            "[vpi-productive-minimum] hook mitigation applied: motion_push_in "
            "for score=%d perceptible=%s",
            first3_score, first3_perceptible,
        )

    logger.info(
        "[hook-strategy] intent=%s style=%s score=%d needs_strengthening=%s",
        hook_intent or "none",
        hook_style or "none",
        first3_score,
        strategy.get("needs_strengthening", False),
    )
    return strategy


def _suggest_hook_strengthening(editorial_type: str, hook_type: str) -> List[str]:
    suggestions: List[str] = []
    if editorial_type in ("client_objection", "myth_debunk"):
        suggestions.append("add_punch_subtitle_before_2s")
        suggestions.append("add_kickframe_or_zoom")
    elif editorial_type == "emotional_protection":
        suggestions.append("add_emotional_push_in_before_2s")
        suggestions.append("add_strong_phrase_subtitle")
    elif editorial_type == "risk_warning":
        suggestions.append("add_risk_punch_zoom")
        suggestions.append("add_dramatic_subtitle")
    else:
        suggestions.append("add_visual_motion_before_2s")
        suggestions.append("add_subtitle_hook")
    if hook_type == "explanation_hook":
        suggestions.append("add_utility_headline_overlay")
    return suggestions


def _suggest_hook_strengthening_via_intent(
    hook_intent: str,
    hook_style: str,
    editorial_type: str,
    hook_type: str,
) -> List[str]:
    """Suggest hook strengthening based on detected hook intent (FASE 7).

    Uses the v1.7 Hook Fit intent classification to produce more precise
    strengthening suggestions than the editorial_type-only fallback.
    """
    suggestions: List[str] = []

    # Intent-specific strengthening
    if hook_intent == "myth_flip":
        suggestions.append("add_contrast_subtitle_before_2s")
        suggestions.append("add_kickframe_or_zoom")
        if hook_style == "calm_reveal":
            suggestions.append("add_subtle_push_in")
    elif hook_intent == "risk_warning":
        suggestions.append("add_risk_punch_zoom")
        suggestions.append("add_dramatic_subtitle")
        if hook_style == "tension_pause_subtle":
            suggestions.append("add_micro_silence_before_2s")
    elif hook_intent == "practical_advice":
        suggestions.append("add_utility_headline_overlay")
        suggestions.append("add_subtitle_hook")
        if hook_style == "clean_explanation":
            suggestions.append("add_visual_motion_before_2s")
    elif hook_intent == "autonomous_business_stakes":
        suggestions.append("add_punch_subtitle_before_2s")
        suggestions.append("add_emphasis_zoom")
        if hook_style == "punchy_business":
            suggestions.append("add_kickframe")
    elif hook_intent == "emotional_closure":
        suggestions.append("add_emotional_push_in_before_2s")
        suggestions.append("add_strong_phrase_subtitle")
        if hook_style == "soft_cinematic_push":
            suggestions.append("add_micro_silence_before_2s")
    elif hook_intent == "neutral_explanation":
        suggestions.append("add_visual_motion_before_2s")
        suggestions.append("add_subtitle_hook")
        if hook_type == "explanation_hook":
            suggestions.append("add_utility_headline_overlay")
    else:
        # Fallback to editorial_type-based suggestions
        return _suggest_hook_strengthening(editorial_type, hook_type)

    logger.info(
        "[hook-strengthen] intent=%s style=%s suggestions=%s",
        hook_intent,
        hook_style,
        "|".join(suggestions),
    )
    return suggestions


# ── Silence strategy ───────────────────────────────────────────────────────────

def _build_silence_strategy(
    silence_plan: Optional[Dict[str, Any]],
    editorial_type: str,
    clip_duration_s: float,
) -> Dict[str, Any]:
    """Build silence-as-retention-tool strategy."""
    if not silence_plan:
        return {"enabled": False, "reason": "no_silence_plan"}

    segments = silence_plan.get("segments") or []
    cuts = silence_plan.get("cuts") or []
    total_removed = float(silence_plan.get("total_removed_s") or 0.0)

    # Count preserved emphasis pauses
    preserved_emphasis = sum(
        1 for s in segments
        if s.get("action") in ("preserve", "preserve_and_emphasize")
        and s.get("pause_type") in ("emphasis_pause", "dramatic_pause", "let_it_land_pause")
    )

    # Count pattern interruption opportunities (silence + SFX)
    pattern_interruptions = _detect_pattern_interruption_opportunities(
        segments, editorial_type, clip_duration_s
    )

    return {
        "enabled": True,
        "total_segments": len(segments),
        "total_cuts": len(cuts),
        "total_removed_s": round(total_removed, 3),
        "preserved_emphasis_pauses": preserved_emphasis,
        "pattern_interruption_opportunities": pattern_interruptions,
        "micro_silence_before_key_phrases": _detect_micro_silence_opportunities(segments),
        "editorial_type": editorial_type,
    }


def _detect_pattern_interruption_opportunities(
    segments: List[Dict[str, Any]],
    editorial_type: str,
    clip_duration_s: float,
) -> List[Dict[str, Any]]:
    """Find pauses where a pattern interruption (silence + SFX) would work."""
    opportunities: List[Dict[str, Any]] = []
    for s in segments:
        pause_type = s.get("pause_type", "")
        action = s.get("action", "")
        start = float(s.get("start_s", 0.0) or 0.0)
        duration = float(s.get("duration_s", 0.0) or 0.0)
        after = str(s.get("after_text", "") or "")

        # Pattern interruption: before a strong phrase, after a list, or mid-editorial
        if action in ("preserve", "preserve_and_emphasize") and duration >= 0.25:
            if pause_type in ("dramatic_pause", "emphasis_pause", "let_it_land_pause"):
                opportunities.append({
                    "start_s": round(start, 3),
                    "duration_s": round(duration, 3),
                    "type": "silence_before_key_phrase",
                    "sfx_candidate": "deep_boom" if editorial_type == "risk_warning" else "magic_whoosh",
                    "after_text": after[:60],
                })
            elif pause_type == "transition_pause" and duration >= 0.3:
                opportunities.append({
                    "start_s": round(start, 3),
                    "duration_s": round(duration, 3),
                    "type": "transition_with_sfx",
                    "sfx_candidate": "dark_riser_combo",
                    "after_text": after[:60],
                })
    return opportunities


def _detect_micro_silence_opportunities(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Find micro-silences before key phrases that should be preserved for tension."""
    opportunities: List[Dict[str, Any]] = []
    for s in segments:
        after = str(s.get("after_text", "") or "").lower()
        duration = float(s.get("duration_s", 0.0) or 0.0)
        # Preserve micro-silence before key VPI concepts
        key_terms = ["responsabilidad", "proteger", "imprevisto", "no es solo", "dependen"]
        if any(term in after for term in key_terms) and 0.12 <= duration <= 0.45:
            opportunities.append({
                "start_s": round(float(s.get("start_s", 0.0) or 0.0), 3),
                "duration_s": round(duration, 3),
                "reason": f"micro_silence_before_key_phrase:{after[:40]}",
            })
    return opportunities


# ── SFX plan ───────────────────────────────────────────────────────────────────

def _build_sfx_plan(
    editorial_type: str,
    hook_type: str,
    pattern_interruptions: List[Dict[str, Any]],
    clip_duration_s: float,
) -> Dict[str, Any]:
    """Build SFX strategy with repetition guard."""
    sfx_events: List[Dict[str, Any]] = []
    used_sfx_types: List[str] = []

    # Hook SFX (first 3 seconds)
    if hook_type not in ("weak_intro", "explanation_hook"):
        if editorial_type == "risk_warning":
            sfx_events.append({
                "start_s": 0.3,
                "duration_s": 0.8,
                "type": "dark_riser_combo",
                "volume": 0.35,
                "reason": "hook_tension_riser",
            })
            used_sfx_types.append("dark_riser_combo")
        elif editorial_type in ("client_objection", "myth_debunk"):
            sfx_events.append({
                "start_s": 0.25,
                "duration_s": 0.6,
                "type": "magic_whoosh",
                "volume": 0.30,
                "reason": "hook_contrast_whoosh",
            })
            used_sfx_types.append("magic_whoosh")
        else:
            sfx_events.append({
                "start_s": 0.35,
                "duration_s": 0.5,
                "type": "magic_whoosh",
                "volume": 0.25,
                "reason": "hook_subtle_whoosh",
            })
            used_sfx_types.append("magic_whoosh")

    # Pattern interruption SFX
    for pi in pattern_interruptions:
        sfx_type = str(pi.get("sfx_candidate", "magic_whoosh"))
        # Repetition guard: skip if same type used in last 3 seconds
        if sfx_type in used_sfx_types:
            # Try alternative
            alternatives = {
                "dark_riser_combo": "deep_boom",
                "magic_whoosh": "dark_riser_combo",
                "deep_boom": "magic_whoosh",
            }
            sfx_type = alternatives.get(sfx_type, "magic_whoosh")
        sfx_events.append({
            "start_s": float(pi.get("start_s", 0.0)),
            "duration_s": 0.5,
            "type": sfx_type,
            "volume": 0.25,
            "reason": f"pattern_interruption:{pi.get('type', 'unknown')}",
        })
        used_sfx_types.append(sfx_type)

    # Emphasis SFX for key moments
    if clip_duration_s >= 15.0 and len(sfx_events) < 4:
        mid_point = clip_duration_s * 0.5
        sfx_events.append({
            "start_s": round(mid_point, 2),
            "duration_s": 0.4,
            "type": "deep_boom",
            "volume": 0.20,
            "reason": "mid_clip_emphasis",
        })

    return {
        "enabled": bool(sfx_events),
        "sfx_events": sfx_events,
        "total_sfx": len(sfx_events),
        "repetition_guard_applied": True,
    }


# ── Music plan ─────────────────────────────────────────────────────────────────

def _build_music_plan(
    editorial_type: str,
    clip_duration_s: float,
    existing_music: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build music background strategy."""
    if existing_music and existing_music.get("music_applied"):
        return {
            "enabled": True,
            "source": "existing",
            "volume_db": -26.0,
            "fade_in_s": 0.25,
            "fade_out_s": 0.5,
            "mood": existing_music.get("mood", "neutral"),
        }

    mood_map: Dict[str, str] = {
        "risk_warning": "tense_cinematic",
        "myth_debunk": "mysterious_curious",
        "client_objection": "thoughtful_serious",
        "emotional_protection": "warm_emotional",
        "actionable_advice": "uplifting_motivational",
        "coverage_explanation": "neutral_informative",
        "generic": "neutral_background",
    }
    mood = mood_map.get(editorial_type, "neutral_background")

    return {
        "enabled": True,
        "source": "library",
        "volume_db": -26.0,
        "fade_in_s": 0.25,
        "fade_out_s": 0.5,
        "mood": mood,
        "editorial_type": editorial_type,
    }


# ── Visual effects plan ────────────────────────────────────────────────────────

def _build_visual_effects_plan(
    editorial_type: str,
    hook_type: str,
    clip_duration_s: float,
    existing_effects: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build visual effects plan with motion scaling and frame rhythm.

    [vpi-productive-minimum] When productive minimum is active, applies a
    subtle micro_zoom even for weak_intro hooks to ensure at least one visual
    effect layer is present for strict QC.
    """
    events: List[Dict[str, Any]] = []
    used_effects: List[str] = []

    if hook_type == "weak_intro":
        if _is_vpi_productive_minimum():
            # Apply subtle micro_zoom as fallback visual support
            events.append({
                "type": "micro_zoom",
                "start_s": 0.5,
                "duration_s": 1.0,
                "scale": 1.015,
                "reason": "vpi_productive_minimum_visual_fallback",
            })
            used_effects.append("micro_zoom")
            logger.info(
                "[vpi-productive-minimum] vfx fallback: micro_zoom at 1.015x "
                "for weak_intro hook_type=%s editorial=%s",
                hook_type, editorial_type,
            )
            frame_rhythm = _build_frame_rhythm(clip_duration_s)
            return {
                "enabled": True,
                "events": events,
                "total_events": len(events),
                "frame_rhythm": frame_rhythm,
                "vpi_productive_minimum_fallback": True,
            }
        return {"enabled": False, "reason": "weak_intro"}

    # Hook motion (first 3 seconds)
    if editorial_type == "risk_warning":
        events.append({
            "type": "hook_push_in",
            "start_s": 0.3,
            "duration_s": 1.2,
            "scale": 1.04,
            "reason": "risk_hook_push",
        })
        used_effects.append("hook_push_in")
    elif editorial_type in ("client_objection", "myth_debunk"):
        events.append({
            "type": "emphasis_zoom",
            "start_s": 0.35,
            "duration_s": 0.8,
            "scale": 1.05,
            "reason": "objection_punch_zoom",
        })
        used_effects.append("emphasis_zoom")
    elif editorial_type == "emotional_protection":
        events.append({
            "type": "subtle_push_in",
            "start_s": 0.4,
            "duration_s": 1.5,
            "scale": 1.03,
            "reason": "emotional_push_in",
        })
        used_effects.append("subtle_push_in")
    else:
        events.append({
            "type": "micro_zoom",
            "start_s": 0.5,
            "duration_s": 1.0,
            "scale": 1.025,
            "reason": "first3_hook_support",
        })
        used_effects.append("micro_zoom")

    # Mid-clip emphasis zoom (if clip is long enough)
    if clip_duration_s >= 12.0:
        mid_start = clip_duration_s * 0.45
        events.append({
            "type": "emphasis_zoom",
            "start_s": round(mid_start, 2),
            "duration_s": 1.0,
            "scale": 1.03,
            "reason": "mid_clip_emphasis",
        })
        used_effects.append("emphasis_zoom")

    # Frame rhythm: 5 frames then 10 frames for narrative progression
    frame_rhythm = _build_frame_rhythm(clip_duration_s)

    return {
        "enabled": bool(events),
        "events": events,
        "total_events": len(events),
        "frame_rhythm": frame_rhythm,
    }


# ── Frame rhythm ───────────────────────────────────────────────────────────────

def _build_frame_rhythm(clip_duration_s: float) -> Dict[str, Any]:
    """Build frame rhythm plan: 5 frames then 10 frames for narrative progression.

    At 30fps: 5 frames = 0.17s, 10 frames = 0.33s.
    This creates a non-robotic visual rhythm.
    """
    if clip_duration_s < 8.0:
        return {"enabled": False, "reason": "clip_too_short"}

    # Generate rhythm segments
    segments: List[Dict[str, Any]] = []
    cursor = 0.0
    rhythm_pattern = [5, 10, 5, 10, 5, 10, 8, 12, 6, 10]  # frames
    fps = 30.0
    pattern_idx = 0

    while cursor < clip_duration_s:
        frames = rhythm_pattern[pattern_idx % len(rhythm_pattern)]
        duration = frames / fps
        end = min(cursor + duration, clip_duration_s)
        actual_frames = round((end - cursor) * fps)
        segments.append({
            "start_s": round(cursor, 3),
            "end_s": round(end, 3),
            "frames": actual_frames,
            "duration_s": round(end - cursor, 3),
            "rhythm_type": "short" if actual_frames <= 7 else "long",
        })
        cursor = end
        pattern_idx += 1

    return {
        "enabled": True,
        "fps": fps,
        "segments": segments,
        "total_segments": len(segments),
        "pattern": "5_10_variable",
    }


# ── Transition plan ────────────────────────────────────────────────────────────

def _build_transition_plan(
    editorial_type: str,
    hook_type: str,
    clip_duration_s: float,
    text: str = "",
    coherence_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build premium transition plan.

    [vpi-productive-minimum] When productive minimum is active, applies a
    clean_cut transition even for weak_intro hooks to ensure at least one
    transition layer is present for strict QC.
    """
    transitions: List[Dict[str, Any]] = []
    text_l = (text or "").lower()
    dense_explanation = any(
        token in text_l for token in ("cobertura", "deducible", "franquicia", "prima", "póliza", "poliza")
    ) and len(text_l.split()) >= 18

    if hook_type == "weak_intro":
        if _is_vpi_productive_minimum():
            # Apply clean_cut as fallback transition
            hook_end = min(4.0, clip_duration_s * 0.25)
            transitions.append({
                "start_s": round(hook_end, 2),
                "duration_s": 0.2,
                "type": "clean_cut",
                "reason": "vpi_productive_minimum_transition_fallback",
            })
            logger.info(
                "[vpi-productive-minimum] transition fallback: clean_cut at %.2fs "
                "for weak_intro editorial=%s",
                hook_end, editorial_type,
            )
            return {
                "enabled": True,
                "transitions": transitions,
                "total_transitions": len(transitions),
                "vpi_productive_minimum_fallback": True,
            }
        return {"enabled": False, "reason": "weak_intro"}

    # Hook-to-content transition (around 3-4 seconds)
    hook_end = min(4.0, clip_duration_s * 0.25)
    intent = "topic_shift"
    confidence = 0.72
    transition_type = "clean_cut"
    reason = "topic_shift_default"
    if editorial_type == "risk_warning":
        intent = "risk_warning"
        confidence = 0.88
        transition_type = "dark_push"
        reason = "risk_warning_context"
    elif editorial_type in ("client_objection", "myth_debunk"):
        intent = "revelation"
        confidence = 0.84
        transition_type = "sweep_reveal"
        reason = "revelation_contrast"
    elif editorial_type == "emotional_protection":
        intent = "emotional_protection"
        confidence = 0.86
        transition_type = "soft_dissolve"
        reason = "emotional_protection_softness"
    elif editorial_type in ("coverage_explanation", "actionable_advice"):
        intent = "paperwork_explanation"
        confidence = 0.82
        transition_type = "document_slide_reveal"
        reason = "paperwork_or_explanation"
    else:
        intent = "topic_shift"
        confidence = 0.76
        transition_type = "soft_push"
        reason = "topic_shift_clean"

    if dense_explanation and transition_type in {"sweep_reveal", "quick_flash_cut", "dark_push", "quick_impact_cut"}:
        transition_type = "clean_cut"
        reason = "dense_technical_explanation_downgrade"
        logger.info("VISUAL_TRANSITION_SKIPPED reason=dense_technical_explanation_flashy_transition")
    coherence_style = str(_as_dict(coherence_plan).get("visual_style") or "")
    if coherence_style == "calm_trust" and transition_type in {"dark_push", "quick_impact_cut"}:
        logger.info("VISUAL_COHERENCE_CONFLICT resolved_primary=calm_trust dropped=aggressive_transition reason=style_guard")
        transition_type = "soft_dissolve"
        reason = "coherence_style_guard_calm"
    if coherence_style == "serious_warning" and transition_type in {"warm_reveal"}:
        logger.info("VISUAL_COHERENCE_CONFLICT resolved_primary=serious_warning dropped=warm_transition reason=style_guard")
        transition_type = "dark_push"
        reason = "coherence_style_guard_warning"

    transitions.append({
        "start_s": round(hook_end, 2),
        "duration_s": 0.3 if transition_type in {"sweep_reveal", "dark_push", "soft_dissolve"} else 0.2,
        "type": transition_type,
        "intent": intent,
        "confidence": round(confidence, 2),
        "reason": reason,
    })
    logger.info(
        "VISUAL_TRANSITION_SELECTED intent=%s transition=%s confidence=%.2f reason=%s",
        intent, transition_type, confidence, reason,
    )

    # Mid-clip transition if clip is long
    if clip_duration_s >= 15.0:
        mid = clip_duration_s * 0.5
        transitions.append({
            "start_s": round(mid, 2),
            "duration_s": 0.3,
            "type": "match_cut",
            "intent": "broll_insertion",
            "confidence": 0.74,
            "reason": "mid_clip_pacing_shift",
        })
        logger.info(
            "VISUAL_TRANSITION_SELECTED intent=%s transition=%s confidence=%.2f reason=%s",
            "broll_insertion", "match_cut", 0.74, "mid_clip_pacing_shift",
        )

    max_transitions = 2 if clip_duration_s <= 20.0 else (3 if clip_duration_s <= 40.0 else 4)
    if len(transitions) > max_transitions:
        transitions = transitions[:max_transitions]
        logger.info("VISUAL_TRANSITION_SKIPPED reason=transition_budget_cap")

    return {
        "enabled": bool(transitions),
        "transitions": transitions,
        "total_transitions": len(transitions),
        "transition_budget_max": max_transitions,
        "transition_contextual": bool(transitions),
    }


# ── Caption visual support plan ────────────────────────────────────────────────

def _build_caption_visual_support_plan(
    editorial_type: str,
    text: str,
    clip_duration_s: float = 20.0,
    *,
    has_broll_active: bool = False,
    has_hook_card_active: bool = False,
    coherence_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build caption visual support plan with icons for VPI concepts.

    [vpi-productive-minimum] When productive minimum is active and no concept
    matched in the text, applies a fallback icon based on editorial_type to
    ensure at least one icon is present for strict QC.
    """
    concept_terms: Dict[str, List[str]] = {
        "familia": ["familia", "family", "hijos", "pareja", "casa"],
        "proteccion": ["proteccion", "proteger", "protection", "escudo"],
        "salud": ["salud", "health", "vida", "corazon"],
        "viaje": ["viaje", "travel", "maleta", "avion"],
        "riesgo": ["riesgo", "risk", "alerta", "imprevisto", "cuidado"],
        "dinero": ["dinero", "hipoteca", "money", "euro", "casa"],
        "responsabilidad": ["responsabilidad", "responsibility", "dependen"],
    }
    icon_assets = _discover_caption_icon_assets()
    text_lower = text.lower()
    matched_icons: List[Dict[str, Any]] = []
    skipped_reason = ""
    for concept, terms in concept_terms.items():
        if not any(term in text_lower for term in terms):
            continue
        asset = _match_caption_icon_asset(concept, terms, icon_assets)
        if asset:
            matched_icons.append({"concept": concept, "asset": str(asset), "reason": f"concept_match:{concept}"})
            logger.info("[caption-visual] concept=%s icon=%s applied=true", concept, asset)
            break
        skipped_reason = "no_local_asset"
        logger.info("[caption-visual] skipped reason=no_local_asset concept=%s", concept)

    # [vpi-productive-minimum] Fallback icon when no concept matched in text
    if not matched_icons and _is_vpi_productive_minimum():
        fallback_concept = _editorial_type_to_fallback_concept(editorial_type)
        asset = _match_caption_icon_asset(fallback_concept, [], icon_assets)
        if asset:
            matched_icons.append({
                "concept": fallback_concept,
                "asset": str(asset),
                "reason": f"vpi_productive_minimum_fallback:{fallback_concept}",
            })
            logger.info(
                "[vpi-productive-minimum] caption icon fallback: concept=%s "
                "icon=%s for editorial_type=%s",
                fallback_concept, asset, editorial_type,
            )
        else:
            logger.info(
                "[vpi-productive-minimum] caption icon fallback skipped: "
                "no_local_asset for concept=%s editorial_type=%s",
                fallback_concept, editorial_type,
            )

    semantic_objects: List[Dict[str, Any]] = []
    semantic_skip_reason = ""
    tokens = [w.strip(".,;:!?") for w in text_lower.split() if w.strip(".,;:!?")]
    stopword_only = len(tokens) < 3
    object_map: List[tuple[str, tuple[str, ...], str]] = [
        ("life_insurance", ("seguro de vida", "vida", "proteger"), "shield"),
        ("paperwork", ("papeleo", "documentos", "poliza", "póliza", "formulario", "tramite", "trámite"), "document"),
        ("risk", ("riesgo", "miedo", "cuidado", "imprevisto"), "warning"),
        ("health", ("salud", "hospital", "medico", "médico"), "health"),
        ("savings_finance", ("ahorro", "dinero", "presupuesto", "finanzas"), "euro"),
        ("protection_calm", ("calma", "tranquilidad", "familia", "proteger"), "family"),
        ("advice_action", ("consejo", "revisa", "haz", "paso"), "checklist"),
    ]
    matched_obj: Optional[tuple[str, str, str]] = None
    for category, terms, icon_hint in object_map:
        phrase = next((t for t in terms if t in text_lower), None)
        if phrase:
            matched_obj = (category, phrase, icon_hint)
            break

    layer_count = 2 + (1 if has_broll_active else 0) + (1 if has_hook_card_active else 0)
    coherence_style = str(_as_dict(coherence_plan).get("visual_style") or "")
    if stopword_only:
        semantic_skip_reason = "stopword_or_low_signal"
    elif not matched_obj:
        semantic_skip_reason = "no_semantic_phrase_match"
    elif layer_count >= 4:
        semantic_skip_reason = "visual_competition_with_face_caption_broll"
        logger.info("VISUAL_CLUTTER_GUARD action=skip_layer layer=semantic_object reason=caption_face_broll_competition")
    else:
        category, phrase, icon_hint = matched_obj
        if coherence_style == "serious_warning" and category in {"protection_calm", "life_insurance"}:
            semantic_skip_reason = "coherence_style_object_conflict"
            logger.info("VISUAL_COHERENCE_CONFLICT resolved_primary=serious_warning dropped=warm_object reason=style_guard")
        if coherence_style == "clear_explanation" and category not in {"paperwork", "advice_action", "savings_finance", "life_insurance"}:
            semantic_skip_reason = "coherence_style_object_conflict"
            logger.info("VISUAL_COHERENCE_CONFLICT resolved_primary=clear_explanation dropped=non_admin_object reason=style_guard")
    if not semantic_skip_reason and matched_obj:
        category, phrase, icon_hint = matched_obj
        candidate = _match_caption_icon_asset(icon_hint, [category, phrase], icon_assets)
        selected_asset = str(candidate) if candidate else f"symbolic:{icon_hint}"
        max_objects = min(3, max(1, int(clip_duration_s // 8)))
        for idx in range(max_objects):
            start = round(1.2 + (idx * 7.0), 2)
            semantic_objects.append(
                {
                    "category": category,
                    "asset": selected_asset,
                    "phrase": phrase,
                    "timing_s": start,
                    "animation": "kick_5_to_10_frames",
                    "opacity": 0.82,
                    "scale": 0.92,
                    "asset_source": "local" if candidate else "symbolic_fallback",
                }
            )
        logger.info(
            "SEMANTIC_OBJECT_SELECTED category=%s asset=%s phrase=%s timing=%s animation=kick_5_to_10_frames",
            category,
            selected_asset,
            phrase,
            ",".join(str(obj["timing_s"]) for obj in semantic_objects),
        )

    if semantic_skip_reason:
        logger.info("SEMANTIC_OBJECT_SKIPPED reason=%s", semantic_skip_reason)

    return {
        "enabled": bool(matched_icons),
        "icons": matched_icons,
        "total_icons": len(matched_icons),
        "style": "simple_text_reinforcement",
        "editorial_type": editorial_type,
        "caption_visual_support_applied": bool(matched_icons),
        "caption_icon_asset": matched_icons[0]["asset"] if matched_icons else None,
        "caption_icon_reason": matched_icons[0]["reason"] if matched_icons else None,
        "caption_visual_support_skipped_reason": "" if matched_icons else (skipped_reason or "no_matching_concept"),
        "semantic_objects_enabled": bool(semantic_objects),
        "semantic_objects": semantic_objects,
        "semantic_objects_count": len(semantic_objects),
        "semantic_object_skip_reason": semantic_skip_reason,
    }


def _build_motion_reveal_plan(
    editorial_type: str,
    text: str,
    clip_duration_s: float,
) -> Dict[str, Any]:
    text_l = (text or "").lower()
    reveals: List[Dict[str, Any]] = []
    major_cap = 1 if clip_duration_s <= 40.0 else 2
    if any(token in text_l for token in ("esto mucha gente no lo sabe", "la realidad es", "lo importante")):
        reveals.append({"type": "sweeping_reveal", "target": "hook", "reason": "revelation_hook", "start_s": 0.7})
        logger.info("MOTION_REVEAL_SELECTED type=sweeping_reveal target=hook reason=revelation_hook")
    elif editorial_type in {"coverage_explanation", "actionable_advice"} and any(
        token in text_l for token in ("papeleo", "póliza", "poliza", "documento", "cobertura")
    ):
        reveals.append({"type": "mask_reveal", "target": "document_object", "reason": "paperwork_intro", "start_s": 1.0})
        logger.info("MOTION_REVEAL_SELECTED type=mask_reveal target=document_object reason=paperwork_intro")
    elif editorial_type == "risk_warning":
        reveals.append({"type": "push_in", "target": "face", "reason": "risk_warning_tension", "start_s": 0.8})
        logger.info("MOTION_REVEAL_SELECTED type=push_in target=face reason=risk_warning_tension")
    elif editorial_type == "emotional_protection":
        reveals.append({"type": "caption_emphasis_reveal", "target": "caption", "reason": "warm_reassurance", "start_s": 1.0})
        logger.info("MOTION_REVEAL_SELECTED type=caption_emphasis_reveal target=caption reason=warm_reassurance")
    else:
        logger.info("MOTION_REVEAL_SKIPPED reason=no_strong_reveal_intent")

    if len(reveals) > major_cap:
        reveals = reveals[:major_cap]
        logger.info("MOTION_REVEAL_SKIPPED reason=major_reveal_budget_cap")
    return {
        "enabled": bool(reveals),
        "reveals": reveals,
        "count": len(reveals),
        "major_reveal_cap": major_cap,
    }


def _editorial_type_to_fallback_concept(editorial_type: str) -> str:
    """Map editorial_type to a fallback icon concept for productive minimum mode."""
    mapping: Dict[str, str] = {
        "risk_warning": "proteccion",
        "client_objection": "dinero",
        "myth_debunk": "responsabilidad",
        "emotional_protection": "familia",
        "actionable_advice": "salud",
        "coverage_explanation": "viaje",
        "generic": "responsabilidad",
    }
    return mapping.get(editorial_type, "responsabilidad")


def _discover_caption_icon_assets() -> List[Path]:
    root = Path(__file__).resolve().parents[3]
    dirs = (
        "assets/icons",
        "assets/overlays",
        "assets/visuals/icons",
        "assets/visuals/3d",
        "frontend/public/icons",
        "/app/assets/icons",
        "/app/assets/visuals/icons",
        "/app/assets/visuals/3d",
    )
    exts = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".glb", ".gltf"}
    assets: List[Path] = []
    for item in dirs:
        directory = Path(item)
        if not directory.is_absolute():
            directory = root / directory
        if not directory.exists() or not directory.is_dir():
            continue
        assets.extend(path for path in sorted(directory.rglob("*")) if path.is_file() and path.suffix.lower() in exts)
    return assets


def _match_caption_icon_asset(concept: str, terms: List[str], assets: List[Path]) -> Optional[Path]:
    needles = [concept, *terms]
    for asset in assets:
        name = asset.stem.lower()
        if any(term in name for term in needles):
            return asset
    return None


# ── Pattern interruptions ──────────────────────────────────────────────────────

def _build_pattern_interruptions(
    editorial_type: str,
    hook_type: str,
    silence_strategy: Dict[str, Any],
    clip_duration_s: float,
) -> List[Dict[str, Any]]:
    """Build pattern interruption plan.

    Pattern interruptions are moments where the video breaks its rhythm
    to re-engage attention: silence + SFX, visual change, or both.
    """
    interruptions: List[Dict[str, Any]] = []

    if hook_type == "weak_intro":
        return interruptions

    # 1. Hook pattern interruption (first 3 seconds)
    if editorial_type == "risk_warning":
        interruptions.append({
            "start_s": 0.5,
            "type": "silence_sfx",
            "sfx": "dark_riser_combo",
            "silence_duration_s": 0.15,
            "reason": "hook_tension_break",
        })
    elif editorial_type in ("client_objection", "myth_debunk"):
        interruptions.append({
            "start_s": 0.4,
            "type": "visual_sfx",
            "sfx": "magic_whoosh",
            "visual": "kickframe",
            "reason": "hook_contrast_break",
        })

    # 2. Mid-clip pattern interruption (around 40-50%)
    if clip_duration_s >= 12.0:
        mid = clip_duration_s * 0.45
        interruptions.append({
            "start_s": round(mid, 2),
            "type": "silence_sfx",
            "sfx": "deep_boom",
            "silence_duration_s": 0.2,
            "reason": "mid_clip_re_engagement",
        })

    # 3. Pattern interruptions from silence opportunities
    for opp in silence_strategy.get("pattern_interruption_opportunities", []):
        interruptions.append({
            "start_s": float(opp.get("start_s", 0.0)),
            "type": "silence_sfx",
            "sfx": str(opp.get("sfx_candidate", "magic_whoosh")),
            "silence_duration_s": min(float(opp.get("duration_s", 0.3)), 0.35),
            "reason": f"editorial_pause:{opp.get('type', 'unknown')}",
        })

    return interruptions


# ── Retention score ────────────────────────────────────────────────────────────

def _compute_retention_score(plan: RetentionEditingPlan) -> int:
    """Compute retention score 0-20 based on active layers and quality."""
    score = 0

    # Hook strategy (max 4 points)
    if plan.hook_strategy.get("enabled"):
        score += 2
        if plan.hook_strategy.get("hook_first3_perceptible"):
            score += 1
        if int(plan.hook_strategy.get("hook_first3_score", 0)) >= 5:
            score += 1

    # Silence strategy (max 3 points)
    if plan.silence_strategy.get("enabled"):
        score += 1
        if plan.silence_strategy.get("preserved_emphasis_pauses", 0) >= 1:
            score += 1
        if plan.silence_strategy.get("pattern_interruption_opportunities"):
            score += 1

    # SFX plan (max 3 points)
    if plan.sfx_plan.get("enabled"):
        score += 1
        sfx_count = int(plan.sfx_plan.get("total_sfx", 0))
        if sfx_count >= 2:
            score += 1
        if sfx_count >= 3:
            score += 1

    # Music plan (max 2 points)
    if plan.music_plan.get("enabled"):
        score += 2

    # Visual effects (max 3 points)
    if plan.visual_effects_plan.get("enabled"):
        score += 1
        event_count = int(plan.visual_effects_plan.get("total_events", 0))
        if event_count >= 2:
            score += 1
        if plan.visual_effects_plan.get("frame_rhythm", {}).get("enabled"):
            score += 1

    # Transitions (max 2 points)
    if plan.transition_plan.get("enabled"):
        score += 1
        if int(plan.transition_plan.get("total_transitions", 0)) >= 2:
            score += 1

    # Caption visual support (max 1 point)
    if plan.caption_visual_support_plan.get("enabled"):
        score += 1

    # Pattern interruptions (max 2 points)
    if plan.pattern_interruptions:
        score += 1
        if len(plan.pattern_interruptions) >= 2:
            score += 1

    return min(20, score)


# ── Main entry point ───────────────────────────────────────────────────────────

def build_retention_editing_plan(
    *,
    clip_index: int = 0,
    clip_duration_s: float = 0.0,
    editorial_type: str = "",
    text: str = "",
    transcript: str = "",
    word_timestamps: Optional[List[Dict[str, Any]]] = None,
    hook_plan: Optional[Dict[str, Any]] = None,
    silence_plan: Optional[Dict[str, Any]] = None,
    broll_plan: Optional[Dict[str, Any]] = None,
    visual_theme: Optional[Dict[str, Any]] = None,
    existing_metadata: Optional[Dict[str, Any]] = None,
    existing_music: Optional[Dict[str, Any]] = None,
    existing_effects: Optional[List[Dict[str, Any]]] = None,
) -> RetentionEditingPlan:
    """Build a complete RetentionEditingPlan for one clip.

    This is the main entry point.  Call after hook_plan and silence_plan
    are available, before SFX/music/effects rendering.
    """
    del visual_theme, existing_metadata
    if transcript and not text:
        text = transcript
    editorial = editorial_type or "generic"
    hook_type = str((hook_plan or {}).get("hook_type") or "")

    visual_coherence_plan = _build_visual_coherence_plan(editorial, text)
    disfluency_plan = _build_disfluency_plan(
        text,
        clip_duration_s,
        word_timestamps=word_timestamps,
        editorial_type=editorial,
    )

    # Build sub-plans (order matters: silence → pattern interruptions → SFX)
    hook_strategy = _build_hook_strategy(hook_plan, editorial)
    silence_strategy = _build_silence_strategy(silence_plan, editorial, clip_duration_s)
    pattern_interruptions = _build_pattern_interruptions(
        editorial, hook_type, silence_strategy, clip_duration_s,
    )
    sfx_plan = _build_sfx_plan(editorial, hook_type, pattern_interruptions, clip_duration_s)
    music_plan = _build_music_plan(editorial, clip_duration_s, existing_music)
    visual_effects_plan = _build_visual_effects_plan(editorial, hook_type, clip_duration_s, existing_effects)
    transition_plan = _build_transition_plan(editorial, hook_type, clip_duration_s, text, visual_coherence_plan)
    caption_visual_support_plan = _build_caption_visual_support_plan(
        editorial,
        text,
        clip_duration_s,
        has_broll_active=bool(broll_plan),
        has_hook_card_active=bool(_as_dict(hook_plan).get("overlay_rendered") or _as_dict(hook_plan).get("kickframe_applied")),
        coherence_plan=visual_coherence_plan,
    )
    caption_overlay_coherence = _build_caption_overlay_coherence_plan(
        text=text,
        clip_duration_s=clip_duration_s,
        visual_coherence_plan=visual_coherence_plan,
        disfluency_plan=disfluency_plan,
        semantic_objects=list(caption_visual_support_plan.get("semantic_objects") or []),
        has_broll_active=bool(broll_plan),
        has_hook_card_active=bool(_as_dict(hook_plan).get("overlay_rendered") or _as_dict(hook_plan).get("kickframe_applied")),
    )
    motion_reveal_plan = _build_motion_reveal_plan(editorial, text, clip_duration_s)
    visual_layer_count = 2 + (1 if bool(broll_plan) else 0) + (1 if caption_visual_support_plan.get("semantic_objects_enabled") else 0) + (1 if bool(_as_dict(hook_plan).get("overlay_rendered")) else 0)
    visual_clutter_score = round(min(1.0, visual_layer_count / 4.0), 2)
    if visual_layer_count >= 4:
        logger.info("VISUAL_CLUTTER_GUARD action=skip_layer layer=semantic_object reason=simultaneous_layer_budget")
    visual_effects_plan["motion_reveal_plan"] = motion_reveal_plan
    visual_effects_plan["has_motion_reveal"] = bool(motion_reveal_plan.get("enabled"))
    visual_effects_plan["visual_clutter_score"] = visual_clutter_score
    visual_effects_plan["visual_editing_quality"] = "needs_review" if visual_clutter_score > 0.9 else "premium_visual"
    visual_effects_plan["visual_coherence_plan"] = visual_coherence_plan
    visual_effects_plan["visual_style"] = str(visual_coherence_plan.get("visual_style") or "clear_explanation")
    visual_effects_plan["visual_coherence_score"] = round(
        max(
            0.0,
            1.0
            - (0.30 if visual_effects_plan["visual_editing_quality"] == "needs_review" else 0.0)
            - (0.15 if disfluency_plan.get("high_severity_unhandled_count", 0) > 0 else 0.0),
        ),
        2,
    )
    visual_effects_plan["disfluency_plan"] = disfluency_plan
    visual_effects_plan["has_disfluency_cleanup"] = bool(disfluency_plan.get("has_disfluency_cleanup"))
    visual_effects_plan["disfluency_cleanup_count"] = int(disfluency_plan.get("disfluency_cleanup_count") or 0)
    visual_effects_plan["covered_disfluency_count"] = int(disfluency_plan.get("covered_disfluency_count") or 0)
    visual_effects_plan["preserved_emphasis_pause_count"] = int(disfluency_plan.get("preserved_emphasis_pause_count") or 0)
    visual_effects_plan["disfluency_edit_quality"] = str(disfluency_plan.get("disfluency_edit_quality") or "good")
    visual_effects_plan["disfluency_events"] = list(disfluency_plan.get("events") or [])
    visual_effects_plan["caption_overlay_coherence"] = caption_overlay_coherence
    transition_plan["has_transition"] = bool(transition_plan.get("enabled"))
    caption_visual_support_plan["has_semantic_object"] = bool(caption_visual_support_plan.get("semantic_objects_enabled"))
    caption_visual_support_plan["caption_clean_text"] = str(caption_overlay_coherence.get("caption_clean_text") or "")
    caption_visual_support_plan["has_clean_captions"] = bool(caption_overlay_coherence.get("has_clean_captions"))
    caption_visual_support_plan["caption_disfluency_cleanup"] = dict(caption_overlay_coherence.get("caption_disfluency_cleanup") or {})
    caption_visual_support_plan["caption_readability_score"] = float(caption_overlay_coherence.get("caption_readability_score") or 0.0)
    caption_visual_support_plan["caption_style"] = str(caption_overlay_coherence.get("caption_style") or "clean_readable")
    caption_visual_support_plan["highlight_count"] = int(caption_overlay_coherence.get("highlight_count") or 0)
    caption_visual_support_plan["highlight_phrases"] = list(caption_overlay_coherence.get("highlight_phrases") or [])
    caption_visual_support_plan["overlay_coherence_score"] = float(caption_overlay_coherence.get("overlay_coherence_score") or 0.0)
    caption_visual_support_plan["overlay_duplication_warning"] = bool(caption_overlay_coherence.get("overlay_duplication_warning"))
    caption_visual_support_plan["safe_area_conflicts"] = list(caption_overlay_coherence.get("safe_area_conflicts") or [])
    caption_visual_support_plan["caption_timing_conflict"] = bool(caption_overlay_coherence.get("caption_timing_conflict"))
    frame_rhythm = visual_effects_plan.get("frame_rhythm", {})

    # Assemble plan
    plan = RetentionEditingPlan(
        enabled=True,
        clip_index=clip_index,
        clip_duration_s=clip_duration_s,
        editorial_type=editorial,
        hook_strategy=hook_strategy,
        silence_strategy=silence_strategy,
        pattern_interruptions=pattern_interruptions,
        sfx_plan=sfx_plan,
        music_plan=music_plan,
        visual_effects_plan=visual_effects_plan,
        transition_plan=transition_plan,
        caption_visual_support_plan=caption_visual_support_plan,
        frame_rhythm_plan=frame_rhythm,
    )

    # Compute retention score
    plan.retention_score = _compute_retention_score(plan)

    # Collect missing layers
    missing: List[str] = []
    if not hook_strategy.get("enabled"):
        missing.append("hook_strategy")
    if not silence_strategy.get("enabled"):
        missing.append("silence_strategy")
    if not sfx_plan.get("enabled"):
        missing.append("sfx")
    if not music_plan.get("enabled"):
        missing.append("music")
    if not visual_effects_plan.get("enabled"):
        missing.append("visual_effects")
    if not transition_plan.get("enabled"):
        missing.append("transitions")
    if not caption_visual_support_plan.get("enabled"):
        missing.append("caption_visual_support")
    if not pattern_interruptions:
        missing.append("pattern_interruptions")
    plan.retention_missing_layers = missing

    # Warnings
    warnings: List[str] = []
    if plan.retention_score < 8:
        warnings.append(f"low_retention_score:{plan.retention_score}")
    if hook_strategy.get("needs_strengthening"):
        warnings.append("hook_needs_strengthening")
    if not pattern_interruptions:
        warnings.append("no_pattern_interruptions")
    plan.retention_warnings = warnings

    logger.info(
        "[retention-plan] hook=%s sfx=%s visual=%s music=%s score=%d",
        hook_strategy.get("hook_type") or "none",
        str(bool(sfx_plan.get("enabled"))).lower(),
        str(bool(visual_effects_plan.get("enabled"))).lower(),
        str(bool(music_plan.get("enabled"))).lower(),
        plan.retention_score,
    )
    logger.info("[retention-plan] warnings=%s", "|".join(warnings) if warnings else "none")
    return plan


def retention_plan_metadata(plan: RetentionEditingPlan) -> Dict[str, Any]:
    return {
        "retention_plan": plan.to_dict(),
        "retention_score": plan.retention_score,
        "retention_strategy": {
            "hook": plan.hook_strategy.get("hook_type"),
            "sfx": plan.sfx_plan.get("enabled"),
            "music": plan.music_plan.get("mood"),
            "visual": plan.visual_effects_plan.get("enabled"),
        },
        "retention_warnings": list(plan.retention_warnings),
    }
