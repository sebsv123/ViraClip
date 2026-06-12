from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any, Dict

from .vpi_visual_effects_service import get_vpi_visual_design_tokens


_REPO_ROOT = Path(__file__).resolve().parents[3]
_SAFE_OUTPUT_ROOT = (_REPO_ROOT / "exports" / "dynamic_overlay_cards").resolve()
_SAFE_TMP_OUTPUT_ROOT = Path("/tmp/viraclip_dynamic_overlay_cards").resolve()
_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".gif"}
_IMAGE_EXTS = {".png", ".apng"}
_OVERLAY_EXTS = _VIDEO_EXTS | _IMAGE_EXTS


def _safe_output_dir(output_dir: str | Path | None) -> Path:
    def _mkdir_or_tmp(path: Path) -> Path:
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except Exception:
            _SAFE_TMP_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
            return _SAFE_TMP_OUTPUT_ROOT

    if output_dir is None:
        return _mkdir_or_tmp(_SAFE_OUTPUT_ROOT)
    candidate = Path(output_dir)
    candidate = candidate if candidate.is_absolute() else (_REPO_ROOT / candidate)
    resolved = candidate.resolve()
    try:
        resolved.relative_to(_REPO_ROOT)
    except ValueError:
        return _mkdir_or_tmp(_SAFE_OUTPUT_ROOT)
    return _mkdir_or_tmp(resolved)


def _invalid_path(path_value: str | Path) -> bool:
    raw = str(path_value or "")
    if not raw.strip():
        return True
    return ".." in Path(raw).parts


def _probe_readable(path: Path) -> bool:
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return out.returncode == 0 and bool((out.stdout or "").strip())
    except Exception:
        return False


def _probe_duration(path: Path) -> float | None:
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if out.returncode != 0:
            return None
        return float((out.stdout or "").strip())
    except Exception:
        return None


def compose_dynamic_overlay_card(
    overlay_asset_path: str | Path,
    text_asset_path: str | Path,
    output_dir: str | Path | None = None,
    width: int = 1080,
    height: int = 1080,
    duration: float | None = None,
    position: str = "center",
    layout_strategy: str = "",
    layout_zone: str = "",
    layout_size: str = "",
    layout_opacity: float | None = None,
    layout_duration: float | None = None,
) -> Dict[str, Any]:
    visual_tokens = get_vpi_visual_design_tokens()
    out: Dict[str, Any] = {
        "planned": True,
        "rendered": False,
        "dropped_by_budget": False,
        "budget_drop_reason": "",
        "overlay_card_composed": False,
        "overlay_card_path": "",
        "overlay_card_exists": False,
        "ffprobe_readable": False,
        "duration": 0.0,
        "error": None,
        "reason": "not_started",
        "visual_design_version": str(visual_tokens.get("visual_design_version") or "a1"),
        "visual_design_tokens_applied": True,
        "visual_design_tokens_applied_to_reinforcement": True,
        "visual_layout_strategy": str(layout_strategy or ""),
        "visual_layout_zone": str(layout_zone or position or "center"),
        "visual_layout_size": str(layout_size or "small"),
        "visual_layout_opacity": float(layout_opacity if layout_opacity is not None else (visual_tokens.get("opacity") or {}).get("overlay_opacity") or 0.88),
        "visual_layout_duration": float(layout_duration if layout_duration is not None else (duration or 0.0) or 0.0),
        "visual_layout_ok": True,
        "visual_layout_warnings": [],
    }

    if _invalid_path(overlay_asset_path) or _invalid_path(text_asset_path):
        out["reason"] = "path_traversal_blocked"
        return out

    overlay_path = Path(overlay_asset_path).resolve()
    text_path = Path(text_asset_path).resolve()
    if not overlay_path.exists() or not overlay_path.is_file():
        out["reason"] = "overlay_missing"
        return out
    if not text_path.exists() or not text_path.is_file():
        out["reason"] = "text_missing"
        return out
    if text_path.suffix.lower() != ".png":
        out["reason"] = "text_not_png"
        return out
    if overlay_path.suffix.lower() not in _OVERLAY_EXTS:
        out["reason"] = "overlay_extension_not_supported"
        return out

    safe_dir = _safe_output_dir(output_dir)
    digest = hashlib.sha1(
        f"{overlay_path}|{text_path}|{width}|{height}|{duration}|{position}".encode("utf-8")
    ).hexdigest()[:12]

    overlay_ext = overlay_path.suffix.lower()
    is_video_like = overlay_ext in _VIDEO_EXTS
    output_ext = ".mp4" if is_video_like else ".png"
    output_path = (safe_dir / f"dynamic_overlay_card_{digest}{output_ext}").resolve()

    _position = str(layout_zone or position or "center")
    if _position in {"lower_third", "lower_center", "lower_center_small", "bottom", "bottom_safe"}:
        overlay_expr = "(W-w)/2:(H-h)*0.72"
    elif _position in {"bottom"}:
        overlay_expr = "(W-w)/2:(H-h)*0.82"
    elif _position in {"upper_left", "upper_left_small"}:
        overlay_expr = "20:20"
    elif _position in {"upper_right", "upper_right_small"}:
        overlay_expr = "W-w-20:20"
    elif _position in {"middle_safe", "center"}:
        overlay_expr = "(W-w)/2:(H-h)/2"
    else:
        overlay_expr = "(W-w)/2:(H-h)/2"

    filter_complex = (
        f"[0:v]scale={int(width)}:{int(height)}:force_original_aspect_ratio=decrease,"
        f"pad={int(width)}:{int(height)}:(ow-iw)/2:(oh-ih)/2:color=black@0[bg];"
        f"[1:v]scale=-1:min(280\\,ih)[txt];"
        f"[bg][txt]overlay={overlay_expr}:format=auto[outv]"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(overlay_path),
        "-i",
        str(text_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[outv]",
    ]
    if is_video_like:
        if duration and duration > 0:
            cmd.extend(["-t", str(float(duration))])
        cmd.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output_path)])
    else:
        cmd.extend(["-frames:v", "1", str(output_path)])

    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if run.returncode != 0:
            out["reason"] = "ffmpeg_failed"
            out["error"] = ((run.stderr or "") + "\n" + (run.stdout or "")).strip()[-600:]
            return out
    except FileNotFoundError:
        out["reason"] = "ffmpeg_missing"
        out["error"] = "ffmpeg_missing"
        return out
    except Exception as exc:
        out["reason"] = "compose_failed"
        out["error"] = str(exc)
        return out

    out["overlay_card_composed"] = True
    out["overlay_card_path"] = str(output_path)
    out["overlay_card_exists"] = output_path.exists() and output_path.is_file()
    out["ffprobe_readable"] = _probe_readable(output_path) if is_video_like else out["overlay_card_exists"]
    out["duration"] = float(_probe_duration(output_path) or 0.0) if is_video_like else 0.0
    out["rendered"] = bool(out["overlay_card_exists"])
    out["reason"] = "composed" if out["overlay_card_exists"] else "output_missing"
    out["visual_design_tokens_applied_to_reinforcement"] = True
    return out
