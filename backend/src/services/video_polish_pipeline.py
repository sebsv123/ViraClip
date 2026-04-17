"""
Video Polish Pipeline — Viral clip enhancement orchestration.

Applies caption burn-in, hook visuals, audio ducking, and beat sync
to rendered clips in sequence. Each step is optional and failure-tolerant.
"""
import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


async def apply_viral_polish(
    clips: List[Dict[str, Any]],
    config: Dict[str, Any],
    task_id: str,
) -> List[Dict[str, Any]]:
    """
    Apply viral polish steps to each clip in sequence.

    Steps (all optional, failure-tolerant):
      1. caption_service — ASS karaoke-style subtitles
      2. hook_visual_service — overlay text on first 3s
      3. audio_ducking_service — duck music during speech
      4. beat_sync_service — cuts aligned to beat

    Args:
        clips: List of clip dicts with "path" and optional "words"
        config: Pipeline config with feature flags
        task_id: Task identifier for logging

    Returns:
        Enhanced clips list with polish metadata added
    """
    for idx, clip in enumerate(clips):
        clip_path = clip.get("path")
        if not clip_path:
            logger.warning(f"[Polish] Clip {idx} has no path, skipping")
            continue

        _in = Path(clip_path)
        if not _in.exists():
            logger.warning(f"[Polish] Clip {idx} file not found: {_in}")
            continue

        logger.info(f"[Polish] Processing clip {idx}: {_in.name}")

        # ── PASO 1: Captiones animadas ASS ─────────────────────────────────────
        if config.get("add_subtitles", True) and clip.get("words"):
            cap_out = _in.with_name(f"cap_{_in.name}")
            try:
                from .caption_service import get_caption_service

                svc = get_caption_service()
                style = svc.style_for_template(
                    config.get("caption_template", "tiktok_viral"),
                    config.get("target_platform", "tiktok"),
                )
                ok = await svc.burn(
                    video_path=_in,
                    output_path=cap_out,
                    words=clip.get("words", []),
                    style=style,
                    platform=config.get("target_platform", "tiktok"),
                )
                if ok and cap_out.exists() and cap_out.stat().st_size > 0:
                    _in.unlink(missing_ok=True)
                    cap_out.rename(_in)
                    clip["captions_applied"] = True
                    clip["caption_style_used"] = style
                    logger.info(f"  [Captions] ASS {style} OK")
                else:
                    cap_out.unlink(missing_ok=True)
            except Exception as e:
                logger.debug(f"Caption service skipped clip {idx}: {e}")
                cap_out.unlink(missing_ok=True)

        # ── PASO 2: Hook visual overlay (primeros 3s) ───────────────────────────
        if config.get("add_hook_visual", True):
            hk_out = _in.with_name(f"hk_{_in.name}")
            try:
                from .hook_visual_service import add_hook_overlay_to_clip

                hook_text = (
                    clip.get("hook_text")
                    or clip.get("title")
                    or clip.get("text", "")[:60]
                )
                ok = await add_hook_overlay_to_clip(
                    input_path=_in,
                    output_path=hk_out,
                    hook_text=hook_text,
                    platform=config.get("target_platform", "tiktok"),
                )
                if ok and hk_out.exists() and hk_out.stat().st_size > 0:
                    _in.unlink(missing_ok=True)
                    hk_out.rename(_in)
                    clip["hook_visual_applied"] = True
                    logger.info(f"  [HookVisual] OK: {hook_text[:30]}...")
                else:
                    hk_out.unlink(missing_ok=True)
            except Exception as e:
                logger.debug(f"Hook visual skipped clip {idx}: {e}")
                hk_out.unlink(missing_ok=True)

        # ── PASO 3: Audio ducking (bajar música en palabras) ────────────────────
        if config.get("audio_ducking", True):
            duck_out = _in.with_name(f"duck_{_in.name}")
            try:
                from .audio_ducking_service import get_audio_ducking_service

                svc = get_audio_ducking_service()
                ok = await svc.apply_ducking(
                    input_path=_in,
                    output_path=duck_out,
                    words=clip.get("words", []),
                )
                if ok and duck_out.exists() and duck_out.stat().st_size > 0:
                    _in.unlink(missing_ok=True)
                    duck_out.rename(_in)
                    clip["audio_ducking_applied"] = True
                    logger.info(f"  [AudioDucking] OK")
                else:
                    duck_out.unlink(missing_ok=True)
            except Exception as e:
                logger.debug(f"Audio ducking skipped clip {idx}: {e}")
                duck_out.unlink(missing_ok=True)

        # ── PASO 4: Beat sync (cortes al ritmo) ─────────────────────────────────
        if config.get("beat_sync", False):
            bs_out = _in.with_name(f"bs_{_in.name}")
            try:
                from .beat_sync_service import get_beat_sync_service

                svc = get_beat_sync_service()
                result = await svc.sync_to_beat(
                    video_path=_in,
                    output_path=bs_out,
                    words=clip.get("words", []),
                )
                ok = isinstance(result, dict) and result.get("success")
                if ok and bs_out.exists() and bs_out.stat().st_size > 0:
                    _in.unlink(missing_ok=True)
                    bs_out.rename(_in)
                    clip["beat_sync_applied"] = True
                    clip["beat_sync_cuts"] = result.get("cuts_applied", 0)
                    logger.info(f"  [BeatSync] {result.get('cuts_applied', 0)} cuts OK")
                else:
                    bs_out.unlink(missing_ok=True)
            except Exception as e:
                logger.debug(f"Beat sync skipped clip {idx}: {e}")
                bs_out.unlink(missing_ok=True)

        # ── Cleanup de archivos temporales residuales ──────────────────────────
        for prefix in ("cap_", "hk_", "duck_", "bs_"):
            temp_file = _in.with_name(f"{prefix}{_in.name}")
            temp_file.unlink(missing_ok=True)

        # Actualizar path en el dict (por si acaso)
        clip["path"] = str(_in)

    return clips
