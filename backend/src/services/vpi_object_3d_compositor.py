"""
vpi_object_3d_compositor.py — OUTPUT-OBJECTS-3D-53 FASE 6/11.

Resolve a pre-rendered alpha 3D object from the offline cache and composite it onto a master
with ffmpeg, preserving audio / duration / fps / resolution / colour. Geometry is NEVER
rendered here — only the cached WebM-alpha clip is overlaid. Works with the worker's ffmpeg
4.4.2 (libvpx-vp9 alpha decode + overlay).
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# object width as a fraction of master width (FASE 10: 18%–28%)
OBJECT_WIDTH_FRAC = 0.23
PALETTE_VERSION = "vpi-3d-v1"


def _rendered_root() -> Path:
    # backend/src/services/ -> repo root /assets/objects_3d/rendered
    import os as _os
    env = _os.environ.get("VPI_OBJECTS_3D_ROOT")  # sandbox override (tests / offline mint)
    if env:
        return Path(env) / "rendered"
    here = Path(__file__).resolve()
    for base in (here.parents[3], Path("/app"), Path.cwd()):
        cand = base / "assets" / "objects_3d" / "rendered"
        if cand.exists():
            return cand
    return here.parents[3] / "assets" / "objects_3d" / "rendered"


def load_manifest(root: Optional[Path] = None) -> Dict[str, Any]:
    root = root or _rendered_root()
    mf = root / "manifest.json"
    if not mf.exists():
        return {"objects": {}}
    try:
        return json.loads(mf.read_text())
    except (OSError, ValueError):
        return {"objects": {}}


def cache_key(asset_id: str, variant: str, *, w: int = 720, h: int = 720,
              fps: int = 30, frames: int = 54, palette: str = PALETTE_VERSION) -> str:
    return f"{asset_id}__{variant}__{w}x{h}__{fps}fps__{frames}f__{palette}"


@dataclass(frozen=True)
class CachedObject3D:
    cache_key: str
    render_path: Path
    frame_count: int
    fps: int
    duration_s: float
    alpha_verified: bool
    asset_sha256: str


def resolve_cached_object_3d(asset_id: str, variant: str,
                             root: Optional[Path] = None) -> Optional[CachedObject3D]:
    """FASE 6: look up the cached alpha render for (asset_id, variant). Returns None on miss."""
    root = root or _rendered_root()
    manifest = load_manifest(root)
    objects = manifest.get("objects") or {}
    key = cache_key(asset_id, variant)
    entry = objects.get(key)
    if not entry:
        # 53C: composite/library assets may use a different frame count than the 53 default (54).
        # Fall back to an asset_id + animation_variant search so the exact key is not required.
        for k, e in objects.items():
            if str(e.get("asset_id")) == asset_id and str(e.get("animation_variant")) == variant:
                key, entry = (e.get("object_3d_cache_key") or k), e
                break
    if not entry:
        logger.info("VPI_OBJECT_3D_RENDER_CACHE_MISS key=%s", key)
        return None
    path = root / Path(entry["render_path"]).name
    if not path.exists():
        logger.warning("VPI_OBJECT_3D_RENDER_CACHE_MISS key=%s reason=file_absent", key)
        return None
    logger.info("VPI_OBJECT_3D_RENDER_CACHE_HIT key=%s path=%s", key, path.name)
    return CachedObject3D(
        cache_key=key, render_path=path,
        frame_count=int(entry.get("frame_count") or 0),
        fps=int(entry.get("fps") or 30),
        duration_s=float(entry.get("duration_s") or 0.0),
        alpha_verified=bool(entry.get("alpha_verified")),
        asset_sha256=str(entry.get("asset_sha256") or ""),
    )


def _ffprobe(path: Path) -> Dict[str, Any]:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate,nb_frames,duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(out.stdout or "{}")
        return (data.get("streams") or [{}])[0]
    except Exception:
        return {}


def _placement_xy(placement: str, W: int, H: int, ow: int, oh: int) -> Tuple[str, str]:
    margin = int(0.05 * W)
    top = int(0.12 * H)
    midy = int((H - oh) / 2 - 0.04 * H)
    right_x = W - ow - margin
    if placement == "upper_left":
        return str(margin), str(top)
    if placement == "upper_right":
        return str(right_x), str(top)
    if placement == "mid_left":
        return str(margin), str(midy)
    if placement == "mid_right":
        return str(right_x), str(midy)
    return str(right_x), str(top)  # safe default: never centre over the face


def composite_object_3d(
    master_path: str,
    out_path: str,
    *,
    asset_id: str,
    variant: str,
    placement: str,
    window_start_s: float,
    window_end_s: float,
    ffmpeg_bin: str = "ffmpeg",
    width_frac: float = OBJECT_WIDTH_FRAC,
    root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Overlay the cached alpha 3D object onto the master between window_start..end.

    Preserves the master's audio (copied), duration, fps, resolution and colour. Returns a
    result dict with the composite metadata or an error (caller falls back to 2D on failure).
    """
    cached = resolve_cached_object_3d(asset_id, variant, root=root)
    if cached is None:
        return {"ok": False, "error": "cache_miss", "asset_id": asset_id, "variant": variant}
    if not cached.alpha_verified:
        logger.warning("VPI_OBJECT_3D_COMPOSITE_FAILED asset=%s variant=%s reason=alpha_not_verified", asset_id, variant)
        return {"ok": False, "error": "alpha_not_verified", "asset_id": asset_id, "variant": variant}

    mp = _ffprobe(Path(master_path))
    try:
        W, H = int(mp.get("width")), int(mp.get("height"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "master_unprobeable", "master": master_path}

    ow = max(2, int(round(W * float(width_frac))))
    oh = ow  # square source (720x720)
    x, y = _placement_xy(placement, W, H, ow, oh)
    ws = max(0.0, float(window_start_s))
    we = max(ws + 0.2, float(window_end_s))

    # shift the object onto the window start, scale to target width, overlay only within window,
    # keep alpha (format=yuva420p), copy the master audio untouched.
    filtergraph = (
        f"[1:v]setpts=PTS-STARTPTS+{ws:.3f}/TB,scale={ow}:{oh},format=yuva420p[obj];"
        f"[0:v][obj]overlay={x}:{y}:enable='between(t,{ws:.3f},{we:.3f})':eof_action=pass[v]"
    )
    cmd = [
        ffmpeg_bin, "-y", "-v", "error",
        "-i", str(master_path),
        "-c:v", "libvpx-vp9", "-i", str(cached.render_path),
        "-filter_complex", filtergraph,
        "-map", "[v]", "-map", "0:a?",
        "-c:a", "copy",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
        "-movflags", "+faststart",
        str(out_path),
    ]
    logger.info(
        "VPI_OBJECT_3D_COMPOSITED asset=%s variant=%s placement=%s win=%.2f-%.2f size=%dpx@%dx%d",
        asset_id, variant, placement, ws, we, ow, W, H,
    )
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not Path(out_path).exists():
        logger.warning("VPI_OBJECT_3D_COMPOSITE_FAILED rc=%s err=%s", proc.returncode, proc.stderr[-400:])
        return {"ok": False, "error": "ffmpeg_failed", "stderr": proc.stderr[-400:],
                "asset_id": asset_id, "variant": variant}

    op = _ffprobe(Path(out_path))
    return {
        "ok": True,
        "asset_id": asset_id,
        "variant": variant,
        "placement": placement,
        "object_3d_cache_key": cached.cache_key,
        "object_3d_render_path": str(cached.render_path),
        "object_3d_asset_sha256": cached.asset_sha256,
        "alpha_verified": cached.alpha_verified,
        "object_width_px": ow,
        "object_x": int(x),
        "object_y": int(y),
        "window_start_s": round(ws, 3),
        "window_end_s": round(we, 3),
        "out_width": op.get("width"),
        "out_height": op.get("height"),
        "out_path": out_path,
    }
