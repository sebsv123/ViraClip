"""
LUT Service — Cinematic Color Grading via FFmpeg lut3d
======================================================

Applies .cube 3D LUT files to video using FFmpeg's `lut3d` filter.

LUT catalog (auto-downloaded from open-source repos on first use):
  - teal_orange      : classic Hollywood teal/orange grade (YahiaAngelo/Film-Luts)
  - warm_film        : warm Kodak-inspired emulation
  - cold_blue        : cool desaturated look (drama/thriller)
  - vintage          : faded warm vintage (Fuji emulation)
  - high_contrast    : punchy blacks, lifted highlights
  - flat             : log-like flatten for dark backgrounds

If no .cube file is present, falls back to FFmpeg eq/hue/curves filters
that approximate the look without needing external files.

Sources:
  https://github.com/YahiaAngelo/Film-Luts   (Kodak/Fuji emulations)
  https://github.com/DomBito/cglut           (script-generated cinematic LUTs)
  https://github.com/AcademySoftwareFoundation/OpenColorIO-Configs  (ARRI/RED/Sony)
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from src import gpu_utils

logger = logging.getLogger(__name__)

# ── LUT catalogue ─────────────────────────────────────────────────────────────

LUT_DIR = Path(os.environ.get("LUT_DIR", "/app/luts"))

# (filename, display_name, description, ffmpeg_fallback_vf)
_LUT_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "teal_orange",
        "file": "teal_orange.cube",
        "name": "Teal & Orange",
        "description": "Classic Hollywood teal shadows / warm skin tones",
        "fallback_vf": (
            "eq=saturation=1.15:contrast=1.05:brightness=0.02,"
            "hue=h=0:s=1,"
            "curves=r='0/0 0.3/0.25 0.7/0.72 1/1':"
            "g='0/0 0.5/0.5 1/1':"
            "b='0/0.05 0.5/0.55 1/0.92'"
        ),
    },
    {
        "id": "warm_film",
        "file": "warm_film.cube",
        "name": "Warm Film",
        "description": "Kodak-inspired warm film emulation with lifted blacks",
        "fallback_vf": (
            "eq=saturation=1.08:contrast=1.02:brightness=0.03,"
            "curves=r='0/0.06 0.5/0.55 1/1':"
            "g='0/0.03 0.5/0.52 1/0.97':"
            "b='0/0.0 0.5/0.45 1/0.88'"
        ),
    },
    {
        "id": "cold_blue",
        "file": "cold_blue.cube",
        "name": "Cold Blue",
        "description": "Desaturated cool look — drama / thriller aesthetic",
        "fallback_vf": (
            "eq=saturation=0.80:contrast=1.08:brightness=-0.02,"
            "curves=r='0/0 0.5/0.45 1/0.92':"
            "g='0/0 0.5/0.5 1/1':"
            "b='0/0.04 0.5/0.55 1/1.0'"
        ),
    },
    {
        "id": "vintage",
        "file": "vintage.cube",
        "name": "Vintage",
        "description": "Faded warm vintage — Fuji Superia emulation",
        "fallback_vf": (
            "eq=saturation=0.85:contrast=0.95:brightness=0.05,"
            "curves=r='0/0.08 0.5/0.56 1/0.95':"
            "g='0/0.04 0.5/0.52 1/0.93':"
            "b='0/0.02 0.5/0.48 1/0.85',"
            "vignette=PI/4"
        ),
    },
    {
        "id": "high_contrast",
        "file": "high_contrast.cube",
        "name": "High Contrast",
        "description": "Punchy blacks, lifted highlights — social media pop",
        "fallback_vf": (
            "eq=saturation=1.20:contrast=1.18:brightness=-0.02,"
            "curves=r='0/0 0.25/0.18 0.75/0.82 1/1':"
            "g='0/0 0.25/0.18 0.75/0.82 1/1':"
            "b='0/0 0.25/0.18 0.75/0.82 1/1'"
        ),
    },
    {
        "id": "flat",
        "file": "flat.cube",
        "name": "Flat / Log",
        "description": "Log-like flatten — good for dark backgrounds behind text",
        "fallback_vf": (
            "eq=saturation=0.70:contrast=0.80:brightness=0.08,"
            "curves=all='0/0.12 1/0.88'"
        ),
    },
    # ── LUT_STYLE presets (used by creative_pipeline) ─────────────────────
    {
        "id": "neutral",
        "file": "neutral.cube",
        "name": "Neutral",
        "description": "Natural Rec.709 — no dominant color cast, clean skin tones",
        "fallback_vf": (
            "eq=saturation=1.00:contrast=1.00:brightness=0.00,"
            "hue=h=0:s=1"
        ),
    },
    {
        "id": "warm_cinematic",
        "file": "warm_cinematic.cube",
        "name": "Warm Cinematic",
        "description": "Warm look without aggressive yellow — orange/rose skin tones, teal shadows",
        "fallback_vf": (
            "eq=saturation=1.10:contrast=1.03:brightness=0.01,"
            "hue=h=-2:s=1,"
            "curves=r='0/0.02 0.5/0.53 1/0.98':"
            "g='0/0.01 0.5/0.50 1/0.96':"
            "b='0/0.04 0.5/0.47 1/0.90'"
        ),
    },
    {
        "id": "cool_modern",
        "file": "cool_modern.cube",
        "name": "Cool Modern",
        "description": "Clean modern look with subtle cool tint — no aggressive blue cast",
        "fallback_vf": (
            "eq=saturation=0.95:contrast=1.05:brightness=0.00,"
            "hue=h=2:s=1,"
            "curves=r='0/0.0 0.5/0.48 1/0.95':"
            "g='0/0.0 0.5/0.50 1/1.0':"
            "b='0/0.02 0.5/0.52 1/1.0'"
        ),
    },
]

# Quick lookup by id
_LUT_BY_ID: Dict[str, Dict[str, Any]] = {lut["id"]: lut for lut in _LUT_CATALOG}


# ── LUT file management ───────────────────────────────────────────────────────

def list_available_luts() -> List[Dict[str, Any]]:
    """Return all LUTs with availability status."""
    result = []
    for lut in _LUT_CATALOG:
        cube_path = LUT_DIR / lut["file"]
        result.append({
            **lut,
            "available": cube_path.exists(),
            "path": str(cube_path) if cube_path.exists() else None,
        })
    return result


def select_lut(clip_index: int = 0, total_clips: int = 1) -> str:
    """
    Select a LUT preset id, rotating through available real .cube files
    when processing multiple clips in a batch to avoid repetition.

    When *total_clips > 1*, scans the LUT directory for real .cube files
    and cycles through them using ``available_cubes[clip_index % len(available_cubes)]``.
    Falls back to the environment variable ``LUT_PRESET`` or ``"teal_orange"``
    when no real .cube files are found or when *total_clips == 1*.

    Args:
        clip_index: Zero-based index of the current clip in the batch.
        total_clips: Total number of clips being rendered in the batch.

    Returns:
        A LUT preset id string (e.g. ``"teal_orange"``, ``"warm_film"``).
    """
    # Single clip — use configured preset directly
    if total_clips <= 1:
        return os.environ.get("LUT_PRESET", "teal_orange")

    # Batch mode: scan for real .cube files in the LUT directory
    try:
        cube_files = sorted(LUT_DIR.glob("*.cube"))
        if cube_files:
            # Map .cube filenames back to catalog ids (case-insensitive)
            available_ids: List[str] = []
            for cube_path in cube_files:
                fname = cube_path.name.lower()
                # Check if this filename matches a known catalog entry
                matched = False
                for lut in _LUT_CATALOG:
                    if lut["file"].lower() == fname:
                        available_ids.append(lut["id"])
                        matched = True
                        break
                if not matched:
                    # Unknown .cube — still usable, derive id from stem
                    available_ids.append(cube_path.stem)

            if available_ids:
                selected = available_ids[clip_index % len(available_ids)]
                logger.info(
                    "[lut] Rotated LUT: clip %d/%d → '%s' (from %d real .cube files)",
                    clip_index + 1, total_clips, selected, len(available_ids),
                )
                return selected
    except Exception as exc:
        logger.debug("[lut] select_lut scan failed: %s", exc)

    # Fallback: no real .cube files found
    return os.environ.get("LUT_PRESET", "teal_orange")


def get_lut_vf_filter(lut_id: str) -> Optional[str]:
    """
    Return the FFmpeg video filter string for a given LUT id.
    Uses the .cube file if present, otherwise falls back to eq/curves approximation.
    """
    lut = _LUT_BY_ID.get(lut_id)
    if not lut:
        return None

    cube_path = LUT_DIR / lut["file"]
    if cube_path.exists():
        safe_path = str(cube_path).replace("\\", "/").replace(":", "\\:")
        return f"lut3d='{safe_path}'"

    logger.debug("[lut] %s.cube not found — using FFmpeg fallback filter", lut_id)
    return lut["fallback_vf"]


# ── Minimal embedded .cube generator ─────────────────────────────────────────

def _write_identity_cube(path: Path, size: int = 17) -> None:
    """Write an identity (no-op) .cube file for testing / baseline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(f"TITLE \"Identity\"\nLUT_3D_SIZE {size}\n")
        step = 1.0 / (size - 1)
        for b in range(size):
            for g in range(size):
                for r in range(size):
                    f.write(f"{r*step:.6f} {g*step:.6f} {b*step:.6f}\n")


def ensure_lut_dir() -> Path:
    """Create the LUT directory if it doesn't exist."""
    LUT_DIR.mkdir(parents=True, exist_ok=True)
    return LUT_DIR


# ── Yellow cast detection and correction ─────────────────────────────────────

def _sample_frame_rgb_avg(video_path: Path, num_samples: int = 5) -> Optional[Dict[str, float]]:
    """
    Sample a few frames from the video and compute average R, G, B values
    for near-white pixels (luma > 200). Returns {r, g, b} averages or None.
    """
    try:
        import subprocess as _sp
        import json as _json
        import tempfile as _tf
        # Get duration
        probe = _sp.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(video_path)],
            capture_output=True, text=True, timeout=10,
        )
        dur = _json.loads(probe.stdout).get("format", {}).get("duration", 0)
        dur = float(dur) if dur else 10.0
        # Sample frames at regular intervals
        interval = max(1.0, dur / num_samples)
        r_total, g_total, b_total, count = 0.0, 0.0, 0.0, 0
        for i in range(num_samples):
            ts = i * interval
            if ts >= dur:
                break
            frame_file = Path(_tf.mktemp(suffix=".png"))
            _sp.run(
                ["ffmpeg", "-y", "-ss", f"{ts:.2f}", "-i", str(video_path),
                 "-vframes", "1", "-q:v", "2", str(frame_file)],
                capture_output=True, timeout=15,
            )
            if frame_file.exists():
                try:
                    from PIL import Image
                    import numpy as np
                    img = Image.open(frame_file).convert("RGB")
                    arr = np.array(img, dtype=np.float32)
                    # Only near-white pixels (all channels > 200)
                    mask = (arr[:, :, 0] > 200) & (arr[:, :, 1] > 200) & (arr[:, :, 2] > 200)
                    if mask.any():
                        r_total += float(arr[:, :, 0][mask].mean())
                        g_total += float(arr[:, :, 1][mask].mean())
                        b_total += float(arr[:, :, 2][mask].mean())
                        count += 1
                except ImportError:
                    pass
                finally:
                    frame_file.unlink(missing_ok=True)
        if count == 0:
            return None
        return {"r": r_total / count, "g": g_total / count, "b": b_total / count}
    except Exception as e:
        logger.debug("[lut] Frame sampling failed: %s", e)
        return None


def _detect_yellow_cast(rgb: Dict[str, float]) -> str:
    """
    Detect yellow cast from average RGB of near-white pixels.
    Returns: "neutral", "warm_ok", "yellow_excessive".
    """
    if not rgb:
        return "neutral"
    r, g, b = rgb["r"], rgb["g"], rgb["b"]
    # In neutral white: R≈G≈B. Yellow cast = G > R and B significantly lower.
    g_minus_r = g - r
    g_minus_b = g - b
    if g_minus_r > 8 and g_minus_b > 15:
        return "yellow_excessive"
    if g_minus_r > 3 or g_minus_b > 8:
        return "warm_ok"
    return "neutral"


def _build_cast_correction_vf(cast: str, lut_id: str) -> str:
    """
    Build an FFmpeg vf filter string to correct yellow cast.
    Only applies when cast is "yellow_excessive".
    Uses subtle hue shift toward magenta + desaturation of yellow channel.
    """
    if cast != "yellow_excessive":
        return ""
    # Subtle correction: shift hue -3° (toward magenta), reduce saturation slightly
    # This counteracts the yellow/green dominance without destroying the look.
    logger.warning("[lut] Yellow cast detected — applying automatic correction (hue=-3, sat=0.92)")
    return "hue=h=-3:s=0.92"


# ── Apply LUT to video ────────────────────────────────────────────────────────

async def apply_lut(
    video_path: Path,
    output_path: Path,
    lut_id: str = "teal_orange",
    extra_vf: Optional[str] = None,
) -> bool:
    """
    Apply a cinematic LUT to a video clip.

    Chains: [lut3d or eq fallback] → [extra_vf if provided] → [cast correction if needed]
    After applying the LUT, samples a few frames to detect yellow cast.
    If yellow cast is excessive, applies a subtle hue/saturation correction.
    Always re-encodes with libx264 (fast preset) since lut3d requires it.
    """
    vf = get_lut_vf_filter(lut_id)
    if not vf:
        logger.warning("[lut] Unknown LUT id '%s' — skipping", lut_id)
        return False

    if extra_vf:
        vf = f"{vf},{extra_vf}"

    tmp = Path(tempfile.mktemp(suffix=video_path.suffix, dir=video_path.parent))
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path),
            "-vf", vf,
            *gpu_utils.ffmpeg_codec_flags("high"),
            "-c:a", "copy",
            str(tmp),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        if proc.returncode != 0:
            logger.error("[lut] FFmpeg lut3d failed: %s", stderr.decode()[-400:])
            tmp.unlink(missing_ok=True)
            return False

        # ── Post-LUT yellow cast detection ──
        _rgb = _sample_frame_rgb_avg(tmp)
        _cast = _detect_yellow_cast(_rgb) if _rgb else "neutral"
        _correction = _build_cast_correction_vf(_cast, lut_id)
        if _correction:
            # Apply correction in a second pass
            _corrected = Path(tempfile.mktemp(suffix=video_path.suffix, dir=video_path.parent))
            _proc2 = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(tmp),
                "-vf", _correction,
                *gpu_utils.ffmpeg_codec_flags("high"),
                "-c:a", "copy",
                str(_corrected),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, _stderr2 = await asyncio.wait_for(_proc2.communicate(), timeout=120.0)
            if _proc2.returncode == 0 and _corrected.exists():
                tmp.unlink(missing_ok=True)
                tmp = _corrected
                logger.info("[lut] Yellow cast correction applied (cast=%s, lut=%s)", _cast, lut_id)
            else:
                _corrected.unlink(missing_ok=True)
                logger.warning("[lut] Cast correction pass failed: %s", _stderr2.decode()[:200])
        else:
            logger.info("[lut] Cast check: %s (no correction needed)", _cast)

        tmp.rename(output_path)
        logger.info("[lut] Applied '%s' LUT → %s", lut_id, output_path.name)
        return True
    except (asyncio.TimeoutError, Exception) as exc:
        logger.error("[lut] apply_lut error: %s", exc)
        tmp.unlink(missing_ok=True)
        return False


# ── LUT download helper (uses git clone / curl) ───────────────────────────────

async def download_film_luts(target_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Clone YahiaAngelo/Film-Luts into the LUT directory.
    Run once to populate /app/luts with 100+ free cinematic LUTs.
    Returns a summary of what was downloaded.
    """
    dest = target_dir or LUT_DIR
    dest.mkdir(parents=True, exist_ok=True)
    repo_url = "https://github.com/YahiaAngelo/Film-Luts.git"

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth=1", repo_url, str(dest / "film-luts"),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
        if proc.returncode == 0:
            cubes = list((dest / "film-luts").rglob("*.cube"))
            logger.info("[lut] Downloaded %d .cube files from Film-Luts", len(cubes))
            return {"success": True, "lut_count": len(cubes), "dir": str(dest / "film-luts")}
        return {"success": False, "error": stderr.decode()[-200:]}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ── Singleton ─────────────────────────────────────────────────────────────────

class LUTService:
    """Cinematic LUT application and management service."""

    def list_luts(self) -> List[Dict[str, Any]]:
        return list_available_luts()

    async def apply(self, video_path: Path, output_path: Path,
                    lut_id: str = "teal_orange") -> bool:
        return await apply_lut(video_path, output_path, lut_id)

    def get_vf_filter(self, lut_id: str) -> Optional[str]:
        return get_lut_vf_filter(lut_id)

    async def download_luts(self) -> Dict[str, Any]:
        return await download_film_luts()

    def ensure_dir(self) -> str:
        return str(ensure_lut_dir())

    def get_info(self) -> Dict[str, Any]:
        available = [l for l in list_available_luts() if l["available"]]
        return {
            "lut_dir": str(LUT_DIR),
            "total_presets": len(_LUT_CATALOG),
            "cube_files_present": len(available),
            "luts": list_available_luts(),
        }


_instance: Optional[LUTService] = None


def get_lut_service() -> LUTService:
    global _instance
    if _instance is None:
        _instance = LUTService()
    return _instance
