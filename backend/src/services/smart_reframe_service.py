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
        # RHYTHM-34: progressive eased hook push-in (smoothstep ramp) instead of
        # the old instant step. Perceptible but professional; captions burn after.
        comp = self._eased_scale_component(start, end, scale)
        vf = (
            f"scale=w='ceil(1080*({comp})/2)*2':"
            f"h='ceil(1920*({comp})/2)*2':eval=frame,"
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
    def _eased_scale_component(
        start: float,
        end: float,
        scale: float,
        ease_in_s: float = 0.5,
        ease_out_s: float = 0.4,
    ) -> str:
        """RHYTHM-34: progressive (smoothstep) push-in component.

        Returns an ffmpeg expression that ramps from 1 -> scale over an ease-in
        window, holds, then ramps scale -> 1 over an ease-out window, and is
        exactly 1 outside [start, end]. Replaces the old binary
        ``if(between(t,s,e),scale,1)`` step (instant zoom in/out) which read as a
        cheap template pop. Captions are unaffected: the push-in renders before
        the ASS caption burn, so the eased scale never touches the caption layer.
        """
        span = max(0.001, end - start)
        ti = max(0.05, min(ease_in_s, span / 2.0))
        to = max(0.05, min(ease_out_s, span / 2.0))
        ein = f"max(0,min(1,(t-{start:.3f})/{ti:.3f}))"
        eout = f"max(0,min(1,({end:.3f}-t)/{to:.3f}))"
        smooth_in = f"({ein}*{ein}*(3-2*{ein}))"
        smooth_out = f"({eout}*{eout}*(3-2*{eout}))"
        env = f"between(t,{start:.3f},{end:.3f})*min({smooth_in},{smooth_out})"
        coef = round(scale - 1.0, 4)
        return f"(1+{coef:.4f}*({env}))"

    @staticmethod
    def _scale_expr(events: List[Dict[str, Any]]) -> str:
        # RHYTHM-34: combine non-overlapping eased push-ins via max(); each
        # component is exactly 1 outside its own window, so max() selects the
        # active push-in and falls back to 1 (no zoom) elsewhere.
        components: List[str] = []
        for event in events:
            start = float(event.get("start_s", 0.0))
            end = start + float(event.get("duration_s", 0.0))
            scale = float(event.get("scale", 1.0))
            if end <= start or scale <= 1.0:
                continue
            components.append(
                SmartReframeService._eased_scale_component(start, end, scale)
            )
        if not components:
            return "1"
        expr = components[0]
        for comp in components[1:]:
            expr = f"max({expr},{comp})"
        return expr

    # ------------------------------------------------------------------
    # RHYTHM-35: live FFmpeg editorial punch-ins (production-safe, pre-caption)
    # ------------------------------------------------------------------
    @staticmethod
    def _editorial_priority(reason: str) -> int:
        r = (reason or "").lower()
        for key, rank in (("payoff", 0), ("revelation", 1), ("contrast", 2), ("emphasis", 3)):
            if key in r:
                return rank
        return 4

    @staticmethod
    def select_editorial_punch_events(
        events: List[Dict[str, Any]],
        *,
        clip_duration: float = 0.0,
        hook_window: Optional[Dict[str, Any]] = None,
        protected_ranges: Optional[List[Dict[str, Any]]] = None,
        max_events: int = 2,
        min_separation_s: float = 4.0,
    ) -> List[Dict[str, Any]]:
        """FASE 2: reuse existing non-hook events; keep them sober and separated.

        Rules: <=2 events, >=4s apart, not in the first 3s when a hook is active,
        not over a protected range (micro-repair +-0.5s / B-roll / closure), scale
        clamped to 1.035-1.07. Priority payoff > revelation > contrast > emphasis.
        Creates no new detection — it only filters events already in the plan.
        """
        hook_end = float((hook_window or {}).get("end_s", 0.0) or 0.0) if hook_window else 0.0
        protected = list(protected_ranges or [])
        candidates: List[Dict[str, Any]] = []
        for ev in events or []:
            if (ev or {}).get("hook"):
                continue
            reason = str(ev.get("reason") or "") or "editorial_punch"
            if "hook" in reason.lower():
                # hook-flavoured events belong to the hook stage, not editorial punch-ins
                continue
            try:
                start = float(ev.get("start_s", 0.0))
                dur = float(ev.get("duration_s", 0.0))
            except (TypeError, ValueError):
                continue
            if dur <= 0.0:
                continue
            end = start + dur
            if hook_end > 0.0 and start < max(3.0, hook_end + 0.5):
                continue
            if clip_duration > 0.0 and end > clip_duration - 0.3:
                continue
            overlaps_protected = False
            for pr in protected:
                ps = float(pr.get("start_s", 0.0)) - 0.5
                pe = float(pr.get("end_s", pr.get("start_s", 0.0)) or 0.0) + 0.5
                if not (end < ps or start > pe):
                    overlaps_protected = True
                    break
            if overlaps_protected:
                continue
            scale = max(1.035, min(1.07, float(ev.get("scale", 1.05) or 1.05)))
            candidates.append({
                **ev,
                "start_s": round(start, 2),
                "duration_s": round(dur, 2),
                "scale": round(scale, 3),
                "reason": reason,
            })
        candidates.sort(key=lambda e: (SmartReframeService._editorial_priority(e["reason"]), e["start_s"]))
        selected: List[Dict[str, Any]] = []
        for cand in candidates:
            if len(selected) >= max_events:
                break
            if any(abs(cand["start_s"] - s["start_s"]) < min_separation_s for s in selected):
                continue
            selected.append(cand)
        selected.sort(key=lambda e: e["start_s"])
        return selected

    def apply_editorial_punch_ins(
        self,
        video_path: Path,
        output_path: Path,
        events: List[Dict[str, Any]],
        *,
        clip_duration: float = 0.0,
        hook_window: Optional[Dict[str, Any]] = None,
        protected_ranges: Optional[List[Dict[str, Any]]] = None,
        max_events: int = 2,
    ) -> Dict[str, Any]:
        """Apply 1-2 sober eased editorial punch-ins in a single FFmpeg pass.

        Runs after the hook push-in and before the caption burn. The hook zoom is
        already baked in; editorial events are temporally separated from it, so
        the combined scale never compounds. Total scale is hard-capped at 1.08.
        """
        planned = [e for e in (events or []) if not (e or {}).get("hook")]
        selected = self.select_editorial_punch_events(
            events,
            clip_duration=clip_duration,
            hook_window=hook_window,
            protected_ranges=protected_ranges,
            max_events=max_events,
        )
        for ev in selected:
            logger.info(
                "VPI_EDITORIAL_PUNCH_SELECTED reason=%s start=%.2f dur=%.2f scale=%.3f",
                ev.get("reason"), float(ev["start_s"]), float(ev["duration_s"]), float(ev["scale"]),
            )
        skipped = len(planned) - len(selected)
        if not selected:
            logger.info("VPI_EDITORIAL_PUNCH_SKIPPED planned=%d reason=no_safe_editorial_events", len(planned))
            return {
                "rendered": False, "output_path": str(video_path), "events": [],
                "planned": len(planned), "selected": 0, "applied": 0, "skipped": len(planned),
                "reason": "no_editorial_events",
            }
        components = []
        for ev in selected:
            s = float(ev["start_s"]); e = s + float(ev["duration_s"]); sc = float(ev["scale"])
            components.append(self._eased_scale_component(s, e, sc, ease_in_s=0.28, ease_out_s=0.35))
        expr = components[0]
        for comp in components[1:]:
            expr = f"max({expr},{comp})"
        expr = f"min(1.080,{expr})"
        vf = (
            f"scale=w='ceil(1080*({expr})/2)*2':"
            f"h='ceil(1920*({expr})/2)*2':eval=frame,"
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
            "-colorspace", "bt709", "-color_primaries", "bt709",
            "-color_trc", "bt709", "-color_range", "tv",
            "-movflags", "+faststart",
            str(output_path),
        ]
        logger.info(
            "VPI_EDITORIAL_PUNCH_FFMPEG_START count=%d filter_chain=%s", len(selected), vf,
        )
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode == 0 and output_path.exists():
                logger.info(
                    "VPI_EDITORIAL_PUNCH_FFMPEG_APPLIED count=%d output=%s", len(selected), str(output_path),
                )
                return {
                    "rendered": True, "output_path": str(output_path), "events": selected,
                    "method": "ffmpeg_editorial_punch_in",
                    "planned": len(planned), "selected": len(selected),
                    "applied": len(selected), "skipped": skipped,
                }
            logger.warning(
                "VPI_EDITORIAL_PUNCH_SKIPPED reason=ffmpeg_failed detail=%s",
                (result.stderr or "ffmpeg_failed")[-200:],
            )
        except Exception as exc:
            logger.warning("VPI_EDITORIAL_PUNCH_SKIPPED reason=exception detail=%s", exc)
        return {
            "rendered": False, "output_path": str(video_path), "events": selected,
            "planned": len(planned), "selected": len(selected), "applied": 0, "skipped": len(planned),
            "reason": "ffmpeg_failed",
        }

    # ------------------------------------------------------------------
    # RHYTHM-37: conditional sober fades (fade-in/fade-out), pre-caption
    # ------------------------------------------------------------------
    def apply_conditional_fades(
        self,
        video_path: Path,
        output_path: Path,
        *,
        clip_duration: float,
        first_word_start_s: Optional[float] = None,
        last_word_end_s: Optional[float] = None,
        last_caption_end_s: Optional[float] = None,
        hook_active: bool = False,
        has_end_visual: bool = False,
        closure_complete: bool = False,
        fps: float = 24.0,
    ) -> Dict[str, Any]:
        """Apply a short fade-in and/or fade-out only when the edges need it.

        Fade-in (5 frames) only when no hook covers the start and speech begins almost
        immediately (a hard cut into the clip). Fade-out (6 frames) only when there is a
        safe silent tail after the last word and no card/B-roll closes the clip — it starts
        AFTER the last word so no syllable is covered. Video-only fade; captions burn after,
        so they stay sharp. Duration is unchanged, so the timeline gate is unaffected.
        """
        fps = float(fps or 24.0) or 24.0
        meta: Dict[str, Any] = {
            "rendered": False,
            "output_path": str(video_path),
            "fade_in_needed": False, "fade_in_applied": False, "fade_in_frames": 0, "fade_in_reason": "",
            "fade_out_needed": False, "fade_out_applied": False, "fade_out_frames": 0, "fade_out_reason": "",
        }
        filters: List[str] = []
        # fade-in
        if (not hook_active) and (first_word_start_s is not None) and float(first_word_start_s) < 0.25:
            meta["fade_in_needed"] = True
            fi_frames = 5
            d = round(fi_frames / fps, 3)
            filters.append(f"fade=t=in:st=0:d={d:.3f}")
            meta.update({"fade_in_frames": fi_frames, "fade_in_reason": "abrupt_start_no_hook"})
        else:
            meta["fade_in_reason"] = "hook_present_or_clean_start"
        # OUTPUT-CLOSURE-54: word/caption timings can arrive in a stale (pre-reconciliation)
        # coordinate space that overruns the real probed master (clip_duration) — e.g. the
        # editorial timeline still measured ~26.8s while the rendered master is ~17.8s. Left
        # unclamped, `tail = clip_duration - last_word_end` goes NEGATIVE for a closure that
        # ends flush against the edge, which silently fails BOTH the fade-out gate and the
        # breathing-tail gate (`0.0 <= tail < 0.40`), so the master ends hard on the last
        # word with no respiration. Clamp into the master's own space so a flush complete
        # closure is seen as tail≈0 and the breathing-tail padding below can run.
        _dur_clamp = float(clip_duration)
        if last_word_end_s is not None:
            last_word_end_s = max(0.0, min(float(last_word_end_s), _dur_clamp))
        if last_caption_end_s is not None:
            last_caption_end_s = max(0.0, min(float(last_caption_end_s), _dur_clamp))
        # fade-out — anchored to the canonical final (clip_duration), faded over the last
        # frames so the master truly ends in black. RHYTHM-37B: clip_duration here MUST be the
        # real final video duration (the caller passes a correctly-probed value, never the
        # broken probe_duration 30.0 fallback or a nominal segment length).
        fo_frames = 6
        d = round(fo_frames / fps, 3)
        st = round(float(clip_duration) - d, 3)
        tail = float(clip_duration) - float(last_word_end_s if last_word_end_s is not None else clip_duration)
        _cap_end = float(last_caption_end_s) if last_caption_end_s is not None else (
            float(last_word_end_s) if last_word_end_s is not None else 0.0)
        # Require a real silent tail, no end card/B-roll, and the fade to start AFTER both the
        # last word and the last caption (so neither speech nor an active caption is darkened).
        if (
            (last_word_end_s is not None)
            and tail >= 0.40
            and (not has_end_visual)
            and st > float(last_word_end_s) + 0.10
            and st > _cap_end + 0.10
        ):
            meta["fade_out_needed"] = True
            filters.append(f"fade=t=out:st={st:.3f}:d={d:.3f}")
            meta.update({"fade_out_frames": fo_frames, "fade_out_reason": "dry_end_with_safe_tail", "fade_out_start_s": st})
        elif (last_word_end_s is not None) and tail >= 0.40 and (not has_end_visual):
            meta["fade_out_reason"] = "insufficient_final_tail_or_caption_overlap"
        else:
            meta["fade_out_reason"] = "natural_end_or_end_visual_or_tight_tail"

        # OUTPUT-CLOSURE-54: tail padding for a COMPLETE spoken closure that ends flush
        # against the clip edge (no breathing room), so the master doesn't "cut sin pensarlo"
        # right on the last word. Only when: the closure is a complete sentence, the current
        # tail after the last word is too tight (0.0-0.40s), there is no end card/B-roll, and
        # the last caption has finished. Holds the final frame ~0.6s (imagen estable), pads the
        # audio with matching silence, and runs the sober fade AFTER the last word. Never applied
        # to truncated closures / end visuals / clips that already breathe.
        if (
            not filters
            and bool(closure_complete)
            and (last_word_end_s is not None)
            and (not has_end_visual)
            and 0.0 <= tail < 0.40
            and float(clip_duration) > 1.0
        ):
            # Pad capped at 0.70s so the new duration stays under the rhythm-verify +0.75
            # guard. Anchor the fade on the SPOKEN last word (not the caption display hold,
            # which lingers past the word) so ~0.45s of stable image follows the speech.
            fo_d = 0.35
            pad_s = round(min(0.70, 0.80 - max(0.0, tail)), 3)
            new_dur = round(float(clip_duration) + pad_s, 3)
            fo_st = round(min(float(last_word_end_s) + 0.45, new_dur - fo_d), 3)
            fo_st = round(max(fo_st, float(last_word_end_s) + 0.10), 3)
            if fo_st < new_dur - 0.05:
                meta["fade_out_needed"] = True
                meta.update({
                    "fade_out_frames": int(round(fo_d * fps)),
                    "fade_out_reason": "tail_padded_complete_closure",
                    "fade_out_start_s": fo_st,
                    "tail_pad_applied_s": pad_s,
                })
                _vf_tail = f"tpad=stop_mode=clone:stop_duration={pad_s:.3f},fade=t=out:st={fo_st:.3f}:d={fo_d:.3f},format=yuv420p"
                if meta["fade_in_frames"]:
                    _vf_tail = filters[0] + "," + _vf_tail
                _af_tail = f"apad=pad_dur={pad_s:.3f},afade=t=out:st={fo_st:.3f}:d={fo_d:.3f}"
                encoder_info = select_ffmpeg_video_encoder(stage="rhythm", quality="high")
                cmd = [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(video_path),
                    "-vf", _vf_tail,
                    "-af", _af_tail,
                    "-c:v", str(encoder_info.get("encoder") or "libx264"),
                    "-preset", str(encoder_info.get("preset") or "veryfast"),
                    *list(encoder_info.get("extra_args") or []),
                    "-c:a", "aac", "-b:a", "192k",
                    "-pix_fmt", "yuv420p",
                    "-colorspace", "bt709", "-color_primaries", "bt709",
                    "-color_trc", "bt709", "-color_range", "tv",
                    "-movflags", "+faststart",
                    str(output_path),
                ]
                logger.info(
                    "VPI_TAIL_PADDING_APPLIED pad_s=%.3f new_dur=%.3f fade_start=%.3f fade_d=%.3f last_word_end=%.3f",
                    pad_s, new_dur, fo_st, fo_d, float(last_word_end_s),
                )
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                    if result.returncode == 0 and output_path.exists():
                        meta["rendered"] = True
                        meta["output_path"] = str(output_path)
                        meta["fade_out_applied"] = True
                        return meta
                    logger.warning("VPI_TAIL_PADDING_SKIPPED reason=ffmpeg_failed detail=%s", (result.stderr or "")[-200:])
                except Exception as exc:
                    logger.warning("VPI_TAIL_PADDING_SKIPPED reason=exception detail=%s", exc)
                meta["fade_out_needed"] = False
                meta["fade_out_reason"] = "tail_pad_render_failed"

        if not filters:
            return meta
        vf = ",".join(filters) + ",format=yuv420p"
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
            "-colorspace", "bt709", "-color_primaries", "bt709",
            "-color_trc", "bt709", "-color_range", "tv",
            "-movflags", "+faststart",
            str(output_path),
        ]
        if meta["fade_in_frames"]:
            logger.info("VPI_FADE_IN_APPLIED frames=%d reason=%s filter=%s", meta["fade_in_frames"], meta["fade_in_reason"], vf)
        if meta["fade_out_frames"]:
            logger.info("VPI_FADE_OUT_APPLIED frames=%d reason=%s filter=%s", meta["fade_out_frames"], meta["fade_out_reason"], vf)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode == 0 and output_path.exists():
                meta["rendered"] = True
                meta["output_path"] = str(output_path)
                meta["fade_in_applied"] = bool(meta["fade_in_frames"])
                meta["fade_out_applied"] = bool(meta["fade_out_frames"])
                return meta
            logger.warning("VPI_FADE_SKIPPED reason=ffmpeg_failed detail=%s", (result.stderr or "")[-200:])
        except Exception as exc:
            logger.warning("VPI_FADE_SKIPPED reason=exception detail=%s", exc)
        return meta
