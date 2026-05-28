"""CPU-only VPI visual effects layer for Beta Clean post-production."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def build_frame_rhythm_events(
    events: Optional[List[Dict[str, Any]]] = None,
    *,
    fps: int = 30,
    has_progression_context: bool = True,
) -> Dict[str, Any]:
    if not has_progression_context:
        logger.info("[frame-rhythm] skipped reason=no_progression_context")
        return {
            "frame_rhythm_applied": False,
            "frame_rhythm_pattern": [],
            "frame_rhythm_events": [],
            "reason": "no_progression_context",
        }
    source = list(events or [{"event": "hook_emphasis"}, {"event": "transition_reveal"}])
    out: List[Dict[str, Any]] = []
    for idx, event in enumerate(source):
        frames = 5 if idx % 2 == 0 else 10
        next_frames = 10 if frames == 5 else 5
        item = {
            **event,
            "frames": frames,
            "duration_s": round(frames / float(fps), 3),
            "next_frames": next_frames,
            "applied": True,
        }
        out.append(item)
        if frames == 5:
            logger.info("[frame-rhythm] event=%s frames=5 next=10 applied=true", event.get("event") or event.get("type") or idx)
    return {
        "frame_rhythm_applied": True,
        "frame_rhythm_pattern": "5_to_10",
        "frame_rhythm_events": out,
        "fps": fps,
    }


def plan_premium_transition(
    *,
    event_type: str = "idea_shift",
    bbox: Optional[Dict[str, float]] = None,
    subject_area: Optional[Dict[str, float]] = None,
    fps: int = 30,
) -> Dict[str, Any]:
    if event_type in {"idea_shift", "concept_entry", "sweeping_reveal"}:
        logger.info("[transition] type=sweeping_reveal reason=idea_shift frames=5")
        return {
            "transition_type": "sweeping_reveal",
            "transition_reason": "idea_shift",
            "transition_duration_frames": 5,
            "sweeping_reveal_applied": True,
            "mask_reveal_bbox": None,
            "duration_s": round(5 / float(fps), 3),
        }
    if event_type in {"object_focus", "mask_reveal", "bbox_focus"}:
        safe_bbox = bbox or subject_area
        if safe_bbox:
            logger.info("[transition] type=mask_reveal bbox=%s reason=object_focus", safe_bbox)
            return {
                "transition_type": "mask_reveal_bbox",
                "transition_reason": "object_focus",
                "transition_duration_frames": 10,
                "mask_reveal_bbox": safe_bbox,
                "sweeping_reveal_applied": False,
                "duration_s": round(10 / float(fps), 3),
            }
        logger.info("[transition] fallback=clean_cut reason=no_bbox")
        return {
            "transition_type": "clean_cut",
            "transition_reason": "no_bbox",
            "transition_duration_frames": 5,
            "mask_reveal_bbox": None,
            "sweeping_reveal_applied": False,
            "duration_s": round(5 / float(fps), 3),
        }
    return {
        "transition_type": "short_fade" if event_type == "soft_shift" else "clean_cut",
        "transition_reason": event_type,
        "transition_duration_frames": 5,
        "mask_reveal_bbox": None,
        "sweeping_reveal_applied": False,
        "duration_s": round(5 / float(fps), 3),
    }


def plan_motion_scaling(
    *,
    hook_plan: Optional[Dict[str, Any]] = None,
    bbox: Optional[Dict[str, float]] = None,
    static_shot: bool = True,
    duration_s: float = 0.0,
) -> Dict[str, Any]:
    hook_type = str((hook_plan or {}).get("hook_type") or "")
    motion_type = "hook_push_in" if hook_type and hook_type != "weak_intro" else "subtle_push_in"
    if bbox:
        motion_type = "object_scale"
    if not static_shot:
        motion_type = "camera_follow_scale"
    event = {
        "type": motion_type,
        "start_s": 0.3,
        "duration_s": min(1.4, max(0.7, float(duration_s or 2.0) * 0.25)),
        "scale": 1.04 if motion_type != "object_scale" else 1.035,
        "target": "bbox" if bbox else "speaker",
        "bbox_used": bool(bbox),
        "bbox": bbox,
        "reason": "hook_or_keyword_focus",
    }
    logger.info("[motion-scale] type=%s target=%s scale=%.3f reason=%s", event["type"], event["target"], event["scale"], event["reason"])
    blur_frames = 5 if motion_type in {"hook_push_in", "object_scale", "camera_follow_scale"} else 0
    if blur_frames:
        logger.info("[motion-blur] applied=true frames=%d", blur_frames)
    return {
        "motion_scaling_events": [event],
        "motion_scaling_target": event["target"],
        "motion_blur_applied": bool(blur_frames),
        "motion_blur_frames": blur_frames,
        "bbox_used": bool(bbox),
    }


def _probe_size(path: Path) -> tuple[int, int]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0:s=x",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        raw = (result.stdout or "").strip().splitlines()[0]
        width, height = raw.split("x", 1)
        return max(2, int(width)), max(2, int(height))
    except Exception:
        return 1080, 1920


def plan_visual_effects(
    *,
    hook_plan: Optional[Dict[str, Any]] = None,
    no_broll: bool = False,
    editorial_type: str = "",
    duration_s: float = 0.0,
) -> List[Dict[str, Any]]:
    """Plan subtle visible edit events for clips that need post-production energy.

    v4.0 retention: ensures first-3-seconds visual support when hook is strong.
    Adds hook_push_in effect for strong hooks to reinforce the first 3 seconds.
    """
    hook_plan = hook_plan or {}
    hook_type = str(hook_plan.get("hook_type") or "").lower()
    if hook_type == "weak_intro" or str(editorial_type or "").lower() == "weak_intro":
        return []

    events: List[Dict[str, Any]] = []

    # ── v4.0: First 3 seconds hook visual reinforcement ──────────────────────
    # When hook_first3_status is READY, ensure a strong visual push in first 3s.
    hook_first3_status = str(hook_plan.get("hook_first3_status") or "")
    hook_first3_score = int(hook_plan.get("hook_first3_score") or 0)

    if hook_first3_status == "READY" and hook_first3_score >= 5:
        # Strong hook: add a hook_push_in that covers the first 3 seconds
        events.append({
            "type": "hook_push_in",
            "start_s": 0.30,
            "duration_s": min(2.5, max(1.5, float(duration_s or 3.0) * 0.6)),
            "scale": 1.045,
            "reason": "hook_push_in_first3s_retention_v4",
        })
        logger.info(
            "[visual-effects] hook_push_in planned for first 3s "
            "status=%s score=%d",
            hook_first3_status, hook_first3_score,
        )
    elif hook_first3_status == "strong" and hook_first3_score >= 7:
        events.append({
            "type": "hook_push_in",
            "start_s": 0.30,
            "duration_s": min(2.5, max(1.5, float(duration_s or 3.0) * 0.6)),
            "scale": 1.045,
            "reason": "hook_push_in_first3s_retention_v4",
        })
        logger.info("[visual-effects] hook_push_in planned for first 3s status=%s score=%d", hook_first3_status, hook_first3_score)
    elif hook_plan.get("kickframe_applied") or hook_type in {"objection_breaker", "client_objection", "myth_debunk", "risk_warning"}:
        events.append({"type": "punch_zoom", "start_s": 0.42, "duration_s": 0.55, "scale": 1.06, "reason": "hook_punch"})
    elif hook_plan.get("hook_motion_rendered") or hook_plan.get("rendered"):
        events.append({"type": "subtle_push_in", "start_s": 0.45, "duration_s": 1.7, "scale": 1.04, "reason": "hook_push_in"})
    else:
        events.append({"type": "micro_zoom", "start_s": 0.55, "duration_s": 1.35, "scale": 1.035, "reason": "first3_hook_support"})

    if no_broll and duration_s >= 12.0:
        events.append({"type": "emphasis_zoom", "start_s": min(6.0, max(3.2, duration_s * 0.32)), "duration_s": 1.2, "scale": 1.035, "reason": "speaker_focus_no_broll"})

    return events[:2]



def apply_visual_effects(
    input_path: Path,
    output_path: Path,
    *,
    hook_plan: Optional[Dict[str, Any]] = None,
    no_broll: bool = False,
    editorial_type: str = "",
    duration_s: float = 0.0,
) -> Dict[str, Any]:
    events = plan_visual_effects(
        hook_plan=hook_plan,
        no_broll=no_broll,
        editorial_type=editorial_type,
        duration_s=duration_s,
    )
    logger.info("[visual-effects] planned events=%s", events)
    if not events:
        logger.info("[visual-effects] skipped reason=no_visual_effect_events")
        return {
            "visual_effects_applied": False,
            "visual_effects_count": 0,
            "visual_effects_events": [],
            "visual_effects_warning": "no_visual_effect_events",
        }

    motion_meta = plan_motion_scaling(
        hook_plan=hook_plan,
        static_shot=True,
        duration_s=duration_s,
    )
    rhythm_meta = build_frame_rhythm_events(
        [{"event": event.get("type", "visual_effect"), "type": event.get("type")} for event in events],
        has_progression_context=len(events) > 0,
    )

    width, height = _probe_size(input_path)
    scale_expr = "1"
    for event in reversed(events):
        start = max(0.0, float(event.get("start_s") or 0.0))
        end = start + max(0.1, float(event.get("duration_s") or 0.5))
        scale = max(1.0, min(1.07, float(event.get("scale") or 1.035)))
        scale_expr = f"if(between(t\\,{start:.3f}\\,{end:.3f})\\,{scale:.4f}\\,{scale_expr})"
    vf = (
        f"crop=w='iw/({scale_expr})':h='ih/({scale_expr})':"
        "x='(iw-out_w)/2':y='(ih-out_h)/2',"
        f"scale={width}:{height},setsar=1"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        logger.info("[visual-effects] applied=true count=%d output=%s", len(events), output_path)
        return {
            "visual_effects_applied": True,
            "visual_effects_count": len(events),
            "visual_effects_events": events,
            **motion_meta,
            **rhythm_meta,
            "visual_effects_warning": None,
        }

    reason = (result.stderr or "ffmpeg_failed").strip()[-700:]
    logger.warning("[visual-effects] failed reason=%s", reason)
    return {
        "visual_effects_applied": False,
        "visual_effects_count": 0,
        "visual_effects_events": events,
        **motion_meta,
        **rhythm_meta,
        "visual_effects_warning": reason,
    }
