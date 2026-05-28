"""Safe VPI smart reframe rendering."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List

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
        warnings: List[str] = []
        if strategy == "no_zoom" or not events:
            logger.info("[smart-reframe] skipped reason=no_zoom_or_no_events")
            return {
                "rendered": False,
                "output_path": str(video_path),
                "events": [],
                "reason": "no_zoom_or_no_events",
                "warnings": warnings,
            }

        capped = self._sanitize_events(events, strategy, has_broll)
        if not capped:
            logger.info("[smart-reframe] skipped reason=no_safe_events")
            return {
                "rendered": False,
                "output_path": str(video_path),
                "events": [],
                "reason": "no_safe_events",
                "warnings": ["no_safe_events"],
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
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
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
                    "warnings": warnings,
                    "method": "ffmpeg_dynamic_scale_crop",
                }
            warning = (result.stderr or "ffmpeg_failed")[-240:]
            warnings.append("ffmpeg_failed")
            logger.warning("[smart-reframe] failed fallback=input reason=%s", warning)
            fallback = self._apply_static_push_in(video_path, output_path, capped)
            if fallback.get("rendered"):
                fallback["warnings"] = warnings
                return fallback
        except Exception as exc:
            warnings.append(str(exc))
            logger.warning("[smart-reframe] failed fallback=input reason=%s", exc)
            fallback = self._apply_static_push_in(video_path, output_path, capped)
            if fallback.get("rendered"):
                fallback["warnings"] = warnings
                return fallback

        return {
            "rendered": False,
            "output_path": str(video_path),
            "planned_output_path": str(output_path),
            "events": capped,
            "reason": "ffmpeg_failed_fallback_input",
            "warnings": warnings,
        }

    def _apply_static_push_in(self, video_path: Path, output_path: Path, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        hook_event = next((event for event in events if event.get("hook")), None)
        if not hook_event:
            return {"rendered": False}
        fallback_event = {
            **hook_event,
            "start_s": round(min(0.8, max(0.4, float(hook_event.get("start_s", 0.55) or 0.55))), 2),
            "duration_s": round(min(2.2, max(1.6, float(hook_event.get("duration_s", 1.8) or 1.8))), 2),
            "scale": round(min(1.035, max(1.02, float(hook_event.get("scale", 1.025) or 1.025))), 3),
            "reason": f"{hook_event.get('reason', 'hook')}:fallback_static_push_in",
            "hook": True,
        }
        start = float(fallback_event["start_s"])
        end = start + float(fallback_event["duration_s"])
        scale = float(fallback_event["scale"])
        vf = (
            f"scale=w='ceil(1080*if(between(t,{start:.3f},{end:.3f}),{scale:.3f},1)/2)*2':"
            f"h='ceil(1920*if(between(t,{start:.3f},{end:.3f}),{scale:.3f},1)/2)*2':eval=frame,"
            "crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2"
        )
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-c:a", "copy",
            str(output_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode == 0 and output_path.exists():
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
    def _sanitize_events(events: List[Dict[str, Any]], strategy: str, has_broll: bool) -> List[Dict[str, Any]]:
        max_events = 1 if has_broll else 2
        sanitized: List[Dict[str, Any]] = []
        for raw in events:
            try:
                start = float(raw.get("start_s", 0.0))
                scale = float(raw.get("scale", 1.0))
            except (TypeError, ValueError):
                continue
            if start < 1.0 and not raw.get("hook"):
                continue
            if strategy == "emphasis_punch":
                duration = min(0.7, max(0.45, float(raw.get("duration_s", 0.55) or 0.55)))
                scale = min(1.05, max(1.04, scale))
            else:
                duration = min(1.8, max(1.2, float(raw.get("duration_s", 1.4) or 1.4)))
                scale = min(1.035, max(1.025, scale))
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
