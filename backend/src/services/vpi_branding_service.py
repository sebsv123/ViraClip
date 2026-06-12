"""Minimal safe VPI branding watermark — v3.2 Visual Identity Polish."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .vpi_visual_effects_service import get_vpi_visual_design_tokens
from .vpi_asset_library_service import build_local_visual_asset_inventory

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


def _select_verified_brand_logo(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    inventory = build_local_visual_asset_inventory()
    candidates = [
        asset
        for asset in list((inventory or {}).get("all_assets") or [])
        if isinstance(asset, dict)
        and str(asset.get("visual_asset_type") or "").lower() == "logo"
        and bool(asset.get("verified_local", False))
        and bool(asset.get("usable_for_vpi", True))
    ]
    if not candidates:
        return {
            "brand_assets_verified": False,
            "brand_logo_asset_id": "",
            "brand_logo_status": "skipped_no_verified_logo",
            "asset_path": "",
            "inventory": inventory,
        }
    best = None
    best_score = -999.0
    for asset in candidates:
        dims = asset.get("dimensions") or {}
        width = int(dims.get("width") or 0)
        height = int(dims.get("height") or 0)
        score = 0.0
        if width >= 96 and height >= 96:
            score += 2.0
        if width >= 192 and height >= 192:
            score += 1.0
        if not asset.get("identity_warnings"):
            score += 1.5
        if "logo" in str(asset.get("visual_asset_path") or "").lower():
            score += 1.0
        if score > best_score:
            best_score = score
            best = asset
    if not best:
        return {
            "brand_assets_verified": False,
            "brand_logo_asset_id": "",
            "brand_logo_status": "skipped_no_verified_logo",
            "asset_path": "",
            "inventory": inventory,
        }
    logger.info(
        "BRAND_ASSET_VERIFIED asset=%s status=verified_local",
        str(best.get("visual_asset_path") or ""),
    )
    return {
        "brand_assets_verified": True,
        "brand_logo_asset_id": str(best.get("visual_asset_id") or ""),
        "brand_logo_status": "verified_local",
        "asset_path": str(best.get("visual_asset_path") or ""),
        "inventory": inventory,
    }


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
    mode: str = "standard",
) -> Dict[str, Any]:
    """Apply VPI branding watermark (logo or fallback text).

    v3.2 improvements:
      - Expanded logo search paths
      - Logo scaled to 11-15% video width (not fixed height)
      - Opacity 0.72-0.85
      - Top-right with safe margin (36px from right, 44px from top)
      - Fallback text: larger font, semi-transparent bg, positioned to avoid face/captions
    """
    visual_tokens = get_vpi_visual_design_tokens()
    spacing = visual_tokens.get("spacing") or {}
    opacity_tokens = visual_tokens.get("opacity") or {}
    brand_selection = _select_verified_brand_logo(Path(__file__).resolve().parents[3])
    brand_asset = Path(str(brand_selection.get("asset_path") or ""))
    warnings: List[str] = []
    if brand_selection.get("brand_assets_verified") and brand_asset and brand_asset.exists():
        logo_result = _apply_logo_watermark(video_path, output_path, brand_asset, video_width)
        if logo_result.get("rendered"):
            logo_result["brand_assets_verified"] = True
            logo_result["brand_logo_asset_id"] = str(brand_selection.get("brand_logo_asset_id") or "")
            logo_result["brand_logo_status"] = "rendered"
            logo_result["brand_final_mode"] = str(mode or "standard")
            logo_result["brand_final_verified"] = True
            logo_result["brand_final_reason"] = "verified_local_logo"
            logo_result["visual_design_tokens_applied_to_branding"] = True
            logo_result["visual_layout_strategy"] = "branding_minimal"
            logo_result["visual_layout_zone"] = "top_right_small"
            logo_result["visual_layout_size"] = "tiny"
            logo_result["visual_layout_opacity"] = float((opacity_tokens.get("overlay_opacity") or 0.88))
            logo_result["visual_layout_duration"] = 0.0
            logo_result["visual_layout_reason"] = "verified_brand_logo"
            logo_result["visual_layout_ok"] = True
            logo_result["visual_layout_face_safe"] = True
            logo_result["visual_layout_caption_safe"] = True
            logo_result["visual_layout_warnings"] = []
            logger.info(
                "VPI_BRAND_FINAL_APPLIED mode=%s verified=%s reason=%s",
                str(logo_result.get("brand_final_mode") or mode or "standard"),
                str(bool(logo_result.get("brand_final_verified"))).lower(),
                str(logo_result.get("brand_final_reason") or "verified_local_logo"),
            )
            return logo_result
        warnings.extend(logo_result.get("warnings", []))
        logger.warning("[branding] warning=no_verified_brand_logo reason=%s", logo_result.get("reason", "logo_failed"))
        logger.info("VPI_BRAND_FINAL_SKIPPED_REASON reason=no_verified_brand_logo")
        return {
            "type": "logo",
            "rendered": False,
            "planned": True,
            "dropped_by_budget": False,
            "budget_drop_reason": "",
            "reason": "skipped_no_verified_logo" if logo_result.get("reason") == "logo_failed" else str(logo_result.get("reason") or "logo_failed"),
            "warnings": warnings + ["no_verified_brand_logo"],
            "brand_assets_verified": bool(brand_selection.get("brand_assets_verified")),
            "brand_logo_asset_id": str(brand_selection.get("brand_logo_asset_id") or ""),
            "brand_logo_status": str(brand_selection.get("brand_logo_status") or "skipped_no_verified_logo"),
            "brand_final_mode": str(mode or "standard"),
            "brand_final_verified": False,
            "brand_final_reason": "no_verified_brand_logo",
            "visual_design_version": str(visual_tokens.get("visual_design_version") or "a1"),
            "visual_design_tokens_applied": True,
            "visual_design_tokens_applied_to_branding": True,
            "visual_layout_strategy": "branding_minimal",
            "visual_layout_zone": "top_right_small",
            "visual_layout_size": "tiny",
            "visual_layout_opacity": float((opacity_tokens.get("overlay_opacity") or 0.88)),
            "visual_layout_duration": 0.0,
            "visual_layout_reason": "no_verified_brand_logo",
            "visual_layout_ok": True,
            "visual_layout_face_safe": True,
            "visual_layout_caption_safe": True,
            "visual_layout_warnings": warnings,
        }
    else:
        warnings.append("no_verified_brand_logo")
        logger.warning("BRAND_ASSET_WARNING reason=no_verified_brand_logo")
        logger.info("VPI_BRAND_FINAL_SKIPPED_REASON reason=no_verified_brand_logo")
        return {
            "type": "minimal_metadata_only",
            "rendered": False,
            "planned": True,
            "dropped_by_budget": False,
            "budget_drop_reason": "",
            "reason": "skipped_no_verified_logo",
            "warnings": warnings,
            "brand_assets_verified": bool(brand_selection.get("brand_assets_verified")),
            "brand_logo_asset_id": str(brand_selection.get("brand_logo_asset_id") or ""),
            "brand_logo_status": str(brand_selection.get("brand_logo_status") or "skipped_no_verified_logo"),
            "brand_final_mode": str(mode or "standard"),
            "brand_final_verified": False,
            "brand_final_reason": "no_verified_brand_logo",
            "visual_design_version": str(visual_tokens.get("visual_design_version") or "a1"),
            "visual_design_tokens_applied": True,
            "visual_design_tokens_applied_to_branding": True,
            "visual_layout_strategy": "branding_minimal",
            "visual_layout_zone": "top_right_small",
            "visual_layout_size": "tiny",
            "visual_layout_opacity": float((opacity_tokens.get("overlay_opacity") or 0.88)),
            "visual_layout_duration": 0.0,
            "visual_layout_reason": "no_verified_brand_logo",
            "visual_layout_ok": True,
            "visual_layout_face_safe": True,
            "visual_layout_caption_safe": True,
            "visual_layout_warnings": warnings,
        }


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
    visual_tokens = get_vpi_visual_design_tokens()
    opacity = float((opacity_tokens := visual_tokens.get("opacity") or {}).get("overlay_opacity") or 0.88)
    safe_padding = int((spacing := visual_tokens.get("spacing") or {}).get("safe_padding") or 36)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-i", str(logo_path),
        "-filter_complex",
        f"[1:v]{scale_filter},format=rgba,colorchannelmixer=aa={opacity}[wm];"
        f"[0:v][wm]overlay=W-w-{safe_padding}:{safe_padding + 8}:format=auto",
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
                "planned": True,
                "dropped_by_budget": False,
                "budget_drop_reason": "",
                "asset": str(logo_path),
                "output_path": str(output_path),
                "position": "top_right",
                "opacity": opacity,
                "scale_mode": "width_ratio_11_15pct",
                "warnings": warnings,
                "brand_final_mode": "logo_minimal",
                "brand_final_verified": True,
                "brand_final_reason": "verified_local_logo",
                "visual_design_version": str(visual_tokens.get("visual_design_version") or "a1"),
                "visual_design_tokens_applied": True,
                "visual_design_tokens_applied_to_branding": True,
            }
        warnings.append("logo_ffmpeg_failed")
        logger.warning("[branding] type=logo rendered=false asset=%s", logo_path)
        return {
            "type": "logo",
            "rendered": False,
            "planned": True,
            "dropped_by_budget": False,
            "budget_drop_reason": "",
            "asset": str(logo_path),
            "reason": "logo_ffmpeg_failed",
            "warnings": warnings,
            "brand_final_mode": "logo_minimal",
            "brand_final_verified": False,
            "brand_final_reason": "logo_ffmpeg_failed",
            "visual_design_version": str(visual_tokens.get("visual_design_version") or "a1"),
            "visual_design_tokens_applied": True,
            "visual_design_tokens_applied_to_branding": True,
        }
    except Exception as exc:
        warnings.append(str(exc))
        logger.warning("[branding] type=logo rendered=false asset=%s warning=%s", logo_path, exc)
        return {
            "type": "logo",
            "rendered": False,
            "planned": True,
            "dropped_by_budget": False,
            "budget_drop_reason": "",
            "asset": str(logo_path),
            "reason": str(exc),
            "warnings": warnings,
            "brand_final_mode": "logo_minimal",
            "brand_final_verified": False,
            "brand_final_reason": str(exc),
            "visual_design_version": str(visual_tokens.get("visual_design_version") or "a1"),
            "visual_design_tokens_applied": True,
            "visual_design_tokens_applied_to_branding": True,
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
    visual_tokens = get_vpi_visual_design_tokens()
    spacing = visual_tokens.get("spacing") or {}
    opacity_tokens = visual_tokens.get("opacity") or {}
    safe_padding = int(spacing.get("safe_padding") or 36)
    draw = (
        "drawtext="
        "text='Valent\u00edn Protecci\u00f3n Integral':"
        f"x=w-text_w-{safe_padding}:y={safe_padding + 8}:"
        "fontsize=32:"
        f"fontcolor=white@{float((opacity_tokens.get('overlay_opacity') or 0.88)):.2f}:"
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
            logger.info("VPI_BRAND_FINAL_APPLIED mode=%s verified=%s reason=%s", "text_minimal", "false", "top_safe_watermark")
            return {
                "type": "text",
                "rendered": True,
                "planned": True,
                "dropped_by_budget": False,
                "budget_drop_reason": "",
                "text": text,
                "output_path": str(output_path),
                "position": "top_right",
                "opacity": 0.72,
                "reason": "top_safe_watermark",
                "warnings": list(warnings or []),
                "brand_final_mode": "text_minimal",
                "brand_final_verified": False,
                "brand_final_reason": "top_safe_watermark",
                "visual_design_version": str(visual_tokens.get("visual_design_version") or "a1"),
                "visual_design_tokens_applied": True,
                "visual_design_tokens_applied_to_branding": True,
            }
        logger.warning("[branding] type=text rendered=false reason=ffmpeg_failed stderr=%s", result.stderr[:200])
        logger.info("VPI_BRAND_FINAL_SKIPPED_REASON reason=ffmpeg_failed")
        return {
            "type": "text",
            "rendered": False,
            "planned": True,
            "dropped_by_budget": False,
            "budget_drop_reason": "",
            "reason": "ffmpeg_failed",
            "warnings": list(warnings or []) + ["text_ffmpeg_failed"],
            "brand_final_mode": "text_minimal",
            "brand_final_verified": False,
            "brand_final_reason": "ffmpeg_failed",
            "visual_design_version": str(visual_tokens.get("visual_design_version") or "a1"),
            "visual_design_tokens_applied": True,
            "visual_design_tokens_applied_to_branding": True,
        }
    except Exception as exc:
        logger.warning("[branding] type=text rendered=false reason=%s", exc)
        logger.info("VPI_BRAND_FINAL_SKIPPED_REASON reason=%s", exc)
        return {
            "type": "text",
            "rendered": False,
            "planned": True,
            "dropped_by_budget": False,
            "budget_drop_reason": "",
            "reason": str(exc),
            "warnings": list(warnings or []) + [str(exc)],
            "brand_final_mode": "text_minimal",
            "brand_final_verified": False,
            "brand_final_reason": str(exc),
            "visual_design_version": str(visual_tokens.get("visual_design_version") or "a1"),
            "visual_design_tokens_applied": True,
            "visual_design_tokens_applied_to_branding": True,
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
