#!/usr/bin/env python3
"""
bootstrap_luts.py — create minimal sample .cube LUT files in /app/luts/
so the lut_service has something to work with out of the box.

Run once inside the Docker container:
  python /app/scripts/bootstrap_luts.py

Each generated LUT is a 33-point identity that is then shifted to produce a
recognisable colour grade without requiring any external downloads.
"""

import os
import math
from pathlib import Path

LUT_DIR = Path(os.environ.get("LUT_DIR", "/app/luts"))
LUT_DIR.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _identity_entries(size: int = 33):
    """Yield (r, g, b) float triples for an identity LUT of given size."""
    step = 1.0 / (size - 1)
    for b_i in range(size):
        for g_i in range(size):
            for r_i in range(size):
                yield r_i * step, g_i * step, b_i * step


def _write_cube(path: Path, title: str, size: int, transform):
    """Write a .cube file.  transform(r,g,b) → (r,g,b) in [0,1]."""
    lines = [
        f"TITLE {title}",
        f"LUT_3D_SIZE {size}",
        "",
    ]
    for r, g, b in _identity_entries(size):
        nr, ng, nb = transform(r, g, b)
        nr = max(0.0, min(1.0, nr))
        ng = max(0.0, min(1.0, ng))
        nb = max(0.0, min(1.0, nb))
        lines.append(f"{nr:.6f} {ng:.6f} {nb:.6f}")
    path.write_text("\n".join(lines) + "\n")
    print(f"  ✓  {path.name}  ({size}³ points)")


# ------------------------------------------------------------------
# Colour-grade recipes
# ------------------------------------------------------------------

def _teal_orange(r, g, b):
    """Classic teal shadows + warm orange highlights."""
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    shadow_w = max(0.0, 1.0 - lum * 3)
    highlight_w = max(0.0, lum * 2 - 1.0)
    r2 = r + 0.06 * highlight_w - 0.03 * shadow_w
    g2 = g + 0.02 * highlight_w - 0.01 * shadow_w
    b2 = b - 0.04 * highlight_w + 0.05 * shadow_w
    # slight contrast S-curve
    r2 = _s_curve(r2)
    g2 = _s_curve(g2)
    b2 = _s_curve(b2)
    return r2, g2, b2


def _cinema_cold(r, g, b):
    """Cold blue-teal cinema look."""
    r2 = r * 0.92
    g2 = g * 0.96
    b2 = b * 1.08 + 0.02
    return _s_curve(r2), _s_curve(g2), _s_curve(b2)


def _vintage_warm(r, g, b):
    """Warm vintage / film-orange look."""
    r2 = r * 1.06 + 0.02
    g2 = g * 1.00
    b2 = b * 0.88 - 0.01
    # lift blacks slightly
    r2 = r2 * 0.95 + 0.03
    g2 = g2 * 0.95 + 0.02
    b2 = b2 * 0.95 + 0.01
    return r2, g2, b2


def _high_contrast(r, g, b):
    """High-contrast punchy look."""
    r2 = _s_curve(r, strength=1.4)
    g2 = _s_curve(g, strength=1.4)
    b2 = _s_curve(b, strength=1.4)
    return r2, g2, b2


def _matte_fade(r, g, b):
    """Matte / faded look — lifts blacks, pulls whites."""
    r2 = r * 0.85 + 0.05
    g2 = g * 0.85 + 0.05
    b2 = b * 0.85 + 0.07
    return r2, g2, b2


def _s_curve(x: float, strength: float = 1.0) -> float:
    """Simple S-curve contrast boost."""
    x = max(0.0, min(1.0, x))
    # cubic S-curve centred at 0.5
    t = x - 0.5
    return 0.5 + t * (1.0 + strength * (-4.0 * t * t + 1.0) * 0.25)


# ------------------------------------------------------------------
# Write all LUTs
# ------------------------------------------------------------------

LUTS = [
    ("teal_orange.cube",   "Teal Orange",    17, _teal_orange),
    ("cinema_cold.cube",   "Cinema Cold",    17, _cinema_cold),
    ("vintage_warm.cube",  "Vintage Warm",   17, _vintage_warm),
    ("high_contrast.cube", "High Contrast",  17, _high_contrast),
    ("matte_fade.cube",    "Matte Fade",     17, _matte_fade),
]

print(f"Writing sample LUTs to {LUT_DIR}  …")
for filename, title, size, fn in LUTS:
    dest = LUT_DIR / filename
    if dest.exists():
        print(f"  –  {filename}  (already exists, skipping)")
        continue
    _write_cube(dest, title, size, fn)

print(f"\nDone — {len(LUTS)} LUT(s) available in {LUT_DIR}")
