"""
Optical Flow Transition Service — Phase 2.3 wrapper
=====================================================
Service facade over video_processing/optical_flow_transitions.py.
Called by the GPU worker and directly from video_service.py.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

TEMP_DIR = Path(os.environ.get("TEMP_DIR", "/app/temp/uploads"))


class OpticalFlowService:
    """
    Generate smooth morph transitions between two clips using RAFT optical flow.

    Priority chain (auto-detected at runtime):
      1. RAFT PyTorch (GPU preferred, CPU slow but works)
      2. FFmpeg xfade filter
      3. NumPy cross-dissolve

    Usage:
        svc    = OpticalFlowService()
        result = await svc.generate_transition(clip_a, clip_b, duration=0.5)
        # → {"output_path": str, "transition_frames": int, "method": str}
    """

    def __init__(self):
        self.out_dir = TEMP_DIR / "transitions"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    async def generate_transition(
        self,
        clip_a: str,
        clip_b: str,
        duration: float = 0.5,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Blend the tail of *clip_a* into the head of *clip_b* over *duration* seconds.

        Returns:
            {"output_path": str, "transition_frames": int, "method": str}
        """
        src_a = Path(clip_a)
        src_b = Path(clip_b)
        dest  = Path(output_path) if output_path else (
            self.out_dir / f"trans_{src_a.stem}_{src_b.stem}_{int(time.time())}.mp4"
        )

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, self._generate_sync, src_a, src_b, duration, dest
        )
        return result

    # ── Sync worker ───────────────────────────────────────────────────────────

    def _generate_sync(
        self,
        src_a: Path,
        src_b: Path,
        duration: float,
        dest: Path,
    ) -> Dict[str, Any]:
        from ..video_processing.optical_flow_transitions import (
            apply_optical_flow_transition,
            get_transition_capabilities,
        )

        caps     = get_transition_capabilities()
        method   = "raft" if caps.get("raft") else ("xfade" if caps.get("xfade") else "crossfade")
        n_frames = max(4, int(duration * 30))

        try:
            out = apply_optical_flow_transition(
                clip_a_path=str(src_a),
                clip_b_path=str(src_b),
                output_path=str(dest),
                transition_frames=n_frames,
            )
            if out and Path(out).exists():
                logger.info(f"[OptFlow] ✓ Transition ({method}) → {dest.name}")
                return {"output_path": str(dest), "transition_frames": n_frames, "method": method}
        except Exception as exc:
            logger.warning(f"[OptFlow] Transition failed ({method}): {exc}")

        return {"output_path": None, "transition_frames": 0, "method": "none"}

    @staticmethod
    def is_available() -> bool:
        try:
            from ..video_processing.optical_flow_transitions import get_transition_capabilities
            caps = get_transition_capabilities()
            return bool(caps.get("xfade") or caps.get("raft") or caps.get("crossfade"))
        except Exception:
            return False
