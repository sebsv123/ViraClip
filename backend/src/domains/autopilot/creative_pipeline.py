"""
Creative Pipeline — Phase 9 Creative Engine

The unified post-render enhancement layer.
Runs AFTER video_service.create_single_clip() produces the base 9:16 clip.

Pipeline:
  base clip → multimodal timeline → virality prediction → template selection
           → hook analysis → B-roll overlay → video effects (zoom punch + grade)
           → audio mastering (loudnorm + SFX) → QA + render manifest

Updated: 2026-04-23 - Added SAM2+LTX Background Composite integration
"""

import logging
import os
import traceback
from pathlib import Path


from ...domains.video.background_composite_service import background_composite_service

logger = logging.getLogger(__name__)

# Runtime diagnostics flag - set to True to see detailed error traces
DIAGNOSTIC_MODE = True

def _log_step_error(step_name: str, exc: Exception, critical: bool = False):
    """Log detailed error information for pipeline step failures."""
    level = logging.ERROR if critical else logging.WARNING
    logger.log(level, f"[Creative Pipeline] {step_name} FAILED: {type(exc).__name__}: {exc}")
    if DIAGNOSTIC_MODE:
        logger.log(level, f"[Creative Pipeline] {step_name} Full traceback:\n{''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))}")


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
        skip_stages: "set[str] | None" = None,
        task_config: "dict | None" = None,
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
        def _ts(val, default=0.0):
            if val is None:
                return default
            try:
                return float(val)
            except (ValueError, TypeError):
                try:
                    parts = str(val).split(":")
                    if len(parts) == 2:
                        return int(parts[0]) * 60 + float(parts[1])
                    if len(parts) == 3:
                        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                except Exception:
                    pass
                return default

        start = _ts(segment.get("start_time") or segment.get("start"), 0.0)
        end = _ts(segment.get("end_time") or segment.get("end"), start + 60.0)
        transcript = segment.get("text", segment.get("transcript", ""))

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

        # Step tracking for granular visibility
        steps_ok: list[str] = []
        steps_failed: list[str] = []

        # Suggestion Studio: caller may explicitly disable some stages.
        skip = {s.lower() for s in (skip_stages or set())}

        def _skip(stage: str) -> bool:
            if stage in skip:
                steps_failed.append(f"{stage}_skipped_by_user")
                logger.info("  [Creative] Stage '%s' skipped (user override)", stage)
                return True
            return False

        def _mark_ok(name: str, result=None) -> bool:
            """Mark step as OK only if result is not empty/None."""
            if result is None or result == [] or result == {} or result is False:
                steps_failed.append(f"{name}_empty")
                return False
            steps_ok.append(name)
            return True

        def _mark_fail(name: str):
            steps_failed.append(name)

        # ── 1. Multimodal event timeline ──────────────────────────────────────
        logger.info("  [Creative] Step 1/8: Multimodal timeline generation...")
        timeline: list = []
        try:
            logger.debug("  [Creative] Importing multimodal_detector...")
            from ...domains.detection.multimodal_detector import get_multimodal_detector
            logger.debug("  [Creative] multimodal_detector import OK")
            import asyncio as _asyncio
            try:
                timeline = await _asyncio.wait_for(
                    get_multimodal_detector().generate_timeline(
                        video_path=source_video,
                        segment_start=start,
                        segment_end=end,
                        words=words or [],
                    ),
                    timeout=20.0,
                )
            except _asyncio.TimeoutError:
                timeline = []
                _mark_fail("step_1_timeline_timeout")
                logger.warning("  [Creative] ⚠️ Step 1: multimodal_detector timeout (>20s) — skipping")

            if not isinstance(timeline, list):
                timeline = []

            if timeline:
                meta["timeline_events"] = len(timeline)
                steps_ok.append("step_1_timeline")
                logger.info("  [Creative] ✓ Step 1/8: %d timeline events", len(timeline))
            else:
                if "step_1_timeline_timeout" not in steps_failed:
                    _mark_fail("step_1_timeline_empty")
                logger.info("  [Creative] Step 1/8: No timeline events (empty result)")
        except ImportError as exc:
            _log_step_error("Step 1 (Timeline) - Import", exc, critical=True)
            _mark_fail("step_1_timeline")
        except Exception as exc:
            _log_step_error("Step 1 (Timeline)", exc)
            _mark_fail("step_1_timeline")

        # ── 2. Virality prediction ────────────────────────────────────────────
        logger.info("  [Creative] Step 2/8: Virality prediction...")
        viral_pred = None
        try:
            logger.debug("  [Creative] Importing virality_engine...")
            from ...domains.virality.virality_engine import get_virality_engine
            logger.debug("  [Creative] virality_engine import OK")
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
                "  [Creative] ✓ Step 2/8: Score=%.1f hook=%.0f pacing=%.0f emotion=%.0f",
                viral_pred.score, viral_pred.hook_score,
                viral_pred.pacing_score, viral_pred.emotion_score,
            )
            if viral_pred and viral_pred.score is not None:
                steps_ok.append("step_2_virality")
            else:
                _mark_fail("step_2_virality_empty")
        except ImportError as exc:
            _log_step_error("Step 2 (Virality) - Import", exc, critical=True)
            _mark_fail("step_2_virality")
        except Exception as exc:
            _log_step_error("Step 2 (Virality)", exc)
            _mark_fail("step_2_virality")

        # ── 3. Template selection ─────────────────────────────────────────────
        logger.info("  [Creative] Step 3/8: Template selection...")
        preset = None
        try:
            logger.debug("  [Creative] Importing smart_templates...")
            from ...core.smart_templates import get_template_selector
            logger.debug("  [Creative] smart_templates import OK")
            energy = float((audio_features or {}).get("energy", 0.5) or 0.5)
            preset = get_template_selector().select(
                platform=platform,
                transcript=transcript,
                virality_score=viral_pred.score if viral_pred else 50.0,
                audio_energy=energy,
            )
            meta["preset_used"] = preset.name
            logger.info("  [Creative] ✓ Step 3/8: Template: %s", preset.name)
            steps_ok.append("step_3_template")
        except ImportError as exc:
            _log_step_error("Step 3 (Template) - Import", exc, critical=True)
            _mark_fail("step_3_template")
        except Exception as exc:
            _log_step_error("Step 3 (Template)", exc)
            _mark_fail("step_3_template")

        # ── 4. Hook analysis (informational — no reordering yet) ──────────────
        logger.info("  [Creative] Step 4/8: Hook analysis...")
        try:
            logger.debug("  [Creative] Importing hook_engine...")
            from ...domains.virality.hook_engine import get_hook_engine
            logger.debug("  [Creative] hook_engine import OK")
            hook_result = get_hook_engine().find_best_hook(
                words=words or [],
                segment_duration=end - start,
            )
            meta["hook_already_optimized"] = hook_result.already_optimized
            meta["hook_reorder_suggested"] = hook_result.reorder
            if hook_result.hook_text:
                meta["hook_text"] = hook_result.hook_text
            logger.info(
                "  [Creative] ✓ Step 4/8: Hook score=%.2f optimized=%s",
                hook_result.hook_score, hook_result.already_optimized,
            )
            steps_ok.append("step_4_hook")
        except ImportError as exc:
            _log_step_error("Step 4 (Hook) - Import", exc)
            _mark_fail("step_4_hook")
        except Exception as exc:
            _log_step_error("Step 4 (Hook)", exc)
            _mark_fail("step_4_hook")

        # ── 4.5 Hook-flash reorder ────────────────────────────────────────────
        reordered = None
        if _skip("hook_reorder"):
            _hook_reorder = False
        else:
          try:
            _hook_reorder = meta.get("hook_reorder_suggested", False)
            _hook_start   = meta.get("hook_text") and next(
                (w["start"] for w in (words or [])
                 if meta.get("hook_text", "").lower() in w.get("word", "").lower()),
                None,
            )
            if _hook_reorder and _hook_start and float(_hook_start) > 3.0:
                from ...domains.virality.hook_reorder import prepend_hook_flash
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
            logger.warning("  [Creative] Hook reorder skipped: %s", exc)

        # ── Background Composite (SAM2 + LTX) ────────────────────────────
        _composite_enabled = os.getenv("BACKGROUND_COMPOSITE_ENABLED", "false").lower() == "true"
        _composite_result = None

        if _composite_enabled:
            try:
                _viral_score = segment.get("viral_score",
                               segment.get("score",
                               segment.get("virality_score", 5.0)))
                _duration = float(segment.get("duration", end - start))
                _prompt = (segment.get("keywords", ["cinematic background"])
                           if isinstance(segment.get("keywords"), list)
                           else str(segment.get("keywords", "cinematic background")))

                _composite_result = await background_composite_service.process(
                    clip_path=str(clip_path),
                    task_id=task_id,
                    viral_score=float(_viral_score),
                    duration=_duration,
                    broll_prompt=_prompt
                )
            except Exception as _e:
                logger.warning(f"Background composite error, continuing: {_e}")
                _composite_result = None

        if _composite_result and _composite_result.get("mode_used") == "A":
            # Mode A: Replace clip with composite result
            composite_path = Path(_composite_result["output_path"])
            if composite_path.exists():
                clip_path.unlink(missing_ok=True)
                composite_path.rename(clip_path)
                meta["background_composite_applied"] = True
                meta["composite_mode"] = "A"
                logger.info(f"✅ Composite Mode A: {task_id}")
            # SKIP b-roll logic completely
        elif _composite_result and _composite_result.get("mode_used") == "C":
            meta["background_composite_applied"] = False
            meta["composite_mode"] = "C"
            logger.info(f"🎯 Clean clip, no B-roll: {task_id}")
            # SKIP b-roll logic completely
        else:
            # mode_used == "B" o composite deshabilitado → ejecutar B-roll normal
            pass  # continúa con la lógica de B-roll existente
        # ── Fin Background Composite ──────────────────────────────────────

        # ── 5. B-roll overlay ─────────────────────────────────────────────────
        logger.info("  [Creative] Step 5/8: B-roll overlay...")
        broll_count = 0

        # Solo ejecutar B-roll si no se aplicó composite Mode A o C
        _skip_broll = (_composite_result and _composite_result.get("mode_used") in ("A", "C"))
        if _skip("broll"):
            _skip_broll = True

        if not _skip_broll:
            try:
                logger.debug("  [Creative] Importing contextual_broll & video_effects...")
                from ...domains.broll.contextual_broll import get_contextual_broll
                from ...domains.video.video_effects import overlay_broll_clips
                from ...domains.broll.broll_compositor import compose_overlay_items
                logger.debug("  [Creative] B-roll imports OK")

                # SUGGESTION STUDIO: Use editable broll_items from task_config if provided
                broll_items = task_config.get("broll_items") if task_config else None
                # Fallback: try to get from segment metadata if task_config not provided
                if not broll_items and segment.get("broll_items"):
                    broll_items = segment.get("broll_items")
                if broll_items and isinstance(broll_items, list) and len(broll_items) > 0:
                    logger.info("  [Creative] Using %d editable B-roll items from Suggestion Studio", len(broll_items))
                    try:
                        _broll_success = await compose_overlay_items(
                            main_path=clip_path,
                            items=broll_items,
                            output_path=Path(str(clip_path).replace(".mp4", "_broll.mp4")),
                            fade=0.5,
                        )
                        if _broll_success:
                            broll_count = len(broll_items)
                            meta["broll_items_used"] = broll_items
                            # Replace clip with broll version
                            _broll_temp = Path(str(clip_path).replace(".mp4", "_broll.mp4"))
                            if _broll_temp.exists():
                                clip_path.unlink(missing_ok=True)
                                _broll_temp.rename(clip_path)
                                logger.info("  [Creative] ✓ Applied %d editable B-roll overlays", broll_count)
                                steps_ok.append("step_5_broll_editable")
                    except Exception as _editable_e:
                        logger.warning("  [Creative] Editable B-roll failed, falling back to auto: %s", _editable_e)
                        broll_items = None  # Fall through to auto generation

                # Priority 0: SemanticEditPlan — word-level precise B-roll cues
                # (populated by _clip_renderer.py before calling creative_pipeline)
                _sem_plan   = segment.get("_semantic_plan") if segment else None
                _render_plan = segment.get("_render_plan")  if segment else None
                broll_pairs = []
                if _sem_plan and getattr(_sem_plan, "broll_cues", None):
                    try:
                        from ...domains.detection.multimodal_detector import TimelineEvent
                        # Director section filter: drop cues that fall in
                        # sections where broll_allowed=False (hook + CTA)
                        _filtered_cues = list(_sem_plan.broll_cues)
                        if _render_plan:
                            _filtered_cues = [
                                c for c in _filtered_cues
                                if _render_plan.is_broll_allowed_at(c.timestamp)
                            ]
                            if len(_filtered_cues) < len(_sem_plan.broll_cues):
                                logger.info(
                                    "  [Creative] Director dropped %d B-roll cues "
                                    "(hook/CTA sections)",
                                    len(_sem_plan.broll_cues) - len(_filtered_cues),
                                )
                        for cue in _filtered_cues:
                            asset = await get_contextual_broll().get_for_keyword(
                                cue.keyword, duration=cue.duration
                            )
                            if asset:
                                evt = TimelineEvent(
                                    t=cue.timestamp,
                                    type="keyword",
                                    strength=cue.confidence,
                                    duration=cue.duration,
                                    payload={"word": cue.keyword, "category": "semantic_plan"},
                                )
                                broll_pairs.append((evt, asset))
                        if broll_pairs:
                            logger.info(
                                "  [Creative] B-roll from SemanticEditPlan: %d cues [%s]",
                                len(broll_pairs),
                                ", ".join(
                                    f"{c.timestamp:.1f}s:{c.keyword}"
                                    for c in _sem_plan.broll_cues[:3]
                                ),
                            )
                    except Exception as _sp_e:
                        logger.warning("  [Creative] SemanticPlan B-roll skipped: %s", _sp_e)
                        broll_pairs = []

                # Priority 1: timeline-based (multimodal detector hook/impact events)
                if not broll_pairs:
                    broll_pairs = await get_contextual_broll().get_for_timeline(
                        timeline, max_assets=3
                    )

                # Fallback: if timeline had no hook/impact keyword hits, use LLM to extract
                # visual keywords from the actual transcript ("what the speaker says")
                if not broll_pairs and transcript:
                    try:
                        from ...domains.broll.broll_service import BrollService
                        from ...domains.detection.multimodal_detector import TimelineEvent
                        llm_kws = await BrollService().extract_keywords(transcript)
                        clip_dur = max(1.0, end - start)
                        llm_pairs = []
                        for i, kw in enumerate(llm_kws[:2]):
                            asset = await get_contextual_broll().get_for_keyword(kw, duration=3.0)
                            if asset:
                                t_ins = max(2.0, min(4.0 + i * 7.0, clip_dur - 4.0))
                                evt = TimelineEvent(
                                    t=t_ins, type="keyword", strength=0.7,
                                    duration=3.0, payload={"word": kw, "category": "broll_llm"},
                                )
                                llm_pairs.append((evt, asset))
                        if llm_pairs:
                            broll_pairs = llm_pairs
                            logger.info(
                                "  [Creative] B-roll LLM fallback: keywords=%s", llm_kws
                            )
                    except Exception as _fb:
                        logger.warning("  [Creative] B-roll LLM fallback skipped: %s", _fb)

                brolled = None
                if broll_pairs:
                    brolled = clip_path.with_name(f"broll_{clip_path.name}")
                    result = await overlay_broll_clips(clip_path, broll_pairs, brolled)
                    if result and brolled.exists() and brolled.stat().st_size > 0:
                        clip_path.unlink(missing_ok=True)
                        brolled.rename(clip_path)
                        broll_count = len(broll_pairs)
                        logger.info("  [Creative] ✓ Step 5/8: B-roll overlay: %s", brolled.name)
                        steps_ok.append("step_5_broll")
                    else:
                        brolled.unlink(missing_ok=True)
                        logger.warning("  [Creative] B-roll render failed, using base clip")
                        _mark_fail("step_5_broll_render_failed")
                else:
                    _mark_fail("step_5_broll_empty")
            except ImportError as exc:
                _log_step_error("Step 5 (B-roll) - Import", exc)
                _mark_fail("step_5_broll")
            except Exception as exc:
                _log_step_error("Step 5 (B-roll)", exc)
                _mark_fail("step_5_broll")
        else:
            logger.info("  [Creative] Step 5/8: B-roll skipped (composite Mode A/C applied)")
            if _composite_result and _composite_result.get("mode_used") == "A":
                steps_ok.append("step_5_composite_a")
            elif _composite_result and _composite_result.get("mode_used") == "C":
                steps_ok.append("step_5_clean_clip")

        meta["broll_overlays"] = broll_count

        # ── 5.5. Contextual overlays (viral feature: full-screen with corner bubble) ─
        logger.info("  [Creative] Step 5.5/8: Contextual overlays...")
        contextual_overlays = 0
        overlayed = None
        overlay_result = None
        _do_overlays = not _skip("contextual_overlay")
        try:
         if _do_overlays:
            logger.debug("  [Creative] Importing contextual_overlay_engine...")
            from ...domains.broll.contextual_overlay_engine import get_contextual_overlay_engine
            logger.debug("  [Creative] contextual_overlay_engine import OK")
            
            overlay_engine = get_contextual_overlay_engine()
            overlayed = clip_path.with_name(f"overlayed_{clip_path.name}")
            
            overlay_result = await overlay_engine.apply_overlays(
                video_path=clip_path,
                output_path=overlayed,
                transcript=transcript,
                word_timings=words or [],
                audio_features=audio_features or {},
                virality_score=meta.get("viral_score", 50.0),
                overlay_frequency="adaptive"
            )
            
            if overlay_result.success and overlayed.exists() and overlayed.stat().st_size > 0:
                clip_path.unlink(missing_ok=True)
                overlayed.rename(clip_path)
                contextual_overlays = overlay_result.overlays_applied
                logger.info(
                    "  [Creative] ✓ Step 5.5/8: Contextual overlays: %d applied (%d keywords detected)",
                    contextual_overlays, overlay_result.keywords_detected
                )
            else:
                overlayed.unlink(missing_ok=True)
                logger.warning("  [Creative] Contextual overlays skipped: %s", overlay_result.error)
            if overlay_result.success:
                steps_ok.append("step_5_5_overlays")
            else:
                _mark_fail("step_5_5_overlays_empty")
         else:
            pass
        except ImportError as exc:
            _log_step_error("Step 5.5 (Contextual Overlays) - Import", exc)
            _mark_fail("step_5_5_overlays")
        except Exception as exc:
            _log_step_error("Step 5.5 (Contextual Overlays)", exc)
            _mark_fail("step_5_5_overlays")
        
        meta["contextual_overlays"] = contextual_overlays

        # ── 6. Video effects (zoom punch + color grade from preset) ───────────
        logger.info("  [Creative] Step 6/8: Video effects (zoom + grade)...")
        effected = None
        _skip_vfx = _skip("vfx")
        try:
            if preset is None:
                logger.warning("  [Creative] No preset selected, using default fallback")
                from ...core.smart_templates import Preset
                preset = Preset(
                    name="default_fallback",
                    zoom_punch_enabled=True,
                    zoom_punch_zoom=1.15,
                    zoom_punch_duration=0.25,
                    extra_vf_filters=["eq=contrast=1.08:saturation=1.15:brightness=0.01"],
                    caption_style="standard",
                    beat_sync=False,
                )
                meta["preset_used"] = "default_fallback"
        except Exception as _fb:
            logger.warning("  [Creative] Fallback preset failed: %s", _fb)
        try:
            if preset is not None and not _skip_vfx:
                logger.debug("  [Creative] Importing video_effects for apply_preset_effects...")
                from ...domains.video.video_effects import apply_preset_effects
                logger.debug("  [Creative] video_effects import OK")
                peak_events = [e for e in timeline if e.type == "audio_peak"]
                effected = clip_path.with_name(f"vfx_{clip_path.name}")
                result = await apply_preset_effects(
                    clip_path, preset, peak_events, effected
                )
                if result and effected.exists() and effected.stat().st_size > 0:
                    clip_path.unlink(missing_ok=True)
                    effected.rename(clip_path)
                    meta["zoom_punch_applied"] = preset.zoom_punch_enabled and bool(peak_events)
                    meta["zoom_punch_zoom"] = preset.zoom_punch_zoom if preset.zoom_punch_enabled else 1.0
                    meta["zoom_punch_duration"] = preset.zoom_punch_duration if preset.zoom_punch_enabled else 0.0
                    meta["color_grade_applied"] = bool(preset.extra_vf_filters)
                    meta["extra_vf_filters"] = preset.extra_vf_filters if preset.extra_vf_filters else []
                    meta["preset_used"] = preset.name
                    logger.info(
                        "  [Creative] ✓ Step 6/8: VFX: zoom_punch=%s (%.2fx, %.2fs) grade=%s preset=%s",
                        meta["zoom_punch_applied"], meta.get("zoom_punch_zoom", 1.0), 
                        meta.get("zoom_punch_duration", 0.0),
                        meta["color_grade_applied"], preset.name,
                    )
                else:
                    effected.unlink(missing_ok=True)
            else:
                logger.info("  [Creative] Step 6/8: Skipped (no preset)")
                _mark_fail("step_6_vfx_no_preset")
        except ImportError as exc:
            _log_step_error("Step 6 (VFX) - Import", exc, critical=True)
            _mark_fail("step_6_vfx")
        except Exception as exc:
            _log_step_error("Step 6 (VFX)", exc)
            _mark_fail("step_6_vfx")

        # ── 6.5. Speed control (playback speed / dramatic slow-mo) ────────────
        logger.info("  [Creative] Step 6.5/8: Speed control...")
        speed_applied = False
        speed_output = None
        try:
            if _skip("speed_control"):
                playback_speed, dramatic_slowmo = 1.0, False
            else:
                playback_speed = segment.get("playback_speed", 1.0)
                dramatic_slowmo = segment.get("dramatic_slowmo", False)
            
            if playback_speed != 1.0 or dramatic_slowmo:
                from ...domains.video.speed_control_service import get_speed_control_service
                
                speed_svc = get_speed_control_service()
                speed_output = clip_path.with_name(f"speed_{clip_path.name}")
                
                # Get hook info for dramatic slow-mo
                hook_start = meta.get("hook_start", 0.0)
                hook_end = meta.get("hook_end", 3.0)
                
                success = await speed_svc.apply_speed_control(
                    clip_path=clip_path,
                    output_path=speed_output,
                    playback_speed=playback_speed,
                    dramatic_slowmo=dramatic_slowmo,
                    hook_start=hook_start,
                    hook_end=hook_end
                )
                
                if success and speed_output.exists() and speed_output.stat().st_size > 0:
                    clip_path.unlink(missing_ok=True)
                    speed_output.rename(clip_path)
                    speed_applied = True
                    logger.info(
                        "  [Creative] ✓ Step 6.5/8: Speed control (speed=%.2fx slowmo=%s)",
                        playback_speed, dramatic_slowmo
                    )
                    steps_ok.append("step_6_5_speed")
                else:
                    speed_output.unlink(missing_ok=True)
            else:
                logger.debug("  [Creative] Step 6.5/8: Skipped (no speed change)")
        except ImportError as exc:
            _log_step_error("Step 6.5 (Speed) - Import", exc)
            _mark_fail("step_6_5_speed")
        except Exception as exc:
            _log_step_error("Step 6.5 (Speed Control)", exc)
            _mark_fail("step_6_5_speed")
        
        meta["speed_control_applied"] = speed_applied

        # ── 6.5. SFX Orchestrator (Freesound + LLM) — before audio mastering ──
        if os.getenv("SFX_ENABLED", "false").lower() == "true":
            try:
                from ...domains.sfx.sfx_orchestrator import SFXOrchestrator
                sfx = SFXOrchestrator()
                sfx_output = clip_path.with_name(f"sfx_{clip_path.name}")
                jump_cut_times = [
                    float(e.get("time", e.get("timestamp", 0)))
                    for e in (timeline or [])
                    if isinstance(e, dict) and e.get("type") in ("jump_cut", "cut")
                ]
                result = await sfx.process_clip(
                    input_path=str(clip_path),
                    output_path=str(sfx_output),
                    transcript_segments=[{"text": transcript or ""}],
                    jump_cuts=jump_cut_times,
                    clip_metadata={
                        "topic": meta.get("niche", meta.get("topic", "")),
                        "mood": meta.get("mood", "neutral"),
                        "energy": meta.get("energy_level", 0.5),
                        "duration": meta.get("duration", end - start or 60),
                    },
                )
                if result and sfx_output.exists() and sfx_output.stat().st_size > 0:
                    clip_path.unlink(missing_ok=True)
                    sfx_output.rename(clip_path)
                    logger.info("  [Creative] ✓ Step 6.5/8: SFX applied via Freesound+LLM")
                else:
                    logger.info("  [Creative] Step 6.5/8: SFX skipped (no assets found)")
            except Exception as e:
                logger.warning(f"  [Creative] Step 6.5/8: SFX failed — continuing without: {e}")

        # ── 7. Audio mastering (loudnorm + SFX + ducking) ─────────────────────
        logger.info("  [Creative] Step 7/8: Audio mastering (loudnorm + SFX + ducking)...")
        sfx_count = 0
        loudnorm_applied = False
        ducking_applied = False
        mastered = None
        ducked = None
        _skip_audio_master = _skip("audio_master")

        class _AudioMasterSkipped(Exception):
            pass

        try:
            if _skip_audio_master:
                raise _AudioMasterSkipped()
            logger.debug("  [Creative] Importing smart_audio...")
            from ...domains.audio.smart_audio import get_smart_audio, find_bgm_track
            logger.debug("  [Creative] smart_audio import OK")
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
                
                # Apply audio ducking if enabled and we have word timings
                if words:
                    try:
                        from ...domains.audio.audio_ducking_service import get_audio_ducking_service
                        ducked = clip_path.with_name(f"ducked_{clip_path.name}")
                        duck_result = await get_audio_ducking_service().apply_ducking(
                            video_path=clip_path,
                            output_path=ducked,
                            word_timings=words
                        )
                        if duck_result.success and ducked.exists() and ducked.stat().st_size > 0:
                            clip_path.unlink(missing_ok=True)
                            ducked.rename(clip_path)
                            ducking_applied = True
                            logger.info("  [Creative] ✓ Audio ducking applied (%d voice segments)", duck_result.ducked_segments)
                        else:
                            ducked.unlink(missing_ok=True)
                    except Exception as duck_err:
                        logger.warning("  [Creative] Audio ducking skipped: %s", duck_err)
                
                logger.info(
                    "  [Creative] ✓ Step 7/8: Audio mastered (sfx=%d bgm=%s ducking=%s)",
                    sfx_count, bgm.name if bgm else "none", ducking_applied,
                )
            else:
                mastered.unlink(missing_ok=True)
            if loudnorm_applied:
                steps_ok.append("step_7_audio")
            else:
                _mark_fail("step_7_audio_empty")
        except _AudioMasterSkipped:
            logger.info("  [Creative] Step 7/8: Audio mastering skipped (user override)")
            steps_ok.append("step_7_audio_skipped")
        except ImportError as exc:
            _log_step_error("Step 7 (Audio) - Import", exc, critical=True)
            _mark_fail("step_7_audio")
        except Exception as exc:
            _log_step_error("Step 7 (Audio)", exc)
            _mark_fail("step_7_audio")

        meta["sfx_injected"] = sfx_count
        meta["loudnorm_applied"] = loudnorm_applied
        meta["audio_ducking_applied"] = ducking_applied

        # ── 8. QA + render manifest ───────────────────────────────────────────
        logger.info("  [Creative] Step 8/8: QA + render manifest...")
        try:
            logger.debug("  [Creative] Importing learning_loop...")
            from ...domains.feedback.learning_loop import get_learning_loop
            logger.debug("  [Creative] learning_loop import OK")
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
            if manifest.qa_passed:
                steps_ok.append("step_8_qa")
            else:
                _mark_fail("step_8_qa_failed")
            logger.info("  [Creative] ✓ Step 8/8: QA complete (passed=%s)", manifest.qa_passed)
        except ImportError as exc:
            _log_step_error("Step 8 (QA) - Import", exc)
            _mark_fail("step_8_qa")
        except Exception as exc:
            _log_step_error("Step 8 (QA)", exc)
            _mark_fail("step_8_qa")

        # Calculate creative_enhanced based on actual metadata flags (at least 2 must be true)
        _ok = sum([
            meta.get("timeline_events", 0) > 0,
            meta.get("viral_score") is not None,
            meta.get("preset_used") is not None,
            meta.get("broll_overlays", 0) > 0,
            meta.get("loudnorm_applied", False),
            meta.get("color_grade_applied", False),
            meta.get("hook_visual_applied", False),
            meta.get("cinematic_intro_applied", False),
        ])
        if _ok >= 2:
            meta["creative_enhanced"] = True

        meta["creative_steps_ok"]     = steps_ok
        meta["creative_steps_failed"] = steps_failed
        meta["creative_steps_total"]  = len(steps_ok) + len(steps_failed)

        if steps_failed:
            logger.warning(
                "  [Creative] ⚠️ Pipeline partial — ok=%s | failed=%s",
                steps_ok, steps_failed,
            )
        else:
            logger.info(
                "  [Creative] ✅ Pipeline complete — all %d steps ok: %s",
                len(steps_ok), steps_ok,
            )

        if not meta["creative_enhanced"]:
            logger.error(
                "  [Creative] ❌ creative_enhanced=False — failed steps: %s",
                set(steps_failed),
            )

        return meta


# ── Singleton ─────────────────────────────────────────────────────────────────

_pipeline: "CreativePipeline | None" = None


def get_creative_pipeline() -> CreativePipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = CreativePipeline()
    return _pipeline
