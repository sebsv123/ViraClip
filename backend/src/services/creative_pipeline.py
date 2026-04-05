"""
Creative Pipeline — Phase 9 Creative Engine

The unified post-render enhancement layer.
Runs AFTER video_service.create_single_clip() produces the base 9:16 clip.

Pipeline:
  base clip → multimodal timeline → virality prediction → template selection
           → hook analysis → B-roll overlay → video effects (zoom punch + grade)
           → audio mastering (loudnorm + SFX) → QA + render manifest
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class CreativePipeline:
    """
    Orchestrates all Phase 9 creative modules on a single rendered clip.

    Design contract:
    - Never replaces the base clip path unless the enhanced version is valid.
    - All steps are individually guarded — one failure cannot break the rest.
    - Returns a metadata dict that is merged into the clip_info returned by
      the coordinator.
    """

    async def enhance(
        self,
        clip_path: Path,
        source_video: Path,
        segment: dict,
        words: "list[dict]",
        audio_features: dict,
        task_id: str,
        clip_index: int,
        platform: str = "tiktok",
    ) -> dict:
        """
        Apply the creative enhancement chain to a rendered base clip.

        Args:
            clip_path:      Path to the base 9:16 rendered clip.
            source_video:   Original source video (for audio peak analysis).
            segment:        Segment dict with start_time / end_time / transcript.
            words:          Word-level transcript [{start, end, word, confidence?}].
            audio_features: Dict from audio analysis (energy, rms_energy, etc.).
            task_id:        For logging and manifest naming.
            clip_index:     Clip number within the task.
            platform:       Target platform for template selection.

        Returns:
            Dict of creative metadata keys merged into the clip result.
        """
        start = float(segment.get("start_time") or segment.get("start", 0.0))
        end = float(segment.get("end_time") or segment.get("end", start + 60.0))
        transcript = segment.get("transcript", "")

        meta: dict = {
            "creative_enhanced": False,
            "timeline_events": 0,
            "viral_score": None,
            "hook_score": None,
            "pacing_score": None,
            "emotion_score": None,
            "improvements": [],
            "preset_used": None,
            "hook_reorder_applied": False,
            "broll_overlays": 0,
            "zoom_punch_applied": False,
            "color_grade_applied": False,
            "sfx_injected": 0,
            "loudnorm_applied": False,
            "qa_passed": None,
            "qa_issues": [],
        }

        # ── 1. Multimodal event timeline ──────────────────────────────────────
        timeline: list = []
        try:
            from .multimodal_detector import get_multimodal_detector
            timeline = await get_multimodal_detector().generate_timeline(
                video_path=source_video,
                segment_start=start,
                segment_end=end,
                words=words or [],
            )
            meta["timeline_events"] = len(timeline)
            logger.info("  [Creative] %d timeline events", len(timeline))
        except Exception as exc:
            logger.warning("  [Creative] Timeline failed: %s", exc)

        # ── 2. Virality prediction ────────────────────────────────────────────
        viral_pred = None
        try:
            from .virality_engine import get_virality_engine
            viral_pred = await get_virality_engine().predict(
                transcript=transcript,
                words=words or [],
                audio_features=audio_features or {},
                timeline_events=timeline,
            )
            meta.update({
                "viral_score": viral_pred.score,
                "hook_score": viral_pred.hook_score,
                "pacing_score": viral_pred.pacing_score,
                "emotion_score": viral_pred.emotion_score,
                "improvements": viral_pred.improvements,
            })
            logger.info(
                "  [Creative] Score=%.1f hook=%.0f pacing=%.0f emotion=%.0f",
                viral_pred.score, viral_pred.hook_score,
                viral_pred.pacing_score, viral_pred.emotion_score,
            )
        except Exception as exc:
            logger.warning("  [Creative] Virality prediction failed: %s", exc)

        # ── 3. Template selection ─────────────────────────────────────────────
        preset = None
        try:
            from .smart_templates import get_template_selector
            energy = float((audio_features or {}).get("energy", 0.5) or 0.5)
            preset = get_template_selector().select(
                platform=platform,
                transcript=transcript,
                virality_score=viral_pred.score if viral_pred else 50.0,
                audio_energy=energy,
            )
            meta["preset_used"] = preset.name
            logger.info("  [Creative] Template: %s", preset.name)
        except Exception as exc:
            logger.warning("  [Creative] Template selection failed: %s", exc)

        # ── 4. Hook analysis (informational — no reordering yet) ──────────────
        try:
            from .hook_engine import get_hook_engine
            hook_result = get_hook_engine().find_best_hook(
                words=words or [],
                segment_duration=end - start,
            )
            meta["hook_already_optimized"] = hook_result.already_optimized
            meta["hook_reorder_suggested"] = hook_result.reorder
            if hook_result.hook_text:
                meta["hook_text"] = hook_result.hook_text
            logger.info(
                "  [Creative] Hook: score=%.2f optimized=%s",
                hook_result.hook_score, hook_result.already_optimized,
            )
        except Exception as exc:
            logger.debug("  [Creative] Hook analysis failed: %s", exc)

        # ── 4.5 Hook-flash reorder ────────────────────────────────────────────
        try:
            _hook_reorder = meta.get("hook_reorder_suggested", False)
            _hook_start   = meta.get("hook_text") and next(
                (w["start"] for w in (words or [])
                 if meta.get("hook_text", "").lower() in w.get("word", "").lower()),
                None,
            )
            if _hook_reorder and _hook_start and float(_hook_start) > 3.0:
                from .hook_reorder import prepend_hook_flash
                _hook_end = _hook_start + 0.5
                reordered = clip_path.with_name(f"hook_{clip_path.name}")
                result = await prepend_hook_flash(
                    clip_path=clip_path,
                    hook_start=float(_hook_start),
                    hook_end=float(_hook_end),
                    output_path=reordered,
                )
                if result and reordered.exists() and reordered.stat().st_size > 0:
                    clip_path.unlink(missing_ok=True)
                    reordered.rename(clip_path)
                    meta["hook_reorder_applied"] = True
                    logger.info(
                        "  [Creative] Hook flash prepended (t=%.1fs)", _hook_start
                    )
                else:
                    reordered.unlink(missing_ok=True)
        except Exception as exc:
            logger.debug("  [Creative] Hook reorder failed: %s", exc)

        # ── 5. B-roll overlay ─────────────────────────────────────────────────
        broll_count = 0
        try:
            from .contextual_broll import get_contextual_broll
            from .video_effects import overlay_broll_clips
            broll_pairs = await get_contextual_broll().get_for_timeline(
                timeline, max_assets=3
            )
            if broll_pairs:
                brolled = clip_path.with_name(f"broll_{clip_path.name}")
                result = await overlay_broll_clips(clip_path, broll_pairs, brolled)
                if result and brolled.exists() and brolled.stat().st_size > 0:
                    clip_path.unlink(missing_ok=True)
                    brolled.rename(clip_path)
                    broll_count = len(broll_pairs)
                    logger.info("  [Creative] B-roll: %d overlays applied", broll_count)
                else:
                    brolled.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("  [Creative] B-roll overlay failed: %s", exc)

        meta["broll_overlays"] = broll_count

        # ── 6. Video effects (zoom punch + color grade from preset) ───────────
        try:
            if preset is not None:
                from .video_effects import apply_preset_effects
                peak_events = [e for e in timeline if e.type == "audio_peak"]
                effected = clip_path.with_name(f"vfx_{clip_path.name}")
                result = await apply_preset_effects(
                    clip_path, preset, peak_events, effected
                )
                if result and effected.exists() and effected.stat().st_size > 0:
                    clip_path.unlink(missing_ok=True)
                    effected.rename(clip_path)
                    meta["zoom_punch_applied"] = preset.zoom_punch_enabled and bool(peak_events)
                    meta["color_grade_applied"] = bool(preset.extra_vf_filters)
                    logger.info(
                        "  [Creative] VFX: zoom_punch=%s grade=%s",
                        meta["zoom_punch_applied"], meta["color_grade_applied"],
                    )
                else:
                    effected.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("  [Creative] Video effects failed: %s", exc)

        # ── 7. Audio mastering (loudnorm + SFX) ───────────────────────────────
        sfx_count = 0
        loudnorm_applied = False
        try:
            from .smart_audio import get_smart_audio, find_bgm_track
            mastered = clip_path.with_name(f"mastered_{clip_path.name}")
            bgm = find_bgm_track()
            result_path = await get_smart_audio().master(
                input_path=clip_path,
                output_path=mastered,
                timeline_events=timeline,
                bgm_path=bgm,
            )
            if result_path == mastered and mastered.exists() and mastered.stat().st_size > 0:
                clip_path.unlink(missing_ok=True)
                mastered.rename(clip_path)
                loudnorm_applied = True
                sfx_count = sum(1 for e in timeline if e.strength >= 0.6)
                logger.info(
                    "  [Creative] Audio mastered (sfx=%d bgm=%s)",
                    sfx_count, bgm.name if bgm else "none",
                )
            else:
                mastered.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("  [Creative] Audio mastering failed: %s", exc)

        meta["sfx_injected"] = sfx_count
        meta["loudnorm_applied"] = loudnorm_applied

        # ── 8. QA + render manifest ───────────────────────────────────────────
        try:
            from .learning_loop import get_learning_loop
            manifest = await get_learning_loop().post_render_analysis(
                clip_path=clip_path,
                source_path=source_video,
                task_id=task_id,
                clip_index=clip_index,
                virality_prediction=viral_pred,
                timeline_events=timeline,
                preset_name=preset.name if preset else "default",
                sfx_count=sfx_count,
                broll_count=broll_count,
                loudnorm_applied=loudnorm_applied,
            )
            meta["qa_passed"] = manifest.qa_passed
            meta["qa_issues"] = manifest.qa_issues
            meta["creative_enhanced"] = True
        except Exception as exc:
            logger.warning("  [Creative] QA failed: %s", exc)

        return meta


# ── Singleton ─────────────────────────────────────────────────────────────────

_pipeline: "CreativePipeline | None" = None


def get_creative_pipeline() -> CreativePipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = CreativePipeline()
    return _pipeline
