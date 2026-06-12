from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any, Dict

from .vpi_visual_effects_service import get_vpi_visual_design_tokens


_REPO_ROOT = Path(__file__).resolve().parents[3]
_SAFE_OUTPUT_ROOT = (_REPO_ROOT / "exports" / "final_overlay_composed").resolve()
_SAFE_TMP_OUTPUT_ROOT = Path("/tmp/viraclip_final_overlay_composed").resolve()
_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".gif"}
_IMAGE_EXTS = {".png", ".apng"}
_OVERLAY_EXTS = _VIDEO_EXTS | _IMAGE_EXTS
_POSITIONS = {"upper_right", "upper_left", "lower_right", "lower_left", "center", "lower_center"}


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


def _probe_readable(path: Path) -> bool:
    return _probe_duration(path) is not None


def _overlay_xy(position: str) -> str:
    pos = (position or "").lower()
    if pos == "upper_left":
        return "20:20"
    if pos == "lower_right":
        return "W-w-20:H-h-20"
    if pos == "lower_left":
        return "20:H-h-20"
    if pos == "center":
        return "(W-w)/2:(H-h)/2"
    if pos == "lower_center":
        return "(W-w)/2:H-h-24"
    return "W-w-20:20"  # upper_right


def apply_overlay_card_to_video(
    input_video_path: str | Path,
    overlay_card_path: str | Path,
    output_video_path: str | Path | None = None,
    position: str = "upper_right",
    start_time: float = 0.35,
    duration: float = 2.5,
    scale_width: int | None = 420,
    opacity: float = 1.0,
    layout_strategy: str = "",
    layout_zone: str = "",
    layout_size: str = "",
    layout_opacity: float | None = None,
    layout_duration: float | None = None,
) -> Dict[str, Any]:
    visual_tokens = get_vpi_visual_design_tokens()
    token_opacity = float((visual_tokens.get("opacity") or {}).get("overlay_opacity") or 0.88)
    opacity = min(max(float(layout_opacity if layout_opacity is not None else opacity), 0.0), 1.0) if (layout_opacity is not None or opacity is not None) else token_opacity
    out: Dict[str, Any] = {
        "planned": True,
        "rendered": False,
        "dropped_by_budget": False,
        "budget_drop_reason": "",
        "motion_overlay_applied": False,
        "final_output_uses_motion_overlay": False,
        "output_video_path": "",
        "output_exists": False,
        "ffprobe_readable": False,
        "overlay_position": str(position),
        "overlay_start_time": float(start_time),
        "overlay_duration": float(duration),
        "error": None,
        "reason": "not_started",
        "visual_design_version": str(visual_tokens.get("visual_design_version") or "a1"),
        "visual_design_tokens_applied": True,
        "visual_design_tokens_applied_to_reinforcement": True,
        "visual_layout_strategy": str(layout_strategy or ""),
        "visual_layout_zone": str(layout_zone or position or "upper_right"),
        "visual_layout_size": str(layout_size or "small"),
        "visual_layout_opacity": float(opacity),
        "visual_layout_duration": float(layout_duration if layout_duration is not None else duration),
        "visual_layout_ok": True,
        "visual_layout_warnings": [],
    }

    if _invalid_path(input_video_path) or _invalid_path(overlay_card_path):
        out["reason"] = "path_traversal_blocked"
        return out

    daily_mode_active = os.environ.get("VPI_DAILY_MODE", "").lower() in {"1", "true", "yes", "on"}
    if daily_mode_active:
        logger = None
        try:
            from logging import getLogger

            logger = getLogger(__name__)
            logger.info(
                "VPI_PIP_ACTIVE_BRANCH_DISABLED reason=daily_mode input=%s overlay=%s",
                str(input_video_path),
                str(overlay_card_path),
            )
            logger.info(
                "VPI_MOTION_OVERLAY_BOTTOM_RIGHT_DISABLED reason=daily_mode position=%s",
                str(position),
            )
            logger.info(
                "VPI_FINAL_OVERLAY_CARD_DISABLED_DAILY input=%s overlay=%s",
                str(input_video_path),
                str(overlay_card_path),
            )
        except Exception:
            pass
        input_path = Path(input_video_path).resolve()
        out.update(
            {
                "motion_overlay_applied": False,
                "final_output_uses_motion_overlay": False,
                "output_video_path": str(input_path),
                "output_exists": input_path.exists() and input_path.is_file(),
                "ffprobe_readable": _probe_readable(input_path) if input_path.exists() and input_path.is_file() else False,
                "reason": "daily_mode_no_overlay",
                "planned": False,
            }
        )
        return out

    try:
        _start = float(start_time)
        _dur = float(duration)
        _opacity = float(opacity if opacity is not None else token_opacity)
    except Exception:
        out["reason"] = "invalid_numeric_params"
        return out

    if _start < 0 or _dur <= 0:
        out["reason"] = "invalid_timing"
        return out
    if _opacity < 0 or _opacity > 1:
        out["reason"] = "invalid_opacity"
        return out
    layout_position = str(layout_zone or position or "upper_right")
    layout_position = {
        "upper_left_small": "upper_left",
        "upper_right_small": "upper_right",
        "lower_center_small": "lower_center",
        "middle_safe": "center",
        "top_safe": "upper_right",
        "bottom_safe": "lower_center",
        "final_safe": "lower_center",
    }.get(layout_position, layout_position)
    if layout_position not in _POSITIONS:
        out["reason"] = "invalid_position"
        return out

    input_path = Path(input_video_path).resolve()
    overlay_path = Path(overlay_card_path).resolve()
    if not input_path.exists() or not input_path.is_file():
        out["reason"] = "input_video_missing"
        return out
    if not _probe_readable(input_path):
        out["reason"] = "input_video_unreadable"
        return out
    if not overlay_path.exists() or not overlay_path.is_file():
        out["reason"] = "overlay_missing"
        return out
    if overlay_path.suffix.lower() not in _OVERLAY_EXTS:
        out["reason"] = "overlay_extension_not_supported"
        return out

    if output_video_path is None:
        safe_dir = _safe_output_dir(None)
        digest = hashlib.sha1(
            f"{input_path}|{overlay_path}|{layout_position}|{_start}|{_dur}|{scale_width}|{_opacity}".encode("utf-8")
        ).hexdigest()[:10]
        output_path = (safe_dir / f"{input_path.stem}_with_overlay_{digest}.mp4").resolve()
    else:
        safe_dir = _safe_output_dir(Path(output_video_path).parent)
        output_path = (safe_dir / Path(output_video_path).name).resolve()

    xy = _overlay_xy(layout_position if layout_position in _POSITIONS else position)
    overlay_scale = f"scale={int(scale_width)}:-2," if scale_width and int(scale_width) > 0 else ""
    alpha = f"colorchannelmixer=aa={_opacity}," if _opacity < 0.999 else ""
    overlay_pre = f"[1:v]{overlay_scale}{alpha}setpts=PTS-STARTPTS[ov]"
    overlay_filter = f"[0:v][ov]overlay={xy}:enable='between(t,{_start},{_start + _dur})':format=auto[outv]"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-i",
        str(overlay_path),
        "-filter_complex",
        f"{overlay_pre};{overlay_filter}",
        "-map",
        "[outv]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-c:a",
        "aac",
        "-shortest",
        str(output_path),
    ]

    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if run.returncode != 0:
            out["reason"] = "ffmpeg_failed"
            out["error"] = ((run.stderr or "") + "\n" + (run.stdout or "")).strip()[-800:]
            return out
    except FileNotFoundError:
        out["reason"] = "ffmpeg_missing"
        out["error"] = "ffmpeg_missing"
        return out
    except Exception as exc:
        out["reason"] = "compose_failed"
        out["error"] = str(exc)
        return out

    exists = output_path.exists() and output_path.is_file()
    readable = _probe_readable(output_path) if exists else False
    out.update(
        {
            "motion_overlay_applied": bool(exists and readable),
            "final_output_uses_motion_overlay": bool(exists and readable),
            "rendered": bool(exists and readable),
            "output_video_path": str(output_path),
            "output_exists": exists,
            "ffprobe_readable": readable,
            "reason": "applied" if exists and readable else "output_unreadable",
            "visual_design_tokens_applied_to_reinforcement": True,
        }
    )
    return out
