"""
Generate synthetic SFX and BGM tracks using FFmpeg lavfi source.
Run once at container build time to populate /app/assets/sounds/ and /app/assets/sounds/bgm/.
No external assets required.
"""
import subprocess
import sys
from pathlib import Path

OUT_DIR = Path("/app/assets/sounds")
OUT_DIR.mkdir(parents=True, exist_ok=True)

BGM_DIR = OUT_DIR / "bgm"
BGM_DIR.mkdir(parents=True, exist_ok=True)

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

# ── BGM tracks: loopable ambient/cinematic synthesized music (30s each) ─────
# These are programmatic approximations of common background music styles.
# They loop cleanly and are inaudible under speech at 10% volume.
BGM_TRACKS = {
    "bgm_cinematic_ambient.mp3": (
        # Slow evolving pad: low sine + filtered noise sweep
        "aevalsrc=0.12*sin(2*PI*55*t)+0.08*sin(2*PI*110*t)+0.05*sin(2*PI*165*t):c=stereo:s=44100:d=30",
        "afade=t=in:st=0:d=2,afade=t=out:st=28:d=2,"
        "lowpass=f=3000,aecho=0.6:0.3:1000:0.2"
    ),
    "bgm_upbeat_positive.mp3": (
        # Pulsing energetic feel: 120 BPM pulse with harmonics
        "aevalsrc=0.15*sin(2*PI*110*t)*(1+0.3*sin(2*PI*2*t))+0.08*sin(2*PI*220*t)+0.05*sin(2*PI*330*t):c=stereo:s=44100:d=30",
        "afade=t=in:st=0:d=1.5,afade=t=out:st=28.5:d=1.5"
    ),
    "bgm_lofi_chill.mp3": (
        # Lo-fi feel: warm low frequencies with subtle movement
        "aevalsrc=0.10*sin(2*PI*65*t)+0.07*sin(2*PI*98*t)+0.04*sin(2*PI*130*t)+0.03*sin(2*PI*196*t):c=stereo:s=44100:d=30",
        "afade=t=in:st=0:d=2,afade=t=out:st=28:d=2,"
        "lowpass=f=4000,highpass=f=60"
    ),
    "bgm_dramatic_tension.mp3": (
        # Rising tension: slow frequency sweep with reverb
        "aevalsrc=0.10*sin(2*PI*(80+20*t/30)*t)+0.06*sin(2*PI*(160+40*t/30)*t):c=stereo:s=44100:d=30",
        "afade=t=in:st=0:d=3,afade=t=out:st=27:d=3,"
        "aecho=0.7:0.4:800:0.3"
    ),
    "bgm_energetic_hype.mp3": (
        # High-energy: fast pulsing with bright harmonics
        "aevalsrc=0.14*sin(2*PI*130*t)*(0.8+0.2*sin(2*PI*4*t))+0.09*sin(2*PI*260*t)+0.05*sin(2*PI*390*t):c=stereo:s=44100:d=30",
        "afade=t=in:st=0:d=1,afade=t=out:st=29:d=1"
    ),
}

errors = 0

# Generate SFX
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

# Generate BGM tracks
print("\nGenerating BGM tracks...")
bgm_errors = 0
for filename, (lavfi_expr, af_filter) in BGM_TRACKS.items():
    out_path = BGM_DIR / filename
    if out_path.exists():
        print(f"  ✓ {filename} already exists, skipping")
        continue

    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", lavfi_expr]
    if af_filter:
        cmd += ["-af", af_filter]
    cmd += ["-ar", "44100", "-ac", "2", "-b:a", "128k", str(out_path)]

    result = subprocess.run(cmd, capture_output=True, timeout=60)
    if result.returncode == 0:
        print(f"  ✓ Generated {filename}")
    else:
        print(f"  ✗ Failed {filename}: {result.stderr.decode()[-200:]}", file=sys.stderr)
        bgm_errors += 1

total = len(SOUNDS) + len(BGM_TRACKS)
total_errors = errors + bgm_errors
print(f"\nAudio generation complete. {total - total_errors}/{total} files created.")
print(f"  SFX: {len(SOUNDS) - errors}/{len(SOUNDS)}")
print(f"  BGM: {len(BGM_TRACKS) - bgm_errors}/{len(BGM_TRACKS)}")
sys.exit(0 if total_errors == 0 else 1)
