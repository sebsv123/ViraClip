"""
Video Polish Pipeline
=====================

Orchestrates viral-polish services (captions, hook visual, audio ducking,
beat-sync) over a list of clips.  Each step is applied sequentially per clip;
failures are caught and logged so they never block the next step.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


async def apply_viral_polish(
    clips: List[Dict[str, Any]],
    config: Dict[str, Any],
    task_id: str,
) -> List[Dict[str, Any]]:
    """
    Apply viral-polish steps to every clip in *clips* and return the
    (mutated) list with per-step flags added to each clip dict.

    Steps (in order):
      1. caption_service   – burn ASS karaoke captions
      2. hook_visual_service – add hook overlay for scroll-stop effect
      3. audio_ducking_service – lower BGM when voice is present
      4. beat_sync_service (opt-in) – cut/re-time to music BPM

    Each step follows the coordinator.py pattern:
      • build a side-car output path with a short prefix
      • call the async service
      • on success + non-empty output: rename → original path, set flag
      • on any exception: logger.debug("…skipped…"), continue
    """
    for clip in clips:
        clip_path = Path(clip["path"])

        # ── Temp paths (cleaned up at the end of each clip) ──────────────────
        cap_out  = clip_path.with_name("cap_"  + clip_path.name)
        hk_out   = clip_path.with_name("hk_"   + clip_path.name)
        duck_out = clip_path.with_name("duck_" + clip_path.name)
        bs_out   = clip_path.with_name("bs_"   + clip_path.name)

        # ── STEP 1: caption_service ───────────────────────────────────────────
        if config.get("add_subtitles", True):
            try:
                from .caption_service import get_caption_service  # noqa: PLC0415

                svc = get_caption_service()
                style = svc.style_for_template(
                    config.get("caption_template", "tiktok_viral"),
                    config.get("target_platform", "tiktok"),
                )
                ok = await svc.burn(
                    video_path=Path(clip["path"]),
                    output_path=cap_out,
                    words=clip.get("words", []),
                    style=style,
                    platform=config.get("target_platform", "tiktok"),
                )
                if ok and cap_out.exists() and cap_out.stat().st_size > 0:
                    cap_out.rename(clip["path"])
                    clip["captions_applied"] = True
                    clip["caption_style_used"] = style
                    logger.info("[%s] captions applied (style=%s)", task_id, style)
            except Exception:
                logger.debug("[%s] caption step skipped", task_id, exc_info=True)

        # ── STEP 2: hook_visual_service ───────────────────────────────────────
        if config.get("add_hook_visual", True):
            try:
                from .hook_visual_service import add_hook_overlay_to_clip  # noqa: PLC0415

                hook_text = (
                    clip.get("hook_text")
                    or clip.get("title")
                    or clip.get("text", "")[:60]
                )
                ok = await add_hook_overlay_to_clip(
                    input_path=Path(clip["path"]),
                    output_path=hk_out,
                    hook_text=hook_text,
                    platform=config.get("target_platform", "tiktok"),
                )
                if ok and hk_out.exists() and hk_out.stat().st_size > 0:
                    hk_out.rename(clip["path"])
                    clip["hook_visual_applied"] = True
                    logger.info("[%s] hook visual applied", task_id)
            except Exception:
                logger.debug("[%s] hook_visual step skipped", task_id, exc_info=True)

        # ── STEP 3: audio_ducking_service ─────────────────────────────────────
        if config.get("audio_ducking", True):
            try:
                from .audio_ducking_service import get_audio_ducking_service  # noqa: PLC0415

                svc = get_audio_ducking_service()
                ok = await svc.apply_ducking(
                    input_path=Path(clip["path"]),
                    output_path=duck_out,
                    words=clip.get("words", []),
                )
                if ok and duck_out.exists() and duck_out.stat().st_size > 0:
                    duck_out.rename(clip["path"])
                    clip["audio_ducking_applied"] = True
                    logger.info("[%s] audio ducking applied", task_id)
            except Exception:
                logger.debug("[%s] audio_ducking step skipped", task_id, exc_info=True)

        # ── STEP 4: beat_sync_service (opt-in) ────────────────────────────────
        if config.get("beat_sync", False):
            try:
                from .beat_sync_service import get_beat_sync_service  # noqa: PLC0415

                svc = get_beat_sync_service()
                result = await svc.sync_to_beat(
                    video_path=Path(clip["path"]),
                    output_path=bs_out,
                    words=clip.get("words", []),
                )
                ok = isinstance(result, dict) and result.get("success")
                if ok and bs_out.exists() and bs_out.stat().st_size > 0:
                    bs_out.rename(clip["path"])
                    clip["beat_sync_applied"] = True
                    clip["beat_sync_cuts"] = result.get("cuts_applied", 0)
                    logger.info("[%s] beat sync applied (cuts=%s)", task_id, clip["beat_sync_cuts"])
            except Exception:
                logger.debug("[%s] beat_sync step skipped", task_id, exc_info=True)

        # ── CLEANUP: remove any leftover temp files ───────────────────────────
        for tmp in (cap_out, hk_out, duck_out, bs_out):
            tmp.unlink(missing_ok=True)

    return clips
