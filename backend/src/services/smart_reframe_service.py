"""Safe VPI smart reframe rendering."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .vpi_gpu_runtime import select_ffmpeg_video_encoder
from .vpi_visual_effects_service import choose_vpi_framing_profile

logger = logging.getLogger(__name__)


class SmartReframeService:
    def apply(
        self,
        video_path: Path,
        output_path: Path,
        editing_plan: Dict[str, Any],
        has_broll: bool = False,
    ) -> Dict[str, Any]:
        events = list(editing_plan.get("smart_zoom_events") or [])
        strategy = str(editing_plan.get("reframe_strategy") or "no_zoom")
        framing_profile = dict(editing_plan.get("framing_profile") or {})
        if not framing_profile:
            try:
                framing_profile = choose_vpi_framing_profile(
                    editorial_type=str(editing_plan.get("editorial_type") or ""),
                    motion_profile=str((editing_plan.get("motion_rhythm_profile") or {}).get("motion_profile") or ""),
                    caption_polish_profile=str(editing_plan.get("caption_polish_profile") or ""),
                    premium_restraint_mode=str(editing_plan.get("premium_restraint_mode") or ""),
                    visual_layout_strategy=str(editing_plan.get("visual_layout_strategy") or ""),
                    face_bbox=editing_plan.get("face_bbox") if isinstance(editing_plan.get("face_bbox"), dict) else None,
                    speaker_bbox=editing_plan.get("speaker_bbox") if isinstance(editing_plan.get("speaker_bbox"), dict) else None,
                    clip_duration=float(editing_plan.get("clip_duration") or editing_plan.get("duration") or 0.0),
                    broll_applied=bool(has_broll or editing_plan.get("broll_applied")),
                    hook_strategy_final=str((editing_plan.get("hook_plan") or {}).get("hook_strategy_final") or (editing_plan.get("hook_plan") or {}).get("hook_strategy") or ""),
                    sensitive_topic=bool(str(editing_plan.get("editorial_type") or "").strip().lower() in {"sensitive_decesos", "decesos"}),
                )
            except Exception as _framing_compute_e:
                framing_profile = {"framing_profile": "speaker_centered", "framing_polish_warnings": [str(_framing_compute_e)]}
        profile_name = str(framing_profile.get("framing_profile") or "speaker_centered")
        warnings: List[str] = []
        framing_warnings = list(framing_profile.get("framing_polish_warnings") or [])
        if profile_name in {"no_reframe", "static_safe"}:
            logger.info("[smart-reframe] skipped reason=framing_no_reframe")
            return {
                "rendered": False,
                "output_path": str(video_path),
                "events": [],
                "reason": "framing_no_reframe",
                "warnings": warnings + ["framing_no_reframe"] + framing_warnings,
                **framing_profile,
            }
        if strategy == "no_zoom" or not events:
            logger.info("[smart-reframe] skipped reason=no_zoom_or_no_events")
            return {
                "rendered": False,
                "output_path": str(video_path),
                "events": [],
                "reason": "no_zoom_or_no_events",
                "warnings": warnings + framing_warnings,
                **framing_profile,
            }

        capped = self._sanitize_events(events, strategy, has_broll, framing_profile)
        if not capped:
            logger.info("[smart-reframe] skipped reason=no_safe_events")
            return {
                "rendered": False,
                "output_path": str(video_path),
                "events": [],
                "reason": "no_safe_events",
                "warnings": ["no_safe_events"] + framing_warnings,
                **framing_profile,
            }
        hook_events = [event for event in capped if event.get("hook")]
        for event in hook_events:
            logger.info(
                "[smart-reframe] hook_event=%s valid=true start=%.2f dur=%.2f scale=%.3f",
                event.get("reason", "hook"),
                float(event.get("start_s", 0.0)),
                float(event.get("duration_s", 0.0)),
                float(event.get("scale", 1.0)),
            )

        scale_expr = self._scale_expr(capped)
        vf = (
            f"scale=w='ceil(1080*({scale_expr})/2)*2':"
            f"h='ceil(1920*({scale_expr})/2)*2':eval=frame,"
            "crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2"
        )
        encoder_info = select_ffmpeg_video_encoder(stage="rhythm", quality="high")
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path),
            "-vf", vf,
            "-c:v", str(encoder_info.get("encoder") or "libx264"),
            "-preset", str(encoder_info.get("preset") or "veryfast"),
            *list(encoder_info.get("extra_args") or []),
            "-c:a", "copy",
            str(output_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode == 0 and output_path.exists():
                for event in capped:
                    logger.info(
                        "[smart-reframe] rendered=true event=%s start=%.2f dur=%.2f scale=%.3f",
                        event.get("reason", "emphasis"),
                        float(event.get("start_s", 0.0)),
                        float(event.get("duration_s", 0.0)),
                        float(event.get("scale", 1.0)),
                    )
                return {
                    "rendered": True,
                    "output_path": str(output_path),
                    "events": capped,
                    "warnings": warnings + framing_warnings,
                    "method": "ffmpeg_dynamic_scale_crop",
                    **framing_profile,
                }
            warning = (result.stderr or "ffmpeg_failed")[-240:]
            warnings.append("ffmpeg_failed")
            logger.warning("[smart-reframe] failed fallback=input reason=%s", warning)
            fallback = self._apply_static_push_in(video_path, output_path, capped)
            if fallback.get("rendered"):
                fallback["warnings"] = warnings + framing_warnings
                fallback.update(framing_profile)
                return fallback
        except Exception as exc:
            warnings.append(str(exc))
            logger.warning("[smart-reframe] failed fallback=input reason=%s", exc)
            fallback = self._apply_static_push_in(video_path, output_path, capped)
            if fallback.get("rendered"):
                fallback["warnings"] = warnings + framing_warnings
                fallback.update(framing_profile)
                return fallback

        return {
            "rendered": False,
            "output_path": str(video_path),
            "planned_output_path": str(output_path),
            "events": capped,
            "reason": "ffmpeg_failed_fallback_input",
            "warnings": warnings + framing_warnings,
            **framing_profile,
        }

    def _apply_static_push_in(self, video_path: Path, output_path: Path, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        hook_event = next((event for event in events if event.get("hook")), None)
        if not hook_event:
            return {"rendered": False}
        fallback_event = {
            **hook_event,
            "start_s": round(min(0.75, max(0.4, float(hook_event.get("start_s", 0.55) or 0.55))), 2),
            "duration_s": round(min(3.0, max(1.8, float(hook_event.get("duration_s", 2.2) or 2.2))), 2),
            "scale": round(min(1.08, max(1.04, float(hook_event.get("scale", 1.05) or 1.05))), 3),
            "reason": f"{hook_event.get('reason', 'hook')}:fallback_static_push_in",
            "hook": True,
        }
        start = float(fallback_event["start_s"])
        end = start + float(fallback_event["duration_s"])
        scale = float(fallback_event["scale"])
        caller = "apply_static_hook_push_in"
        vf = (
            f"scale=w='ceil(1080*if(between(t,{start:.3f},{end:.3f}),{scale:.3f},1)/2)*2':"
            f"h='ceil(1920*if(between(t,{start:.3f},{end:.3f}),{scale:.3f},1)/2)*2':eval=frame,"
            "crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2,format=yuv420p"
        )
        encoder_info = select_ffmpeg_video_encoder(stage="rhythm", quality="high")
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path),
            "-vf", vf,
            "-c:v", str(encoder_info.get("encoder") or "libx264"),
            "-preset", str(encoder_info.get("preset") or "veryfast"),
            *list(encoder_info.get("extra_args") or []),
            "-c:a", "copy",
            "-pix_fmt", "yuv420p",
            "-colorspace", "bt709",
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-color_range", "tv",
            "-movflags", "+faststart",
            str(output_path),
        ]
        logger.info(
            "VPI_SMART_REFRAME_BT709_TAGS_APPLIED input_path=%s output_path=%s caller=%s filter_chain=%s command=%s",
            str(video_path),
            str(output_path),
            caller,
            vf,
            " ".join(cmd),
        )
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode == 0 and output_path.exists():
                probe_cmd = [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_format",
                    "-show_streams",
                    "-print_format",
                    "json",
                    str(output_path),
                ]
                probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=60)
                probe_text = probe_result.stdout if probe_result.returncode == 0 else ""
                logger.info(
                    "VPI_SMART_REFRAME_OUTPUT_COLOR_PROBE input_path=%s output_path=%s probe=%s",
                    str(video_path),
                    str(output_path),
                    probe_text[:2000],
                )
                logger.info("[smart-reframe] fallback_static_push_in applied=true")
                return {
                    "rendered": True,
                    "output_path": str(output_path),
                    "events": [fallback_event],
                    "method": "ffmpeg_static_push_in_fallback",
                    "fallback_static_push_in": True,
                }
            logger.warning("[smart-reframe] fallback_static_push_in failed reason=%s", (result.stderr or "ffmpeg_failed")[-240:])
        except Exception as exc:
            logger.warning("[smart-reframe] fallback_static_push_in failed reason=%s", exc)
        return {"rendered": False}

    def apply_static_hook_push_in(
        self,
        video_path: Path,
        output_path: Path,
        hook_event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Public safe fallback for emotional hook motion."""
        event = {
            **(hook_event or {}),
            "hook": True,
            "start_s": round(min(0.8, max(0.4, float((hook_event or {}).get("start_s", 0.55) or 0.55))), 2),
            "duration_s": round(min(2.2, max(1.6, float((hook_event or {}).get("duration_s", 1.8) or 1.8))), 2),
            "scale": round(min(1.035, max(1.02, float((hook_event or {}).get("scale", 1.025) or 1.025))), 3),
            "reason": (hook_event or {}).get("reason") or "hook:emotional_hook",
        }
        return self._apply_static_push_in(video_path, output_path, [event])

    @staticmethod
    def _sanitize_events(
        events: List[Dict[str, Any]],
        strategy: str,
        has_broll: bool,
        framing_profile: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        profile_name = str((framing_profile or {}).get("framing_profile") or "").strip().lower()
        if profile_name in {"no_reframe"}:
            return []
        max_events = 1 if has_broll else 2
        if profile_name in {"sensitive_stable", "static_safe"}:
            max_events = min(max_events, 1)
        elif profile_name in {"speaker_upper_safe", "speaker_centered"} and has_broll:
            max_events = 1
        sanitized: List[Dict[str, Any]] = []
        scale_cap = {
            "sensitive_stable": 1.025,
            "static_safe": 1.02,
            "speaker_upper_safe": 1.03,
            "speaker_centered": 1.04,
            "subtle_push_in": 1.055,
        }.get(profile_name, 1.045)
        min_duration = {
            "sensitive_stable": 0.40,
            "static_safe": 0.38,
            "speaker_upper_safe": 0.42,
            "speaker_centered": 0.45,
            "subtle_push_in": 0.40,
        }.get(profile_name, 0.40)
        max_duration = {
            "sensitive_stable": 2.0,
            "static_safe": 1.8,
            "speaker_upper_safe": 2.4,
            "speaker_centered": 2.8,
            "subtle_push_in": 2.6,
        }.get(profile_name, 2.4)
        for raw in events:
            try:
                start = float(raw.get("start_s", 0.0))
                scale = float(raw.get("scale", 1.0))
            except (TypeError, ValueError):
                continue
            reason = str(raw.get("reason") or "").lower()
            is_hook = bool(raw.get("hook")) or "hook" in reason
            if start < 1.0 and not is_hook:
                continue
            if is_hook:
                duration = min(max_duration, max(1.4, float(raw.get("duration_s", 2.2) or 2.2)))
                scale = min(scale_cap, max(1.02, scale))
            elif strategy == "emphasis_punch" or "punch" in reason:
                duration = min(min(0.75, max_duration), max(min_duration, float(raw.get("duration_s", 0.55) or 0.55)))
                scale = min(scale_cap, max(1.01, scale))
            else:
                duration = min(min(0.75, max_duration), max(min_duration, float(raw.get("duration_s", 0.55) or 0.55)))
                scale = min(scale_cap, max(1.01, scale))
            sanitized.append({
                **raw,
                "start_s": round(start, 2),
                "duration_s": round(duration, 2),
                "scale": round(scale, 3),
            })
            if len(sanitized) >= max_events:
                break
        return sanitized

    @staticmethod
    def _scale_expr(events: List[Dict[str, Any]]) -> str:
        expr = "1"
        for event in reversed(events):
            start = float(event.get("start_s", 0.0))
            end = start + float(event.get("duration_s", 0.0))
            scale = float(event.get("scale", 1.0))
            expr = f"if(between(t,{start:.3f},{end:.3f}),{scale:.3f},{expr})"
        return expr
