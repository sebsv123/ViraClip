"""
B-roll Provider Strategy — single source of truth for provider ordering.

Every B-roll entry point in the codebase (BrollService.fetch_broll_asset,
ContextualBroll.get_for_keyword, etc.) MUST use this module to decide which
providers to try and in what order.  No other file should hard-code
premium_first / stock_first branching.

Provider types:
  PREMIUM  — generative AI (LTXV local, ComfyUI AnimateDiff, T2V Replicate)
  STOCK    — stock API search (Pexels video, Pixabay video, Coverr video)
  IMAGE    — image search + Ken Burns (Pexels/Unsplash image)
  LOCAL    — offline local asset bank
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional

from .vpi_production_safe_edit import production_safe_mode_active

logger = logging.getLogger(__name__)

# ── Configuration (read once at import, stable for process lifetime) ──────────

# Beta defaults: stock_first, premium disabled, stock enabled
BROLL_PROVIDER_PRIORITY = os.environ.get("BROLL_PROVIDER_PRIORITY", "stock_first")
BROLL_ENABLE_PREMIUM = os.environ.get("BROLL_ENABLE_PREMIUM", "false").lower() not in ("false", "0", "no")
BROLL_ENABLE_STOCK = os.environ.get("BROLL_ENABLE_STOCK", "true").lower() not in ("false", "0", "no")

# Quality gate thresholds — RAISED for WOW quality (reject mediocre assets)
_MIN_ASSET_SIZE_BYTES = int(os.environ.get("BROLL_MIN_ASSET_SIZE", "50000"))      # 50 KB (was 10K) — rejects tiny garbage files
_MIN_ASSET_DURATION = float(os.environ.get("BROLL_MIN_ASSET_DURATION", "2.0"))    # 2.0 s (was 0.8) — ensures meaningful B-roll
_MIN_VERTICAL_AR = float(os.environ.get("BROLL_MIN_VERTICAL_AR", "0.75"))          # h/w ≥ 0.75 (was 0.7) — stricter vertical
_MIN_RESOLUTION_HEIGHT = int(os.environ.get("BROLL_MIN_RESOLUTION_HEIGHT", "720"))  # ≥ 720 px (was 480) — HD minimum

# Duration guard constants for B-roll cue placement
BROLL_MIN_CLIP_DURATION_SEC = float(os.environ.get("BROLL_MIN_CLIP_DURATION_SEC", "4.0"))   # skip B-roll on clips shorter than this
BROLL_MAX_DURATION_RATIO = float(os.environ.get("BROLL_MAX_DURATION_RATIO", "0.6"))          # B-roll overlay ≤ 60% of clip duration


# ── Provider enum ─────────────────────────────────────────────────────────────

class ProviderType(str, Enum):
    LOCAL = "local"
    LTXV = "ltxv"
    ANIMATEDIFF = "animatediff"
    T2V_REPLICATE = "t2v_replicate"
    STOCK_VIDEO = "stock_video"      # Pexels/Pixabay/Coverr video
    STOCK_IMAGE = "stock_image"      # Pexels image → Ken Burns
    CACHE = "cache"


# ── Ordered provider lists ────────────────────────────────────────────────────

_PREMIUM_PROVIDERS: List[ProviderType] = [
    ProviderType.LTXV,
    ProviderType.ANIMATEDIFF,
    ProviderType.T2V_REPLICATE,
]

_STOCK_PROVIDERS: List[ProviderType] = [
    ProviderType.STOCK_VIDEO,
    ProviderType.STOCK_IMAGE,
    ProviderType.CACHE,
]


def get_provider_order(priority_label: str = "NORMAL") -> List[ProviderType]:
    """Return the ordered list of provider types to attempt.

    Always starts with LOCAL.
    Then premium or stock depending on BROLL_PROVIDER_PRIORITY.
    Respects BROLL_ENABLE_PREMIUM / BROLL_ENABLE_STOCK flags.
    For HIGH priority, image fallback is excluded (video-only).

    Args:
        priority_label: "HIGH", "MED", or "NORMAL"/"LOW"
    """
    prio = priority_label.upper()
    order: List[ProviderType] = [ProviderType.LOCAL]

    premium = list(_PREMIUM_PROVIDERS) if BROLL_ENABLE_PREMIUM else []
    stock = list(_STOCK_PROVIDERS) if BROLL_ENABLE_STOCK else []

    if production_safe_mode_active():
        premium = []
        stock = [provider for provider in stock if provider == ProviderType.CACHE]

    # HIGH: skip image fallback to keep assets video-only
    if prio == "HIGH":
        stock = [p for p in stock if p != ProviderType.STOCK_IMAGE]

    if BROLL_PROVIDER_PRIORITY == "premium_first":
        order += premium + stock
    else:
        order += stock + premium

    if production_safe_mode_active():
        order = [provider for provider in order if provider in {ProviderType.LOCAL, ProviderType.CACHE}]
    return order


def get_provider_order_labels(priority_label: str = "NORMAL") -> List[str]:
    """Convenience: same as get_provider_order but returns string labels."""
    return [p.value for p in get_provider_order(priority_label)]


# ── Provider diagnostics ─────────────────────────────────────────────────────

@dataclass
class ProviderStatus:
    """Snapshot of all provider availability at a point in time."""
    ltxv_enabled: bool
    comfyui_enabled: bool
    t2v_available: bool
    pexels: bool
    pixabay: bool
    coverr: bool
    priority: str
    premium_enabled: bool
    stock_enabled: bool

    def as_dict(self) -> dict:
        return {
            "ltxv_enabled": self.ltxv_enabled,
            "comfyui_enabled": self.comfyui_enabled,
            "t2v_available": self.t2v_available,
            "pexels": self.pexels,
            "pixabay": self.pixabay,
            "coverr": self.coverr,
            "priority": self.priority,
            "premium_enabled": self.premium_enabled,
            "stock_enabled": self.stock_enabled,
        }


def diagnose_providers() -> ProviderStatus:
    """Check all provider availability and log the result.

    Safe to call at startup — catches all import/config errors.
    Works both when imported as module and when run standalone.
    """
    # Safe imports with fallbacks for standalone execution
    try:
        from ..comfyui_bridge import COMFYUI_ENABLED, LTXV_ENABLED
    except ImportError:
        try:
            from comfyui_bridge import COMFYUI_ENABLED, LTXV_ENABLED
        except ImportError:
            COMFYUI_ENABLED = os.environ.get("COMFYUI_ENABLED", "false").lower() == "true"
            LTXV_ENABLED = os.environ.get("LTXV_ENABLED", "false").lower() == "true"

    try:
        from .t2v_broll_service import T2VBrollService
        t2v = T2VBrollService.is_available()
    except Exception:
        try:
            from t2v_broll_service import T2VBrollService
            t2v = T2VBrollService.is_available()
        except Exception:
            t2v = bool(os.environ.get("T2V_ENABLED", "false").lower() == "true" and
                       os.environ.get("REPLICATE_API_TOKEN"))

    status = ProviderStatus(
        ltxv_enabled=LTXV_ENABLED,
        comfyui_enabled=COMFYUI_ENABLED,
        t2v_available=t2v,
        pexels=bool(os.getenv("PEXELS_API_KEY")),
        pixabay=bool(os.getenv("PIXABAY_API_KEY")),
        coverr=bool(os.getenv("COVERR_API_KEY")),
        priority=BROLL_PROVIDER_PRIORITY,
        premium_enabled=BROLL_ENABLE_PREMIUM,
        stock_enabled=BROLL_ENABLE_STOCK,
    )
    logger.info(
        "[BRoll Strategy] Provider diagnostics:\n"
        "  priority       = %s\n"
        "  premium_enabled= %s  (LTXV=%s, ComfyUI=%s, T2V=%s)\n"
        "  stock_enabled  = %s  (Pexels=%s, Pixabay=%s, Coverr=%s)\n"
        "  provider_order = %s",
        status.priority,
        status.premium_enabled, status.ltxv_enabled, status.comfyui_enabled, status.t2v_available,
        status.stock_enabled, status.pexels, status.pixabay, status.coverr,
        get_provider_order_labels(),
    )
    return status


# ── Quality gate ──────────────────────────────────────────────────────────────

def passes_quality_gate(path: Path, provider: str, check_motion: bool = True) -> bool:
    """Unified quality gate applied to every B-roll asset regardless of source.

    Checks:
      1. File exists and meets minimum size
      2. Video duration ≥ threshold (for video files)
      3. Vertical-friendly aspect ratio (h/w ≥ 0.7)
      4. Minimum resolution height (≥ 480px)
      5. Motion score (frame variance) — reject static/loop clips
      6. Loop detection (frame uniqueness)
    """
    if not path.exists():
        return False

    size = path.stat().st_size
    if size < _MIN_ASSET_SIZE_BYTES:
        logger.warning("[QualityGate] REJECT %s from %s: %d bytes < %d min",
                       path.name, provider, size, _MIN_ASSET_SIZE_BYTES)
        return False

    is_video = path.suffix.lower() in (".mp4", ".mov", ".webm")
    if not is_video:
        return True  # images pass if size is OK

    # ── Video-specific checks via ffprobe ──────────────────────────────────
    try:
        # Get stream info (resolution + duration)
        probe_cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration",
            "-of", "json", str(path),
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            streams = json.loads(result.stdout).get("streams", [])
            if streams:
                stream = streams[0]
                w = int(stream.get("width", 0))
                h = int(stream.get("height", 0))
                dur_str = stream.get("duration")

                # Duration check
                if dur_str:
                    dur = float(dur_str)
                    if dur < _MIN_ASSET_DURATION:
                        logger.warning("[QualityGate] REJECT %s from %s: %.1fs < %.1fs min",
                                       path.name, provider, dur, _MIN_ASSET_DURATION)
                        return False

                # Aspect ratio check (reject strongly horizontal)
                if w > 0 and h > 0:
                    ar = h / w
                    if ar < _MIN_VERTICAL_AR:
                        logger.warning("[QualityGate] REJECT %s from %s: aspect %.2f (h/w) < %.2f min",
                                       path.name, provider, ar, _MIN_VERTICAL_AR)
                        return False

                # Minimum resolution
                if h > 0 and h < _MIN_RESOLUTION_HEIGHT:
                    logger.warning("[QualityGate] REJECT %s from %s: height %dpx < %dpx min",
                                   path.name, provider, h, _MIN_RESOLUTION_HEIGHT)
                    return False

        # ── Motion analysis (frame size variance as motion proxy) ─────────────
        if check_motion:
            motion_cmd = [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "frame=pkt_pts_time,pkt_size", "-of", "json",
                str(path),
            ]
            motion_result = subprocess.run(motion_cmd, capture_output=True, text=True, timeout=10)
            if motion_result.returncode == 0:
                frames = json.loads(motion_result.stdout).get("frames", [])
                if len(frames) >= 10:
                    sizes = [int(f.get("pkt_size", 0)) for f in frames if f.get("pkt_size")]
                    if len(sizes) >= 10:
                        avg_size = sum(sizes) / len(sizes)
                        variance = sum((s - avg_size) ** 2 for s in sizes) / len(sizes)
                        motion_score = min(1.0, variance / (avg_size ** 2 + 1)) if avg_size > 0 else 0

                        # Reject low motion (static/photo-like) — RAISED to 0.5 for WOW quality
                        _MIN_MOTION_SCORE = 0.5
                        if motion_score < _MIN_MOTION_SCORE:
                            logger.warning("[QualityGate] REJECT %s from %s: motion_score %.2f < %.1f (too static for WOW)",
                                           path.name, provider, motion_score, _MIN_MOTION_SCORE)
                            return False

                        # Loop detection: start/mid/end frames should differ significantly
                        if len(frames) >= 20:
                            start_size = sum(int(frames[i].get("pkt_size", 0)) for i in range(3)) / 3
                            mid_size = sum(int(frames[len(frames)//2 + i].get("pkt_size", 0)) for i in range(3)) / 3
                            end_size = sum(int(frames[-3 + i].get("pkt_size", 0)) for i in range(3)) / 3
                            unique_variance = max(abs(start_size - mid_size), abs(mid_size - end_size), abs(start_size - end_size))
                            _MIN_UNIQUE_VARIANCE = 2000  # RAISED from 500 — stricter loop detection
                            if unique_variance < _MIN_UNIQUE_VARIANCE:
                                logger.warning("[QualityGate] REJECT %s from %s: low unique variance %.0f < %.0f (loop/static content)",
                                               path.name, provider, unique_variance, _MIN_UNIQUE_VARIANCE)
                                return False

    except Exception as exc:
        logger.debug("[QualityGate] probe error for %s — accepting: %s", path.name, exc)

    return True
