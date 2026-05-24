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

def _get_duration(path) -> float:
    """Return video duration in seconds via ffprobe, or 0 on failure."""
    import subprocess, json
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(path)],
            capture_output=True, text=True, timeout=10
        )
        return float(json.loads(r.stdout).get("format", {}).get("duration", 0))
    except Exception:
        return 0.0

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

    async def _load_creative_hints(self) -> dict:
        """
        Load active CreativeHints from the optimization loop and return
        a dict of adjusted parameters for the pipeline.

        Returns:
            Dict with keys like:
              - preferred_hook_type: str | None
              - preferred_caption_style: str | None
              - broll_boost: float (0.0 = no boost, 1.0 = strong preference)
              - target_duration_s: float | None
              - zoom_punch_preference: bool | None
              - music_preference: bool | None
              - sfx_preference: str | None ("no_sfx", "1-3_sfx", "4+_sfx")
              - hints_applied: list[str]  (human-readable descriptions)
        """
        result: dict = {
            "preferred_hook_type": None,
            "preferred_caption_style": None,
            "broll_boost": 0.0,
            "target_duration_s": None,
            "zoom_punch_preference": None,
            "music_preference": None,
            "sfx_preference": None,
            "hints_applied": [],
        }

        try:
            from ...config import get_config
            cfg = get_config()
            if not cfg.optimization_loop_enabled:
                return result

            from ...services.clip_features import ClipFeaturesRepository
            from sqlalchemy.ext.asyncio import AsyncSession
            from ...main import get_db  # lazy import to avoid circular deps

            # Get a DB session
            db_gen = get_db()
            db: AsyncSession = await db_gen.__anext__()

            try:
                workspace_id = cfg.optimization_loop_workspace_id
                hints = await ClipFeaturesRepository.get_active_hints(db, workspace_id)

                if not hints:
                    logger.info("  [Creative] No active CreativeHints for workspace '%s'", workspace_id)
                    return result

                logger.info(
                    "  [Creative] Loaded %d active CreativeHints for workspace '%s'",
                    len(hints), workspace_id,
                )

                for h in hints:
                    if h.hint_type == "hook" and h.delta > 0:
                        # Extract hook type from pattern: "Hook type 'question' outperforms average"
                        import re
                        m = re.search(r"'([^']+)'", h.pattern)
                        if m:
                            result["preferred_hook_type"] = m.group(1)
                            result["hints_applied"].append(
                                f"hook_type={m.group(1)} (+{h.delta*100:.0f}% {h.metric})"
                            )

                    elif h.hint_type == "caption_style" and h.delta > 0:
                        m = re.search(r"'([^']+)'", h.pattern)
                        if m:
                            result["preferred_caption_style"] = m.group(1)
                            result["hints_applied"].append(
                                f"caption_style={m.group(1)} (+{h.delta*100:.0f}% {h.metric})"
                            )

                    elif h.hint_type == "broll" and h.delta > 0:
                        # B-roll boost: scale delta to 0.0–1.0 range
                        result["broll_boost"] = min(1.0, max(0.0, h.delta * 3))
                        result["hints_applied"].append(
                            f"broll_boost={result['broll_boost']:.2f} (+{h.delta*100:.0f}% {h.metric})"
                        )

                    elif h.hint_type == "duration" and h.delta > 0:
                        # Extract target duration from bucket label
                        m = re.search(r"'([^']+)'", h.pattern)
                        if m:
                            bucket = m.group(1)
                            if bucket == "0-15s":
                                result["target_duration_s"] = 12.0
                            elif bucket == "15-30s":
                                result["target_duration_s"] = 22.0
                            elif bucket == "30-60s":
                                result["target_duration_s"] = 45.0
                            elif bucket == "60s+":
                                result["target_duration_s"] = 75.0
                            result["hints_applied"].append(
                                f"target_duration={result['target_duration_s']:.0f}s (+{h.delta*100:.0f}% {h.metric})"
                            )

                    elif h.hint_type == "pacing" and h.delta > 0:
                        if "zoom" in h.pattern.lower():
                            result["zoom_punch_preference"] = True
                            result["hints_applied"].append(
                                f"zoom_punch=enabled (+{h.delta*100:.0f}% {h.metric})"
                            )

                    elif h.hint_type == "audio" and h.delta > 0:
                        if "music" in h.pattern.lower():
                            result["music_preference"] = True
                            result["hints_applied"].append(
                                f"music=enabled (+{h.delta*100:.0f}% {h.metric})"
                            )
                        elif "sfx" in h.pattern.lower() or "SFX" in h.pattern:
                            m = re.search(r"'([^']+)'", h.pattern)
                            if m:
                                result["sfx_preference"] = m.group(1)
                                result["hints_applied"].append(
                                    f"sfx={m.group(1)} (+{h.delta*100:.0f}% {h.metric})"
                                )

                logger.info(
                    "  [Creative] Applied %d CreativeHints: %s",
                    len(result["hints_applied"]), result["hints_applied"],
                )

            finally:
                await db.close()

        except ImportError:
            logger.debug("  [Creative] CreativeHints not available (import error)")
        except Exception as exc:
            logger.warning("  [Creative] Failed to load CreativeHints: %s", exc)

        return result

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
        if not transcript and words:
            transcript = " ".join(w.get("word", "") for w in words if isinstance(w, dict))
            logger.debug("  [Creative] Reconstructed transcript from %d word timings: %s", len(words), transcript[:120])

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

        # ── 1.5. Smart Auto Editor (viral text pops + jump cuts) ──────────────
        _sae_enabled = os.getenv("SMART_AUTO_EDITOR_ENABLED", "false").lower() == "true"
        if _sae_enabled and not _skip("smart_auto_editor"):
            logger.info("  [Creative] Step 1.5/8: Smart Auto Editor...")
            try:
                from ...services.smart_auto_editor import SmartAutoEditor, ViralEditRules
                sae = SmartAutoEditor()
                rules = ViralEditRules()
                # Run analysis
                decisions = await sae.analyze_and_edit(
                    clip_path=clip_path,
                    transcript=transcript,
                    words=words or [],
                    audio_features=audio_features or {},
                    rules=rules,
                )
                if decisions and decisions.get("text_pops"):
                    # Apply text pop overlays
                    text_pops = decisions["text_pops"]
                    sae_output = clip_path.with_name(f"sae_{clip_path.name}")
                    ok = await sae.apply_text_pops(
                        clip_path=clip_path,
                        output_path=sae_output,
                        text_pops=text_pops,
                    )
                    if ok and sae_output.exists() and sae_output.stat().st_size > 0:
                        clip_path.unlink(missing_ok=True)
                        sae_output.rename(clip_path)
                        logger.info(f"[DURATION] post_smart_auto_editor: {_get_duration(clip_path):.2f}s")
                        meta["sae_text_pops"] = len(text_pops)
                        meta["sae_jump_cuts"] = len(decisions.get("jump_cuts", []))
                        meta["sae_speed_ramps"] = len(decisions.get("speed_ramps", []))
                        logger.info(
                            "  [Creative] ✓ Step 1.5/8: SAE applied (%d text pops, %d jump cuts, %d speed ramps)",
                            meta["sae_text_pops"], meta["sae_jump_cuts"], meta["sae_speed_ramps"],
                        )
                        steps_ok.append("step_1_5_smart_auto_editor")
                    else:
                        sae_output.unlink(missing_ok=True)
                        _mark_fail("step_1_5_sae_render_failed")
                else:
                    logger.info("  [Creative] Step 1.5/8: No SAE decisions generated")
                    _mark_fail("step_1_5_sae_empty")
            except ImportError as exc:
                _log_step_error("Step 1.5 (Smart Auto Editor) - Import", exc)
                _mark_fail("step_1_5_sae")
            except Exception as exc:
                _log_step_error("Step 1.5 (Smart Auto Editor)", exc)
                _mark_fail("step_1_5_sae")
        else:
            if _sae_enabled:
                logger.info("  [Creative] Step 1.5/8: Smart Auto Editor skipped (user override)")
            else:
                logger.debug("  [Creative] Step 1.5/8: Smart Auto Editor disabled (SMART_AUTO_EDITOR_ENABLED=false)")

        # ── 1.75. SFX Orchestrator (after jump cuts, BEFORE BGM/audio mastering) ──
        _sfx_profile = os.getenv("SFX_PROFILE", "subtle").lower()
        if _sfx_profile != "none":
            try:
                from ...domains.sfx.sfx_orchestrator import SFXOrchestrator
                sfx = SFXOrchestrator()
                sfx_output = clip_path.with_name(f"sfx_{clip_path.name}")
                jump_cut_times = [
                    float(e.get("time", e.get("timestamp", 0)))
                    for e in (timeline or [])
                    if isinstance(e, dict) and e.get("type") in ("jump_cut", "cut")
                ]
                # Mood/energy from virality prediction or audio features
                _mood = meta.get("mood", "neutral")
                _energy = meta.get("energy_level", audio_features.get("energy", 0.5) if audio_features else 0.5)
                result = await sfx.process_clip(
                    input_path=str(clip_path),
                    output_path=str(sfx_output),
                    transcript_segments=[{"text": transcript or ""}],
                    jump_cuts=jump_cut_times,
                    clip_metadata={
                        "topic": meta.get("niche", meta.get("topic", "")),
                        "mood": _mood,
                        "energy": _energy,
                        "duration": meta.get("duration", end - start or 60),
                    },
                )
                if result and sfx_output.exists() and sfx_output.stat().st_size > 0:
                    clip_path.unlink(missing_ok=True)
                    sfx_output.rename(clip_path)
                    logger.info(f"[DURATION] post_sfx: {_get_duration(clip_path):.2f}s")
                    meta["sfx_injected"] = len(jump_cut_times)
                    logger.info("  [Creative] ✓ Step 1.75/8: SFX applied (profile=%s, %d SFX)", _sfx_profile, len(jump_cut_times))
                    steps_ok.append("step_1_75_sfx")
                else:
                    logger.info("  [Creative] Step 1.75/8: SFX skipped (no assets found)")
                    _mark_fail("step_1_75_sfx_empty")
            except Exception as e:
                logger.warning(f"  [Creative] Step 1.75/8: SFX failed — continuing without: {e}")
                _mark_fail("step_1_75_sfx")

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

        # ── 4.5 Shorts Highlight Engine (LLM-based highlight detection) ──────
        logger.info("  [Creative] Step 4.5/8: Shorts Highlight Engine...")
        shorts_highlights = []
        if _skip("shorts_highlight"):
            logger.info("  [Creative] Step 4.5/8: Skipped (user override)")
        else:
            try:
                from ...config import get_config
                cfg = get_config()
                if cfg.shorts_engine_enabled:
                    from ...services.shorts_highlight_engine import get_shorts_highlight_engine
                    engine = get_shorts_highlight_engine()
                    # Build transcript dict from available data
                    transcript_dict = {
                        "segments": [
                            {"start": w.get("start", 0), "end": w.get("end", 0), "text": w.get("word", "")}
                            for w in (words or [])
                        ],
                        "duration": end - start,
                    }
                    # Build existing segments list for score fusion
                    existing_segments = [segment] if segment else []
                    highlights = await engine.find_highlights(
                        transcript=transcript_dict,
                        num_clips=3,
                        existing_segments=existing_segments,
                    )
                    if highlights:
                        shorts_highlights = [
                            {
                                "title": h.title,
                                "start_time": h.start_time,
                                "end_time": h.end_time,
                                "score": h.score,
                                "hook_sentence": h.hook_sentence,
                                "virality_reason": h.virality_reason,
                            }
                            for h in highlights
                        ]
                        meta["shorts_highlights"] = shorts_highlights
                        meta["shorts_highlight_count"] = len(shorts_highlights)
                        logger.info(
                            "  [Creative] ✓ Step 4.5/8: %d highlights found (top score=%.1f)",
                            len(shorts_highlights),
                            shorts_highlights[0]["score"] if shorts_highlights else 0,
                        )
                        steps_ok.append("step_4_5_shorts_highlight")
                    else:
                        _mark_fail("step_4_5_shorts_highlight_empty")
                        logger.info("  [Creative] Step 4.5/8: No highlights found")
                else:
                    logger.info("  [Creative] Step 4.5/8: Shorts Engine disabled (config)")
                    _mark_fail("step_4_5_shorts_engine_disabled")
            except ImportError as exc:
                _log_step_error("Step 4.5 (Shorts Highlight) - Import", exc)
                _mark_fail("step_4_5_shorts_highlight")
            except Exception as exc:
                _log_step_error("Step 4.5 (Shorts Highlight)", exc)
                _mark_fail("step_4_5_shorts_highlight")

        # ── 4.75 Hook-flash reorder ──────────────────────────────────────────
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
                    logger.info(f"[DURATION] post_hook_reorder: {_get_duration(clip_path):.2f}s")
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
                                logger.info(f"[DURATION] post_broll_v1: {_get_duration(clip_path):.2f}s")
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
                        logger.info(f"[DURATION] post_broll_v2: {_get_duration(clip_path):.2f}s")
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
            
            # Collect B-roll keywords for overlay fallback
            _broll_kws = []
            if segment and segment.get("broll_items"):
                _broll_kws = [b.get("keyword", "") for b in segment["broll_items"] if b.get("keyword")]
            if not _broll_kws and segment and segment.get("keywords"):
                _broll_kws = segment["keywords"] if isinstance(segment["keywords"], list) else []
            
            # DEBUG: log what we have before LLM fallback
            logger.info(
                "  [Creative] Step 5.5: _broll_kws=%s (len=%d) transcript=%s (len=%d)",
                _broll_kws, len(_broll_kws),
                repr(transcript[:80]) if transcript else "EMPTY",
                len(transcript) if transcript else 0,
            )
            
            # Fallback: use LLM to extract keywords from transcript if no B-roll keywords available
            if not _broll_kws and transcript:
                try:
                    from ...domains.broll.broll_service import BrollService
                    llm_kws = await BrollService().extract_keywords(transcript)
                    if llm_kws:
                        _broll_kws = llm_kws
                        logger.info("  [Creative] Step 5.5: LLM fallback keywords: %s", llm_kws)
                except Exception as _llm_e:
                    logger.debug("  [Creative] Step 5.5: LLM keyword fallback failed: %s", _llm_e)
            
            # Also try LLM fallback even if _broll_kws is populated but from broll_items (may not match VISUAL_KEYWORDS dict)
            if _broll_kws and transcript:
                try:
                    from ...domains.broll.broll_service import BrollService
                    llm_kws = await BrollService().extract_keywords(transcript)
                    if llm_kws:
                        logger.info("  [Creative] Step 5.5: LLM keywords (supplement): %s (existing: %s)", llm_kws, _broll_kws)
                        # Prefer LLM keywords over broll_items keywords (more likely to match VISUAL_KEYWORDS dict)
                        _broll_kws = llm_kws
                except Exception as _llm_e2:
                    logger.debug("  [Creative] Step 5.5: LLM keyword supplement failed: %s", _llm_e2)
            
            overlay_result = await overlay_engine.apply_overlays(
                video_path=clip_path,
                output_path=overlayed,
                transcript=transcript,
                word_timings=words or [],
                audio_features=audio_features or {},
                virality_score=meta.get("viral_score", 50.0),
                overlay_frequency="adaptive",
                mood=meta.get("mood", "neutral"),
                broll_keywords=_broll_kws or None,
            )
            
            if overlay_result.success and overlayed.exists() and overlayed.stat().st_size > 0:
                clip_path.unlink(missing_ok=True)
                overlayed.rename(clip_path)
                logger.info(f"[DURATION] post_overlays: {_get_duration(clip_path):.2f}s")
                contextual_overlays = overlay_result.overlays_applied
                logger.info(
                    "  [Creative] ✓ Step 5.5/8: Contextual overlays: %d applied (%d keywords detected)",
                    contextual_overlays, overlay_result.keywords_detected
                )
            else:
                overlayed.unlink(missing_ok=True)
                logger.debug("  [Creative] Contextual overlays skipped: %s", overlay_result.error)
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
        # NOTE: If FACE_AUTOCROP_ENABLED is True and autocrop was applied,
        # zoom_punch is skipped to avoid conflicting crop trajectories.
        logger.info("  [Creative] Step 6/8: Video effects (zoom + grade)...")
        effected = None
        _skip_vfx = _skip("vfx")
        # Check if autocrop was applied — if so, disable zoom_punch to avoid conflict
        _autocrop_applied = meta.get("autocrop_applied", False)
        _face_autocrop_enabled = False
        try:
            from ...config import get_config
            _face_autocrop_enabled = get_config().face_autocrop_enabled
        except Exception:
            pass
        # FIX 2: When face_autocrop is enabled, skip impact_zoom entirely to avoid
        # conflicting crop trajectories. Previously only skipped when autocrop had
        # already been applied to this specific clip — now also skips when the
        # feature is enabled in config (even if not yet applied to this clip).
        _skip_zoom = _face_autocrop_enabled
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
                # ── Zoom/crop conflict resolution ──────────────────────────────
                # If face autocrop was applied, disable zoom_punch to avoid
                # conflicting crop trajectories (triple zoom stack).
                if _skip_zoom:
                    logger.info(
                        "  [Creative] Step 6/8: [Zoom] Skipping impact zoom: "
                        "autocrop already applied for clip %s",
                        clip_path.name,
                    )
                    # Disable zoom_punch but keep color grading
                    preset.zoom_punch_enabled = False
                    preset.zoom_punch_zoom = 1.0
                    preset.zoom_punch_duration = 0.0
                    meta["zoom_pipeline"] = "none"
                else:
                    meta["zoom_pipeline"] = "zoom_punch"

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
                logger.info(f"[DURATION] post_audio_mastering: {_get_duration(clip_path):.2f}s")
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
                            logger.info(f"[DURATION] post_audio_ducking_1: {_get_duration(clip_path):.2f}s")
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

        # ── 7.5. Audio Denoiser (after ducking, before QA) ────────────────────
        _denoise_enabled = os.getenv("AUDIO_DENOISE_ENABLED", "false").lower() == "true"
        denoise_applied = False
        if _denoise_enabled and not _skip("audio_denoise"):
            logger.info("  [Creative] Step 7.5/8: Audio denoiser...")
            try:
                from ...domains.audio.audio_denoiser import denoise_audio
                denoised = clip_path.with_name(f"denoised_{clip_path.name}")
                denoise_result = await denoise_audio(
                    input_path=str(clip_path),
                    output_path=str(denoised),
                    noise_reduction=True,
                    voice_isolation=True,
                    loudnorm_target_lufs=-14.0,
                    apply_loudnorm=True,
                )
                if denoise_result.success and denoised.exists() and denoised.stat().st_size > 0:
                    clip_path.unlink(missing_ok=True)
                    denoised.rename(clip_path)
                    logger.info(f"[DURATION] post_audio_denoise: {_get_duration(clip_path):.2f}s")
                    denoise_applied = True
                    meta["audio_denoise_applied"] = True
                    logger.info(
                        "  [Creative] ✓ Step 7.5/8: Audio denoised (noise_reduction=%s, voice_isolation=%s)",
                        denoise_result.noise_reduction_applied,
                        denoise_result.voice_isolation_applied,
                    )
                    steps_ok.append("step_7_5_audio_denoise")
                else:
                    denoised.unlink(missing_ok=True)
                    _mark_fail("step_7_5_denoise_failed")
                    logger.warning("  [Creative] Step 7.5/8: Audio denoise failed")
            except ImportError as exc:
                _log_step_error("Step 7.5 (Audio Denoise) - Import", exc)
                _mark_fail("step_7_5_audio_denoise")
            except Exception as exc:
                _log_step_error("Step 7.5 (Audio Denoise)", exc)
                _mark_fail("step_7_5_audio_denoise")
        else:
            if _denoise_enabled:
                logger.info("  [Creative] Step 7.5/8: Audio denoise skipped (user override)")
            else:
                logger.debug("  [Creative] Step 7.5/8: Audio denoise disabled (AUDIO_DENOISE_ENABLED=false)")

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
                pipeline_failed_steps=steps_failed,
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

        # ── 8.5. Brand Overlay (final step before export) ──────────────────────
        _brand_enabled = os.getenv("BRAND_OVERLAY_ENABLED", "false").lower() == "true"
        brand_applied = False
        if _brand_enabled and not _skip("brand_overlay"):
            logger.info("  [Creative] Step 8.5/8: Brand overlay...")
            try:
                from ...services.brand_overlay_service import BrandConfig, apply_brand_overlay
                cfg = BrandConfig(
                    text=os.getenv("BRAND_OVERLAY_TEXT", ""),
                    image_path=os.getenv("BRAND_OVERLAY_IMAGE", ""),
                    position=os.getenv("BRAND_OVERLAY_POSITION", "bottom_right"),
                    padding_x=int(os.getenv("BRAND_OVERLAY_PADDING_X", "20")),
                    padding_y=int(os.getenv("BRAND_OVERLAY_PADDING_Y", "20")),
                    font_size=int(os.getenv("BRAND_OVERLAY_FONT_SIZE", "28")),
                    font_color=os.getenv("BRAND_OVERLAY_FONT_COLOR", "white"),
                    font_opacity=float(os.getenv("BRAND_OVERLAY_FONT_OPACITY", "0.85")),
                    image_opacity=float(os.getenv("BRAND_OVERLAY_IMAGE_OPACITY", "0.80")),
                    image_scale=os.getenv("BRAND_OVERLAY_IMAGE_SCALE", "80:-1"),
                )
                branded = clip_path.with_name(f"branded_{clip_path.name}")
                result_path = await apply_brand_overlay(
                    input_path=str(clip_path),
                    output_path=str(branded),
                    cfg=cfg,
                )
                if result_path == str(branded) and branded.exists() and branded.stat().st_size > 0:
                    clip_path.unlink(missing_ok=True)
                    branded.rename(clip_path)
                    logger.info(f"[DURATION] post_branding_1: {_get_duration(clip_path):.2f}s")
                    brand_applied = True
                    meta["brand_overlay_applied"] = True
                    logger.info("  [Creative] ✓ Step 8.5/8: Brand overlay applied")
                    steps_ok.append("step_8_5_brand_overlay")
                else:
                    branded.unlink(missing_ok=True)
                    _mark_fail("step_8_5_brand_overlay_failed")
                    logger.warning("  [Creative] Step 8.5/8: Brand overlay failed")
            except ImportError as exc:
                _log_step_error("Step 8.5 (Brand Overlay) - Import", exc)
                _mark_fail("step_8_5_brand_overlay")
            except Exception as exc:
                _log_step_error("Step 8.5 (Brand Overlay)", exc)
                _mark_fail("step_8_5_brand_overlay")
        else:
            if _brand_enabled:
                logger.info("  [Creative] Step 8.5/8: Brand overlay skipped (user override)")
            else:
                logger.debug("  [Creative] Step 8.5/8: Brand overlay disabled (BRAND_OVERLAY_ENABLED=false)")

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
