"""
variant_generator.py
====================
Generate quick A/B test variants from an already-rendered clip.

Each variant is produced by re-applying a single inexpensive layer:
  Variant A — different ASS caption style (e.g. highlight vs tiktok)
  Variant B — different BGM category (chill/cinematic vs hype)

The primary clip is never modified; variants are written as siblings:
  clip_1_viral_82_0000-0030.mp4          ← primary
  clip_1_viral_82_0000-0030_va.mp4       ← variant A (caption)
  clip_1_viral_82_0000-0030_vb.mp4       ← variant B (bgm)
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Caption style rotation order: if primary is style[i], use style[i+1 % len]
_CAPTION_STYLE_ROTATION: List[str] = ["tiktok", "highlight", "karaoke", "minimal", "neon"]

# BGM category fallback order for variant B
_BGM_VARIANT_CATEGORIES: List[str] = ["chill", "cinematic", "lofi", "upbeat", "hype"]


def _next_caption_style(current_style: str) -> str:
    """Return the next style in the rotation after *current_style*."""
    try:
        idx = _CAPTION_STYLE_ROTATION.index(current_style)
    except ValueError:
        idx = 0
    return _CAPTION_STYLE_ROTATION[(idx + 1) % len(_CAPTION_STYLE_ROTATION)]


async def _generate_caption_variant(
    source_path: Path,
    output_path: Path,
    words: List[Dict[str, Any]],
    current_style: str,
    platform: str = "tiktok",
) -> bool:
    """Re-burn captions with the next style in the rotation."""
    if not words:
        return False
    try:
        from .caption_service import burn_captions
        new_style = _next_caption_style(current_style)
        ok = await burn_captions(
            source_path, output_path, words,
            style=new_style, platform=platform,
        )
        if ok and output_path.exists() and output_path.stat().st_size > 0:
            logger.info("  [Variant A] Caption style %s → %s", current_style, new_style)
            return True
    except Exception as exc:
        logger.debug("  [Variant A] Caption variant failed: %s", exc)
    return False


async def _generate_bgm_variant(
    source_path: Path,
    output_path: Path,
    speech_segments: List[Dict[str, Any]],
    primary_category: str = "hype",
    bgm_volume: float = 0.13,
) -> Optional[str]:  # returns variant_category used, or None on failure
    """Mix a different BGM category than the primary clip used."""
    try:
        from .beat_sync_service import get_beat_sync_service, BGMLibrary
        svc = get_beat_sync_service()

        # Pick a category that differs from what the primary already used
        variant_category: Optional[str] = None
        for cat in _BGM_VARIANT_CATEGORIES:
            if cat != primary_category:
                variant_category = cat
                break

        result = await svc.mix_bgm_beat_synced(
            video_path=source_path,
            output_path=output_path,
            speech_segments=speech_segments,
            bgm_volume=bgm_volume,
            preferred_category=variant_category,
        )
        if result.get("success") and output_path.exists() and output_path.stat().st_size > 0:
            logger.info(
                "  [Variant B] BGM category: %s → %s",
                primary_category, variant_category,
            )
            return variant_category
    except Exception as exc:
        logger.debug("  [Variant B] BGM variant failed: %s", exc)
    return None


async def generate_clip_variants(
    clip_path: Path,
    words: List[Dict[str, Any]],
    platform: str = "tiktok",
    primary_caption_style: str = "tiktok",
    primary_bgm_category: str = "hype",
    bgm_volume: float = 0.13,
) -> List[Dict[str, Any]]:
    """
    Generate up to 2 quick A/B variants for *clip_path*.

    Returns a list of variant dicts (may be empty if all variants fail):
        [{"path": str, "variant": "A", "label": "caption:highlight"}, ...]
    """
    variants: List[Dict[str, Any]] = []

    speech_segs = [
        {"start": w["start"], "end": w.get("end", w["start"] + 0.3)}
        for w in (words or [])[::3]
    ]

    stem = clip_path.stem
    suffix = clip_path.suffix
    parent = clip_path.parent

    path_a = parent / f"{stem}_va{suffix}"
    path_b = parent / f"{stem}_vb{suffix}"

    # Run both variants concurrently
    ok_a, used_category = await asyncio.gather(
        _generate_caption_variant(clip_path, path_a, words, primary_caption_style, platform),
        _generate_bgm_variant(clip_path, path_b, speech_segs, primary_bgm_category, bgm_volume),
        return_exceptions=False,
    )

    if ok_a:
        new_style = _next_caption_style(primary_caption_style)
        variants.append({
            "path":    str(path_a),
            "variant": "A",
            "label":   f"caption:{new_style}",
            "type":    "caption_style",
        })

    if used_category:
        variants.append({
            "path":    str(path_b),
            "variant": "B",
            "label":   f"bgm:{used_category}",
            "type":    "bgm_category",
        })

    return variants
