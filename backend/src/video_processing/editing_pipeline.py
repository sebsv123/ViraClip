"""
EditingPipeline — single-pass FFmpeg editing engine.

Applies professional visual + audio effects in one FFmpeg invocation:
  • Color grading     (eq: saturation, contrast, brightness + unsharp)
  • Cinematic look    (teal shadows + warm highlights via colorbalance)
  • Vignette          (darkened edges, focus on subject)
  • Zoom punch-in     (zoompan at detected emphasis word timestamps)
  • Ken Burns effect  (slow drift/zoom when no emphasis words detected)
  • Pattern interrupts (periodic micro-zoom every 3.5s for attention reset)
  • Lower thirds      (animated speaker/topic text overlay, 0-3s)
  • Progress bar      (drawbox that grows across the top)
  • Loudness norm     (loudnorm → -14 LUFS, broadcast standard)

All effects compose into a single filter_complex — one decode + encode pass.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _get_ffmpeg_exe() -> str:
    """
    Prefer the system-installed ffmpeg (typically has drawtext/freetype/etc.)
    over the imageio-ffmpeg bundled binary which is a minimal build that
    lacks libfreetype and therefore does not include the drawtext filter.
    Falls back to imageio_ffmpeg only when no system ffmpeg is found.
    """
    import shutil
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


# ── tuneable constants (override via env vars) ────────────────────────────────
SATURATION      = float(os.environ.get("EP_SATURATION",      "1.25"))
CONTRAST        = float(os.environ.get("EP_CONTRAST",        "1.10"))
BRIGHTNESS      = float(os.environ.get("EP_BRIGHTNESS",      "0.02"))
SHARPNESS       = float(os.environ.get("EP_SHARPNESS",       "0.8"))
ZOOM_FACTOR     = float(os.environ.get("EP_ZOOM_FACTOR",     "1.12"))
ZOOM_FRAMES     = int(os.environ.get("EP_ZOOM_FRAMES",       "8"))     # ~0.27s @ 30fps
KB_ZOOM_RATE    = float(os.environ.get("EP_KB_ZOOM_RATE",    "0.00004"))  # Ken Burns per-frame growth
PI_INTERVAL     = float(os.environ.get("EP_PI_INTERVAL",     "12.0"))  # Pattern interrupt interval (s)
PI_ZOOM         = float(os.environ.get("EP_PI_ZOOM",         "1.04"))  # Pattern interrupt peak zoom
PI_FRAMES       = int(os.environ.get("EP_PI_FRAMES",         "12"))    # Pattern interrupt ramp frames
PROGRESS_H      = int(os.environ.get("EP_PROGRESS_H",        "6"))
PROGRESS_CLR    = os.environ.get("EP_PROGRESS_COLOR",        "ff4444")
LUFS_TARGET     = float(os.environ.get("EP_LUFS_TARGET",     "-14"))
SPEECH_TEMPO_PROFILES = {
    "insurance_explainer": 1.12,   # seguros: +12%, óptimo para explicaciones técnicas
    "interview":           1.08,   # entrevista: +8%, respeta el ritmo natural
    "testimonial":         1.05,   # testimonio: +5%, más emocional, no acelerar mucho
    "default":             1.10,   # default seguro para cualquier contenido
}
RNNOISE_MODEL_PATH = os.environ.get("RNNOISE_MODEL_PATH", "")
# Para activar denoising neuronal, descargar modelo bd.rnnn de:
# https://github.com/GregorR/rnnoise-models
# y configurar: RNNOISE_MODEL_PATH=/path/to/bd.rnnn en el entorno Docker.
LOWER_THIRD_ON    = os.environ.get("EP_LOWER_THIRD",   "true").lower() != "false"
FONT_PATH         = os.environ.get("EP_FONT_PATH",    "/app/fonts/TikTokSans-Regular.ttf")
VOICE_COMPRESS_ON = os.environ.get("EP_VOICE_COMPRESS", "true").lower() != "false"
FILM_GRAIN        = int(os.environ.get("EP_FILM_GRAIN",  "10"))    # 0 = off
WORD_CALLOUT_ON   = os.environ.get("EP_WORD_CALLOUT",   "true").lower() != "false"
FACE_ZOOM_ON      = os.environ.get("EP_FACE_ZOOM",      "true").lower() != "false"
CALLOUT_FONT_SIZE = int(os.environ.get("EP_CALLOUT_FONT_SIZE", "88"))
CALLOUT_DURATION  = float(os.environ.get("EP_CALLOUT_DURATION", "0.45"))
EP_HOOK_ZOOM_ON   = os.environ.get("EP_HOOK_ZOOM_ON",  "true").lower() != "false"
EP_BEAT_SYNC_ON   = os.environ.get("EP_BEAT_SYNC_ON",  "true").lower() != "false"
EP_FADE_ON        = os.environ.get("EP_FADE_ON",       "true").lower() != "false"
EP_FADE_DURATION  = float(os.environ.get("EP_FADE_DURATION",   "0.25"))
EP_CTA_ON         = os.environ.get("EP_CTA_ON",        "false").lower() != "false"
EP_CTA_TEXT       = os.environ.get("EP_CTA_TEXT",      "Follow for more!")
EP_CTA_DURATION   = float(os.environ.get("EP_CTA_DURATION",    "2.0"))
EP_CTA_FONT_SIZE  = int(os.environ.get("EP_CTA_FONT_SIZE",     "54"))
EP_SAT_PULSE_ON       = os.environ.get("EP_SAT_PULSE_ON",       "true").lower() != "false"
EP_SAT_PULSE_STRENGTH = float(os.environ.get("EP_SAT_PULSE_STRENGTH", "1.60"))
EP_LETTERBOX_ON       = os.environ.get("EP_LETTERBOX_ON",       "false").lower() != "false"
EP_LETTERBOX_H        = float(os.environ.get("EP_LETTERBOX_H",   "0.07"))
EP_WATERMARK_ON       = os.environ.get("EP_WATERMARK_ON",       "false").lower() != "false"
EP_WATERMARK_TEXT     = os.environ.get("EP_WATERMARK_TEXT",     "")
EP_THEME_GRADE_ON     = os.environ.get("EP_THEME_GRADE_ON",     "true").lower() != "false"
EP_THEME_EQ_ON        = os.environ.get("EP_THEME_EQ_ON",        "true").lower() != "false"
EP_PROGRESS_STYLE     = os.environ.get("EP_PROGRESS_STYLE",     "solid")  # solid | gradient | dots
VIGNETTE_ENABLED      = os.environ.get("VIGNETTE_ENABLED",     "false").lower() == "true"
SUBJECT_ENHANCE       = os.environ.get("SUBJECT_ENHANCE",      "true").lower() == "true"


# ── helpers ───────────────────────────────────────────────────────────────────

def _probe_video(path: Path) -> Tuple[int, int, float, float]:
    """Return (width, height, fps, duration) via ffmpeg -i."""
    # Use ffmpeg -i instead of ffprobe (imageio_ffmpeg doesn't bundle ffprobe)
    out = subprocess.run(
        [
            _get_ffmpeg_exe(), "-i", str(path),
        ],
        capture_output=True, timeout=15,
    )
    # Parse from stderr instead of JSON
    import re
    stderr = out.stderr.decode('utf-8', errors='replace') if out.stderr else ''
    # Default values
    w, h, fps, dur = 1080, 1920, 30.0, 0.0
    # Parse dimensions
    dim_match = re.search(r'(\d{3,4})x(\d{3,4})', stderr)
    if dim_match:
        w, h = int(dim_match.group(1)), int(dim_match.group(2))
    # Parse FPS
    fps_match = re.search(r'(\d+\.?\d*)\s*fps', stderr)
    if fps_match:
        fps = float(fps_match.group(1))
    # Parse duration
    dur_match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", stderr)
    if dur_match:
        dur = int(dur_match.group(1)) * 3600 + int(dur_match.group(2)) * 60 + float(dur_match.group(3))
    else:
        # Fallback: try ffprobe when ffmpeg -i returns Duration: N/A
        try:
            import shutil
            if shutil.which("ffprobe"):
                _fp = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(path)],
                    capture_output=True, text=True, timeout=15
                )
                if _fp.returncode == 0 and _fp.stdout.strip():
                    dur = float(_fp.stdout.strip())
        except Exception:
            pass
    # BUG B fix: raise ValueError if both duration detection methods failed
    if dur <= 0:
        raise ValueError(
            f"Could not determine duration for {path} — "
            f"ffmpeg -i returned no Duration: line and ffprobe fallback also failed"
        )
    return w, h, fps, dur


def _probe_actual_frame_count(path: Path, dur: float = 0.0, fps: float = 30.0) -> int:
    """
    Probe the actual number of video frames in a file using ffprobe.
    
    Uses `-count_packets` to count packets in the video stream, which gives
    the real frame count even for VFR (Variable Frame Rate) videos where
    dur * fps would overestimate.
    
    If ffprobe is not available or probing fails, returns a conservative
    estimate using ceil(dur * fps) — better to have one extra frame than
    to run out of frames mid-clip.
    """
    try:
        import shutil
        if not shutil.which("ffprobe"):
            # Try imageio_ffmpeg as fallback for ffprobe
            try:
                import imageio_ffmpeg as _iio
                ffprobe_path = _iio.get_ffmpeg_exe().replace("ffmpeg", "ffprobe")
                if not Path(ffprobe_path).exists():
                    return max(1, int(math.ceil(dur * fps)))
            except Exception:
                return max(1, int(math.ceil(dur * fps)))
        else:
            ffprobe_path = "ffprobe"

        result = subprocess.run(
            [
                ffprobe_path,
                "-v", "error",
                "-select_streams", "v:0",
                "-count_packets",
                "-show_entries", "stream=nb_read_packets",
                "-of", "csv=p=0",
                str(path),
            ],
            capture_output=True, timeout=15,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            count = int(result.stdout.strip())
            return max(0, count)
    except Exception:
        pass
    return max(1, int(math.ceil(dur * fps)))


def _emphasis_items(
    words: List[Dict[str, Any]], max_zooms: int = 1
) -> List[Tuple[float, str]]:
    """Return up to max_zooms (timestamp, word_text) pairs for zoom + callout effects."""
    hits: List[Tuple[float, float, str]] = []
    for w in words:
        start = float(w.get("start", 0))
        if start < 0.3:
            continue
        conf  = float(w.get("confidence", w.get("score", 0.8)))
        text  = str(w.get("word", w.get("text", ""))).strip()
        is_emph = bool(w.get("is_emphasis", False))
        is_loud = text == text.upper() and len(text) > 2
        is_excl = text.endswith("!")
        if is_emph or (conf >= 0.92 and (is_loud or is_excl)):
            hits.append((start, conf, text))

    hits.sort(key=lambda x: -x[1])
    selected: List[Tuple[float, str]] = []
    for ts, _, word in hits:
        if all(abs(ts - s) > 8.0 for s, _ in selected):
            selected.append((ts, word))
        if len(selected) >= max_zooms:
            break
    return sorted(selected, key=lambda x: x[0])


def _beat_timestamps(video_path: Path, dur: float, max_beats: int = 6) -> List[float]:
    """
    Extract audio beat timestamps using librosa beat tracker.
    Returns up to max_beats beat times in the range (1.0s, dur-1.0s).
    Falls back to [] on any error (librosa not installed, silent audio, etc.).
    """
    try:
        import librosa  # type: ignore
        import numpy as np

        y, sr = librosa.load(
            str(video_path), sr=22050, mono=True,
            duration=min(dur, 90.0),
        )
        _, beat_times = librosa.beat.beat_track(y=y, sr=sr, units="time")
        valid = [float(t) for t in beat_times if 1.0 < float(t) < dur - 1.0]
        if not valid:
            return []
        if len(valid) <= max_beats:
            return valid
        idxs = np.linspace(0, len(valid) - 1, max_beats, dtype=int)
        return sorted(float(valid[i]) for i in idxs)
    except Exception:
        return []


def _detect_face_position(path: Path, dur: float) -> Tuple[float, float]:
    """
    Sample 5 frames distributed across the clip and return the averaged
    normalised face centre (cx_norm, cy_norm).
    Uses MediaPipe FaceMesh first, falls back to Haar cascade.
    Returns (0.5, 0.5) if face not found.
    """
    try:
        import cv2
        import mediapipe as mp

        sample_times = [dur * t for t in (0.20, 0.35, 0.50, 0.65, 0.80)]
        cx_values, cy_values = [], []
        cap = cv2.VideoCapture(str(path))
        w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)

        with mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True, max_num_faces=1,
            refine_landmarks=True, min_detection_confidence=0.3,
        ) as face_mesh:
            for t in sample_times:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
                ret, frame = cap.read()
                if not ret:
                    continue
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(rgb)
                if results.multi_face_landmarks:
                    lm = results.multi_face_landmarks[0].landmark
                    cx_values.append(float(lm[1].x))
                    cy_values.append(float(lm[1].y))

        # Fallback: Haar cascade si FaceMesh no detectó nada
        if not cx_values:
            cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
            for t in sample_times:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
                ret, frame = cap.read()
                if not ret:
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = cascade.detectMultiScale(gray, 1.1, 4, minSize=(30, 30))
                if len(faces) > 0:
                    x, y, fw, fh = faces[0]
                    cx_values.append((x + fw / 2) / w)
                    cy_values.append((y + fh / 2) / h)

        cap.release()

        if cx_values:
            cx = max(0.15, min(0.85, sum(cx_values) / len(cx_values)))
            cy = max(0.15, min(0.85, sum(cy_values) / len(cy_values)))
            logger.info(f"[face] detected={len(cx_values)} cx={cx:.3f} cy={cy:.3f}")
            return cx, cy

    except Exception:
        pass

    logger.info("[face] no face detected, using center fallback")
    return 0.5, 0.5


def _pattern_interrupt_timestamps(dur: float, interval: float = PI_INTERVAL) -> List[float]:
    """Generate evenly-spaced pattern-interrupt timestamps across the clip duration."""
    if dur <= 0 or interval <= 0:
        return []
    ts_list: List[float] = []
    t = interval
    while t < dur - 0.5:
        ts_list.append(t)
        t += interval
    return ts_list


def _build_zoom_expr(
    timestamps: List[float],
    fps: float,
    zoom_factor: float = ZOOM_FACTOR,
    zoom_frames: int = ZOOM_FRAMES,
) -> str:
    """
    Build a zoompan z= expression using Gaussian bell curves centred at each
    timestamp.  Uses only single-argument functions so no commas appear in the
    expression — required for FFmpeg 4.4 where commas inside option values act
    as filter-chain separators even inside single-quoted strings.

    z = 1 + delta * sum_i( exp(-k * (in - f_i)^2) )

    where k is chosen so the bell is at ~5 % of peak at ±zoom_frames frames.
    Variable name is 'in' (input frame counter in zoompan, not 'n').
    """
    if not timestamps:
        return "1.0"

    half  = max(1, zoom_frames // 2)
    delta = zoom_factor - 1.0
    # k: exp(-k * half^2) = 0.05  →  k = ln(20) / half^2
    k = math.log(20.0) / max(1, half * half)

    terms: List[str] = []
    for ts in timestamps:
        fi = int(round(ts * fps))
        # (in - fi)^2  written without pow() or any multi-arg function
        sq = f"(in-{fi})*(in-{fi})"
        terms.append(f"{delta:.4f}*exp(-{k:.5f}*{sq})")

    return "1+" + "+".join(terms)


def _build_ken_burns_zoom(fps: float, dur: float, pi_timestamps: List[float]) -> str:
    """
    Build a single zoompan z= expression that combines:
      • Ken Burns slow drift: linear zoom growth (no functions/commas)
      • Pattern interrupt Gaussian pulses at pi_timestamps

    Uses only 'in' variable and single-arg exp() — safe for FFmpeg 4.4.
    """
    # Ken Burns: uncapped linear growth (stays well below 1.05 for clips < 25s)
    kb_term = f"1+{KB_ZOOM_RATE:.6f}*in"

    if not pi_timestamps:
        return kb_term

    # Pattern interrupt Gaussian bumps
    delta = PI_ZOOM - 1.0
    half  = max(1, PI_FRAMES // 2)
    k     = math.log(20.0) / max(1, half * half)
    pi_terms: List[str] = []
    for ts in pi_timestamps:
        fi = int(round(ts * fps))
        sq = f"(in-{fi})*(in-{fi})"
        pi_terms.append(f"{delta:.4f}*exp(-{k:.5f}*{sq})")

    return kb_term + "+" + "+".join(pi_terms)


def _sanitize_drawtext(text: str, max_chars: int = 40) -> str:
    """Escape text for FFmpeg drawtext and truncate."""
    # Remove special chars that break drawtext
    cleaned = re.sub(r"[:\\'\[\]@]", "", text)
    cleaned = cleaned.replace("%", "%%").replace("\n", " ").strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars - 1] + "…"
    return cleaned


def _classify_theme(text: str) -> str:
    """
    Classify clip theme from keyword matching into 'warm', 'cool', or 'neutral'.
    Drives the adaptive colorbalance grade and optional audio EQ preset.
    """
    warm = {
        "motivat", "fitness", "workout", "lifestyle", "fashion", "food",
        "travel", "love", "success", "mindset", "growth", "wellness",
        "beauty", "relat", "health", "inspir", "positiv", "sport",
    }
    cool = {
        "tech", "coding", "program", "gaming", "finance", "crypto", "invest",
        "stock", "market", "ai ", "robot", "science", "data", "develop",
        "software", "hardware", "startup", "business", "network",
    }
    low = text.lower()
    wc = sum(1 for k in warm if k in low)
    cc = sum(1 for k in cool if k in low)
    if wc > cc:
        return "warm"
    if cc > wc:
        return "cool"
    return "neutral"


def _build_flash_filter(flash_timestamps: List[float], duration: float = 0.07) -> str:
    """
    Return a geq expression that flashes white for `duration` seconds at each timestamp.
    Used as: geq=r='255*...:g='255*...:b='255*...'
    Composited as an overlay on top of the video via blend.
    """
    if not flash_timestamps:
        return ""
    parts = []
    for ts in flash_timestamps:
        # alpha ramps: 0→1 in first half, 1→0 in second half of duration
        h = duration / 2
        # Using 'between' in geq lum expression: full white during flash windows
        parts.append(f"between(t\\,{ts:.3f}\\,{ts+duration:.3f})")
    return "+".join(parts)


def _build_filter_complex(
    w: int,
    h: int,
    fps: float,
    dur: float,
    emphasis_items: List[Tuple[float, str]],
    has_audio: bool,
    segment_text: str = "",
    flash_timestamps: Optional[List[float]] = None,
    face_cx_norm: float = 0.5,
    face_cy_norm: float = 0.5,
    beat_pi_ts: Optional[List[float]] = None,
    energy_level: float = 0.5,
    zoom_intensity: str = "medium",
    grain_override: int = 0,
    lut_vf: str = "",
    denoise_audio: bool = True,
    sections: Optional[List[Any]] = None,
    video_path: Optional[Path] = None,
) -> Tuple[str, str, Optional[str]]:
    """
    Compose the full filter_complex string for one clip.
    Returns (filter_complex_str, v_out_label, a_out_label_or_None).
    """

    filters: List[str] = []

    # ── 0. Determine clip theme for adaptive grade + audio EQ ──────────────────
    theme = _classify_theme(segment_text) if segment_text else "neutral"

    # ── Per-clip energy overrides (scale module globals by energy_level) ───────
    _sat    = round(max(1.0, min(1.50, SATURATION * (0.82 + energy_level * 0.40))), 3)
    _con    = round(max(1.0, min(1.30, CONTRAST   * (0.88 + energy_level * 0.28))), 3)
    _zoom   = {"off": 1.0, "subtle": 1.06, "medium": ZOOM_FACTOR, "strong": min(1.18, ZOOM_FACTOR * 1.06)}.get(zoom_intensity, ZOOM_FACTOR)
    _pi_int = max(8.0, PI_INTERVAL + (0.5 - energy_level) * 6.0)
    _grain  = grain_override if grain_override > 0 else max(0, int(FILM_GRAIN * (0.4 + energy_level * 1.2)))
    logger.debug("[EP] energy=%.2f → sat=%.2f con=%.2f zoom=%.3f pi_int=%.1f grain=%d%s",
                 energy_level, _sat, _con, _zoom, _pi_int, _grain,
                 " (cat-override)" if grain_override > 0 else "")

    # ── 1. Colour grading: eq + unsharp ──────────────────────────────────────
    eq_f     = f"eq=saturation={_sat}:contrast={_con}:brightness={BRIGHTNESS}"
    sharp_f  = f"unsharp=5:5:{SHARPNESS}:5:5:0"
    filters.append(f"[0:v]{eq_f},{sharp_f}[vgrade]")

    # ── 1.5. Saturation pulse at emphasis moments ─────────────────────────────
    # A second eq layer briefly boosts saturation at emphasis timestamps via the
    # `enable` timeline option. When inactive it is identity (pass-through).
    prev_grade = "[vgrade]"
    if EP_SAT_PULSE_ON and emphasis_items:
        ratio        = EP_SAT_PULSE_STRENGTH / max(SATURATION, 0.01)
        enable_parts = [
            f"between(t,{ts-0.10:.3f},{ts+0.50:.3f})" for ts, _ in emphasis_items
        ]
        filters.append(
            f"[vgrade]eq=saturation={ratio:.3f}"
            f":enable='{'+'.join(enable_parts)}'[vpulse]"
        )
        prev_grade = "[vpulse]"

    # ── 1.6. Section-aware grade overrides (Master Director) ──────────────────
    # Each narrative section (hook/build/payoff/cta) can lift saturation and
    # contrast above the base grade. We chain one `eq=...:enable='between(t,...)'`
    # per section that has a non-trivial multiplier (>3% off neutral).
    # Outside the section's time range the eq is identity (pass-through).
    if sections:
        _sec_idx = 0
        for sec in sections:
            try:
                t0 = float(getattr(sec, "t_start", 0.0))
                t1 = float(getattr(sec, "t_end",   0.0))
                if t1 <= t0:
                    continue
                sm = float(getattr(sec, "saturation_mult", 1.0))
                cm = float(getattr(sec, "contrast_mult",   1.0))
                # Skip sections that are essentially no-ops to keep filter chain short
                if abs(sm - 1.0) < 0.03 and abs(cm - 1.0) < 0.03:
                    continue
                _label = f"[vsec{_sec_idx}]"
                filters.append(
                    f"{prev_grade}eq=saturation={sm:.3f}:contrast={cm:.3f}"
                    f":enable='between(t,{t0:.3f},{t1:.3f})'{_label}"
                )
                prev_grade  = _label
                _sec_idx   += 1
            except Exception:
                continue
        if _sec_idx > 0:
            logger.debug("[EP] Section grade overrides: %d sections active", _sec_idx)

    # ── 2. Cinematic colour balance: theme-adaptive ───────────────────────────
    # warm: red midtones/highlights up, blue down (golden-hour feel)
    # cool: blue shadows/midtones up, red down (clean tech/digital feel)
    # neutral: default teal/orange grade
    if EP_THEME_GRADE_ON and theme == "warm":
        cb_params = "rs=0.00:gs=0.03:bs=-0.02:rm=0.04:gm=0:bm=-0.02:rh=0.10:gh=0:bh=-0.08"
    elif EP_THEME_GRADE_ON and theme == "cool":
        cb_params = "rs=-0.06:gs=0.02:bs=0.10:rm=-0.02:gm=0:bm=0.03:rh=0.04:gh=0:bh=-0.02"
    else:
        cb_params = "rs=-0.03:gs=0.03:bs=0.06:rm=0:gm=0:bm=0:rh=0.06:gh=0:bh=-0.06"
    filters.append(f"{prev_grade}colorbalance={cb_params}[vcine]")

    # ── 3. Enhancement de sujeto (sin vignette oscurecedor) ──────────────────
    # VIGNETTE_ENABLED=false por defecto — el vignette oscurece la imagen sin aportar.
    # En su lugar se aplica un enhancement sutil de persona:
    #   - unsharp: añade nitidez suave (cara más definida, texto más nítido)
    #   - hqdn3d: reduce ruido/granos de piel sin emborronar
    # Se puede restaurar el vignette con VIGNETTE_ENABLED=true si se desea.
    if VIGNETTE_ENABLED:
        _vignette_angle = os.environ.get("VIGNETTE_ANGLE", "PI/15")
        filters.append(f"[vcine]vignette=angle={_vignette_angle}[vvig]")
        prev_v = "[vvig]"
    elif SUBJECT_ENHANCE:
        # unsharp luma 3x3 suave + chroma sin tocar + denoise leve para piel
        # hqdn3d=luma_spatial:chroma_spatial:luma_temporal:chroma_temporal
        filters.append(
            "[vcine]"
            "unsharp=luma_msize_x=3:luma_msize_y=3:luma_amount=0.6:"
            "chroma_msize_x=3:chroma_msize_y=3:chroma_amount=0.0,"
            "hqdn3d=2:1:3:2.5"
            "[vvig]"
        )
        prev_v = "[vvig]"
    else:
        filters.append(f"[vcine]copy[vvig]")
        prev_v = "[vvig]"

    # ── 3.5. Film grain (cinematic texture) ───────────────────────────────────
    # noise=alls: strength 0-100; allf=t: temporal (varies per-frame like real grain)
    if _grain > 0:
        filters.append(f"{prev_v}noise=alls={_grain}:allf=t[vgrain]")
        prev_v = "[vgrain]"

    # ── 4. Zoom: emphasis punch-in OR Ken Burns + pattern interrupts ────────────
    # All zoom logic runs in ONE zoompan call to avoid chained decode quality loss.
    # Uses Gaussian exp(-k*(in-fi)^2) — no commas in expressions (FFmpeg 4.4 safe).
    # x/y are face-aware: (iw-iw/zoom)*face_cx_norm centres the crop on the face.
    x_expr = f"(iw-iw/zoom)*{face_cx_norm:.4f}"
    y_expr = f"(ih-ih/zoom)*{face_cy_norm:.4f}"

    emphasis_ts = [ts for ts, _ in emphasis_items]
    if emphasis_ts and zoom_intensity != "off":
        z_expr = _build_zoom_expr(emphasis_ts, fps, _zoom, ZOOM_FRAMES)
    elif dur >= 4.0 and zoom_intensity != "off":
        # Prefer beat-synced PI; fall back to evenly-spaced
        if beat_pi_ts:
            pi_ts = beat_pi_ts
        elif dur >= _pi_int * 2:
            pi_ts = _pattern_interrupt_timestamps(dur, _pi_int)
        else:
            pi_ts = []
        z_expr = _build_ken_burns_zoom(fps, dur, pi_ts)
    else:
        z_expr = "1.0"

    # ── 4.5. Hook zoom: sharp punch-in at t=0 to grab immediate attention ─────
    # Gaussian bell centred on frame 0 — no comma in expression (FFmpeg 4.4 safe).
    if EP_HOOK_ZOOM_ON and dur >= 1.0:
        hook_delta = (ZOOM_FACTOR - 1.0) * 0.70         # 70% of normal punch
        hook_half  = max(3, int(fps * 0.15))             # ~0.15 s radius
        hook_k     = math.log(20.0) / max(1, hook_half * hook_half)
        hook_term  = f"{hook_delta:.4f}*exp(-{hook_k:.5f}*in*in)"
        if z_expr == "1.0":
            z_expr = f"1+{hook_term}"
        elif z_expr.startswith("1+"):
            z_expr = "1+" + hook_term + "+" + z_expr[2:]

    # ── 4. Zoom: scale+crop animado con expresiones de tiempo ────────────────
    # Reemplaza zoompan (que requiere d=N_frames y congela el último frame
    # cuando el frame count del input se sobreestima en VFR o FPS mal detectado).
    # Usa scale + crop con enable='between(t,...)' para cada tipo de zoom:
    #   • Hook zoom: t=0 → ~0.4s, escala a zoom_factor y vuelve
    #   • Emphasis zoom: en cada ts, escala a zoom_factor ~0.3s
    #   • Ken Burns: escala lineal lenta 1.0 → 1.04 en toda la duración
    #   • Pattern interrupts: pulsos periódicos con enable
    # El centrado de cara se aplica en el crop con face_cx_norm, face_cy_norm.
    _zoom_scale_exprs: List[str] = []
    
    # Hook zoom: t=0 hasta ~0.4s
    if EP_HOOK_ZOOM_ON and dur >= 1.0:
        _hook_delta = (ZOOM_FACTOR - 1.0) * 0.70
        _zoom_scale_exprs.append(
            f"if(between(t,0,0.4),1+{_hook_delta:.4f}*sin(PI*t/0.4),1)"
        )
    
    # Emphasis zoom: en cada ts
    if emphasis_ts and zoom_intensity != "off":
        for ts in emphasis_ts:
            _zoom_scale_exprs.append(
                f"if(between(t,{ts-0.15:.3f},{ts+0.45:.3f}),{ZOOM_FACTOR:.4f},1)"
            )
    
    # Ken Burns: escala lineal lenta (cuando no hay emphasis)
    if not emphasis_ts and dur >= 4.0 and zoom_intensity != "off":
        _zoom_scale_exprs.append(f"1+0.004*t/{dur:.3f}")
    
    # Pattern interrupts
    if not emphasis_ts and dur >= 4.0 and zoom_intensity != "off":
        if beat_pi_ts:
            _pi_ts_list = beat_pi_ts
        elif dur >= PI_INTERVAL * 2:
            _pi_ts_list = _pattern_interrupt_timestamps(dur, PI_INTERVAL)
        else:
            _pi_ts_list = []
        for _pi_ts in _pi_ts_list:
            _zoom_scale_exprs.append(
                f"if(between(t,{_pi_ts-0.15:.3f},{_pi_ts+0.45:.3f}),{PI_ZOOM:.4f},1)"
            )
    
    if _zoom_scale_exprs:
        # Combine all zoom expressions: multiply them together (1*1.12*1 = 1.12)
        _combined_zoom = "*".join(_zoom_scale_exprs)
        _scale_expr = f"iw*{_combined_zoom}"
        _crop_w = f"iw/{_combined_zoom}"
        _crop_h = f"ih/{_combined_zoom}"
        filters.append(
            f"{prev_v}scale={_scale_expr}:{_scale_expr},"
            f"crop=w={_crop_w}:h={_crop_h}:"
            f"x=(iw-{_crop_w})*{face_cx_norm:.4f}:"
            f"y=(ih-{_crop_h})*{face_cy_norm:.4f}[vzoom]"
        )
    else:
        filters.append(f"{prev_v}null[vzoom]")
    prev_v = "[vzoom]"

    # ── 5. (Pattern interrupts now baked into step 4 — no second zoompan) ─────

    # ── 6. Progress bar (solid | gradient | dots) ─────────────────────────────
    if dur > 0:
        pb_w = f"iw*t/{dur:.3f}"
        if EP_PROGRESS_STYLE == "gradient":
            # Two-layer drawbox: dim full bar + bright right half = left-to-right gradient
            half_dur = dur * 2
            filters.append(
                f"{prev_v}drawbox=x=0:y=0:w={pb_w}:h={PROGRESS_H}"
                f":color={PROGRESS_CLR}@0.40:t=fill,"
                f"drawbox=x=iw*t/{half_dur:.3f}:y=0:w=iw*t/{half_dur:.3f}:h={PROGRESS_H}"
                f":color={PROGRESS_CLR}@0.55:t=fill[vpbar]"
            )
        elif EP_PROGRESS_STYLE == "dots":
            # N evenly spaced dots that appear sequentially as time advances
            n_dots = 10
            dot_w  = max(4, int(w * 0.055))
            gap    = w / n_dots
            dot_x0 = max(0, int((gap - dot_w) // 2))
            parts  = [
                f"drawbox=x={int(dot_x0 + i * gap)}:y=0:w={dot_w}:h={PROGRESS_H}"
                f":color={PROGRESS_CLR}@0.9:t=fill:enable='gte(t,{dur * i / n_dots:.3f})'"
                for i in range(n_dots)
            ]
            filters.append(f"{prev_v}" + ",".join(parts) + "[vpbar]")
        else:
            # Default solid
            filters.append(
                f"{prev_v}drawbox=x=0:y=0:w={pb_w}:h={PROGRESS_H}"
                f":color={PROGRESS_CLR}@0.9:t=fill[vpbar]"
            )
        prev_v = "[vpbar]"

    # ── 7. Lower thirds ───────────────────────────────────────────────────────
    if LOWER_THIRD_ON and segment_text:
        safe_text = _sanitize_drawtext(segment_text)
        font_arg  = f":fontfile={FONT_PATH}" if Path(FONT_PATH).exists() else ""
        # alpha: fade-in 0→0.4s, hold 0.4→3.0s, fade-out 3.0→3.5s
        alpha_expr = "if(lt(t,0.4),t/0.4,if(lt(t,3.0),1,if(lt(t,3.5),(3.5-t)/0.5,0)))"
        # Push lower-third up if face is in the lower portion of frame
        lt_frac = 0.68 if face_cy_norm > 0.60 else 0.80
        y_pos = int(h * lt_frac)
        filters.append(
            f"{prev_v}drawtext=text='{safe_text}'{font_arg}"
            f":fontsize=38:fontcolor=white@1.0"
            f":x=60:y={y_pos}"
            f":alpha='{alpha_expr}'"
            f":box=1:boxcolor=black@0.55:boxborderw=12[vlt]"
        )
        prev_v = "[vlt]"

    # ── 7.5. Emphasis word callouts ────────────────────────────────────────────
    # Center-screen pop-in of the emphasis word for 0.45s. Distinct from lower
    # thirds (smaller, permanent) — these are punchy attention-grabbing bursts.
    if WORD_CALLOUT_ON and emphasis_items:
        font_arg = f":fontfile={FONT_PATH}" if Path(FONT_PATH).exists() else ""
        # Place callouts opposite the face: upper face → mid-frame callouts, lower face → top callouts
        y_callout = int(h * 0.58) if face_cy_norm < 0.45 else int(h * 0.38)
        cd = CALLOUT_DURATION
        for i, (ts, word) in enumerate(emphasis_items):
            safe_word = _sanitize_drawtext(word.upper(), max_chars=12)
            # alpha: ramp-in 0.08s, hold, ramp-out 0.07s
            alpha_expr = (
                f"if(lt(t-{ts:.3f},0),0,"
                f"if(lt(t-{ts:.3f},0.08),(t-{ts:.3f})/0.08,"
                f"if(lt(t-{ts:.3f},{cd-0.07:.3f}),1,"
                f"max(0,1-(t-{ts:.3f}-{cd-0.07:.3f})/0.07))))"
            )
            label_out = f"[vcall{i}]"
            filters.append(
                f"{prev_v}drawtext=text='{safe_word}'{font_arg}"
                f":fontsize={CALLOUT_FONT_SIZE}:fontcolor=white"
                f":x=(w-tw)/2:y={y_callout}"
                f":alpha='{alpha_expr}'"
                f":shadowx=4:shadowy=4:shadowcolor=black@0.9{label_out}"
            )
            prev_v = label_out

    # ── 8. Flash/whiteout at cut transitions ─────────────────────────────────
    if flash_timestamps:
        # Intensity controlled by env (default 0.15 — subtle, not blinding).
        # Earlier 0.35 caused viewer eye-strain on dark scenes.
        try:
            _flash_intensity = float(os.environ.get("EP_FLASH_INTENSITY", "0.15"))
        except ValueError:
            _flash_intensity = 0.15
        _flash_intensity = max(0.05, min(0.5, _flash_intensity))
        enable_parts = [
            f"between(t,{ts:.3f},{ts + 0.07:.3f})" for ts in flash_timestamps
        ]
        enable_expr = "+".join(enable_parts)
        filters.append(
            f"{prev_v}eq=brightness={_flash_intensity:.2f}:enable='{enable_expr}'[vflash]"
        )
        prev_v = "[vflash]"

    # ── 8.5. Cinematic letterbox bars (opt-in via EP_LETTERBOX_ON=true) ───────────
    # Two drawbox calls chained with comma within one filter segment.
    if EP_LETTERBOX_ON:
        bars_h = max(1, int(h * EP_LETTERBOX_H))
        filters.append(
            f"{prev_v}drawbox=x=0:y=0:w=iw:h={bars_h}:color=black@1:t=fill,"
            f"drawbox=x=0:y=ih-{bars_h}:w=iw:h={bars_h}:color=black@1:t=fill[vbars]"
        )
        prev_v = "[vbars]"

    # ── 9. CTA end-card overlay (opt-in via EP_CTA_ON=true) ─────────────────────
    # Shows a configurable call-to-action in the last EP_CTA_DURATION seconds.
    if EP_CTA_ON and dur > EP_CTA_DURATION + 1.0:
        cta_start = dur - EP_CTA_DURATION
        safe_cta  = _sanitize_drawtext(EP_CTA_TEXT, max_chars=40)
        ramp      = 0.30
        alpha_cta = (
            f"if(lt(t,{cta_start:.3f}),0,"
            f"if(lt(t,{cta_start+ramp:.3f}),(t-{cta_start:.3f})/{ramp:.2f},"
            f"if(lt(t,{dur-ramp:.3f}),1,"
            f"max(0,1-(t-{dur-ramp:.3f})/{ramp:.2f}))))"
        )
        font_arg = f":fontfile={FONT_PATH}" if Path(FONT_PATH).exists() else ""
        y_cta = int(h * 0.55)
        filters.append(
            f"{prev_v}drawtext=text='{safe_cta}'{font_arg}"
            f":fontsize={EP_CTA_FONT_SIZE}:fontcolor=yellow"
            f":x=(w-tw)/2:y={y_cta}"
            f":alpha='{alpha_cta}'"
            f":shadowx=3:shadowy=3:shadowcolor=black@0.9[vcta]"
        )
        prev_v = "[vcta]"

    # ── 9.5. Watermark corner text (opt-in via EP_WATERMARK_ON=true) ────────────
    if EP_WATERMARK_ON and EP_WATERMARK_TEXT:
        safe_wm  = _sanitize_drawtext(EP_WATERMARK_TEXT, max_chars=30)
        font_arg = f":fontfile={FONT_PATH}" if Path(FONT_PATH).exists() else ""
        filters.append(
            f"{prev_v}drawtext=text='{safe_wm}'{font_arg}"
            f":fontsize=26:fontcolor=white@0.25"
            f":x=(w-tw-20):y=(h-th-20)[vwm]"
        )
        prev_v = "[vwm]"

    # ── 10. Fade-in / fade-out con TransitionSelector (template+energy aware) ────
    if EP_FADE_ON and dur > EP_FADE_DURATION * 2 + 0.5:
        fd = min(EP_FADE_DURATION, dur * 0.08)
        _xfade_effect = "fade"
        try:
            # NarrativeCutEngine: detectar energía real del segmento para selector
            _energy_level = 0.5
            try:
                from ..video_processing.narrative_cut_engine import NarrativeCutEngine
                _nce = NarrativeCutEngine()
                _cut_pts = _nce.find_narrative_cuts(
                    transcript=segment_text or "",
                    words_with_timestamps=[],  # words not available in this scope
                    audio_silences=[],
                )
                if _cut_pts:
                    _energy_level = min(1.0, len(_cut_pts) / 10.0 + 0.3)
            except Exception:
                pass

            # TransitionSelector: selección template+energy → tipo de transición
            from ..domains.video.transition_selector import TransitionSelector, TransitionType as _TT
            _ts = TransitionSelector()
            _selected = _ts.select_transition(
                template_style=theme or "viral",
                energy_level=_energy_level,
                use_morph=False,
            )
            # Map TransitionType → FFmpeg xfade effect (safe subset — sin flash)
            _xfade_map = {
                _TT.BLUR: "fade",
                _TT.SWIPE_LEFT: "slideleft",
                _TT.GLITCH: "fade",       # glitch no tiene soporte nativo — degradar a fade
                _TT.FLASH_WHITE: "fade",  # flash prohibido — degradar a fade
                _TT.MORPH: "fade",
            }
            _xfade_effect = _xfade_map.get(_selected, "fade")
            logger.debug(f"[EP] TransitionSelector: {_selected} → xfade={_xfade_effect} energy={_energy_level:.2f}")
        except Exception as _ts_e:
            logger.debug(f"[EP] TransitionSelector skipped: {_ts_e}")

        filters.append(
            f"{prev_v}fade=t=in:d={fd:.3f},"
            f"fade=t=out:st={dur - fd:.3f}:d={fd:.3f}[vfade]"
        )
        prev_v = "[vfade]"

    # ── 10.5. Cinematic LUT (merged in — eliminates a separate FFmpeg pass) ─────
    if lut_vf:
        filters.append(f"{prev_v}{lut_vf}[vlut]")
        prev_v = "[vlut]"

    # rename last video label to [vout]
    if prev_v != "[vout]":
        filters.append(f"{prev_v}null[vout]")

    # ── audio ──────────────────────────────────────────────────────────────────
    # highpass: remove low-frequency rumble (<80 Hz) from non-bass content
    # acompressor: tighten dynamic range so quiet/loud speech sound balanced
    # loudnorm: broadcast-standard LUFS target (-14 by default)
    # theme EQ: per-niche shelf filters (warm=low-shelf boost, cool=presence boost)
    if has_audio:
        theme_eq = ""
        if EP_THEME_EQ_ON:
            if theme == "warm":
                theme_eq = "lowshelf=g=2:f=150:width_type=s:width=200,"
            elif theme == "cool":
                theme_eq = "highshelf=g=2:f=6000:width_type=s:width=2000,"
        _rnnoise_prefix = ""
        if RNNOISE_MODEL_PATH and Path(RNNOISE_MODEL_PATH).exists():
            _rnnoise_prefix = f"arnndn=m={RNNOISE_MODEL_PATH},"
        _dn = "arnndn=m=cb.rnnn," if denoise_audio else ""
        _silence_remove = (
            "silenceremove=start_periods=0:stop_periods=-1:"
            "stop_duration=0.45:stop_threshold=-42dB:"
            "stop_silence=0.12:leave_silence=1,"
        )
        _content_type = segment_text if segment_text else "default"
        _tempo_val = SPEECH_TEMPO_PROFILES.get(_content_type, SPEECH_TEMPO_PROFILES["default"])
        _tempo = f"atempo={_tempo_val:.3f},"
        if VOICE_COMPRESS_ON:
            filters.append(
                f"[0:a]atrim=end={dur:.3f},"
                f"{_silence_remove}"
                f"{_dn}"
                f"highpass=f=90,"
                f"{theme_eq}"
                f"equalizer=f=3000:t=o:w=2:g=3,"
                f"equalizer=f=200:t=o:w=2:g=-2,"
                f"acompressor=threshold=0.08:ratio=5:attack=3:release=50:makeup=2,"
                f"loudnorm=I={LUFS_TARGET}:TP=-1.0:LRA=9,"
                f"apad=whole_dur={dur:.3f},"
                f"aresample=44100,"
                f"aformat=channel_layouts=stereo[aout]"
            )
        else:
            filters.append(
                f"[0:a]atrim=end={dur:.3f},"
                f"{_silence_remove}"
                f"{_dn}{theme_eq}"
                f"loudnorm=I={LUFS_TARGET}:TP=-1.0:LRA=9,"
                f"apad=whole_dur={dur:.3f},"
                f"aresample=44100,"
                f"aformat=channel_layouts=stereo[aout]"
            )
        return ";".join(filters), "[vout]", "[aout]"
    else:
        return ";".join(filters), "[vout]", None


# Muletillas comunes en español para contenido de seguros
_SPANISH_FILLERS = {
    "eh", "este", "pues", "bueno", "entonces", "osea", "o sea",
    "mm", "mmm", "ah", "mhm", "ehm", "este...", "pues...",
    "digamos", "básicamente", "literalmente"
}
_MAX_FILLER_DURATION_S = 0.65  # muletillas duran < 650ms

def detect_spanish_fillers(words: list) -> list:
    """
    Detecta timestamps de muletillas en español usando dos métodos:
    1. Palabras explícitas de la lista _SPANISH_FILLERS.
    2. Gaps entre palabras de 100-650ms donde Whisper no transcribió nada
       (zona típica de 'eh', 'mm' no capturados por el modelo).
    Retorna lista de (start_s, end_s) a eliminar del timeline.
    """
    cuts = []
    if not words:
        return cuts

    # Método 1: palabras explícitas
    for w in words:
        text = w.get("text", "").strip().lower().rstrip(".,;:")
        if text in _SPANISH_FILLERS:
            s = w.get("start", 0) / 1000.0
            e = w.get("end", 0) / 1000.0
            if 0 < (e - s) < _MAX_FILLER_DURATION_S:
                cuts.append((s, e))

    # Método 2: gaps silenciosos no transcritos (muletillas inaudibles)
    for i in range(len(words) - 1):
        gap_s = words[i].get("end", 0) / 1000.0
        gap_e = words[i + 1].get("start", 0) / 1000.0
        gap_dur = gap_e - gap_s
        if 0.12 < gap_dur < _MAX_FILLER_DURATION_S:
            cuts.append((gap_s, gap_e))

    # Deduplicar y ordenar
    cuts = sorted(set(cuts), key=lambda x: x)
    return cuts


# ── public API ────────────────────────────────────────────────────────────────

class EditingPipeline:
    """
    Apply a full professional editing pass to a single clip.

    All effects run in one FFmpeg filter_complex pass — no quality loss
    from multiple encode/decode cycles.
    """

    async def apply(
        self,
        video_path: Path,
        words: Optional[List[Dict[str, Any]]],
        output_path: Path,
        segment_text: str = "",
        flash_timestamps: Optional[List[float]] = None,
        gpu_settings: Optional[Dict[str, Any]] = None,
        energy_level: float = 0.5,
        zoom_intensity: str = "medium",
        grain_override: int = 0,
        lut_vf: str = "",
        denoise_audio: bool = True,
        sections: Optional[List[Any]] = None,
    ) -> Path:
        """
        Run the full editing pipeline.
        Returns output_path on success, video_path unchanged on failure.
        """
        try:
            w, h, fps, dur = await asyncio.get_event_loop().run_in_executor(
                None, _probe_video, video_path
            )
        except Exception as probe_e:
            logger.warning(f"[EP] probe failed: {probe_e}")
            return video_path

        if dur <= 0:
            return video_path

        emphasis_items = _emphasis_items(words or [], max_zooms=1)
        emphasis_ts    = [ts for ts, _ in emphasis_items]
        has_audio      = await self._check_has_audio(video_path)

        # Detect face position for face-aware zoom centering
        face_cx_norm, face_cy_norm = 0.5, 0.5
        _face_zoom_on = FACE_ZOOM_ON
        if _face_zoom_on:
            face_cx_norm, face_cy_norm = await asyncio.get_event_loop().run_in_executor(
                None, _detect_face_position, video_path, dur
            )
            # Si no se detectó cara (fallback center), desactivar face zoom
            if face_cx_norm == 0.5 and face_cy_norm == 0.5:
                _face_zoom_on = False
                logger.debug("[EP] No face detected — disabling face-aware zoom for this clip")

        # Beat-sync pattern interrupts via librosa
        beat_pi_ts: List[float] = []
        if EP_BEAT_SYNC_ON and dur >= 4.0 and not emphasis_ts:
            beat_pi_ts = await asyncio.get_event_loop().run_in_executor(
                None, _beat_timestamps, video_path, dur
            )
            if beat_pi_ts:
                logger.debug(f"[EP] Beat sync: {len(beat_pi_ts)} beats → PI timestamps")

        theme = _classify_theme(segment_text) if segment_text else "neutral"
        fc, v_label, a_label = _build_filter_complex(
            w, h, fps, dur, emphasis_items, has_audio, segment_text,
            flash_timestamps=flash_timestamps or [],
            face_cx_norm=face_cx_norm,
            face_cy_norm=face_cy_norm,
            beat_pi_ts=beat_pi_ts,
            energy_level=energy_level,
            zoom_intensity=zoom_intensity,
            grain_override=grain_override,
            lut_vf=lut_vf,
            denoise_audio=denoise_audio,
            sections=sections,
            video_path=video_path,
        )


        # Auto-detect encoder: NVENC (GPU) → libx264 (CPU fallback)
        from ..gpu_utils import ffmpeg_codec_flags as _ep_gpu_flags
        _ep_enc_flags = _ep_gpu_flags("high")
        # ffmpeg_codec_flags returns ["-c:v", codec, "-preset", preset, ...extra_args]
        # We need to extract just the video codec part and append audio/map flags
        vcodec = _ep_enc_flags  # Already includes -c:v, -preset, and all NVENC/libx264 params

        cmd = [_get_ffmpeg_exe(), "-y",
               "-r", str(int(round(max(24.0, fps)))),
               "-i", str(video_path),
               "-filter_complex", fc, "-map", v_label]
        if a_label:
            cmd += ["-map", a_label, "-c:a", "aac", "-b:a", "192k"]
        cmd += vcodec + ["-pix_fmt", "yuv420p",
                "-t", f"{dur:.3f}",
                "-movflags", "+faststart", str(output_path)]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=360)

            if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                # ── Post-render validation: ensure actual frame count matches expected ──
                try:
                    _validate_proc = await asyncio.create_subprocess_exec(
                        _get_ffmpeg_exe(), "-i", str(output_path),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _, _val_stderr = await asyncio.wait_for(_validate_proc.communicate(), timeout=15)
                    _val_stderr_str = _val_stderr.decode('utf-8', errors='replace') if _val_stderr else ''
                    # Parse actual video stream duration from output
                    _dur_match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", _val_stderr_str)
                    _actual_dur = 0.0
                    if _dur_match:
                        _actual_dur = int(_dur_match.group(1)) * 3600 + int(_dur_match.group(2)) * 60 + float(_dur_match.group(3))
                    # Parse actual fps
                    _fps_match = re.search(r"(\d+\.?\d*)\s*fps", _val_stderr_str)
                    _actual_fps = float(_fps_match.group(1)) if _fps_match else 0.0
                    # Expected frames = dur * target_fps
                    _expected_frames = int(round(dur * max(24.0, fps)))
                    _actual_frames = int(round(_actual_dur * _actual_fps)) if _actual_dur > 0 and _actual_fps > 0 else 0
                    if _actual_frames > 0 and _actual_frames < _expected_frames * 0.92:
                        logger.error(
                            f"[EP] ❌ FRAME COUNT MISMATCH: expected ~{_expected_frames} frames "
                            f"({dur:.1f}s × {max(24.0, fps):.1f}fps), got {_actual_frames} "
                            f"({_actual_dur:.1f}s × {_actual_fps:.1f}fps) — output may have frozen frames!"
                        )
                        logger.warning("[EP] Retrying without zoom (zoom_intensity=off)...")
                        fc_retry, v_retry, a_retry = _build_filter_complex(
                            w, h, fps, dur, emphasis_items, has_audio, segment_text,
                            flash_timestamps=flash_timestamps or [],
                            face_cx_norm=face_cx_norm,
                            face_cy_norm=face_cy_norm,
                            beat_pi_ts=[],
                            energy_level=energy_level,
                            zoom_intensity="off",
                            grain_override=grain_override,
                            lut_vf=lut_vf,
                            denoise_audio=denoise_audio,
                            sections=sections,
                            video_path=video_path,
                        )
                        cmd_retry = [_get_ffmpeg_exe(), "-y",
                                     "-r", str(int(round(max(24.0, fps)))),
                                     "-i", str(video_path),
                                     "-filter_complex", fc_retry, "-map", v_retry]
                        if a_retry:
                            cmd_retry += ["-map", a_retry, "-c:a", "aac", "-b:a", "192k"]
                        cmd_retry += vcodec + ["-pix_fmt", "yuv420p",
                                     "-t", f"{dur:.3f}",
                                     "-movflags", "+faststart", str(output_path)]
                        proc_retry = await asyncio.create_subprocess_exec(
                            *cmd_retry,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        _, stderr_retry = await asyncio.wait_for(proc_retry.communicate(), timeout=360)
                        if proc_retry.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
                            import shutil
                            shutil.copy2(str(video_path), str(output_path))
                            logger.warning("[EP] Retry also failed — copied original as last resort")
                        else:
                            logger.info("[EP] ✅ Retry without zoom succeeded")
                except Exception as _val_e:
                    logger.debug(f"[EP] Post-render validation skipped: {_val_e}")

                effects = [f"color+cine({theme})"]
                if EP_SAT_PULSE_ON and emphasis_items:
                    effects.append("sat-pulse")
                if VIGNETTE_ENABLED:
                    effects.append("vignette")
                if FILM_GRAIN > 0:
                    effects.append(f"grain({FILM_GRAIN})")
                if EP_HOOK_ZOOM_ON:
                    effects.append("hook-zoom")
                if emphasis_ts:
                    effects.append(f"zoom({len(emphasis_ts)} punches)")
                elif beat_pi_ts:
                    effects.append(f"KenBurns+beat-PI({len(beat_pi_ts)})")
                else:
                    effects.append("KenBurns+PI")
                if _face_zoom_on:
                    effects.append(f"face({face_cx_norm:.2f},{face_cy_norm:.2f})")
                if WORD_CALLOUT_ON and emphasis_items:
                    effects.append(f"callouts({len(emphasis_items)})")
                effects.append("progress")
                if segment_text and LOWER_THIRD_ON:
                    effects.append("lower-third")
                if EP_CTA_ON:
                    effects.append("CTA")
                if EP_LETTERBOX_ON:
                    effects.append(f"letterbox({int(EP_LETTERBOX_H*100)}%)")
                if EP_WATERMARK_ON and EP_WATERMARK_TEXT:
                    effects.append("watermark")
                if EP_FADE_ON:
                    effects.append(f"fade({EP_FADE_DURATION:.2f}s)")
                if VOICE_COMPRESS_ON:
                    effects.append("compress+loudnorm")
                else:
                    effects.append("loudnorm")
                logger.info(f"[EP] ✅ {video_path.name} → [{', '.join(effects)}]")
                return output_path
            else:
                logger.error(f"[EP] ❌ exit {proc.returncode}: {stderr.decode()[-2000:]}")
                logger.error(f"[EP] filter_complex was: {fc}")
                return video_path
        except asyncio.TimeoutError:
            logger.error(f"[EP] timeout on {video_path.name}")
            return video_path
        except Exception as e:
            logger.error(f"[EP] error: {e}")
            return video_path

    @staticmethod
    async def _check_has_audio(path: Path) -> bool:
        try:
            # Use ffmpeg -i instead of ffprobe
            proc = await asyncio.create_subprocess_exec(
                _get_ffmpeg_exe(), "-i", str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            # Check if stderr contains audio stream info
            return b"Audio:" in stderr or b"audio" in stderr.lower()
        except Exception:
            return True


# ═══════════════════════════════════════════════════════════════════════════════
# OrchestratedEditingPipeline — Phase 3 Final Integration
# ═══════════════════════════════════════════════════════════════════════════════

class OrchestratedEditingPipeline:
    """
    Phase 3 orchestrated pipeline that coordinates:
    1. Clip enhancement (existing EP.apply())
    2. B-roll insertion (Phase 2)
    3. Context-aware transitions (Phase 3)
    4. Audio mixing with normalization (Phase 1)
    
    Strict step ordering with graceful degradation.
    """
    
    def __init__(self):
        self.ep = EditingPipeline()
        self.logger = logging.getLogger(__name__ + ".orchestrator")
    
    async def process_clip(
        self,
        clip_path: Path,
        output_path: Path,
        # Segment info
        segment_text: str = "",
        segment_start: float = 0.0,
        segment_duration: float = 0.0,
        keywords: Optional[List[str]] = None,
        words_with_timestamps: Optional[List[Dict]] = None,
        # Features
        enable_broll: bool = True,
        enable_transitions: bool = False,  # For standalone clips, usually False
        enable_music: bool = True,
        enable_sfx: bool = True,
        video_style: str = "default",
        music_volume: float = 0.35,
        jump_cuts: Optional[List[float]] = None,
        clip_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Path]:
        """
        Process a single clip through the full pipeline.
        
        Pipeline steps (in order):
        1. Apply visual enhancement (EditingPipeline.apply)
        2. Insert B-roll (if enabled and keywords available)
        3. Insert SFX (if enabled — after B-roll, before music)
        4. Mix background music (if enabled)
        
        Args:
            clip_path: Source clip
            output_path: Final output path
            segment_text: Transcript text
            segment_start: Start time in original video
            segment_duration: Segment duration
            keywords: Visual keywords for B-roll
            words_with_timestamps: For ducking
            enable_broll: Enable B-roll insertion
            enable_transitions: Enable transitions (usually for multi-clip)
            enable_music: Enable background music
            enable_sfx: Enable SFX insertion (after B-roll, before music)
            video_style: 'viral_fast', 'cinematic', 'minimal', 'default'
            music_volume: Background music volume (0.0-1.0)
            jump_cuts: Timestamps of jump cuts for SFX placement
            clip_metadata: Clip metadata (duration, energy, etc.) for SFX
        
        Returns:
            Path to processed clip or None on failure
        """
        import tempfile
        from .broll_overlay import BRollDecisionEngine, insert_broll_into_clip
        from .audio import mix_background_music, _validate_audio_stream
        
        current_path = clip_path
        temp_files = []
        
        # ─────────────────────────────────────────────────────────────────
        # STEP 1: Visual Enhancement
        # ─────────────────────────────────────────────────────────────────
        self.logger.info(f"[Pipeline] Step 1: Visual enhancement for {clip_path.name}")
        
        step1_output = Path(tempfile.mktemp(suffix=".mp4"))
        temp_files.append(step1_output)
        
        enhanced_path = await self.ep.apply(
            video_path=current_path,
            output_path=step1_output,
            words=words_with_timestamps or [],
            segment_text=segment_text,
            energy_level=(clip_metadata or {}).get("energy_level", 0.5),
            grain_override=(clip_metadata or {}).get("grain_override", 0),
            flash_timestamps=jump_cuts,
            sections=(clip_metadata or {}).get("sections"),
        )
        
        if enhanced_path and enhanced_path.exists():
            current_path = enhanced_path
            self.logger.info(f"[Pipeline] ✅ Step 1 complete")
            
            # ── Duration guard: validate Step 1 output isn't truncated ──────
            if segment_duration > 0:
                try:
                    from .ffmpeg_guard import get_duration
                    _actual_dur = get_duration(str(current_path))
                    _min_expected = segment_duration * 0.8
                    if _actual_dur > 0 and _actual_dur < _min_expected:
                        self.logger.warning(
                            f"[Pipeline] ⚠️ Step 1 output duration {_actual_dur:.1f}s "
                            f"< 80% of expected {segment_duration:.1f}s — "
                            f"reverting to original clip to avoid frozen-frame output"
                        )
                        current_path = clip_path
                except Exception as _dur_e:
                    self.logger.debug(f"[Pipeline] Duration check skipped: {_dur_e}")
        else:
            self.logger.warning(f"[Pipeline] Step 1 failed, using original")
            current_path = clip_path
        
        # ─────────────────────────────────────────────────────────────────
        # STEP 2: B-Roll Insertion (optional)
        # ─────────────────────────────────────────────────────────────────
        if enable_broll and keywords:
            self.logger.info(f"[Pipeline] Step 2: B-roll insertion ({len(keywords)} keywords)")
            
            # Create decision engine
            decision_engine = BRollDecisionEngine()
            decisions = decision_engine.analyze_segment(
                segment_text=segment_text,
                segment_start=segment_start,
                segment_duration=segment_duration,
                keywords=keywords,
            )
            
            if decisions:
                step2_output = Path(tempfile.mktemp(suffix=".mp4"))
                temp_files.append(step2_output)
                
                success = insert_broll_into_clip(
                    clip_path=current_path,
                    decisions=decisions,
                    output_path=step2_output,
                )
                
                if success:
                    current_path = step2_output
                    self.logger.info(f"[Pipeline] ✅ Step 2 complete ({len(decisions)} B-rolls)")
                else:
                    self.logger.warning(f"[Pipeline] Step 2 failed, continuing without B-roll")
            else:
                self.logger.info(f"[Pipeline] Step 2: No B-roll decisions")
        
        # ─────────────────────────────────────────────────────────────────
        # STEP 2.5: SFX Insertion (optional — after B-roll, before music)
        # ─────────────────────────────────────────────────────────────────
        if enable_sfx:
            self.logger.info(f"[Pipeline] Step 2.5: SFX insertion")
            try:
                from ..domains.sfx.sfx_orchestrator import SFXOrchestrator
                _sfx = SFXOrchestrator()
                _sfx_enabled = os.getenv("SFX_PROFILE", "subtle").lower() != "none"
                if _sfx_enabled:
                    step_sfx_output = Path(tempfile.mktemp(suffix=".mp4"))
                    temp_files.append(step_sfx_output)
                    _sfx_result = await _sfx.process_clip(
                        input_path=str(current_path),
                        output_path=str(step_sfx_output),
                        transcript_segments=[],
                        jump_cuts=jump_cuts or [],
                        clip_metadata=clip_metadata,
                    )
                    if _sfx_result and Path(_sfx_result).exists():
                        current_path = Path(_sfx_result)
                        self.logger.info(f"[Pipeline] ✅ Step 2.5 (SFX) complete")
                    else:
                        self.logger.warning(f"[Pipeline] Step 2.5 (SFX) returned no output — continuing without SFX")
                else:
                    self.logger.info(f"[Pipeline] Step 2.5 (SFX): disabled (SFX_PROFILE=none)")
            except Exception as _sfx_e:
                self.logger.warning(f"[Pipeline] Step 2.5 (SFX) failed: {_sfx_e} — continuing without SFX")
        
        # ─────────────────────────────────────────────────────────────────
        # STEP 3: Audio Mixing (optional)
        # ─────────────────────────────────────────────────────────────────
        if enable_music:
            self.logger.info(f"[Pipeline] Step 3: Audio mixing")
            
            # Validate audio stream before mixing (Phase 1B)
            if not _validate_audio_stream(current_path, "clip"):
                self.logger.warning(f"[Pipeline] Invalid audio stream, skipping music mix")
            else:
                step3_output = Path(tempfile.mktemp(suffix=".mp4"))
                temp_files.append(step3_output)
                
                success = mix_background_music(
                    video_path=current_path,
                    output_path=step3_output,
                    music_volume=music_volume,
                    ducking_enabled=True,
                    word_timings=words_with_timestamps,
                )
                
                if success:
                    current_path = step3_output
                    self.logger.info(f"[Pipeline] ✅ Step 3 complete")
                else:
                    self.logger.warning(f"[Pipeline] Step 3 failed, continuing without music")
        
        # ─────────────────────────────────────────────────────────────────
        # FINAL: Copy to output location
        # ─────────────────────────────────────────────────────────────────
        import shutil
        shutil.copy(current_path, output_path)
        
        # Clean up temp files (including step1_output even if current_path
        # points to the original clip — avoids minor disk leak)
        for temp_file in temp_files:
            try:
                if temp_file.exists() and temp_file != current_path:
                    temp_file.unlink()
            except Exception:
                pass
        
        self.logger.info(f"✅ [Pipeline] Complete: {output_path.name}")
        return output_path
    
    async def process_clips_batch(
        self,
        clips: List[Dict[str, Any]],
        output_dir: Path,
        enable_broll: bool = True,
        enable_music: bool = True,
        video_style: str = "default",
    ) -> List[Path]:
        """
        Process multiple clips in parallel.
        
        Args:
            clips: List of dicts with keys: path, text, start, duration, keywords, words
            output_dir: Directory for output files
            enable_broll: Enable B-roll
            enable_music: Enable music
            video_style: Video style preference
        
        Returns:
            List of successfully processed clip paths
        """
        import asyncio
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        async def process_one(idx: int, clip_info: Dict) -> Optional[Path]:
            output_path = output_dir / f"clip_{idx:03d}.mp4"
            
            return await self.process_clip(
                clip_path=Path(clip_info["path"]),
                output_path=output_path,
                segment_text=clip_info.get("text", ""),
                segment_start=clip_info.get("start", 0.0),
                segment_duration=clip_info.get("duration", 0.0),
                keywords=clip_info.get("keywords"),
                words_with_timestamps=clip_info.get("words"),
                enable_broll=enable_broll,
                enable_music=enable_music,
                video_style=video_style,
            )
        
        # Process with limited concurrency
        semaphore = asyncio.Semaphore(3)  # Max 3 concurrent
        
        async def process_with_limit(idx: int, clip_info: Dict) -> Optional[Path]:
            async with semaphore:
                return await process_one(idx, clip_info)
        
        tasks = [
            process_with_limit(i, clip)
            for i, clip in enumerate(clips)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter successful results
        successful = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"[Pipeline] Clip {i} failed: {result}")
            elif result is not None:
                successful.append(result)
        
        self.logger.info(f"[Pipeline] Batch complete: {len(successful)}/{len(clips)} clips")
        return successful


# Convenience function for simple usage
async def orchestrated_edit(
    clip_path: Path,
    output_path: Path,
    segment_text: str = "",
    keywords: Optional[List[str]] = None,
    enable_broll: bool = True,
    enable_music: bool = True,
) -> Optional[Path]:
    """
    Simple interface to the orchestrated pipeline.
    
    Example:
        result = await orchestrated_edit(
            clip_path=Path("input.mp4"),
            output_path=Path("output.mp4"),
            segment_text="Talking about productivity...",
            keywords=["office", "computer"],
        )
    """
    pipeline = OrchestratedEditingPipeline()
    return await pipeline.process_clip(
        clip_path=clip_path,
        output_path=output_path,
        segment_text=segment_text,
        keywords=keywords,
        enable_broll=enable_broll,
        enable_music=enable_music,
    )
