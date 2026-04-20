"""
Creative Pipeline — Phase 9 Creative Engine

The unified post-render enhancement layer.
Runs AFTER video_service.create_single_clip() produces the base 9:16 clip.

Pipeline:
  base clip → multimodal timeline → virality prediction → template selection
           → hook analysis → B-roll overlay → video effects (zoom punch + grade)
           → audio mastering (loudnorm + SFX) → QA + render manifest
"""

import asyncio
import logging
import os
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)

# Runtime diagnostics flag - set to True to see detailed error traces
DIAGNOSTIC_MODE = True

async def _apply_cinematic_intro(clip_path: Path, output_path: Path) -> bool:
    """
    Apply a cinematic intro effect to the first ~0.5s of the clip:
      1. Letterbox bars slide in from top/bottom (0.0–0.3s)
      2. Slight white flash (0.1s at t=0)
      3. Zoom-in from 115% → 100% over the first 0.4s

    Implemented as a single FFmpeg pass with drawbox + zoompan filters.
    Returns True on success, False on failure.
    """
    try:
        # Fixed: proper zoompan for animated zoom, drawbox for letterbox/flash
        # zoompan: d=12 frames (~0.4s @ 30fps), z zooms from 1.15 to 1.0
        vf = (
            # Zoom in from 115% to 100% over first 0.4s using zoompan
            "zoompan=z='min(1.15,max(1.0,1.15-0.15*in/12))':d=12:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920,"
            # Letterbox bars: black top/bottom, fade out by t=0.35
            "drawbox=x=0:y=0:w=iw:h=ih*0.06:color=black@'if(lt(t,0.35),1-t/0.35,0)':t=fill,"
            "drawbox=x=0:y=ih*0.94:w=iw:h=ih*0.06:color=black@'if(lt(t,0.35),1-t/0.35,0)':t=fill,"
            # White flash at t=0, fades by t=0.12
            "drawbox=x=0:y=0:w=iw:h=ih:color=white@'if(lt(t,0.12),0.55*(1-t/0.12),0)':t=fill"
        )
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "quiet", "-y",
            "-i", str(clip_path),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "copy",
            str(output_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=120.0)
        return output_path.exists() and output_path.stat().st_size > 0
    except Exception as exc:
        logger.debug("_apply_cinematic_intro failed: %s", exc)
        return False


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
        transcript = segment.get("transcript", "")

        # ── Resolve Viral Boost feature config ────────────────────────────
        try:
            from .feature_flags import ViralBoostConfig
            vb = ViralBoostConfig.from_env()
        except Exception:
            vb = None

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
            # ── Viral Boost tracking ─────────────────────────────
            "hook_visual_applied": False,
            "cinematic_intro_applied": False,
            "ltxv_intro_applied": False,
            "broll_slots_planned": 0,
            "broll_slots_filled": 0,
            "ltxv_assets_generated": 0,
            "broll_density_coverage": 0.0,
            "broll_sources": [],  # per-slot: [{keyword, priority, source}]
        }

        # ── 1. Multimodal event timeline ──────────────────────────────────────
        logger.info("  [Creative] Step 1/8: Multimodal timeline generation...")
        timeline: list = []
        try:
            logger.debug("  [Creative] Importing multimodal_detector...")
            from .multimodal_detector import get_multimodal_detector
            logger.debug("  [Creative] multimodal_detector import OK")
            timeline = await get_multimodal_detector().generate_timeline(
                video_path=source_video,
                segment_start=start,
                segment_end=end,
                words=words or [],
            )
            meta["timeline_events"] = len(timeline)
            logger.info("  [Creative] ✓ Step 1/8: %d timeline events generated", len(timeline))
        except ImportError as exc:
            _log_step_error("Step 1 (Timeline) - Import", exc, critical=True)
        except Exception as exc:
            _log_step_error("Step 1 (Timeline)", exc)

        # ── 2. Virality prediction ────────────────────────────────────────────
        logger.info("  [Creative] Step 2/8: Virality prediction...")
        viral_pred = None
        try:
            logger.debug("  [Creative] Importing virality_engine...")
            from .virality_engine import get_virality_engine
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
        except ImportError as exc:
            _log_step_error("Step 2 (Virality) - Import", exc, critical=True)
        except Exception as exc:
            _log_step_error("Step 2 (Virality)", exc)

        # ── 3. Template selection ─────────────────────────────────────────────
        logger.info("  [Creative] Step 3/8: Template selection...")
        preset = None
        try:
            logger.debug("  [Creative] Importing smart_templates...")
            from .smart_templates import get_template_selector
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
        except ImportError as exc:
            _log_step_error("Step 3 (Template) - Import", exc, critical=True)
        except Exception as exc:
            _log_step_error("Step 3 (Template)", exc)

        # ── 4. Hook analysis (informational — no reordering yet) ──────────────
        logger.info("  [Creative] Step 4/8: Hook analysis...")
        try:
            logger.debug("  [Creative] Importing hook_engine...")
            from .hook_engine import get_hook_engine
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
        except ImportError as exc:
            _log_step_error("Step 4 (Hook) - Import", exc)
        except Exception as exc:
            _log_step_error("Step 4 (Hook)", exc)

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

        # ── 4.8. Hook visual overlay (text animation on first 2s) ────────────
        _hook_visual_on = (vb.hook_visual if vb else
                           os.environ.get("HOOK_VISUAL_ENABLED", "true").lower() == "true")
        if _hook_visual_on:
            logger.info("  [Creative] Step 4.8: Hook visual overlay...")
            try:
                from .hook_visual_service import HookVisualService
                _hook_svc = HookVisualService()
                _hook_segment = {
                    "text": transcript or "",
                    "hook_type": meta.get("hook_text") and "curiosity_gap" or "insight_reveal",
                }
                _hook_overlay = _hook_svc.generate_hook_from_segment(_hook_segment, duration=2.0)
                if _hook_overlay.text:
                    _hooked = clip_path.with_name(f"hv_{clip_path.name}")
                    _hv_result = await _hook_svc.add_hook_to_video(
                        str(clip_path), str(_hooked), _hook_overlay
                    )
                    if _hv_result == str(_hooked) and _hooked.exists() and _hooked.stat().st_size > 0:
                        clip_path.unlink(missing_ok=True)
                        _hooked.rename(clip_path)
                        meta["hook_visual_applied"] = True
                        logger.info("  [Creative] ✓ Step 4.8: Hook visual overlay applied: '%s'", _hook_overlay.text[:40])
                    else:
                        _hooked.unlink(missing_ok=True)
            except Exception as exc:
                logger.debug("  [Creative] Step 4.8 (Hook visual) skipped: %s", exc)

        # ── 4.9a. LTXV intro hook (GPU-accelerated, 1.5s animated intro) ─
        _ltxv_intro_on = os.environ.get("LTXV_INTRO_ENABLED", "true").lower() == "true"
        if _ltxv_intro_on:
            logger.info("  [Creative] Step 4.9a: LTXV intro hook...")
            try:
                from ..comfyui_bridge import ComfyUIBridge
                _cfy = ComfyUIBridge()
                if await _cfy.is_available():
                    # Extract first frame for LTXV I2V intro
                    _first_frame = clip_path.with_suffix(".first.jpg")
                    _extract_proc = await asyncio.create_subprocess_exec(
                        "ffmpeg", "-y", "-i", str(clip_path),
                        "-ss", "0", "-vframes", "1",
                        "-vf", "scale=512:768:force_original_aspect_ratio=decrease,pad=512:768:(ow-iw)/2:(oh-ih)/2:black",
                        str(_first_frame),
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await asyncio.wait_for(_extract_proc.wait(), timeout=30.0)
                    if _first_frame.exists():
                        _intro_out = clip_path.with_name(f"ltxv_intro_{clip_path.name}")
                        _theme = preset.name if preset else transcript[:40] if transcript else "cinematic"
                        _ltxv_result = await _cfy.generate_ltxv_intro(
                            first_frame_path=_first_frame,
                            theme=_theme,
                            output_path=_intro_out,
                            timeout=90.0,
                        )
                        if _ltxv_result and _intro_out.exists() and _intro_out.stat().st_size > 0:
                            # Concat the LTXV intro (1.5s) with the main clip
                            _concat_out = clip_path.with_name(f"concat_{clip_path.name}")
                            with open("/tmp/concat_list.txt", "w") as _f:
                                _f.write(f"file '{_intro_out}'\nfile '{clip_path}'\n")
                            _concat_proc = await asyncio.create_subprocess_exec(
                                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                                "-i", "/tmp/concat_list.txt",
                                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                                "-c:a", "aac", "-b:a", "128k",
                                "-movflags", "+faststart",
                                str(_concat_out),
                                stdout=asyncio.subprocess.DEVNULL,
                                stderr=asyncio.subprocess.DEVNULL,
                            )
                            await asyncio.wait_for(_concat_proc.wait(), timeout=120.0)
                            if _concat_out.exists() and _concat_out.stat().st_size > 0:
                                clip_path.unlink(missing_ok=True)
                                _intro_out.unlink(missing_ok=True)
                                _concat_out.rename(clip_path)
                                meta["ltxv_intro_applied"] = True
                                meta["intro_duration_s"] = 1.5
                                logger.info("  [Creative] ✓ Step 4.9a: LTXV intro hook applied")
                            else:
                                _concat_out.unlink(missing_ok=True)
                        _first_frame.unlink(missing_ok=True)
                await _cfy.close()
            except Exception as _ltxv_exc:
                logger.debug("  [Creative] Step 4.9a (LTXV intro) skipped: %s", _ltxv_exc)

        # ── 4.9b. Cinematic intro (FFmpeg letterbox+flash+zoom, fallback if no LTXV) ─
        _cinematic_on = (vb.cinematic_intro if vb else
                         os.environ.get("CINEMATIC_INTRO_ENABLED", "true").lower() == "true")
        _ltxv_intro_active = meta.get("ltxv_intro_applied", False)
        if not _ltxv_intro_active and _cinematic_on:
            logger.info("  [Creative] Step 4.9b: Cinematic intro (FFmpeg)...")
            try:
                _intro_out = clip_path.with_name(f"intro_{clip_path.name}")
                _intro_ok = await _apply_cinematic_intro(clip_path, _intro_out)
                if _intro_ok and _intro_out.exists() and _intro_out.stat().st_size > 0:
                    clip_path.unlink(missing_ok=True)
                    _intro_out.rename(clip_path)
                    meta["cinematic_intro_applied"] = True
                    logger.info("  [Creative] ✓ Step 4.9b: Cinematic intro applied")
                else:
                    _intro_out.unlink(missing_ok=True)
            except Exception as exc:
                logger.debug("  [Creative] Step 4.9b (Cinematic intro) skipped: %s", exc)

        # ── 5. B-roll overlay (density-planned) ────────────────────────────
        logger.info("  [Creative] Step 5/8: B-roll overlay (density-planned)...")
        broll_count = 0
        try:
            from .contextual_broll import get_contextual_broll
            from .video_effects import overlay_broll_clips
            from .multimodal_detector import TimelineEvent

            clip_dur = max(1.0, end - start)
            _broll_ctx = get_contextual_broll()
            broll_pairs: list = []

            # ── 5a. Run density planner to get prioritised slots ─────────
            try:
                from .broll_density_planner import plan_broll_density
                _energy = float((audio_features or {}).get("energy", 0.5) or 0.5)
                density_plan = await plan_broll_density(
                    timeline_events=timeline,
                    clip_duration=clip_dur,
                    transcript=transcript,
                    audio_energy=_energy,
                    preset_name=preset.name if preset else "",
                )
                meta["broll_slots_planned"] = len(density_plan.slots)
                meta["broll_density_coverage"] = round(density_plan.planned_coverage, 3)
                logger.info(
                    "  [Creative] Density plan: %d slots, coverage=%.0f%%, ltxv=%d",
                    len(density_plan.slots),
                    density_plan.planned_coverage * 100,
                    density_plan.ltxv_slots,
                )
                # LTXV budget: cap per clip
                _ltxv_budget = (vb.ltxv_broll_max_per_clip if vb else
                                int(os.environ.get("LTXV_BROLL_MAX_PER_CLIP", "2")))
                _ltxv_used = 0
                # Resolve each slot via the cascade — pass slot priority for hybrid routing
                for slot in density_plan.slots:
                    asset = await _broll_ctx.get_for_keyword(
                        slot.keyword,
                        duration=slot.duration,
                        mood=slot.visual_mode,
                        priority=slot.priority,
                    )
                    if asset:
                        _src = getattr(asset, 'source', 'unknown')
                        if _src in ('t2v', 'ltxv'):
                            _ltxv_used += 1
                            meta["ltxv_assets_generated"] = _ltxv_used
                        meta["broll_sources"].append({
                            "keyword": slot.keyword,
                            "priority": slot.priority,
                            "source": _src,
                        })
                        logger.info(
                            "  [Creative] B-roll slot [%s] '%s' → %s",
                            slot.priority.upper(), slot.keyword, _src,
                        )
                        evt = TimelineEvent(
                            t=slot.t, type="keyword", strength=0.7,
                            duration=slot.duration,
                            payload={"word": slot.keyword, "category": "planner"},
                        )
                        broll_pairs.append((evt, asset))
            except ImportError:
                logger.debug("  [Creative] BrollDensityPlanner not available, falling back to timeline")
            except Exception as _plan_exc:
                logger.debug("  [Creative] Planner failed: %s, falling back", _plan_exc)

            # ── 5b. Fallback: timeline-based if planner yielded nothing ──
            if not broll_pairs:
                broll_pairs = await _broll_ctx.get_for_timeline(timeline, max_assets=8)

            # ── 5c. LLM keyword fallback if still empty ──────────────────
            if not broll_pairs and transcript:
                try:
                    from .broll_service import BrollService
                    llm_kws = await BrollService().extract_keywords(transcript)
                    for i, kw in enumerate(llm_kws[:3]):
                        asset = await _broll_ctx.get_for_keyword(kw, duration=3.0)
                        if asset:
                            t_ins = max(2.0, min(4.0 + i * 6.0, clip_dur - 4.0))
                            evt = TimelineEvent(
                                t=t_ins, type="keyword", strength=0.7,
                                duration=3.0, payload={"word": kw, "category": "broll_llm"},
                            )
                            broll_pairs.append((evt, asset))
                    if broll_pairs:
                        logger.info("  [Creative] B-roll LLM fallback: %d assets", len(broll_pairs))
                except Exception as _fb:
                    logger.debug("  [Creative] B-roll LLM fallback skipped: %s", _fb)

            # ── 5d. Apply overlays ───────────────────────────────────────
            if broll_pairs:
                brolled = clip_path.with_name(f"broll_{clip_path.name}")
                result = await overlay_broll_clips(clip_path, broll_pairs, brolled)
                if result and brolled.exists() and brolled.stat().st_size > 0:
                    clip_path.unlink(missing_ok=True)
                    brolled.rename(clip_path)
                    broll_count = len(broll_pairs)
                    meta["broll_slots_filled"] = broll_count
                    logger.info("  [Creative] ✓ Step 5/8: B-roll: %d overlays applied", broll_count)
                else:
                    brolled.unlink(missing_ok=True)
            else:
                logger.info("  [Creative] Step 5/8: No B-roll pairs found")
        except ImportError as exc:
            _log_step_error("Step 5 (B-roll) - Import", exc, critical=True)
        except Exception as exc:
            _log_step_error("Step 5 (B-roll)", exc)

        meta["broll_overlays"] = broll_count

        # ── 5.5. Contextual overlays (viral feature: full-screen with corner bubble) ─
        logger.info("  [Creative] Step 5.5/8: Contextual overlays...")
        contextual_overlays = 0
        try:
            logger.debug("  [Creative] Importing contextual_overlay_engine...")
            from .contextual_overlay_engine import get_contextual_overlay_engine
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
                logger.debug("  [Creative] Contextual overlays skipped: %s", overlay_result.error)
        except ImportError as exc:
            _log_step_error("Step 5.5 (Contextual Overlays) - Import", exc)
        except Exception as exc:
            _log_step_error("Step 5.5 (Contextual Overlays)", exc)
        
        meta["contextual_overlays"] = contextual_overlays

        # ── 6. Video effects (zoom punch + color grade from preset) ───────────
        logger.info("  [Creative] Step 6/8: Video effects (zoom + grade)...")
        try:
            if preset is not None:
                logger.debug("  [Creative] Importing video_effects for apply_preset_effects...")
                from .video_effects import apply_preset_effects
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
                    meta["color_grade_applied"] = bool(preset.extra_vf_filters)
                    logger.info(
                        "  [Creative] ✓ Step 6/8: VFX: zoom_punch=%s grade=%s",
                        meta["zoom_punch_applied"], meta["color_grade_applied"],
                    )
                else:
                    effected.unlink(missing_ok=True)
            else:
                logger.info("  [Creative] Step 6/8: Skipped (no preset)")
        except ImportError as exc:
            _log_step_error("Step 6 (VFX) - Import", exc, critical=True)
        except Exception as exc:
            _log_step_error("Step 6 (VFX)", exc)

        # ── 6.5. Speed control (playback speed / dramatic slow-mo) ────────────
        logger.info("  [Creative] Step 6.5/8: Speed control...")
        speed_applied = False
        try:
            # Check if speed control is needed
            playback_speed = segment.get("playback_speed", 1.0)
            dramatic_slowmo = segment.get("dramatic_slowmo", False)
            
            if playback_speed != 1.0 or dramatic_slowmo:
                from .speed_control_service import get_speed_control_service
                
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
                else:
                    speed_output.unlink(missing_ok=True)
            else:
                logger.debug("  [Creative] Step 6.5/8: Skipped (no speed change)")
        except Exception as exc:
            _log_step_error("Step 6.5 (Speed Control)", exc)
        
        meta["speed_control_applied"] = speed_applied

        # ── 7. Audio mastering (loudnorm + SFX + ducking) ─────────────────────
        logger.info("  [Creative] Step 7/8: Audio mastering (loudnorm + SFX + ducking)...")
        sfx_count = 0
        loudnorm_applied = False
        ducking_applied = False
        try:
            logger.debug("  [Creative] Importing smart_audio...")
            from .smart_audio import get_smart_audio, find_bgm_track
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
                if bgm and words:
                    try:
                        from .audio_ducking_service import get_audio_ducking_service
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
                        logger.debug("  [Creative] Audio ducking skipped: %s", duck_err)
                
                logger.info(
                    "  [Creative] ✓ Step 7/8: Audio mastered (sfx=%d bgm=%s ducking=%s)",
                    sfx_count, bgm.name if bgm else "none", ducking_applied,
                )
            else:
                mastered.unlink(missing_ok=True)
        except ImportError as exc:
            _log_step_error("Step 7 (Audio) - Import", exc, critical=True)
        except Exception as exc:
            _log_step_error("Step 7 (Audio)", exc)

        meta["sfx_injected"] = sfx_count
        meta["loudnorm_applied"] = loudnorm_applied
        meta["audio_ducking_applied"] = ducking_applied

        # ── 8. QA + render manifest ───────────────────────────────────────────
        logger.info("  [Creative] Step 8/8: QA + render manifest...")
        try:
            logger.debug("  [Creative] Importing learning_loop...")
            from .learning_loop import get_learning_loop
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
            meta["creative_enhanced"] = True
            logger.info("  [Creative] ✓ Step 8/8: QA complete (passed=%s)", manifest.qa_passed)
        except ImportError as exc:
            _log_step_error("Step 8 (QA) - Import", exc)
        except Exception as exc:
            _log_step_error("Step 8 (QA)", exc)

        logger.info("  [Creative] Pipeline complete: enhanced=%s, %d/%d steps succeeded",
                    meta["creative_enhanced"],
                    sum(1 for k in ["timeline_events", "viral_score", "preset_used", 
                                    "zoom_punch_applied", "loudnorm_applied", "qa_passed"] 
                        if meta.get(k) not in [None, False, 0]),
                    8)
        return meta


# ── Singleton ─────────────────────────────────────────────────────────────────

_pipeline: "CreativePipeline | None" = None


def get_creative_pipeline() -> CreativePipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = CreativePipeline()
    return _pipeline
