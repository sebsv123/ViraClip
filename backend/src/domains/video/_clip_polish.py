"""Post-render polishing helpers for the clip pipeline.

Each function here takes the output path of a partially-rendered clip plus
a few metadata args, applies one polishing/analysis step, and returns
either the (possibly mutated) output path or a small result dict.

These helpers are split out of `create_single_clip` to keep the main
orchestrator readable. They are intentionally narrow in scope:

- mutating helpers ALWAYS return the (possibly new) `output_path`
- analysis helpers return small dicts/values, never `None` for a dict
- every helper swallows its own exceptions and logs at debug level

Adding a new phase? Mirror the pattern: small surface, fail-soft.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─── 1. Translation & dubbing ────────────────────────────────────────────
async def apply_translation_dubbing(
    output_path: Path,
    target_language: Optional[str],
) -> Path:
    """Replace audio with target-language dub if `target_language` is non-eng."""
    if not target_language or target_language == "eng":
        return output_path
    try:
        from ...domains.captions.translation_service import TranslationService
        translator = TranslationService()
        dubbed_path = output_path.with_name(f"dubbed_{output_path.name}")
        await translator.dub_clip(output_path, dubbed_path, target_language)
        if dubbed_path.exists() and dubbed_path.stat().st_size > 0:
            logger.info(f"  ✓ Translation/dub applied ({target_language})")
            return dubbed_path
        logger.warning(f"  Translation dub produced no output for lang={target_language}, using original")
    except Exception as e:
        logger.warning(f"  apply_translation_dubbing failed (lang={target_language}): {e}")
    return output_path


# ─── 2. Audio ducking ────────────────────────────────────────────────────
async def apply_audio_ducking(
    output_path: Path,
    words: Optional[List[Dict[str, Any]]],
) -> Path:
    """Sidechain duck BGM under speaker audio when words are available."""
    try:
        from ...domains.audio.audio_ducking_service import get_audio_ducking_service
        duck_svc = get_audio_ducking_service()
        if duck_svc.enabled and words:
            duck_out = output_path.with_name(f"duck_{output_path.name}")
            duck_result = await duck_svc.apply_ducking(
                video_path=output_path,
                output_path=duck_out,
                word_timings=words,
            )
            if duck_result.success and duck_out.exists():
                duck_out.replace(output_path)
                logger.info(
                    f"  ✓ Audio ducking applied ({duck_result.ducked_segments} segments)"
                )
    except Exception as e:
        logger.debug(f"  Audio ducking skipped: {e}")
    return output_path


# ─── 3. Pexels B-Roll overlay ────────────────────────────────────────────
async def apply_pexels_broll(
    output_path: Path,
    segment: Dict[str, Any],
    prefetch_task: Optional[asyncio.Task],
    broll_already_applied: bool,
) -> Path:
    """Overlay free Pexels B-roll if prefetch produced a clip and Step 4.3 didn't run."""
    if prefetch_task is None or broll_already_applied:
        return output_path
    try:
        from ...domains.broll.pexels_service import overlay_broll_on_clip
        broll_path = await asyncio.wait_for(prefetch_task, timeout=30.0)
        if broll_path:
            broll_out = output_path.with_name(f"broll_{output_path.name}")
            ok = overlay_broll_on_clip(
                output_path, broll_path, broll_out,
                broll_start=0.3, broll_end=0.6,
            )
            if ok and broll_out.exists():
                broll_out.replace(output_path)
                logger.info(f"  ✓ Pexels B-Roll overlaid ({segment.get('theme', 'nature')})")
        else:
            logger.debug("  B-Roll prefetch returned no clip — skipping overlay")
    except asyncio.TimeoutError:
        logger.warning("  WARNING: B-Roll prefetch timeout — skipping")
        prefetch_task.cancel()
    except Exception as e:
        logger.warning(f"  Pexels B-Roll skipped: {e}")
    return output_path


# ─── 4. Hook slow-motion ─────────────────────────────────────────────────
def apply_hook_slowmo(output_path: Path, virality_score: float, clip_index: int) -> bool:
    """Apply opt-in hook slo-mo. Returns True if applied."""
    try:
        from ...video_processing.hook_slowmo import maybe_apply_hook_slowmo
        applied = maybe_apply_hook_slowmo(
            output_path,
            virality_score=virality_score,
            inplace=True,
        )
        if applied:
            logger.info(f"  ↳ Hook slo-mo applied to clip {clip_index + 1}")
        return bool(applied)
    except Exception as e:
        logger.debug(f"  Hook slo-mo skipped: {e}")
        return False


# ─── 5. Post-render A/V validation ───────────────────────────────────────
async def validate_clip_output(
    output_path: Path,
    expected_duration: float,
    words: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Run ClipValidator A/V sync + quality checks. Returns report dict."""
    try:
        from ...domains.validation.clip_validator import get_clip_validator
        validator = get_clip_validator()
        report = await validator.validate_output(
            output_path,
            expected_duration=expected_duration,
            words=words,
        )
        if not report.get("valid", True):
            logger.warning(f"  ⚠ ClipValidator issues: {report.get('issues', [])}")
        else:
            logger.debug("  ✓ ClipValidator passed")
        return report
    except Exception as e:
        logger.debug(f"  ClipValidator skipped: {e}")
        return {}


# ─── 6. Scene rhythm analysis ────────────────────────────────────────────
def analyze_scene_rhythm(output_path: Path) -> Dict[str, Any]:
    """Analyze edit pace + loop potential via PySceneDetect."""
    try:
        from ...utils.scene_analysis import analyze_clip_rhythm, detect_loop_potential
        rhythm_data = analyze_clip_rhythm(output_path)
        loop_data = detect_loop_potential(output_path)
        rhythm_data.update(loop_data)
        return rhythm_data
    except Exception as e:
        logger.debug(f"Scene analysis skipped: {e}")
        return {}


# ─── 7. Viral metadata generation ────────────────────────────────────────
async def generate_viral_metadata_safe(
    segment: Dict[str, Any],
    target_platform: str,
) -> Dict[str, Any]:
    """LLM-generated hashtags + SEO title. Empty dict on failure."""
    try:
        from ...domains.virality.viral_metadata_service import generate_viral_metadata
        viral_meta = await generate_viral_metadata(
            text=segment.get("text", ""),
            platform=target_platform,
        )
        logger.info(
            f"  ✓ Viral metadata: '{viral_meta.get('title', '')}' "
            f"({len(viral_meta.get('hashtags', []))} hashtags)"
        )
        return viral_meta or {}
    except Exception as e:
        logger.debug(f"  Viral metadata skipped: {e}")
        return {}


# ─── 8. Engagement prediction ────────────────────────────────────────────
async def predict_engagement(
    words: List[Dict[str, Any]],
    audio_features: Dict[str, Any],
    duration: float,
) -> Dict[str, Any]:
    """LSTM/CNN engagement curve + drop-off + retention score."""
    try:
        from ...domains.virality.engagement_prediction_service import get_engagement_predictor
        predictor = get_engagement_predictor()
        loop = asyncio.get_event_loop()
        eng = await loop.run_in_executor(
            None,
            lambda: predictor.predict_engagement_curve(
                words=words,
                audio_features=audio_features,
                duration=duration,
            ),
        )
        result = {
            "engagement_curve":   eng["curve"],
            "drop_off_points":    eng["drop_off_points"],
            "hook_insertion_pts": eng["hook_points"],
            "retention_score":    eng["retention_score"],
            "engagement_method":  eng["predicted_by"],
        }
        logger.info(
            f"  ✓ Engagement curve [{eng['predicted_by']}]: "
            f"retention={eng['retention_score']}% "
            f"drop-offs={eng['drop_off_points']}"
        )
        return result
    except Exception as e:
        logger.debug(f"  Engagement prediction skipped: {e}")
        return {}


# ─── 9. Quality validator ────────────────────────────────────────────────
def validate_quality(
    output_path: Path,
    duration: float,
    virality: float,
) -> Dict[str, Any]:
    """Run quality validator and return a report dict."""
    try:
        from ...domains.validation.quality_validator import validate_clip
        qr = validate_clip(
            clip_path=output_path,
            clip_info={"duration": duration, "virality_score": virality},
        )
        report = {
            "quality_level": (
                qr.quality_level.value if hasattr(qr.quality_level, "value")
                else str(qr.quality_level)
            ),
            "passed": qr.passed,
            "issues": [c.message for c in qr.checks if not c.passed],
        }
        if not qr.passed:
            logger.warning(f"  ⚠ Quality issues: {report['issues'][:2]}")
        else:
            logger.debug(f"  ✓ Quality: {report['quality_level']}")
        return report
    except Exception as e:
        logger.debug(f"  QualityValidator skipped: {e}")
        return {}


# ─── 10. Audio recommendations ───────────────────────────────────────────
async def recommend_audio(output_path: Path) -> List[Dict[str, Any]]:
    """Suggest 3 alternative music tracks for this clip."""
    try:
        from ...domains.audio.audio_recommendation import recommend_music_for_video
        arecs = await recommend_music_for_video(output_path, count=3)
        result = [
            {
                "title": r.title,
                "genre": r.genre.value if hasattr(r.genre, "value") else str(r.genre),
                "mood": r.mood,
                "bpm": r.bpm,
            }
            for r in arecs[:3]
        ]
        if result:
            logger.debug(f"  ✓ Audio recs: {[r['title'] for r in result]}")
        return result
    except Exception as e:
        logger.debug(f"  Audio recommendation skipped: {e}")
        return []


# ─── 11. Clip health report ──────────────────────────────────────────────
def generate_clip_health_report(
    clip_index: int,
    virality: float,
    segment: Optional[Dict[str, Any]],
    duration: float,
    target_platform: str,
    viral_meta: Dict[str, Any],
) -> Dict[str, Any]:
    """Structured grade (A–F) + actionable top fixes for this clip."""
    try:
        from ...domains.validation.clip_health_service import generate_health_report
        health = generate_health_report(
            clip_id=str(clip_index + 1),
            virality_score=virality,
            hook_score=segment.get("hook_score") if segment else None,
            hook_type=segment.get("hook_type") if segment else None,
            duration=duration,
            platform=target_platform,
            has_subtitles=bool(segment and segment.get("text")),
            hashtag_count=len(viral_meta.get("hashtags", [])),
            zoom_punch_applied=bool(os.environ.get("CUT_ZOOM_ENABLED", "true") == "true"),
        )
        report = health.to_dict()
        if report.get("grade") in ("D", "F"):
            logger.warning(
                f"  ⚠ Clip health grade={report['grade']} "
                f"top_fix={report.get('top_fix','')}"
            )
        else:
            logger.info(
                f"  ✓ Clip health grade={report.get('grade','?')} "
                f"score={report.get('overall_score',0):.0f}"
            )
        return report
    except Exception as e:
        logger.debug(f"  Clip health skipped: {e}")
        return {}


# ─── 12. LTXV intro prepend ──────────────────────────────────────────────
async def maybe_prepend_intro(
    output_path: Path,
    segment: Dict[str, Any],
    virality: float,
) -> Path:
    """Prepend an LTXV-generated intro (opt-in via LTXV_INTRO_ENABLED=true)."""
    try:
        from ...domains.broll.ltxv_intro_service import LTXVIntroService
        intro_out = await LTXVIntroService.maybe_prepend_intro(
            clip_path=output_path,
            theme=segment.get("theme") or segment.get("hook_type"),
            virality_score=float(virality or 0.0),
        )
        if intro_out and Path(intro_out).exists():
            logger.info("  ✓ LTXV intro prepended")
            return Path(intro_out)
    except Exception as e:
        logger.debug(f"  LTXV intro skipped: {e}")
    return output_path
