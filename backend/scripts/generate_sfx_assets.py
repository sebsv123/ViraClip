#!/usr/bin/env python3
"""
Generate viral-style SFX files using FFmpeg's lavfi audio synthesis.

Outputs are written to /app/assets/sounds/. Existing files are NOT overwritten
unless --force is passed. All sounds are stereo, 44.1 kHz, 192 kbps MP3.

Designed to be drop-in: replace any of these files with a professional SFX
(same filename) and the system will pick up the new audio automatically.

Usage:
    python backend/scripts/generate_sfx_assets.py [--force] [--out DIR]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict


# ── SFX definitions ──────────────────────────────────────────────────────────
# Each entry: (filename, lavfi_expression, duration_seconds, description)
# The expression is the L/R pair for stereo sources passed to aevalsrc.
SFX_DEFINITIONS: Dict[str, Dict[str, object]] = {
    # 1) Soft UI pop — appears + B-roll insertion accent
    "pop_appear.mp3": {
        "expr": "sin(2*PI*1500*t)*exp(-t*45)",
        "duration": 0.18,
        "gain_db": -3,
        "description": "Soft high-pitched pop for appearance / UI accent",
    },

    # 2) Camera shutter — short mechanical click for jump-cuts
    "camera_shutter.mp3": {
        "expr": "(sin(2*PI*1800*t)+sin(2*PI*900*t)*0.6)*exp(-t*60)",
        "duration": 0.16,
        "gain_db": -4,
        "description": "Mechanical click for narrative cut / camera shutter",
    },

    # 3) Magic reveal — ascending sweep + chime tail
    "magic_reveal.mp3": {
        "expr": "(sin(2*PI*(440+t*880)*t)+sin(2*PI*(880+t*1200)*t)*0.5)*exp(-t*1.2)",
        "duration": 1.30,
        "gain_db": -2,
        "description": "Ascending magical reveal chime",
    },

    # 4) Riser 01 — long tension build
    "riser_01.mp3": {
        "expr": "sin(2*PI*(150+t*180)*t)*0.8*(1-exp(-t*0.6))*exp(-t*0.15)",
        "duration": 3.0,
        "gain_db": -3,
        "description": "Aggressive tension riser, builds for ~3s before reveal",
    },

    # 5) Whoosh zoom — directional swoosh for zoom punches
    "whoosh_zoom.mp3": {
        "expr": "sin(2*PI*(120+t*4000)*t)*exp(-t*3.5)",
        "duration": 0.45,
        "gain_db": -4,
        "description": "Frequency-sweep whoosh for zoom punch / direction change",
    },

    # 6) Cinematic hit — sub-bass impact with tail
    "cinematic_hit.mp3": {
        "expr": "(sin(2*PI*38*t)+sin(2*PI*55*t)*0.6+sin(2*PI*110*t)*0.3)*exp(-t*4.5)",
        "duration": 0.80,
        "gain_db": -1,
        "description": "Cinematic sub-bass impact hit",
    },

    # 7) Notification ding — modern digital chime (two-note)
    "notification_ding.mp3": {
        "expr": "(sin(2*PI*880*t)+sin(2*PI*1320*t)*0.5)*exp(-t*9)",
        "duration": 0.35,
        "gain_db": -3,
        "description": "Modern digital ding for sub-insights / stats",
    },

    # 8) Glitch burst — bitcrushed noise burst
    "glitch_burst.mp3": {
        "expr": "(sin(2*PI*(80+random(0)*4000)*t)+sin(2*PI*(120+random(0)*2000)*t)*0.5)*exp(-t*8)",
        "duration": 0.30,
        "gain_db": -5,
        "description": "Distorted glitch burst for pattern interrupt",
    },
}


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def generate(out_path: Path, expr: str, duration: float, gain_db: float) -> bool:
    """Render one SFX to MP3 via ffmpeg lavfi aevalsrc."""
    # Stereo: same expression on L and R
    lavfi = f"aevalsrc=exprs={expr}|{expr}:s=44100:d={duration:.3f}"
    cmd = [
        _ffmpeg(), "-y", "-v", "error",
        "-f", "lavfi", "-i", lavfi,
        "-af", f"volume={gain_db}dB,afade=t=out:st={max(0.0, duration - 0.05):.3f}:d=0.05",
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"  ✗ {out_path.name}: {proc.stderr.strip()[-200:]}", file=sys.stderr)
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--out", default="/app/assets/sounds",
                    help="Output directory (default: /app/assets/sounds)")
    ap.add_argument("--force", action="store_true",
                    help="Regenerate even if files already exist")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    created = skipped = failed = 0
    for filename, spec in SFX_DEFINITIONS.items():
        out_path = out_dir / filename
        if out_path.exists() and not args.force:
            print(f"  · {filename}  (exists — skipped)")
            skipped += 1
            continue

        ok = generate(
            out_path,
            expr=str(spec["expr"]),
            duration=float(spec["duration"]),  # type: ignore[arg-type]
            gain_db=float(spec["gain_db"]),    # type: ignore[arg-type]
        )
        if ok:
            print(f"  ✓ {filename}  ({spec['duration']}s — {spec['description']})")
            created += 1
        else:
            failed += 1

    print(
        f"\nResult: {created} created, {skipped} skipped, {failed} failed "
        f"(target: {out_dir})"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
