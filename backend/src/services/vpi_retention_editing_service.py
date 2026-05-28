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
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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

def _build_hook_strategy(
    hook_plan: Optional[Dict[str, Any]],
    editorial_type: str,
) -> Dict[str, Any]:
    """Derive hook strategy from existing hook_plan."""
    if not hook_plan:
        return {"enabled": False, "reason": "no_hook_plan"}
    hook_type = str(hook_plan.get("hook_type") or "")
    if hook_type == "weak_intro":
        return {"enabled": False, "reason": "weak_intro", "hook_type": hook_type}

    first3_score = int(hook_plan.get("hook_first3_score") or 0)
    first3_perceptible = bool(hook_plan.get("hook_first3_perceptible"))
    first4_score = int(hook_plan.get("hook_first_4s_score") or 0)

    strategy: Dict[str, Any] = {
        "enabled": True,
        "hook_type": hook_type,
        "hook_first3_score": first3_score,
        "hook_first3_perceptible": first3_perceptible,
        "hook_first_4s_score": first4_score,
        "needs_strengthening": first3_score < 5 or not first3_perceptible,
        "editorial_type": editorial_type,
    }

    if first3_score < 5:
        strategy["strengthen_suggestions"] = _suggest_hook_strengthening(editorial_type, hook_type)
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
    """Build visual effects plan with motion scaling and frame rhythm."""
    events: List[Dict[str, Any]] = []
    used_effects: List[str] = []

    if hook_type == "weak_intro":
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
) -> Dict[str, Any]:
    """Build premium transition plan."""
    transitions: List[Dict[str, Any]] = []

    if hook_type == "weak_intro":
        return {"enabled": False, "reason": "weak_intro"}

    # Hook-to-content transition (around 3-4 seconds)
    hook_end = min(4.0, clip_duration_s * 0.25)
    if editorial_type == "risk_warning":
        transitions.append({
            "start_s": round(hook_end, 2),
            "duration_s": 0.3,
            "type": "sweeping_reveal",
            "reason": "hook_to_content_risk",
        })
    elif editorial_type in ("client_objection", "myth_debunk"):
        transitions.append({
            "start_s": round(hook_end, 2),
            "duration_s": 0.25,
            "type": "mask_reveal_bbox",
            "reason": "hook_to_content_contrast",
        })
    elif editorial_type == "emotional_protection":
        transitions.append({
            "start_s": round(hook_end, 2),
            "duration_s": 0.35,
            "type": "short_fade",
            "reason": "hook_to_content_emotional",
        })
    else:
        transitions.append({
            "start_s": round(hook_end, 2),
            "duration_s": 0.2,
            "type": "clean_cut",
            "reason": "hook_to_content_clean",
        })

    # Mid-clip transition if clip is long
    if clip_duration_s >= 15.0:
        mid = clip_duration_s * 0.5
        transitions.append({
            "start_s": round(mid, 2),
            "duration_s": 0.3,
            "type": "motion_scaled_reveal",
            "reason": "mid_clip_pacing_shift",
        })

    return {
        "enabled": bool(transitions),
        "transitions": transitions,
        "total_transitions": len(transitions),
    }


# ── Caption visual support plan ────────────────────────────────────────────────

def _build_caption_visual_support_plan(
    editorial_type: str,
    text: str,
) -> Dict[str, Any]:
    """Build caption visual support plan with icons for VPI concepts."""
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
    }


def _discover_caption_icon_assets() -> List[Path]:
    root = Path(__file__).resolve().parents[3]
    dirs = (
        "assets/icons",
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
    del word_timestamps, broll_plan, visual_theme, existing_metadata
    if transcript and not text:
        text = transcript
    editorial = editorial_type or "generic"
    hook_type = str((hook_plan or {}).get("hook_type") or "")

    # Build sub-plans (order matters: silence → pattern interruptions → SFX)
    hook_strategy = _build_hook_strategy(hook_plan, editorial)
    silence_strategy = _build_silence_strategy(silence_plan, editorial, clip_duration_s)
    pattern_interruptions = _build_pattern_interruptions(
        editorial, hook_type, silence_strategy, clip_duration_s,
    )
    sfx_plan = _build_sfx_plan(editorial, hook_type, pattern_interruptions, clip_duration_s)
    music_plan = _build_music_plan(editorial, clip_duration_s, existing_music)
    visual_effects_plan = _build_visual_effects_plan(editorial, hook_type, clip_duration_s, existing_effects)
    transition_plan = _build_transition_plan(editorial, hook_type, clip_duration_s)
    caption_visual_support_plan = _build_caption_visual_support_plan(editorial, text)
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
