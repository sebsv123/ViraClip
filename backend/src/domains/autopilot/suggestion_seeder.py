"""Suggestion seeder.

Builds the initial set of editorial suggestions for a freshly-rendered clip,
based on the metadata produced by the auto-pipeline (analyzers + Phase 9
creative engine). Each suggestion is persisted as a row in ``clip_suggestions``
with status ``pending`` (the user hasn't reviewed it yet) and ``applied``
inside the payload to indicate whether the auto-pipeline already applied it.

The Suggestion Studio frontend reads these rows and lets the user toggle them
on/off; a follow-up "applicator" service (next phase) re-renders the clip
honouring the approved subset.

This module is intentionally side-effect free: it does NOT call FFmpeg, it
only translates analysis metadata into rows.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ...repositories.clip_suggestion_repository import ClipSuggestionRepository

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------- helpers
def _bool(value: Any) -> bool:
    return bool(value) if value is not None else False


def _build_timing_suggestions(
    segment: Dict[str, Any], clip_info: Dict[str, Any]
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    # Trim handles (always available; payload carries current zero offsets).
    out.append(
        {
            "kind": "trim_offsets",
            "category": "timing",
            "label": "Adjust start / end",
            "score": None,
            "sort_order": 0,
            "payload": {
                "start_offset": 0.0,
                "end_offset": 0.0,
                "duration": clip_info.get("duration"),
                "applied": False,
            },
        }
    )

    # Hook reorder if Phase 9 detected a stronger hook later in the clip.
    hook_reorder_applied = clip_info.get("hook_reorder_applied")
    hook_reorder_suggested = clip_info.get("hook_reorder_suggested")
    if hook_reorder_applied or hook_reorder_suggested:
        out.append(
            {
                "kind": "hook_reorder",
                "category": "timing",
                "label": "Reorder hook to start",
                "score": clip_info.get("hook_score"),
                "sort_order": 10,
                "payload": {
                    "applied": _bool(hook_reorder_applied),
                    "suggested": _bool(hook_reorder_suggested),
                    "hook_text": clip_info.get("hook_text"),
                    "hook_type": clip_info.get("hook_type"),
                    "hook_already_optimized": clip_info.get("hook_already_optimized"),
                },
            }
        )

    # Timeline events - viral moments detected (editable)
    timeline_events = clip_info.get("timeline_events") or 0
    if timeline_events > 0:
        # Build editable items from any stored timeline data
        timeline_items = []
        raw_events = clip_info.get("timeline_event_details", []) or []
        if raw_events:
            for idx, event in enumerate(raw_events):
                timeline_items.append({
                    "id": event.get("id") or f"event_{idx}",
                    "type": event.get("type", "moment"),
                    "start_time": event.get("start_time", 0),
                    "strength": event.get("strength", 0.5),
                    "description": event.get("description", ""),
                })
        
        out.append(
            {
                "kind": "timeline_moments",
                "category": "timing",
                "label": f"Viral moments ({timeline_events} detected)",
                "score": clip_info.get("virality_score"),
                "sort_order": 5,
                "payload": {
                    "applied": True,  # Already used for cut detection
                    "count": timeline_events,
                    "items": timeline_items,
                    "editable": True,
                    "stage": "step_1_timeline",
                },
            }
        )

    # Speed control - playback speed / dramatic slow-mo
    speed_applied = clip_info.get("speed_control_applied")
    playback_speed = segment.get("playback_speed", 1.0)
    dramatic_slowmo = segment.get("dramatic_slowmo", False)
    if speed_applied or playback_speed != 1.0 or dramatic_slowmo:
        out.append(
            {
                "kind": "speed_control",
                "category": "timing",
                "label": f"Speed control ({playback_speed}x{' + slow-mo' if dramatic_slowmo else ''})",
                "sort_order": 20,
                "payload": {
                    "applied": _bool(speed_applied),
                    "playback_speed": playback_speed,
                    "dramatic_slowmo": dramatic_slowmo,
                    "stage": "step_6_5_speed",
                    "editable": True,
                },
            }
        )

    return out


def _build_caption_suggestions(
    segment: Dict[str, Any], clip_info: Dict[str, Any]
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    # Caption template with virality score
    virality_score = clip_info.get("virality_score")
    preset_used = clip_info.get("preset_used") or "default"
    
    out.append(
        {
            "kind": "caption_template",
            "category": "captions",
            "label": "Caption template",
            "score": virality_score,
            "sort_order": 0,
            "payload": {
                "template": preset_used,
                "applied": True,
                "options": [
                    "default",
                    "tiktok",
                    "viral_pro",
                    "hormozi",
                    "subtitles",
                ],
                "stage": "step_3_template",
                "virality_score": virality_score,
            },
        }
    )

    # Virality prediction info
    if virality_score is not None:
        out.append(
            {
                "kind": "virality_prediction",
                "category": "captions",
                "label": f"Virality score: {virality_score:.0%}",
                "score": virality_score,
                "sort_order": 1,
                "payload": {
                    "applied": True,
                    "score": virality_score,
                    "stage": "step_2_virality",
                },
            }
        )

    if clip_info.get("emoji_overlays_applied") is not None:
        out.append(
            {
                "kind": "emoji_overlay",
                "category": "captions",
                "label": "Emoji overlays",
                "sort_order": 10,
                "payload": {
                    "applied": _bool(clip_info.get("emoji_overlays_applied")),
                },
            }
        )

    if clip_info.get("cta_overlay_applied") is not None:
        out.append(
            {
                "kind": "cta_overlay",
                "category": "captions",
                "label": "CTA overlay",
                "sort_order": 20,
                "payload": {
                    "applied": _bool(clip_info.get("cta_overlay_applied")),
                },
            }
        )

    if clip_info.get("text_pops_applied"):
        out.append(
            {
                "kind": "text_pops",
                "category": "captions",
                "label": "Text-pop emphasis",
                "sort_order": 30,
                "payload": {
                    "applied": True,
                    "count": int(clip_info.get("text_pops_applied", 0)),
                },
            }
        )

    return out


def _build_media_suggestions(
    segment: Dict[str, Any], clip_info: Dict[str, Any]
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    broll_count = int(clip_info.get("broll_overlays") or 0)
    
    # Always create B-roll suggestion (editable even if empty)
    # Build editable items array for granular control
    broll_items = []
    raw_items = clip_info.get("broll_items", []) or clip_info.get("broll_details", [])
    if raw_items:
        for idx, item in enumerate(raw_items):
            broll_items.append({
                "id": item.get("id") or f"broll_{idx}",
                "video_url": item.get("video_url") or item.get("url") or item.get("path"),
                "start_time": item.get("start_time", 0),
                "duration": item.get("duration", 3.0),
                "position": item.get("position", "fullscreen"),  # fullscreen, corner, split
                "opacity": item.get("opacity", 1.0),
                "scale": item.get("scale", 1.0),
                "keywords": item.get("keywords", []),
            })
    elif broll_count > 0:
        # Generate placeholder items if details not available but count exists
        for i in range(broll_count):
            broll_items.append({
                "id": f"broll_auto_{i}",
                "video_url": None,
                "start_time": i * 5.0,  # Every 5 seconds as placeholder
                "duration": 3.0,
                "position": "fullscreen",
                "opacity": 1.0,
                "scale": 1.0,
                "keywords": segment.get("keywords", [])[:3] if segment else [],
            })
    # else: broll_items stays empty, user can add manually

    # Always add B-roll suggestion (even if empty for manual editing)
    if broll_count > 0 or broll_items:
        label = f"B-roll overlays ({len(broll_items)})"
        applied = True
    else:
        label = "B-roll overlays (add manually)"
        applied = False
        
    out.append(
        {
            "kind": "broll_overlays",
            "category": "media",
            "label": label,
            "sort_order": 0,
            "payload": {
                "applied": applied,
                "count": len(broll_items),
                "items": broll_items,  # Editable array
                "editable": True,  # Always editable
                "auto_detected": broll_count > 0,
            },
        }
    )

    # AI B-roll Generator - LTX Video generation suggestion
    # Always available so users can generate custom AI B-roll
    ltx_enabled = os.getenv("LTXV_ENABLED", "false").lower() == "true" or os.getenv("BROLL_USE_LTX", "false").lower() == "true"
    comfy_enabled = os.getenv("COMFYUI_ENABLED", "false").lower() == "true"
    
    out.append(
        {
            "kind": "ai_broll_generator",
            "category": "media",
            "label": "🎬 AI B-roll Generator (LTX)" if (ltx_enabled and comfy_enabled) else "🎬 AI B-roll Generator (configure LTX)",
            "sort_order": 5,
            "payload": {
                "applied": False,  # User must explicitly generate
                "editable": True,
                "generator_type": "ltx_video",
                "available": ltx_enabled and comfy_enabled,
                "requirements": ["LTXV_ENABLED=true", "COMFYUI_ENABLED=true"],
                "prompt_template": "cinematic B-roll footage of {topic}, professional quality, smooth motion, 9:16 vertical",
                "default_duration": 3.0,
                "stage": "ai_generation",
            },
        }
    )

    if clip_info.get("contextual_overlays"):
        overlay_items = []
        raw_overlays = clip_info.get("overlay_items", []) or []
        if raw_overlays:
            for idx, item in enumerate(raw_overlays):
                overlay_items.append({
                    "id": item.get("id") or f"overlay_{idx}",
                    "type": item.get("type", "contextual"),
                    "start_time": item.get("start_time", 0),
                    "duration": item.get("duration", 2.0),
                    "content": item.get("content", ""),
                    "position": item.get("position", "bottom"),
                })
        else:
            overlay_items.append({
                "id": "overlay_auto",
                "type": "contextual",
                "start_time": 0,
                "duration": 2.0,
                "content": "",
                "position": "bottom",
            })

        out.append(
            {
                "kind": "contextual_overlay",
                "category": "media",
                "label": "Contextual overlay",
                "sort_order": 10,
                "payload": {
                    "applied": True,
                    "items": overlay_items,
                    "editable": True,
                },
            }
        )

    bgm = clip_info.get("bgm_style") or segment.get("bgm_style")
    if bgm:
        out.append(
            {
                "kind": "music_track",
                "category": "media",
                "label": f"Background music ({bgm})",
                "sort_order": 20,
                "payload": {
                    "applied": True,
                    "category": bgm,
                    "track": clip_info.get("bgm_track"),
                    "volume": clip_info.get("bgm_volume", 0.3),
                    "ducking": clip_info.get("audio_ducking_applied", True),
                    "editable": True,
                    "items": [{
                        "id": "bgm_main",
                        "track_id": clip_info.get("bgm_track"),
                        "start_time": 0,
                        "fade_in": 0.5,
                        "fade_out": 0.5,
                    }],
                },
            }
        )

    sfx_count = int(clip_info.get("sfx_injected") or 0)
    if sfx_count:
        sfx_items = []
        raw_sfx = clip_info.get("sfx_items", []) or []
        if raw_sfx:
            for idx, item in enumerate(raw_sfx):
                sfx_items.append({
                    "id": item.get("id") or f"sfx_{idx}",
                    "type": item.get("type", "whoosh"),
                    "start_time": item.get("start_time", idx * 3.0),
                    "volume": item.get("volume", 0.5),
                })
        else:
            for i in range(sfx_count):
                sfx_items.append({
                    "id": f"sfx_auto_{i}",
                    "type": "whoosh",
                    "start_time": i * 3.0,
                    "volume": 0.5,
                })

        out.append(
            {
                "kind": "sfx_cues",
                "category": "media",
                "label": f"SFX cues ({sfx_count})",
                "sort_order": 30,
                "payload": {
                    "applied": True,
                    "count": sfx_count,
                    "items": sfx_items,
                    "editable": True,
                },
            }
        )

    return out


def _build_polish_suggestions(
    segment: Dict[str, Any], clip_info: Dict[str, Any]
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    # --- ZOOM PUNCH (editable with parameters) ---
    zoom_applied = _bool(clip_info.get("zoom_punch_applied"))
    preset_zoom = clip_info.get("zoom_punch_zoom", 1.15)
    preset_duration = clip_info.get("zoom_punch_duration", 0.25)
    
    out.append(
        {
            "kind": "zoom_punch",
            "category": "polish",
            "label": "Zoom punch (audio peaks)" if zoom_applied else "Zoom punch (disabled)",
            "sort_order": 10,
            "payload": {
                "applied": zoom_applied,
                "editable": True,
                "stage": "step_6_vfx",
                "items": [
                    {
                        "id": "zoom_main",
                        "enabled": zoom_applied,
                        "zoom_level": preset_zoom,
                        "duration": preset_duration,
                        "trigger": "audio_peaks",
                        "description": f"Zoom {preset_zoom}x for {preset_duration}s on audio peaks",
                    }
                ],
                "options": {
                    "zoom_levels": [1.1, 1.15, 1.2, 1.25, 1.3],
                    "durations": [0.15, 0.25, 0.3, 0.35, 0.5],
                    "triggers": ["audio_peaks", "beat", "manual_markers"],
                },
            },
        }
    )

    # --- COLOR GRADE (editable with filter presets) ---
    color_applied = _bool(clip_info.get("color_grade_applied"))
    preset_filters = clip_info.get("extra_vf_filters", [])
    
    # Parse current filters for editable form
    current_filters = []
    if preset_filters:
        for f in preset_filters:
            if "eq=contrast" in f:
                current_filters.append({"type": "eq", "params": f})
            elif "vignette" in f.lower():
                current_filters.append({"type": "vignette", "params": f})
            else:
                current_filters.append({"type": "custom", "params": f})
    
    out.append(
        {
            "kind": "color_grade",
            "category": "polish",
            "label": "Color grade (applied)" if color_applied else "Color grade (disabled)",
            "sort_order": 20,
            "payload": {
                "applied": color_applied,
                "editable": True,
                "stage": "step_6_vfx",
                "preset_used": clip_info.get("preset_used", "default"),
                "current_filters": current_filters,
                "items": current_filters if current_filters else [],
                "presets": [
                    {"name": "viral_energetic", "label": "Viral Energetic", "filters": ["eq=contrast=1.1:saturation=1.2:brightness=0.02"]},
                    {"name": "cinematic_calm", "label": "Cinematic Calm", "filters": ["eq=contrast=1.05:saturation=0.95:brightness=0.0"]},
                    {"name": "high_energy", "label": "High Energy", "filters": ["eq=contrast=1.2:saturation=1.3:brightness=0.05"]},
                    {"name": "bw_drama", "label": "B&W Drama", "filters": ["format=gray", "eq=contrast=1.3"]},
                    {"name": "vintage", "label": "Vintage Film", "filters": ["eq=contrast=0.9:saturation=0.8", "curves=vintage"]},
                ],
            },
        }
    )

    # --- ADDITIONAL VISUAL EFFECTS (always available to add) ---
    
    # Sharpen / Unsharp mask
    out.append(
        {
            "kind": "sharpen",
            "category": "polish",
            "label": "Sharpen (unsharp mask)",
            "sort_order": 30,
            "payload": {
                "applied": _bool(clip_info.get("sharpen_applied")),
                "editable": True,
                "stage": "step_6_vfx",
                "items": [
                    {
                        "id": "sharpen_main",
                        "enabled": _bool(clip_info.get("sharpen_applied")),
                        "intensity": clip_info.get("sharpen_intensity", 1.5),
                    }
                ],
                "filter_string": "unsharp=3:3:1.5:3:3:0.0",
            },
        }
    )

    # Vignette
    out.append(
        {
            "kind": "vignette",
            "category": "polish",
            "label": "Vignette effect",
            "sort_order": 40,
            "payload": {
                "applied": _bool(clip_info.get("vignette_applied")),
                "editable": True,
                "stage": "step_6_vfx",
                "items": [
                    {
                        "id": "vignette_main",
                        "enabled": _bool(clip_info.get("vignette_applied")),
                        "intensity": clip_info.get("vignette_intensity", 0.5),
                        "color": clip_info.get("vignette_color", "black"),
                    }
                ],
            },
        }
    )

    # Grain / Film look
    out.append(
        {
            "kind": "film_grain",
            "category": "polish",
            "label": "Film grain",
            "sort_order": 50,
            "payload": {
                "applied": _bool(clip_info.get("film_grain_applied")),
                "editable": True,
                "stage": "step_6_vfx",
                "items": [
                    {
                        "id": "grain_main",
                        "enabled": _bool(clip_info.get("film_grain_applied")),
                        "intensity": clip_info.get("grain_intensity", 0.03),
                    }
                ],
            },
        }
    )

    # Blur / Focus effect
    out.append(
        {
            "kind": "blur",
            "category": "polish",
            "label": "Gaussian blur",
            "sort_order": 55,
            "payload": {
                "applied": _bool(clip_info.get("blur_applied")),
                "editable": True,
                "stage": "step_6_vfx",
                "items": [
                    {
                        "id": "blur_main",
                        "enabled": _bool(clip_info.get("blur_applied")),
                        "radius": clip_info.get("blur_radius", 2.0),
                        "type": clip_info.get("blur_type", "gaussian"),
                    }
                ],
            },
        }
    )

    # --- AUDIO POLISH (also in polish category) ---
    
    # Loudness normalization
    if "loudnorm_applied" in clip_info:
        out.append(
            {
                "kind": "loudnorm",
                "category": "polish",
                "label": "Audio normalize (loudnorm)",
                "sort_order": 60,
                "payload": {
                    "applied": _bool(clip_info.get("loudnorm_applied")),
                    "editable": False,  # Binary on/off
                    "stage": "step_7_audio",
                },
            }
        )

    # Audio ducking
    if "audio_ducking_applied" in clip_info:
        out.append(
            {
                "kind": "audio_ducking",
                "category": "polish",
                "label": "Music ducking",
                "sort_order": 70,
                "payload": {
                    "applied": _bool(clip_info.get("audio_ducking_applied")),
                    "editable": True,
                    "stage": "step_7_audio",
                    "items": [
                        {
                            "id": "ducking_main",
                            "enabled": _bool(clip_info.get("audio_ducking_applied")),
                            "reduction_db": clip_info.get("ducking_reduction", 10),
                            "threshold": clip_info.get("ducking_threshold", -20),
                        }
                    ],
                },
            }
        )

    # Denoise
    if "audio_denoised" in clip_info:
        out.append(
            {
                "kind": "denoise",
                "category": "polish",
                "label": "Audio denoise",
                "sort_order": 80,
                "payload": {
                    "applied": _bool(clip_info.get("audio_denoised")),
                    "editable": False,
                    "stage": "step_7_audio",
                },
            }
        )

    # Background composite
    if "background_composite_applied" in clip_info:
        out.append(
            {
                "kind": "background_composite",
                "category": "polish",
                "label": "Background composite (SAM2+LTX)",
                "sort_order": 90,
                "payload": {
                    "applied": _bool(clip_info.get("background_composite_applied")),
                    "editable": False,
                    "stage": "step_5_broll",
                    "mode": clip_info.get("composite_mode"),
                },
            }
        )

    return out


def _build_missing_suggestions(
    segment: Dict[str, Any], clip_info: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Detect QA failures and suggest missing features that should be added.

    Creates suggestions for features that:
    - Failed during processing (marked in steps_failed)
    - Detected as missing by QA (in qa_issues)
    - Should have been applied but weren't
    """
    out: List[Dict[str, Any]] = []
    qa_issues = clip_info.get("qa_issues", []) or []
    steps_failed = clip_info.get("steps_failed", []) or []
    steps_ok = clip_info.get("steps_ok", []) or []

    # Helper to check if a step failed
    def step_failed(prefix: str) -> bool:
        return any(f.startswith(prefix) for f in steps_failed)

    # Helper to check if QA mentions something
    def qa_mentions(*keywords: str) -> bool:
        return any(kw.lower() in issue.lower() for issue in qa_issues for kw in keywords)

    # --- B-roll: Failed or QA recommends visual variety but no B-roll applied ---
    broll_count = int(clip_info.get("broll_overlays") or 0)
    broll_failed = step_failed("step_5_broll") or step_failed("broll")
    needs_broll = qa_mentions("visual", "variety", "b-roll", "broll", "static", "dull")

    if broll_failed or (needs_broll and broll_count == 0):
        out.append(
            {
                "kind": "broll_overlays",
                "category": "media",
                "label": "⚠️ Añadir B-roll (QA/Falló)",
                "sort_order": 0,
                "payload": {
                    "applied": False,
                    "failed": broll_failed,
                    "qa_reason": "Falta variedad visual" if needs_broll else None,
                    "count": 0,
                },
            }
        )

    # --- Audio Mastering: Failed ---
    audio_failed = step_failed("step_7_audio") or step_failed("audio")
    loudnorm_failed = step_failed("loudnorm")
    if audio_failed or loudnorm_failed:
        out.append(
            {
                "kind": "loudnorm",
                "category": "polish",
                "label": "🔧 Reintentar normalización de audio",
                "sort_order": 50,
                "payload": {
                    "applied": False,
                    "failed": True,
                    "error": "step_7_audio failed" if audio_failed else "loudnorm failed",
                },
            }
        )

    # --- Contextual Overlays: Failed or missing ---
    overlays_failed = step_failed("contextual_overlay") or step_failed("overlay")
    has_overlays = clip_info.get("contextual_overlays") or clip_info.get("emoji_overlays_applied")
    if overlays_failed or (qa_mentions("overlay", "contextual") and not has_overlays):
        out.append(
            {
                "kind": "contextual_overlay",
                "category": "media",
                "label": "⚠️ Añadir overlays contextuales",
                "sort_order": 15,
                "payload": {
                    "applied": False,
                    "failed": overlays_failed,
                },
            }
        )

    # --- VFX (Zoom punch, Color grade): Failed ---
    vfx_failed = step_failed("step_6_vfx") or step_failed("vfx")
    if vfx_failed and not clip_info.get("zoom_punch_applied"):
        out.append(
            {
                "kind": "zoom_punch",
                "category": "polish",
                "label": "🔧 Reintentar zoom-punch VFX",
                "sort_order": 60,
                "payload": {
                    "applied": False,
                    "failed": True,
                },
            }
        )

    # --- Speed Control: Failed ---
    speed_failed = step_failed("speed_control") or step_failed("step_8_speed")
    if speed_failed:
        out.append(
            {
                "kind": "speed_control",
                "category": "polish",
                "label": "🔧 Reintentar control de velocidad",
                "sort_order": 70,
                "payload": {
                    "applied": False,
                    "failed": True,
                },
            }
        )

    # --- Hook Reorder: Suggested by AI but failed/not applied ---
    hook_suggested = clip_info.get("hook_reorder_suggested") and not clip_info.get("hook_reorder_applied")
    hook_failed = step_failed("hook_reorder") or step_failed("hook")
    if hook_suggested or hook_failed:
        out.append(
            {
                "kind": "hook_reorder",
                "category": "timing",
                "label": "🔧 Reordenar hook al inicio",
                "sort_order": 5,
                "payload": {
                    "applied": False,
                    "failed": hook_failed,
                    "hook_text": clip_info.get("hook_text"),
                    "hook_type": clip_info.get("hook_type"),
                },
            }
        )

    # --- QA Failed overall but clip delivered ---
    qa_failed = clip_info.get("qa_passed") is False or step_failed("step_8_qa")
    if qa_failed and not any(s["kind"] == "qa_retry" for s in out):
        out.append(
            {
                "kind": "qa_retry",
                "category": "polish",
                "label": "🔧 Re-ejecutar QA y correcciones",
                "sort_order": 100,
                "payload": {
                    "applied": False,
                    "failed": True,
                    "qa_issues": qa_issues[:3] if qa_issues else ["QA falló"],
                },
            }
        )

    return out


# ----------------------------------------------------------------- public API
async def seed_suggestions_for_clip(
    db: AsyncSession,
    *,
    clip_id: str,
    segment: Dict[str, Any],
    clip_info: Dict[str, Any],
) -> int:
    """Persist the initial suggestion set for ``clip_id``. Returns row count.

    Safe to call after the auto-pipeline finished a clip. Existing rows for
    the same clip are deleted first so re-runs stay idempotent.
    """
    try:
        await ClipSuggestionRepository.delete_by_clip(db, clip_id)

        rows: List[Dict[str, Any]] = []
        rows.extend(_build_timing_suggestions(segment, clip_info))
        rows.extend(_build_caption_suggestions(segment, clip_info))
        rows.extend(_build_media_suggestions(segment, clip_info))
        rows.extend(_build_polish_suggestions(segment, clip_info))
        # Detect failures and suggest missing features
        rows.extend(_build_missing_suggestions(segment, clip_info))

        if not rows:
            return 0

        ids = await ClipSuggestionRepository.bulk_create(db, clip_id, rows)
        await db.commit()
        logger.info(
            "[suggestion_seeder] clip=%s seeded=%d rows", clip_id, len(ids)
        )
        return len(ids)
    except Exception as exc:  # pragma: no cover - never break the pipeline
        logger.warning(
            "[suggestion_seeder] failed for clip=%s: %s", clip_id, exc
        )
        try:
            await db.rollback()
        except Exception:
            pass
        return 0
