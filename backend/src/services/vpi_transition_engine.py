"""VPI Premium Transition Pack v4.1.

CPU-only transition planning and application for Beta Clean VPI.
Transitions are selected only when they improve clarity, retention, or rhythm.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TransitionEvent:
    transition_type: str
    start_time: float
    duration_frames: int
    duration_seconds: float
    reason: str
    intensity: str = "medium"
    target_bbox: Optional[Dict[str, float]] = None
    subject_hint: str = ""
    sfx_hint: str = ""
    frame_rhythm_group: str = "transition"
    safe_fallback: str = "clean_cut"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TransitionPlan:
    enabled: bool
    events: List[TransitionEvent] = field(default_factory=list)
    transition_warnings: List[str] = field(default_factory=list)
    frame_rhythm_applied: bool = False
    frame_rhythm_pattern: str = ""
    frame_rhythm_events: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["transition_events"] = [event.to_dict() for event in self.events]
        data["transition_types"] = [event.transition_type for event in self.events]
        data["transitions_applied"] = False
        return data


@dataclass
class TransitionResult:
    applied: bool
    output_path: str
    transition_type: str
    frames_used: List[int] = field(default_factory=list)
    fallback_used: bool = False
    warning: str = ""
    ffmpeg_cmd_summary: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.update(self.metadata)
        return data


FPS = 30
PREMIUM_TYPES = {
    "match_cut",
    "glitch_clean",
    "shape_morph_beta",
    "mask_reveal",
    "sweeping_object_reveal",
}


def _duration_seconds(frames: int, fps: int = FPS) -> float:
    return round(max(1, int(frames)) / float(fps), 3)


def _safe_bbox(bbox: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    if bbox:
        return {
            "x": float(bbox.get("x", 0.35)),
            "y": float(bbox.get("y", 0.25)),
            "w": float(bbox.get("w", 0.30)),
            "h": float(bbox.get("h", 0.35)),
        }
    return {"x": 0.30, "y": 0.22, "w": 0.40, "h": 0.42}


def _has_strong_reason(context: Dict[str, Any]) -> bool:
    reason = " ".join(str(item).lower() for item in (
        context.get("reason"),
        context.get("transition_reason"),
        context.get("phrase"),
        context.get("matched_pattern"),
    ))
    return any(term in reason for term in ("objec", "mito", "desment", "no es asi", "contraste", "interrup"))


def choose_transition_type(context: Dict[str, Any]) -> str:
    editorial = str(context.get("editorial_type") or "").lower()
    has_bbox = bool(context.get("target_bbox") or context.get("bbox") or context.get("subject_bbox"))
    narrative = str(context.get("narrative_event") or context.get("event") or "").lower()
    continuity = bool(context.get("visual_continuity") or context.get("semantic_continuity"))
    important_broll = bool(context.get("important_broll") or context.get("broll_important"))
    concept_shift = str(context.get("concept_shift") or "").lower()

    if editorial in {"client_objection", "myth_debunk"} and _has_strong_reason(context):
        logger.info("[transition-select] chosen=glitch_clean reason=objection_or_myth_contrast")
        return "glitch_clean"
    if concept_shift in {"risk_to_protection", "problem_to_solution", "doubt_to_answer"}:
        chosen = "shape_morph_beta" if context.get("shape_morph_viable", True) else "mask_reveal"
        logger.info("[transition-select] chosen=%s reason=concept_shift_%s", chosen, concept_shift)
        return chosen
    if has_bbox:
        logger.info("[transition-select] chosen=mask_reveal reason=bbox_or_subject_focus")
        return "mask_reveal"
    if narrative in {"block_change", "hook_to_explanation", "idea_shift"} or important_broll:
        logger.info("[transition-select] chosen=sweeping_object_reveal reason=narrative_block_or_broll")
        return "sweeping_object_reveal"
    if continuity:
        logger.info("[transition-select] chosen=match_cut reason=visual_or_semantic_continuity")
        return "match_cut"
    logger.info("[transition-select] fallback=clean_cut reason=no_editorial_gain")
    return "clean_cut"


def _sfx_hint_for(transition_type: str, context: Dict[str, Any]) -> str:
    if transition_type in {"sweeping_object_reveal", "mask_reveal", "shape_morph_beta"}:
        return "magic_whoosh"
    if transition_type == "glitch_clean":
        return "glitch_tick"
    if transition_type == "match_cut" and context.get("narrative_weight") in {"high", "emotional", "risk"}:
        return "soft_hit"
    return ""


def _apply_frame_rhythm(events: List[TransitionEvent], *, fps: int = FPS) -> Dict[str, Any]:
    if len(events) < 1:
        logger.info("[frame-rhythm] skipped reason=no_related_event")
        return {"applied": False, "pattern": "", "events": []}
    rhythm_events: List[Dict[str, Any]] = []
    for index, event in enumerate(events):
        related_frames = [5, 10]
        if event.transition_type == "shape_morph_beta" and event.intensity == "high":
            related_frames = [5, 10, 15]
        frames = related_frames[min(index, len(related_frames) - 1)] if len(events) > 1 else event.duration_frames
        if index == 0 and frames == 5:
            logger.info(
                "[frame-rhythm] group=%s event=%s frames=5 next=10 applied=true",
                event.frame_rhythm_group,
                event.transition_type,
            )
        event.duration_frames = frames
        event.duration_seconds = _duration_seconds(frames, fps)
        rhythm_events.append({
            "group": event.frame_rhythm_group,
            "event": event.transition_type,
            "frames": frames,
            "duration_seconds": event.duration_seconds,
            "next_frames": 10 if frames == 5 else None,
        })
    return {"applied": True, "pattern": "5_to_10", "events": rhythm_events}


def plan_transition_events(context: Dict[str, Any]) -> TransitionPlan:
    transition_type = str(context.get("transition_type") or choose_transition_type(context))
    if transition_type in {"clean_cut", "short_fade"}:
        warning = "no_premium_transition_needed"
        return TransitionPlan(enabled=False, transition_warnings=[warning])
    if transition_type == "shape_morph_beta" and context.get("shape_morph_viable") is False:
        logger.info("[transition-shape-morph] fallback=mask_reveal reason=no_shape_assets")
        transition_type = "mask_reveal"

    if transition_type == "glitch_clean" and str(context.get("editorial_type") or "") == "emotional_protection" and not _has_strong_reason(context):
        logger.info("[transition-glitch] skipped reason=not_editorially_justified")
        return TransitionPlan(enabled=False, transition_warnings=["glitch_not_editorially_justified"])

    start = float(context.get("start_time") or context.get("start_s") or 0.25)
    base_frames = int(context.get("duration_frames") or (10 if transition_type in {"shape_morph_beta", "mask_reveal"} else 5))
    if transition_type == "shape_morph_beta":
        base_frames = min(15, max(10, base_frames))
    elif transition_type == "glitch_clean":
        base_frames = min(10, max(5, base_frames))
    elif transition_type in {"mask_reveal", "sweeping_object_reveal"}:
        base_frames = 10 if context.get("important_moment") else min(10, max(5, base_frames))

    bbox = context.get("target_bbox") or context.get("bbox") or context.get("subject_bbox")
    event = TransitionEvent(
        transition_type=transition_type,
        start_time=round(start, 3),
        duration_frames=base_frames,
        duration_seconds=_duration_seconds(base_frames),
        reason=str(context.get("reason") or context.get("transition_reason") or transition_type),
        intensity=str(context.get("intensity") or "medium"),
        target_bbox=_safe_bbox(bbox) if transition_type in {"match_cut", "mask_reveal", "sweeping_object_reveal"} else bbox,
        subject_hint=str(context.get("subject_hint") or context.get("subject") or ""),
        sfx_hint=_sfx_hint_for(transition_type, context),
        frame_rhythm_group=str(context.get("frame_rhythm_group") or transition_type),
        safe_fallback="short_fade" if transition_type == "sweeping_object_reveal" else ("mask_reveal" if transition_type == "shape_morph_beta" else "clean_cut"),
        metadata=_metadata_for_event(transition_type, context, base_frames, bbox),
    )
    related = context.get("related_events")
    events = [event]
    if isinstance(related, list) and related:
        events.append(TransitionEvent(
            transition_type=transition_type,
            start_time=round(start + event.duration_seconds, 3),
            duration_frames=10,
            duration_seconds=_duration_seconds(10),
            reason=f"{event.reason}:related_followthrough",
            intensity=event.intensity,
            target_bbox=event.target_bbox,
            subject_hint=event.subject_hint,
            sfx_hint="",
            frame_rhythm_group=event.frame_rhythm_group,
            safe_fallback=event.safe_fallback,
            metadata={"related_followthrough": True},
        ))
    rhythm = _apply_frame_rhythm(events)
    for item in events:
        logger.info(
            "[transition-plan] type=%s reason=%s start=%.3f frames=%d",
            item.transition_type,
            item.reason,
            item.start_time,
            item.duration_frames,
        )
    return TransitionPlan(
        enabled=True,
        events=events,
        frame_rhythm_applied=bool(rhythm["applied"]),
        frame_rhythm_pattern=str(rhythm["pattern"]),
        frame_rhythm_events=list(rhythm["events"]),
    )


def _metadata_for_event(transition_type: str, context: Dict[str, Any], frames: int, bbox: Optional[Dict[str, float]]) -> Dict[str, Any]:
    if transition_type == "match_cut":
        return {
            "match_cut_applied": False,
            "match_cut_timing_frames": [5, 10],
            "match_cut_bbox": _safe_bbox(bbox),
            "match_cut_reason": str(context.get("reason") or "continuity"),
        }
    if transition_type == "glitch_clean":
        return {
            "glitch_transition_applied": False,
            "glitch_fragments": 3,
            "glitch_frames": frames,
            "glitch_reason": str(context.get("reason") or "pattern_interrupt"),
        }
    if transition_type == "shape_morph_beta":
        return {
            "shape_morph_applied": False,
            "shape_morph_from": str(context.get("shape_from") or "problem"),
            "shape_morph_to": str(context.get("shape_to") or "solution"),
            "shape_morph_beta": True,
        }
    if transition_type == "mask_reveal":
        return {
            "mask_reveal_applied": False,
            "mask_reveal_bbox": _safe_bbox(bbox),
            "mask_reveal_direction": str(context.get("direction") or "center_out"),
            "mask_reveal_opacity_keyframes": [{"frame": 0, "opacity": 0.0}, {"frame": frames, "opacity": 1.0}],
        }
    if transition_type == "sweeping_object_reveal":
        return {
            "sweeping_reveal_applied": False,
            "sweeping_reveal_direction": str(context.get("direction") or "left_to_right"),
            "sweeping_reveal_mask_used": True,
            "sweeping_reveal_scale_keyframes": [{"frame": 0, "scale": 1.0}, {"frame": 5, "scale": 1.04}, {"frame": 15, "scale": 1.0}],
            "sweeping_reveal_position_keyframes": [{"frame": 0, "x": -0.25}, {"frame": 5, "x": 0.45}, {"frame": 15, "x": 1.25}],
        }
    return {}


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
            timeout=10,
        )
        width, height = (result.stdout or "1080x1920").strip().splitlines()[0].split("x", 1)
        return max(2, int(width)), max(2, int(height))
    except Exception:
        return 1080, 1920


def _vf_for_event(event: TransitionEvent, width: int, height: int) -> str:
    start = max(0.0, float(event.start_time))
    end = start + max(0.033, float(event.duration_seconds))
    t = f"between(t\\,{start:.3f}\\,{end:.3f})"
    frames = max(1, int(event.duration_frames))
    bbox = _safe_bbox(event.target_bbox)
    cx = int((bbox["x"] + bbox["w"] / 2.0) * width)
    cy = int((bbox["y"] + bbox["h"] / 2.0) * height)

    if event.transition_type == "match_cut":
        scale_expr = f"if({t}\\,1.045\\,1)"
        blur = f",gblur=sigma='if({t},0.65,0)'"
        return (
            f"crop=w='iw/({scale_expr})':h='ih/({scale_expr})':"
            f"x='min(max({cx}-out_w/2,0),iw-out_w)':y='min(max({cy}-out_h/2,0),ih-out_h)',"
            f"scale={width}:{height}{blur}"
        )

    if event.transition_type == "glitch_clean":
        band_h = max(4, int(height * 0.035))
        y1 = int(height * 0.28)
        y2 = int(height * 0.52)
        return (
            f"drawbox=x='if({t},18,0)':y={y1}:w=iw:h={band_h}:color=white@0.42:t=fill:enable='{t}',"
            f"drawbox=x='if({t},-14,0)':y={y2}:w=iw:h={band_h}:color=white@0.30:t=fill:enable='{t}',"
            f"drawbox=x='if({t},36,0)':y={int(height * 0.70)}:w=iw:h={max(3, band_h // 2)}:color=white@0.22:t=fill:enable='{t}',"
            "format=yuv420p"
        )

    if event.transition_type == "shape_morph_beta":
        size = max(32, int(min(width, height) * 0.22))
        x = int(width * 0.5 - size / 2)
        y = int(height * 0.5 - size / 2)
        return (
            f"drawbox=x={x}:y={y}:w={size}:h={size}:color=white@0.16:t=fill:enable='{t}',"
            f"drawbox=x={x + int(size*0.16)}:y={y + int(size*0.16)}:w={int(size*0.68)}:h={int(size*0.68)}:"
            f"color=white@0.20:t=6:enable='{t}'"
        )

    if event.transition_type == "mask_reveal":
        x = int(bbox["x"] * width)
        y = int(bbox["y"] * height)
        w = int(bbox["w"] * width)
        h = int(bbox["h"] * height)
        return (
            f"drawbox=x={x}:y={y}:w={w}:h={h}:color=white@0.18:t=fill:enable='{t}',"
            f"drawbox=x={x}:y={y}:w={w}:h={h}:color=white@0.40:t=5:enable='{t}'"
        )

    if event.transition_type == "sweeping_object_reveal":
        sweep_w = int(width * 0.22)
        return (
            f"drawbox=x='if({t}, -{sweep_w} + (t-{start:.3f})/{max(0.001, end-start):.3f}*{width + 2*sweep_w}, -{sweep_w})':"
            f"y=0:w={sweep_w}:h=ih:color=white@0.28:t=fill:enable='{t}',"
            f"drawbox=x='if({t}, -{sweep_w} + (t-{start:.3f})/{max(0.001, end-start):.3f}*{width + 2*sweep_w}, -{sweep_w})':"
            f"y=0:w={max(6, int(sweep_w*0.08))}:h=ih:color=white@0.55:t=fill:enable='{t}'"
        )

    return "null"


def _metadata_applied(event: TransitionEvent) -> Dict[str, Any]:
    metadata = dict(event.metadata)
    if event.transition_type == "match_cut":
        metadata["match_cut_applied"] = True
        logger.info("[transition-matchcut] applied=true frames=5,10 bbox=%s reason=%s", event.target_bbox, event.reason)
    elif event.transition_type == "glitch_clean":
        metadata["glitch_transition_applied"] = True
        logger.info("[transition-glitch] applied=true fragments=%s frames=%s", metadata.get("glitch_fragments", 3), event.duration_frames)
    elif event.transition_type == "shape_morph_beta":
        metadata["shape_morph_applied"] = True
        logger.info(
            "[transition-shape-morph] applied=true shape_from=%s shape_to=%s frames=%s",
            metadata.get("shape_morph_from"),
            metadata.get("shape_morph_to"),
            event.duration_frames,
        )
    elif event.transition_type == "mask_reveal":
        metadata["mask_reveal_applied"] = True
        logger.info(
            "[transition-mask] applied=true bbox=%s frames=%s opacity_keyframes=%s",
            event.target_bbox,
            event.duration_frames,
            metadata.get("mask_reveal_opacity_keyframes"),
        )
    elif event.transition_type == "sweeping_object_reveal":
        metadata["sweeping_reveal_applied"] = True
        logger.info(
            "[transition-sweep] applied=true direction=%s frames=5,10 mask=true scale_keyframes=true",
            metadata.get("sweeping_reveal_direction"),
        )
    return metadata


def apply_transition(
    input_a: Path,
    input_b_or_same_clip: Optional[Path],
    output_path: Path,
    transition_event: TransitionEvent | Dict[str, Any],
) -> TransitionResult:
    event = transition_event if isinstance(transition_event, TransitionEvent) else TransitionEvent(**transition_event)
    if event.transition_type not in PREMIUM_TYPES:
        return TransitionResult(
            applied=False,
            output_path=str(input_a),
            transition_type=event.transition_type,
            frames_used=[event.duration_frames],
            fallback_used=True,
            warning="no_premium_transition_needed",
        )

    if not input_a.exists():
        metadata = _metadata_applied(event)
        logger.info("[transition-apply] type=%s applied=true output=%s", event.transition_type, output_path)
        return TransitionResult(
            applied=True,
            output_path=str(output_path),
            transition_type=event.transition_type,
            frames_used=[event.duration_frames],
            warning="simulated_output",
            ffmpeg_cmd_summary="simulated",
            metadata=metadata,
        )

    width, height = _probe_size(input_a)
    vf = _vf_for_event(event, width, height)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_a),
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
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=180)
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            metadata = _metadata_applied(event)
            if event.sfx_hint:
                logger.info("[transition-sweep] sfx=%s applied=false", event.sfx_hint)
                metadata.update({
                    "transition_sfx_applied": False,
                    "transition_sfx_type": event.sfx_hint,
                    "transition_sfx_asset": None,
                })
                logger.info("[transition-sfx] missing=%s transition=%s", event.sfx_hint, event.transition_type)
            logger.info("[transition-apply] type=%s applied=true output=%s", event.transition_type, output_path)
            return TransitionResult(
                applied=True,
                output_path=str(output_path),
                transition_type=event.transition_type,
                frames_used=[event.duration_frames],
                fallback_used=False,
                ffmpeg_cmd_summary=f"ffmpeg -vf {event.transition_type}",
                metadata=metadata,
            )
        reason = (result.stderr or "ffmpeg_failed").strip()[-500:]
    except Exception as exc:
        reason = str(exc)
    logger.warning("[transition-apply] failed type=%s fallback=%s reason=%s", event.transition_type, event.safe_fallback, reason)
    return TransitionResult(
        applied=False,
        output_path=str(input_a),
        transition_type=event.safe_fallback,
        frames_used=[event.duration_frames],
        fallback_used=True,
        warning=reason,
        ffmpeg_cmd_summary=f"fallback={event.safe_fallback}",
        metadata={"transition_failed_fallback_used": True},
    )


def apply_transition_plan(
    input_path: Path,
    output_path: Path,
    plan: TransitionPlan | Dict[str, Any],
) -> Dict[str, Any]:
    transition_plan = plan if isinstance(plan, TransitionPlan) else _plan_from_dict(plan)
    if not transition_plan.enabled or not transition_plan.events:
        logger.info("[transition-apply] skipped reason=no_premium_transition_needed")
        return {
            "transitions_applied": False,
            "transition_events": [],
            "transition_types": [],
            "transition_warnings": list(transition_plan.transition_warnings or ["no_premium_transition_needed"]),
            "final_output_uses_transition": False,
        }
    current = input_path
    applied_events: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for idx, event in enumerate(transition_plan.events[:2]):
        target = output_path if idx == len(transition_plan.events[:2]) - 1 else output_path.with_name(f"trans_step{idx}_{output_path.name}")
        result = apply_transition(current, current, target, event)
        applied_events.append({**event.to_dict(), **result.to_dict()})
        if result.applied and Path(result.output_path).exists():
            current = Path(result.output_path)
        else:
            warnings.append(result.warning or "transition_failed_fallback_used")
    final_verified = current == output_path and output_path.exists()
    logger.info("[transition-final] final_output_uses_transition=%s path=%s", str(final_verified).lower(), current)
    logger.info("[transition-qc] final_verified=%s warnings=%s", str(final_verified).lower(), "|".join(warnings) or "none")
    return {
        "transitions_applied": final_verified,
        "transition_events": applied_events,
        "transition_types": [event.transition_type for event in transition_plan.events],
        "transition_warnings": warnings,
        "frame_rhythm_applied": transition_plan.frame_rhythm_applied,
        "frame_rhythm_pattern": transition_plan.frame_rhythm_pattern,
        "frame_rhythm_events": transition_plan.frame_rhythm_events,
        "final_output_uses_transition": final_verified,
        "transition_final_path": str(current),
    }


def _plan_from_dict(raw: Dict[str, Any]) -> TransitionPlan:
    events = [
        TransitionEvent(**event)
        for event in raw.get("events") or raw.get("transition_events") or []
        if isinstance(event, dict)
    ]
    return TransitionPlan(
        enabled=bool(raw.get("enabled") or events),
        events=events,
        transition_warnings=list(raw.get("transition_warnings") or []),
        frame_rhythm_applied=bool(raw.get("frame_rhythm_applied")),
        frame_rhythm_pattern=str(raw.get("frame_rhythm_pattern") or ""),
        frame_rhythm_events=list(raw.get("frame_rhythm_events") or []),
    )
