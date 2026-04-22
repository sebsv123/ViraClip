"""
Variant Generator

Generate A/B test variants from an already-rendered clip using FFmpeg.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


async def generate_clip_variants(
    clip_path: Path,
    words: List[Dict[str, Any]],
    platform: str,
    primary_caption_style: str,
    primary_bgm_category: str,
) -> List[Dict[str, Any]]:
    """
    Generate 2 visual variants of a clip using FFmpeg.

    Args:
        clip_path: Path to the primary clip
        words: Word-level timings (not used in this implementation but kept for API compatibility)
        platform: Target platform
        primary_caption_style: Primary caption style (not used but kept for API compatibility)
        primary_bgm_category: Primary BGM category (not used but kept for API compatibility)

    Returns:
        List of variant dicts with path, variant_type, and style info
    """
    variants: List[Dict[str, Any]] = []

    # Variant A: "caption_swap" - cleaner look with contrast/saturation adjustment
    variant_a_path = clip_path.with_name(f"variant_caption_swap_{clip_path.name}")
    try:
        # FFmpeg: eq filter for cleaner look + drawtext with different styling
        cmd_a = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(clip_path),
            "-vf", "eq=contrast=1.1:saturation=0.85,drawtext=text='[A]':fontsize=30:x=(w-text_w)/2:y=20:fontcolor=white",
            "-c:a", "copy",
            str(variant_a_path),
        ]
        proc_a = await asyncio.create_subprocess_exec(
            *cmd_a,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc_a.communicate(), timeout=120.0)

        if variant_a_path.exists() and variant_a_path.stat().st_size > 0:
            variants.append({
                "path": str(variant_a_path),
                "variant_type": "caption_swap",
                "style": "cleaner",
            })
            logger.info("[VariantGenerator] Created variant A (caption_swap)")
        else:
            variant_a_path.unlink(missing_ok=True)
    except Exception as exc_a:
        logger.debug("[VariantGenerator] Variant A failed: %s", exc_a)
        variant_a_path.unlink(missing_ok=True)

    # Variant B: "energy_boost" - more vibrant look with higher contrast and saturation
    variant_b_path = clip_path.with_name(f"variant_energy_boost_{clip_path.name}")
    try:
        # FFmpeg: eq filter for more vibrant look
        cmd_b = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(clip_path),
            "-vf", "eq=contrast=1.25:saturation=1.45:brightness=0.03,drawtext=text='[B]':fontsize=30:x=(w-text_w)/2:y=20:fontcolor=yellow",
            "-c:a", "copy",
            str(variant_b_path),
        ]
        proc_b = await asyncio.create_subprocess_exec(
            *cmd_b,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc_b.communicate(), timeout=120.0)

        if variant_b_path.exists() and variant_b_path.stat().st_size > 0:
            variants.append({
                "path": str(variant_b_path),
                "variant_type": "energy_boost",
                "style": "vibrant",
            })
            logger.info("[VariantGenerator] Created variant B (energy_boost)")
        else:
            variant_b_path.unlink(missing_ok=True)
    except Exception as exc_b:
        logger.debug("[VariantGenerator] Variant B failed: %s", exc_b)
        variant_b_path.unlink(missing_ok=True)

    return variants
