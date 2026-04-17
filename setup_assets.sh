#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# ViraClip v2 — Setup de assets (100% local, 0 internet)
#
# Genera toda la música (BGM) y efectos (SFX) con ffmpeg.
# Compatible con AudioLibraryService y pipeline.py.
#
# Ejecutar una sola vez:
#   chmod +x setup_assets.sh && ./setup_assets.sh
#
# Estructura creada (AudioLibraryService layout):
#   $AUDIO_DIR/
#     bgm/upbeat/       ← pistas energéticas
#     bgm/emotional/    ← pistas emocionales
#     bgm/suspense/     ← pistas de tensión
#     bgm/professional/ ← pistas corporativas
#     bgm/lofi/         ← pistas lo-fi
#     bgm/general/      ← fallback
#     sfx/whoosh/       sfx/impact/   sfx/riser/   sfx/transition/  sfx/general/
#     audio_index.json  ← índice para AudioLibraryService
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

AUDIO_DIR="${AUDIO_LIBRARY_PATH:-$HOME/proyectos/ViraClip/audio}"
# Legacy SFX dir (pipeline.py also checks here)
SFX_DIR="$HOME/proyectos/ViraClip/sfx"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ViraClip v2 — Setup de assets (100% local, ffmpeg)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  AUDIO_DIR = $AUDIO_DIR"

# ── 1. Crear estructura de directorios ────────────────────────────────────────
echo ""
echo "📁 Creando directorios..."
mkdir -p "$AUDIO_DIR"/bgm/{upbeat,emotional,suspense,professional,lofi,general}
mkdir -p "$AUDIO_DIR"/sfx/{whoosh,impact,riser,transition,general}
mkdir -p "$SFX_DIR"
echo "   ✅ $AUDIO_DIR/bgm/{upbeat,emotional,suspense,professional,lofi,general}"
echo "   ✅ $AUDIO_DIR/sfx/{whoosh,impact,riser,transition,general}"
echo "   ✅ $SFX_DIR (legacy)"

# Helper: genera un MP3 solo si no existe o está corrupto (<10KB)
gen() {
    local dest="$1"; shift
    if [ -f "$dest" ] && [ "$(stat -c%s "$dest" 2>/dev/null || echo 0)" -gt 10000 ]; then
        echo "   ↩ Ya existe: $(basename "$dest")"
        return 0
    fi
    if ffmpeg -y "$@" "$dest" 2>/dev/null; then
        local sz; sz=$(stat -c%s "$dest" 2>/dev/null || echo 0)
        if [ "$sz" -gt 10000 ]; then
            echo "   ✅ $(basename "$dest") ($(du -h "$dest" | cut -f1))"
        else
            echo "   ⚠  $(basename "$dest") demasiado pequeño ($sz bytes)"
            rm -f "$dest"
        fi
    else
        echo "   ⚠  Error generando $(basename "$dest")"
    fi
}

# ── 2. Generar BGM con ffmpeg (90s cada una, 0 internet) ─────────────────────
echo ""
echo "🎵 Generando BGM (background music) con ffmpeg..."

# UPBEAT 1 — Do mayor pulsado, 120bpm feel
gen "$AUDIO_DIR/bgm/upbeat/upbeat_01.mp3" \
    -f lavfi \
    -i "aevalsrc=sin(2*PI*261*t)*0.4+sin(2*PI*392*t)*0.3+sin(2*PI*523*t)*0.2:s=44100" \
    -af "aecho=0.6:0.7:50:0.3,volume=0.55,afade=t=in:st=0:d=2,afade=t=out:st=88:d=2" \
    -t 90 -ar 44100 -ac 2 -b:a 192k

# UPBEAT 2 — Mi mayor brillante
gen "$AUDIO_DIR/bgm/upbeat/upbeat_02.mp3" \
    -f lavfi \
    -i "aevalsrc=sin(2*PI*329*t)*0.4+sin(2*PI*440*t)*0.3+sin(2*PI*523*t)*0.2:s=44100" \
    -af "aecho=0.7:0.8:40:0.25,volume=0.55,afade=t=in:st=0:d=2,afade=t=out:st=88:d=2" \
    -t 90 -ar 44100 -ac 2 -b:a 192k

# PROFESSIONAL — Re mayor corporativo
gen "$AUDIO_DIR/bgm/professional/corporate_01.mp3" \
    -f lavfi \
    -i "aevalsrc=sin(2*PI*293*t)*0.3+sin(2*PI*369*t)*0.3+sin(2*PI*440*t)*0.2:s=44100" \
    -af "aecho=0.8:0.85:80:0.4,volume=0.45,afade=t=in:st=0:d=3,afade=t=out:st=87:d=3" \
    -t 90 -ar 44100 -ac 2 -b:a 192k

# EMOTIONAL — La menor, tempo lento
gen "$AUDIO_DIR/bgm/emotional/emotional_01.mp3" \
    -f lavfi \
    -i "aevalsrc=sin(2*PI*220*t)*0.4+sin(2*PI*261*t)*0.3+sin(2*PI*329*t)*0.2:s=44100" \
    -af "aecho=0.85:0.9:120:0.5,volume=0.45,afade=t=in:st=0:d=3,afade=t=out:st=87:d=3" \
    -t 90 -ar 44100 -ac 2 -b:a 192k

# EMOTIONAL 2 — Re menor melancólico
gen "$AUDIO_DIR/bgm/emotional/emotional_02.mp3" \
    -f lavfi \
    -i "aevalsrc=sin(2*PI*293*t)*0.4+sin(2*PI*349*t)*0.3+sin(2*PI*440*t)*0.15:s=44100" \
    -af "aecho=0.9:0.9:100:0.5,volume=0.4,afade=t=in:st=0:d=3,afade=t=out:st=87:d=3" \
    -t 90 -ar 44100 -ac 2 -b:a 192k

# SUSPENSE — drone grave con beat frequency tension
gen "$AUDIO_DIR/bgm/suspense/suspense_01.mp3" \
    -f lavfi \
    -i "aevalsrc=sin(2*PI*80*t)*0.5+sin(2*PI*84.5*t)*0.4:s=44100" \
    -af "aecho=0.9:0.95:200:0.6,volume=0.5,afade=t=in:st=0:d=4,afade=t=out:st=86:d=4" \
    -t 90 -ar 44100 -ac 2 -b:a 192k

# LOFI — base lo-fi relajada
gen "$AUDIO_DIR/bgm/lofi/lofi_01.mp3" \
    -f lavfi \
    -i "aevalsrc=sin(2*PI*174*t)*0.35+sin(2*PI*261*t)*0.25+sin(2*PI*349*t)*0.2:s=44100" \
    -af "aecho=0.7:0.8:150:0.45,lowpass=f=4000,volume=0.45,afade=t=in:st=0:d=2,afade=t=out:st=88:d=2" \
    -t 90 -ar 44100 -ac 2 -b:a 192k

# GENERAL — fallback neutral
gen "$AUDIO_DIR/bgm/general/ambient_01.mp3" \
    -f lavfi \
    -i "aevalsrc=sin(2*PI*196*t)*0.3+sin(2*PI*261*t)*0.2+sin(2*PI*329*t)*0.15:s=44100" \
    -af "aecho=0.8:0.85:100:0.45,volume=0.4,afade=t=in:st=0:d=3,afade=t=out:st=87:d=3" \
    -t 90 -ar 44100 -ac 2 -b:a 192k

# ── 3. Generar SFX con ffmpeg ────────────────────────────────────────────────
echo ""
echo "💥 Generando SFX (sound effects) con ffmpeg..."

# Whoosh (sweep frequency)
gen "$AUDIO_DIR/sfx/whoosh/whoosh_01.mp3" \
    -f lavfi \
    -i "sine=frequency=800:duration=0.4,asetrate=44100*1.5,aresample=44100,afade=t=in:d=0.05,afade=t=out:st=0.25:d=0.15,volume=0.7" \
    -c:a libmp3lame -q:a 2

# Impact (low frequency hit)
gen "$AUDIO_DIR/sfx/impact/impact_01.mp3" \
    -f lavfi \
    -i "sine=frequency=60:duration=0.5,afade=t=in:d=0.01,afade=t=out:st=0.1:d=0.4,volume=0.8" \
    -c:a libmp3lame -q:a 2

# Riser (ascending tone for build-up)
gen "$AUDIO_DIR/sfx/riser/riser_01.mp3" \
    -f lavfi \
    -i "sine=frequency=200:duration=1.5,asetrate=44100*0.7,aresample=44100,afade=t=in:d=0.1,afade=t=out:st=1.2:d=0.3,volume=0.5" \
    -c:a libmp3lame -q:a 2

# Swoosh / transition
gen "$AUDIO_DIR/sfx/transition/swoosh_01.mp3" \
    -f lavfi \
    -i "sine=frequency=1200:duration=0.25,asetrate=44100*2,aresample=44100,afade=t=in:d=0.02,afade=t=out:st=0.1:d=0.15,volume=0.6" \
    -c:a libmp3lame -q:a 2

# Ding (general notification)
gen "$AUDIO_DIR/sfx/general/ding.mp3" \
    -f lavfi \
    -i "aevalsrc=sin(2*PI*1200*t)*exp(-8*t):s=44100" \
    -t 0.8 -ar 44100 -ac 2 -b:a 192k

# Boom (low impact)
gen "$AUDIO_DIR/sfx/general/boom.mp3" \
    -f lavfi \
    -i "aevalsrc=sin(2*PI*60*t)*exp(-3*t)*0.8:s=44100" \
    -t 1.5 -ar 44100 -ac 2 -b:a 192k

# ── 3b. Copiar SFX a legacy flat dir (pipeline.py SFX_DIR fallback) ──────────
echo ""
echo "📋 Copiando SFX a directorio legacy ($SFX_DIR)..."
cp -f "$AUDIO_DIR/sfx/whoosh/whoosh_01.mp3"      "$SFX_DIR/whoosh.mp3"     2>/dev/null && echo "   ✅ whoosh.mp3" || true
cp -f "$AUDIO_DIR/sfx/impact/impact_01.mp3"      "$SFX_DIR/impact.mp3"     2>/dev/null && echo "   ✅ impact.mp3" || true
cp -f "$AUDIO_DIR/sfx/riser/riser_01.mp3"        "$SFX_DIR/riser.mp3"      2>/dev/null && echo "   ✅ riser.mp3"  || true
cp -f "$AUDIO_DIR/sfx/transition/swoosh_01.mp3"  "$SFX_DIR/swoosh.mp3"     2>/dev/null && echo "   ✅ swoosh.mp3" || true

# ── 4. Generar audio_index.json para AudioLibraryService ─────────────────────
echo ""
echo "📝 Generando audio_index.json..."
python3 << 'PYEOF'
import json, os
from pathlib import Path

audio_dir = Path(os.environ.get("AUDIO_LIBRARY_PATH",
    os.path.expanduser("~/proyectos/ViraClip/audio")))

index = {"bgm": {}, "sfx": {}}

for f in sorted((audio_dir / "bgm").rglob("*.mp3")):
    mood = f.parent.name
    index["bgm"].setdefault(mood, [])
    index["bgm"][mood].append({"path": str(f.relative_to(audio_dir))})

for f in sorted((audio_dir / "sfx").rglob("*.mp3")):
    cat = f.parent.name
    index["sfx"].setdefault(cat, [])
    index["sfx"][cat].append({"path": str(f.relative_to(audio_dir))})

out = audio_dir / "audio_index.json"
with open(out, "w") as fh:
    json.dump(index, fh, indent=2)

bgm_total = sum(len(v) for v in index["bgm"].values())
sfx_total = sum(len(v) for v in index["sfx"].values())
print(f"   ✅ audio_index.json ({bgm_total} BGM, {sfx_total} SFX)")
print(f"      BGM moods:      {list(index['bgm'].keys())}")
print(f"      SFX categories: {list(index['sfx'].keys())}")
PYEOF

# ── 5. Resumen ────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Setup completo — 0 descargas de internet"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📁 BGM:"
find "$AUDIO_DIR/bgm" -type f -name "*.mp3" -printf "   %p (%s bytes)\n" 2>/dev/null
echo ""
echo "📁 SFX:"
find "$AUDIO_DIR/sfx" -type f -name "*.mp3" -printf "   %p (%s bytes)\n" 2>/dev/null
echo ""
echo "📁 Legacy SFX:"
find "$SFX_DIR" -type f -name "*.mp3" -printf "   %p (%s bytes)\n" 2>/dev/null
echo ""
echo "💡 Para agregar tu propia música, coloca .mp3/.wav en:"
echo "   $AUDIO_DIR/bgm/upbeat/       (clips energéticos)"
echo "   $AUDIO_DIR/bgm/emotional/    (clips emocionales)"
echo "   $AUDIO_DIR/bgm/suspense/     (clips de suspenso)"
echo "   $AUDIO_DIR/bgm/professional/ (clips corporativos)"
echo "   $AUDIO_DIR/bgm/lofi/         (clips relajados)"
echo ""
echo "🚀 Ahora ejecuta el pipeline:"
echo "   python3 pipeline.py /ruta/al/video.mp4"
