"""
Generate synthetic SFX using FFmpeg lavfi source.
Run once at container build time to populate /app/assets/sounds/.
No external assets required.
"""
import subprocess
import sys
from pathlib import Path

OUT_DIR = Path("/app/assets/sounds")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SOUNDS = {
    "whoosh_fast.mp3": (
        "aevalsrc=0.4*sin(2*PI*(2000-1800*t)*t):c=stereo:s=44100:d=0.35",
        "afade=t=out:st=0.25:d=0.1"
    ),
    "whoosh_heavy.mp3": (
        "aevalsrc=0.5*sin(2*PI*(1500-1300*t)*t):c=stereo:s=44100:d=0.55",
        "afade=t=out:st=0.4:d=0.15"
    ),
    "punch_impact.mp3": (
        "aevalsrc=0.9*sin(2*PI*80*t)*exp(-18*t)+0.3*sin(2*PI*160*t)*exp(-25*t):c=stereo:s=44100:d=0.25",
        None
    ),
    "ding_chime.mp3": (
        "aevalsrc=0.5*sin(2*PI*880*t)*exp(-2.5*t)+0.25*sin(2*PI*1760*t)*exp(-3*t):c=stereo:s=44100:d=0.6",
        None
    ),
    "bass_boom.mp3": (
        "aevalsrc=0.8*sin(2*PI*55*t)*exp(-4*t)+0.4*sin(2*PI*110*t)*exp(-6*t):c=stereo:s=44100:d=0.9",
        "afade=t=out:st=0.7:d=0.2"
    ),
    "tension_riser.mp3": (
        "aevalsrc=0.3*sin(2*PI*(100+633*t)*t):c=stereo:s=44100:d=1.5",
        "afade=t=in:st=0:d=0.2,afade=t=out:st=1.3:d=0.2"
    ),
    "glitch_hit.mp3": (
        "aevalsrc=0.6*(sin(2*PI*300*t)+sin(2*PI*450*t+1.5))*exp(-30*t):c=stereo:s=44100:d=0.2",
        None
    ),
}

errors = 0
for filename, (lavfi_expr, af_filter) in SOUNDS.items():
    out_path = OUT_DIR / filename
    if out_path.exists():
        print(f"  ✓ {filename} already exists, skipping")
        continue

    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", lavfi_expr]
    if af_filter:
        cmd += ["-af", af_filter]
    cmd += ["-ar", "44100", "-ac", "2", str(out_path)]

    result = subprocess.run(cmd, capture_output=True, timeout=30)
    if result.returncode == 0:
        print(f"  ✓ Generated {filename}")
    else:
        print(f"  ✗ Failed {filename}: {result.stderr.decode()[-200:]}", file=sys.stderr)
        errors += 1

print(f"\nSFX generation complete. {len(SOUNDS) - errors}/{len(SOUNDS)} files created.")
sys.exit(0 if errors == 0 else 1)
