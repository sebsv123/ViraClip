"""Minimal safe VPI branding watermark — v3.2 Visual Identity Polish."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def find_brand_asset(repo_root: Optional[Path] = None) -> Optional[Path]:
    """Search logo in expanded candidate paths (v3.2)."""
    root = repo_root or Path.cwd()
    candidates = [
        # Primary VPI brand logos
        root / "frontend/public/logo-vpi.png",
        root / "frontend/public/logo.png",
        root / "assets/brand/vpi_logo.png",
        root / "assets/brand/logo.png",
        # Fallback paths
        root / "assets/banner.png",
        root / "frontend/src/app/icon.png",
        # Docker container paths
        Path("/app/frontend/public/logo-vpi.png"),
        Path("/app/frontend/public/logo.png"),
        Path("/app/assets/brand/vpi_logo.png"),
        Path("/app/assets/brand/logo.png"),
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.suffix.lower() in {".png", ".webp"}:
            logger.info("[branding] logo_found=true path=%s", candidate)
            return candidate
    logger.info("[branding] logo_found=false reason=no_logo_in_candidates")
    return None


def _compute_logo_scale(target_w: int, logo_w: int) -> str:
    """Scale logo to 11-15% of video width."""
    ratio = logo_w / target_w if logo_w > 0 else 0.15
    if ratio > 0.15:
        # Scale down to 13% width
        pct = 0.13
    elif ratio < 0.11:
        # Scale up to 13% width
        pct = 0.13
    else:
        pct = ratio  # keep as-is if already in 11-15% range
    target_px = int(target_w * pct)
    return f"scale={target_px}:-1"


def apply_vpi_branding(
    video_path: Path,
    output_path: Path,
    video_width: int = 1080,
) -> Dict[str, Any]:
    """Apply VPI branding watermark (logo or fallback text).

    v3.2 improvements:
      - Expanded logo search paths
      - Logo scaled to 11-15% video width (not fixed height)
      - Opacity 0.72-0.85
      - Top-right with safe margin (36px from right, 44px from top)
      - Fallback text: larger font, semi-transparent bg, positioned to avoid face/captions
    """
    brand_asset = find_brand_asset(Path(__file__).resolve().parents[3])
    warnings: List[str] = []
    if brand_asset:
        logo_result = _apply_logo_watermark(video_path, output_path, brand_asset, video_width)
        if logo_result.get("rendered"):
            return logo_result
        warnings.extend(logo_result.get("warnings", []))
        logger.warning("[branding] fallback=text reason=%s", logo_result.get("reason", "logo_failed"))
    else:
        warnings.append("logo_not_found")

    return _apply_text_watermark(video_path, output_path, warnings)


def _apply_logo_watermark(
    video_path: Path,
    output_path: Path,
    logo_path: Path,
    video_width: int = 1080,
) -> Dict[str, Any]:
    """Apply logo watermark with v3.2 specs: 11-15% width, opacity 0.72-0.85, top-right."""
    warnings: List[str] = []

    # Probe logo dimensions for smart scaling
    logo_dims = _probe_image_dimensions(logo_path)
    logo_w = logo_dims.get("width", 0)
    scale_filter = _compute_logo_scale(video_width, logo_w) if logo_w > 0 else "scale=-1:84"

    # Opacity: 0.78 (midpoint of 0.72-0.85 range)
    opacity = 0.78

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-i", str(logo_path),
        "-filter_complex",
        f"[1:v]{scale_filter},format=rgba,colorchannelmixer=aa={opacity}[wm];"
        f"[0:v][wm]overlay=W-w-36:44:format=auto",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "copy",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if result.returncode == 0 and output_path.exists():
            logger.info(
                "[branding] type=logo rendered=true asset=%s opacity=%.2f scale=width_ratio",
                logo_path, opacity,
            )
            return {
                "type": "logo",
                "rendered": True,
                "asset": str(logo_path),
                "output_path": str(output_path),
                "position": "top_right",
                "opacity": opacity,
                "scale_mode": "width_ratio_11_15pct",
                "warnings": warnings,
            }
        warnings.append("logo_ffmpeg_failed")
        logger.warning("[branding] type=logo rendered=false asset=%s", logo_path)
        return {
            "type": "logo",
            "rendered": False,
            "asset": str(logo_path),
            "reason": "logo_ffmpeg_failed",
            "warnings": warnings,
        }
    except Exception as exc:
        warnings.append(str(exc))
        logger.warning("[branding] type=logo rendered=false asset=%s warning=%s", logo_path, exc)
        return {
            "type": "logo",
            "rendered": False,
            "asset": str(logo_path),
            "reason": str(exc),
            "warnings": warnings,
        }


def _apply_text_watermark(
    video_path: Path,
    output_path: Path,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Apply fallback text watermark — v3.2: larger font, semi-transparent bg, safe position.

    Positioned top-right with safe margin to avoid covering face or captions.
    Font size 32 (was 26), box opacity 0.22 (was 0.18) for better readability.
    """
    text = "Valentín Protección Integral"
    draw = (
        "drawtext="
        "text='Valent\u00edn Protecci\u00f3n Integral':"
        "x=w-text_w-36:y=48:"
        "fontsize=32:"
        "fontcolor=white@0.72:"
        "box=1:boxcolor=black@0.22:boxborderw=14"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", draw,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "copy",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if result.returncode == 0 and output_path.exists():
            logger.info("[branding] type=text rendered=true reason=top_safe_watermark")
            return {
                "type": "text",
                "rendered": True,
                "text": text,
                "output_path": str(output_path),
                "position": "top_right",
                "opacity": 0.72,
                "reason": "top_safe_watermark",
                "warnings": list(warnings or []),
            }
        logger.warning("[branding] type=text rendered=false reason=ffmpeg_failed stderr=%s", result.stderr[:200])
        return {
            "type": "text",
            "rendered": False,
            "reason": "ffmpeg_failed",
            "warnings": list(warnings or []) + ["text_ffmpeg_failed"],
        }
    except Exception as exc:
        logger.warning("[branding] type=text rendered=false reason=%s", exc)
        return {
            "type": "text",
            "rendered": False,
            "reason": str(exc),
            "warnings": list(warnings or []) + [str(exc)],
        }


def _probe_image_dimensions(image_path: Path) -> Dict[str, int]:
    """Probe image dimensions using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            str(image_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(",")
            if len(parts) >= 2:
                return {"width": int(parts[0]), "height": int(parts[1])}
    except Exception:
        pass
    return {"width": 0, "height": 0}
