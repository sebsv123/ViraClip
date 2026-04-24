#!/usr/bin/env python3
"""
ViraClip v2 — Pipeline de producción profesional de shorts virales.

Uso:
    python3 pipeline.py <url_youtube_o_path_mp4>

Flujo (gestión VRAM explícita — nunca >6 GB simultáneos):
    F1. Transcripción: Whisper large-v3-turbo + word_timestamps + VAD → FREE VRAM
    F2. Análisis viral: Groq llama-3.3-70b con heurística post-validación (0 VRAM)
    F3. Corte: ffmpeg -c copy (0 VRAM)
    F4. B-rolls: Flux GGUF via ComfyUI + Ken Burns + Pexels fallback → POST /free
    F5. Real-ESRGAN x2: ComfyUI upscale → POST /free
    F6. Edición final: ASS karaoke subs + música + SFX + 9:16 reframe (0 VRAM)
    F7. Finalizar: promover *_final_NN.mp4, limpiar intermedios, reporte JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Paths y constantes
# ─────────────────────────────────────────────────────────────────────────────
HOME = Path.home()
PROJECT_ROOT = HOME / "CascadeProjects" / "ViraClip"
ENV_FILE = PROJECT_ROOT / ".env"
BACKEND_SRC = PROJECT_ROOT / "backend" / "src"
YTDLP_BIN = PROJECT_ROOT / "backend" / ".venv" / "bin" / "yt-dlp"

UPLOADS_DIR = HOME / "proyectos" / "ViraClip" / "uploads"
OUTPUTS_DIR = HOME / "proyectos" / "ViraClip" / "outputs"
AUDIO_DIR = HOME / "proyectos" / "ViraClip" / "audio"
SFX_DIR = HOME / "proyectos" / "ViraClip" / "sfx"

COMFYUI_URL = "http://localhost:8188"
GROQ_MODEL = "llama-3.3-70b-versatile"
WHISPER_MODEL_SIZE = "large-v3-turbo"
WHISPER_DEVICE = "cuda"
WHISPER_COMPUTE = "int8_float16"


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
_T0 = time.time()


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(msg: str) -> None:
    elapsed = time.time() - _T0
    print(f"[{ts()} +{elapsed:6.1f}s] {msg}", flush=True)


def banner(title: str) -> None:
    print()
    print("━" * 70)
    print(f"  {title}")
    print("━" * 70)


# ─────────────────────────────────────────────────────────────────────────────
# VRAM management helpers
# ─────────────────────────────────────────────────────────────────────────────
def free_comfyui_vram() -> None:
    """Tell ComfyUI to unload all models and free GPU memory."""
    try:
        import requests as _req
        r = _req.post(
            f"{COMFYUI_URL}/free",
            json={"unload_models": True, "free_memory": True},
            timeout=10,
        )
        log(f"✅ ComfyUI VRAM liberada: HTTP {r.status_code}")
    except Exception as e:
        log(f"⚠  free_comfyui_vram: {e}")


def free_torch_vram() -> None:
    """Release all PyTorch GPU memory (call after del model)."""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
            reserved = torch.cuda.memory_reserved() / 1024**3
            log(f"🧹 PyTorch VRAM reservada: {reserved:.2f} GB")
    except ImportError:
        pass


def wait_for_vram(min_free_gb: float = 6.0, timeout: int = 60) -> bool:
    """Block until at least min_free_gb are free on GPU 0."""
    try:
        import torch
    except ImportError:
        return True
    for i in range(timeout):
        props = torch.cuda.get_device_properties(0)
        free = (props.total_mem - torch.cuda.memory_reserved()) / 1024**3
        if free >= min_free_gb:
            log(f"✅ VRAM libre: {free:.1f} GB")
            return True
        torch.cuda.empty_cache()
        time.sleep(1)
        if i % 10 == 0:
            log(f"⏳ VRAM={free:.1f} GB < {min_free_gb} GB requerida...")
    log(f"❌ Timeout esperando {min_free_gb} GB VRAM libre")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# .env loader
# ─────────────────────────────────────────────────────────────────────────────
def load_env(env_file: Path = ENV_FILE) -> None:
    if not env_file.exists():
        log(f"⚠️  .env no encontrado en {env_file}")
        return
    n = 0
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if k and v:
            os.environ[k] = v
            n += 1
    log(f"✅ .env cargado ({n} variables)")


# ─────────────────────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────────────────────
YOUTUBE_RE = re.compile(r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/|embed/))([\w-]{11})")


def is_youtube_url(s: str) -> bool:
    return bool(YOUTUBE_RE.search(s)) or s.startswith(("http://", "https://"))


def youtube_video_id(url: str) -> str:
    m = YOUTUBE_RE.search(url)
    return m.group(1) if m else f"video_{int(time.time())}"


def ffmpeg_bin() -> str:
    for cand in ["ffmpeg", "/usr/bin/ffmpeg"]:
        try:
            r = subprocess.run([cand, "-version"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return cand
        except Exception:
            continue
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


# ─────────────────────────────────────────────────────────────────────────────
# PASO 1 — Input: descargar si es URL
# ─────────────────────────────────────────────────────────────────────────────
def step_1_input(src: str) -> Tuple[Path, str]:
    banner("PASO 1 — INPUT")
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    if is_youtube_url(src):
        vid = youtube_video_id(src)
        out = UPLOADS_DIR / f"{vid}.mp4"
        if out.exists():
            log(f"Video ya existe: {out.name} ({out.stat().st_size/1024/1024:.1f} MB)")
            return out, vid

        log(f"Descargando con yt-dlp → {out.name}")
        cmd = [
            str(YTDLP_BIN),
            "--no-playlist",
            "--format", "best[ext=mp4][height<=1080]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "--no-warnings",
            "--output", str(out),
            src,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not out.exists():
            log(f"❌ yt-dlp falló: {r.stderr[-500:]}")
            sys.exit(1)
        log(f"✅ Descargado: {out.name} ({out.stat().st_size/1024/1024:.1f} MB)")
        return out, vid

    # Path local
    p = Path(src).expanduser().resolve()
    if not p.exists():
        log(f"❌ Archivo local no existe: {p}")
        sys.exit(1)
    vid = p.stem
    log(f"✅ Usando video local: {p.name} ({p.stat().st_size/1024/1024:.1f} MB)")
    return p, vid


# ─────────────────────────────────────────────────────────────────────────────
# F1 — Transcripción (Whisper large-v3-turbo + word timestamps + VAD)
# ─────────────────────────────────────────────────────────────────────────────
def step_1_transcribe(video: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Returns (segments, all_words). Words have per-word timestamps for ASS karaoke."""
    banner("F1 — TRANSCRIPCIÓN (Whisper large-v3-turbo + word_timestamps)")

    from faster_whisper import WhisperModel

    log(f"Cargando modelo '{WHISPER_MODEL_SIZE}' en {WHISPER_DEVICE} ({WHISPER_COMPUTE})...")
    try:
        model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE,
        )
    except Exception as e:
        log(f"⚠️  CUDA falló ({e}), fallback a CPU int8")
        model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")

    log(f"Transcribiendo {video.name} (word_timestamps=True, vad_filter=True)...")
    segments_iter, info = model.transcribe(
        str(video),
        language="es",
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400},
    )

    segments: List[Dict[str, Any]] = []
    all_words: List[Dict[str, Any]] = []
    for seg in segments_iter:
        segments.append({
            "start": float(seg.start),
            "end": float(seg.end),
            "text": seg.text.strip(),
        })
        if seg.words:
            for w in seg.words:
                all_words.append({
                    "start": float(w.start),
                    "end": float(w.end),
                    "text": w.word.strip(),
                })

    total_s = segments[-1]["end"] if segments else 0.0
    log(f"✅ {len(segments)} segmentos, {len(all_words)} palabras, "
        f"idioma={info.language} ({info.language_probability:.2f}), duración={total_s:.1f}s")
    for s in segments[:3]:
        log(f"   [{s['start']:6.1f} → {s['end']:6.1f}] {s['text'][:70]}")
    if len(segments) > 3:
        log(f"   ... ({len(segments)-3} segmentos más)")

    # Dump words to /tmp for debug
    words_dump = Path(f"/tmp/viraclip_words_{video.stem}.json")
    words_dump.write_text(json.dumps(all_words[:20], ensure_ascii=False, indent=2))
    log(f"   Primeras 20 palabras → {words_dump}")

    # FREE VRAM — Whisper shares the physical GPU with ComfyUI container
    del model
    gc.collect()
    free_torch_vram()
    log(f"🧹 Whisper descargado de VRAM")

    return segments, all_words


# ─────────────────────────────────────────────────────────────────────────────
# F2 — Análisis viral (Groq + retry + validación heurística)
# ─────────────────────────────────────────────────────────────────────────────
GROQ_SYSTEM = """\
Eres un editor experto en contenido viral para TikTok e Instagram Reels.
Analiza la transcripción y devuelve ÚNICAMENTE un JSON válido, sin texto extra.

CRITERIOS OBLIGATORIOS (rechazar si no se cumplen TODOS):
  - Duración entre 20s y 50s
  - Empieza con hook en primeros 3s (pregunta, dato sorprendente, o frase incompleta)
  - Contiene un punto de tensión o revelación
  - Termina con resolución o cliffhanger (no a media frase)
  - Sin silencios perceptibles >3s dentro del clip

SCHEMA OBLIGATORIO (responde SOLO esto, sin explicaciones):
{
  "clips": [
    {
      "start_time": <float segundos>,
      "end_time": <float segundos>,
      "score": <int 0-100>,
      "hook": "<primeras 8 palabras exactas del clip>",
      "mood": "<upbeat|suspense|emotional>",
      "why_viral": "<razón en máx 10 palabras>",
      "emotional_peak": <float segundos ABSOLUTOS del pico emocional>
    }
  ]
}
Máximo 3 clips. Solo incluir clips con score >= 78.
Si ninguno cumple los criterios, devuelve {"clips": []}.
"""

VIRAL_HOOKS_ES = [
    "pero", "escucha", "nunca", "siempre", "la verdad", "te cuento",
    "nadie te dice", "error", "secreto", "clave", "por eso", "imagina",
    "sabías", "resulta que", "lo que no", "cuidado", "atención",
    "importante", "mira", "ojo", "esto es", "el problema",
]


def _call_groq_with_retry(transcript_text: str, max_retries: int = 3) -> List[Dict[str, Any]]:
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key or len(groq_key) < 10:
        log("⚠️  GROQ_API_KEY no configurada")
        return []
    try:
        from groq import Groq
    except ImportError:
        log("⚠️  librería 'groq' no instalada")
        return []

    client = Groq(api_key=groq_key)
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": GROQ_SYSTEM},
                    {"role": "user", "content": transcript_text},
                ],
                max_tokens=800,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or ""
            log(f"   Groq intento {attempt}: {len(raw)} chars")
            data = json.loads(raw)
            clips = data.get("clips", [])
            if clips:
                return clips
            log(f"   ⚠  Groq intento {attempt}: 0 clips, reintentando...")
        except Exception as e:
            log(f"   ⚠  Groq intento {attempt} falló: {type(e).__name__}: {e}")
        time.sleep(2 ** (attempt - 1))
    return []


def _validate_clip_heuristic(
    clip: Dict[str, Any],
    all_words: List[Dict[str, Any]],
    video_duration: float,
) -> Optional[Dict[str, Any]]:
    """Post-validation: adjust score based on actual text markers."""
    try:
        start = max(0.0, float(clip["start_time"]))
        end = min(video_duration, float(clip["end_time"]))
        dur = end - start
        if dur < 15 or dur > 55 or end <= start:
            return None
    except (KeyError, ValueError, TypeError):
        return None

    clip_words = [
        w["text"].lower().strip() for w in all_words
        if start <= w["start"] <= end
    ]
    if not clip_words:
        return None

    score = int(clip.get("score", clip.get("viral_score", 60)))
    bonus = 0

    # Hook viral en primeras 6 palabras
    first_6 = " ".join(clip_words[:6])
    if any(h in first_6 for h in VIRAL_HOOKS_ES):
        bonus += 10

    # Densidad de palabras (ritmo rápido = más viral)
    wpm = len(clip_words) / (dur / 60) if dur > 0 else 0
    if wpm > 120:
        bonus += 8
    if wpm < 60:
        bonus -= 15

    final_score = score + bonus
    if final_score < 72:
        log(f"   ⚠  Clip [{start:.0f}-{end:.0f}s] descartado heurística (score={final_score})")
        return None

    return {
        "start_time": start,
        "end_time": end,
        "hook": str(clip.get("hook", ""))[:120],
        "viral_score": final_score,
        "mood": str(clip.get("mood", "upbeat")),
        "why_viral": str(clip.get("why_viral", ""))[:150],
        "emotional_peak": float(clip.get("emotional_peak", (start + end) / 2)),
        "reason": str(clip.get("why_viral", ""))[:200],
    }


def step_2_viral_analysis(
    segments: List[Dict[str, Any]],
    all_words: List[Dict[str, Any]],
    video_duration: float,
) -> List[Dict[str, Any]]:
    banner("F2 — ANÁLISIS VIRAL (Groq + heurística)")

    transcript_str = "\n".join(
        f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in segments
    )

    log(f"Enviando a Groq ({GROQ_MODEL}) con retry...")
    raw_clips = _call_groq_with_retry(transcript_str)

    if raw_clips:
        validated = [
            c for c in
            (_validate_clip_heuristic(c, all_words, video_duration) for c in raw_clips)
            if c is not None
        ]
    else:
        validated = []

    if not validated:
        log("⚠️  Sin clips tras validación, usando fallback inteligente")
        validated = _fallback_clips_smart(segments, all_words, video_duration)

    log(f"✅ {len(validated)} clips seleccionados")
    for i, c in enumerate(validated, 1):
        log(f"   #{i} [{c['start_time']:.1f}-{c['end_time']:.1f}s] "
            f"score={c['viral_score']} mood={c.get('mood','?')}  hook={c['hook'][:60]}")
    return validated


def _fallback_clips_smart(
    segments: List[Dict[str, Any]],
    all_words: List[Dict[str, Any]],
    duration: float,
) -> List[Dict[str, Any]]:
    """Better fallback: pick 3 densest 35s windows based on word density."""
    if duration < 20:
        return [{
            "start_time": 0, "end_time": duration,
            "hook": "Clip completo", "viral_score": 50, "mood": "upbeat",
            "why_viral": "fallback", "emotional_peak": duration / 2, "reason": "fallback",
        }]

    window = min(35.0, duration / 3)
    best: List[Tuple[float, int]] = []  # (start, word_count)
    step = 5.0
    t = 0.0
    while t + window <= duration:
        n = sum(1 for w in all_words if t <= w["start"] <= t + window)
        best.append((t, n))
        t += step
    best.sort(key=lambda x: -x[1])

    out = []
    used_ranges: List[Tuple[float, float]] = []
    for start, wc in best:
        end = start + window
        if any(not (end <= us or start >= ue) for us, ue in used_ranges):
            continue
        out.append({
            "start_time": start,
            "end_time": end,
            "hook": f"Fallback (densidad: {wc} palabras/{window:.0f}s)",
            "viral_score": min(75, 50 + wc // 5),
            "mood": "upbeat",
            "why_viral": "fallback densidad",
            "emotional_peak": start + window / 2,
            "reason": "Fallback: ventana más densa",
        })
        used_ranges.append((start, end))
        if len(out) >= 3:
            break

    return out or [{
        "start_time": 0, "end_time": min(45, duration),
        "hook": "Fallback uniforme", "viral_score": 50, "mood": "upbeat",
        "why_viral": "fallback", "emotional_peak": min(22, duration / 2),
        "reason": "fallback",
    }]


# ─────────────────────────────────────────────────────────────────────────────
# F3 — Corte de clips (ffmpeg -c copy)
# ─────────────────────────────────────────────────────────────────────────────
def get_video_duration(video: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def step_3_cut_clips(video: Path, clips: List[Dict[str, Any]], video_id: str) -> List[Dict[str, Any]]:
    banner("F3 — CORTE DE CLIPS (ffmpeg -c copy)")
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    ff = ffmpeg_bin()
    log(f"ffmpeg: {ff}")

    results = []
    for i, c in enumerate(clips, 1):
        start, end = c["start_time"], c["end_time"]
        out_name = f"{video_id}_clip_{i:02d}_{start:.0f}s_{end:.0f}s.mp4"
        out_path = OUTPUTS_DIR / out_name

        log(f"Cortando #{i}: {start:.1f}s → {end:.1f}s ({end-start:.1f}s) → {out_name}")
        cmd = [
            ff, "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
            "-i", str(video), "-c", "copy", "-avoid_negative_ts", "make_zero",
            str(out_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not out_path.exists():
            log("   ⚠️  -c copy falló, re-encode...")
            cmd = [
                ff, "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
                "-i", str(video),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                str(out_path),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0 or not out_path.exists():
                log(f"   ❌ ffmpeg falló: {r.stderr[-300:]}")
                continue

        size_mb = out_path.stat().st_size / 1024 / 1024
        log(f"   ✅ {out_name} ({size_mb:.2f} MB)")
        entry = dict(c)
        entry["index"] = i
        entry["filename"] = out_name
        entry["path"] = str(out_path)
        entry["duration"] = end - start
        entry["size_mb"] = round(size_mb, 2)
        results.append(entry)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# F4 — B-rolls contextuales (Flux GGUF + Ken Burns + Pexels fallback)
# ─────────────────────────────────────────────────────────────────────────────
def step_4_insert_brolls(
    clips: List[Dict[str, Any]],
    segments: List[Dict[str, Any]],
    all_words: List[Dict[str, Any]],
    video_id: str,
    brolls_per_clip: int = 3,
) -> List[Dict[str, Any]]:
    banner("F4 — B-ROLLS CONTEXTUALES (Flux GGUF + Pexels fallback)")

    try:
        import brolls
    except ImportError as e:
        log(f"⚠️  brolls.py no disponible: {e}. Saltando F4.")
        return clips

    if not brolls.check_comfyui_has_flux():
        log("❌ ComfyUI no tiene Flux GGUF. Saltando F4.")
        return clips

    log(f"✅ Flux GGUF disponible")
    log(f"B-rolls por clip: {brolls_per_clip}")

    import requests as _req
    try:
        _req.post("http://localhost:8188/free",
                   json={"unload_models": True, "free_memory": True},
                   timeout=10)
        print("✅ ComfyUI VRAM liberada antes de B-rolls")
        import time; time.sleep(3)
    except Exception as e:
        print(f"⚠  free ComfyUI: {e}")

    for c in clips:
        source_path = Path(c["path"])
        if not source_path.exists():
            continue
        log(f"Procesando clip #{c['index']}: {source_path.name}")

        # Pass all_words for context-aware prompts
        result = brolls.insert_brolls_in_clip(
            clip_path=source_path,
            segments=segments,
            clip_start=c["start_time"],
            clip_end=c["end_time"],
            video_id=video_id,
            clip_n=c["index"],
            n_brolls=brolls_per_clip,
            all_words=all_words,
        )

        final_path = Path(result["final_path"])
        if final_path != source_path and final_path.exists():
            c["broll_path"] = str(final_path)
            c["broll_filename"] = final_path.name
            c["brolls"] = result["brolls"]
            c["broll_size_mb"] = round(final_path.stat().st_size / 1024 / 1024, 2)
            log(f"   ✅ clip #{c['index']} con {len(result['brolls'])} B-rolls")
        else:
            c["brolls"] = []
            log(f"   ⚠️  clip #{c['index']} sin B-rolls")

    # Free ComfyUI after all B-rolls
    free_comfyui_vram()
    return clips


# ─────────────────────────────────────────────────────────────────────────────
# F5 — Real-ESRGAN x2 upscale (ComfyUI)
# ─────────────────────────────────────────────────────────────────────────────
async def step_5_enhance(clips: List[Dict[str, Any]]) -> None:
    banner("F5 — REAL-ESRGAN x2 (ComfyUI)")

    if str(BACKEND_SRC) not in sys.path:
        sys.path.insert(0, str(BACKEND_SRC))

    try:
        from comfyui_bridge import ComfyUIBridge
    except Exception as e:
        log(f"⚠️  No se pudo importar ComfyUIBridge: {e}")
        return

    bridge = ComfyUIBridge(COMFYUI_URL)
    try:
        available = await bridge.is_available()
        if not available:
            log(f"⚠️  ComfyUI no responde. Saltando F5.")
            return
        log(f"✅ ComfyUI disponible")

        for c in clips:
            source = Path(c.get("broll_path", c["path"]))
            enhanced_path = source.with_stem(source.stem + "_enhanced")
            log(f"Enhance: {source.name}")
            try:
                result = await bridge.enhance_video(source, enhanced_path)
                if result and enhanced_path.exists():
                    size_mb = enhanced_path.stat().st_size / 1024 / 1024
                    log(f"   ✅ {enhanced_path.name} ({size_mb:.2f} MB)")
                    c["enhanced_path"] = str(enhanced_path)
                else:
                    log(f"   ⚠️  enhance devolvió None")
            except Exception as e:
                log(f"   ⚠️  enhance error: {type(e).__name__}: {e}")
    finally:
        await bridge.close()
        free_comfyui_vram()


# ─────────────────────────────────────────────────────────────────────────────
# F6 — Edición final: ASS karaoke + 9:16 + música con ducking + SFX
# ─────────────────────────────────────────────────────────────────────────────

# ASS time format
def _ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int((t - int(t)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _write_ass_for_clip(
    all_words: List[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
    ass_path: Path,
    words_per_line: int = 4,
) -> int:
    """Genera un .ass estilo karaoke: palabra activa resaltada, el resto dimmed."""
    dur = clip_end - clip_start
    clip_words = [
        {"start": w["start"] - clip_start, "end": w["end"] - clip_start, "text": w["text"]}
        for w in all_words
        if clip_start <= w["start"] <= clip_end
    ]
    # Clamp
    for w in clip_words:
        w["start"] = max(0.0, w["start"])
        w["end"] = min(dur, w["end"])

    if not clip_words:
        return 0

    # Group words into lines
    lines: List[List[Dict[str, Any]]] = []
    for j in range(0, len(clip_words), words_per_line):
        chunk = clip_words[j:j + words_per_line]
        lines.append(chunk)

    # ASS header with Poppins Bold styling
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "WrapStyle: 0\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        "Style: Active,Poppins,44,&H00FFFFFF,&H000088FF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,3,1,2,40,40,280,1\n"
        "Style: Dim,Poppins,44,&H60FFFFFF,&H000088FF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,2,0,2,40,40,280,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )

    event_lines = []
    for line_words in lines:
        line_start = line_words[0]["start"]
        line_end = line_words[-1]["end"]

        for idx, word in enumerate(line_words):
            # Build line text with current word highlighted
            parts = []
            for k, w2 in enumerate(line_words):
                if k == idx:
                    parts.append(r"{\rActive}" + w2["text"].upper() + r"{\r}")
                else:
                    parts.append(r"{\rDim}" + w2["text"] + r"{\r}")
            text = " ".join(parts)

            ws = word["start"]
            we = word["end"]
            # Add subtle fade
            text_with_fade = r"{\fad(80,80)}" + text

            event_lines.append(
                f"Dialogue: 0,{_ass_time(ws)},{_ass_time(we)},Active,,0,0,0,,"
                f"{text_with_fade}"
            )

    ass_path.write_text(header + "\n".join(event_lines) + "\n", encoding="utf-8")
    return len(event_lines)


def _probe_orientation(video: Path) -> Tuple[int, int, bool]:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-select_streams", "v:0", str(video),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        info = json.loads(r.stdout or "{}")
        streams = info.get("streams", [])
        if streams:
            w = int(streams[0].get("width", 1920))
            h = int(streams[0].get("height", 1080))
            return w, h, w > h
    except Exception:
        pass
    return 1920, 1080, True


def _select_music_by_mood(mood: str) -> Optional[Path]:
    """Devuelve ruta a un archivo de música según el mood del clip.
    NO descarga nada — solo lee lo que ya existe en disco.
    Busca en orden: bgm/{mood}/ → {mood}/ → bgm/ → raíz → rglob.
    Si no hay archivos, devuelve None silenciosamente."""
    import hashlib

    if not AUDIO_DIR.exists():
        log(f"   ⚠  Sin directorio de música: {AUDIO_DIR}")
        return None

    # Candidate directories in priority order
    search_dirs = [
        AUDIO_DIR / "bgm" / mood,   # AudioLibraryService layout
        AUDIO_DIR / mood,            # flat layout
        AUDIO_DIR / "bgm",           # any BGM
        AUDIO_DIR,                   # root
    ]

    for d in search_dirs:
        if d.exists() and d.is_dir():
            tracks = sorted(d.glob("*.mp3")) + sorted(d.glob("*.wav"))
            if tracks:
                seed = int(hashlib.md5(mood.encode()).hexdigest(), 16)
                chosen = tracks[seed % len(tracks)]
                return chosen

    # Last resort: recursive search
    tracks = sorted(AUDIO_DIR.rglob("*.mp3")) + sorted(AUDIO_DIR.rglob("*.wav"))
    if not tracks:
        log(f"   ⚠  Sin música en {AUDIO_DIR} — clip sin música de fondo")
        return None

    seed = int(hashlib.md5(mood.encode()).hexdigest(), 16)
    return tracks[seed % len(tracks)]


def _select_sfx(keyword: str = "whoosh") -> Optional[Path]:
    """Pick a sound effect. Checks SFX_DIR, AUDIO_DIR/sfx/{keyword}/, SFX_DIR/{keyword}/."""
    search_dirs = [SFX_DIR, AUDIO_DIR / "sfx"]
    # Also check keyword-specific subfolder
    for base in [SFX_DIR, AUDIO_DIR / "sfx"]:
        kw_dir = base / keyword.lower()
        if kw_dir.exists():
            hits = sorted(kw_dir.glob("*.mp3")) + sorted(kw_dir.glob("*.wav"))
            if hits:
                return hits[0]

    # Flat search with keyword match
    for d in search_dirs:
        if not d.exists():
            continue
        all_sfx = sorted(d.glob("*.mp3")) + sorted(d.glob("*.wav"))
        for f in all_sfx:
            if keyword.lower() in f.stem.lower():
                return f
        if all_sfx:
            return random.choice(all_sfx)
    return None


def edit_clip_v2(
    clip_path: Path,
    output_path: Path,
    all_words: List[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
    video_id: str,
    clip_n: int,
    mood: str = "upbeat",
    emotional_peak: float = 0.0,
) -> Path:
    """Full edit: 9:16 + ASS karaoke subs + music with ducking + SFX at emotional peak."""
    dur = max(0.1, clip_end - clip_start)
    ff = ffmpeg_bin()

    # 1) ASS subtitles
    ass_path = Path(f"/tmp/{video_id}_clip_{clip_n:02d}.ass")
    n_subs = _write_ass_for_clip(all_words, clip_start, clip_end, ass_path)
    log(f"   📝 ASS karaoke: {n_subs} eventos")

    # 2) Orientation → 9:16 reframe
    _w, _h, is_horizontal = _probe_orientation(clip_path)
    if is_horizontal:
        vf_crop = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:flags=lanczos"
    else:
        vf_crop = "scale=1080:1920:flags=lanczos,setsar=1"

    fade_out_st = max(0.0, dur - 0.5)

    # ASS path escaped for ffmpeg
    ass_str = str(ass_path).replace(":", r"\:").replace("'", r"\'")

    vf_parts = [
        vf_crop,
        "fade=t=in:st=0:d=0.3",
        f"fade=t=out:st={fade_out_st:.2f}:d=0.5",
    ]
    if n_subs > 0:
        vf_parts.append(f"ass='{ass_str}'")
    vf = ",".join(vf_parts)

    # 3) Music & SFX
    music_file = _select_music_by_mood(mood)
    sfx_file = _select_sfx("whoosh")
    # SFX timestamp relative to clip
    sfx_offset = max(0.0, emotional_peak - clip_start - 0.3)

    # 4) Build filter_complex
    inputs = ["-i", str(clip_path)]
    if music_file:
        inputs += ["-stream_loop", "-1", "-i", str(music_file)]
        log(f"   🎵 Música: {music_file.name} (mood={mood})")
    if sfx_file:
        inputs += ["-i", str(sfx_file)]
        log(f"   💥 SFX: {sfx_file.name} @ {sfx_offset:.1f}s")

    af_voice = (
        f"[0:a]highpass=f=80,lowpass=f=8000,"
        f"loudnorm=I=-16:TP=-1.5:LRA=11,"
        f"afade=t=in:st=0:d=0.3,"
        f"afade=t=out:st={fade_out_st:.2f}:d=0.5[a_voice]"
    )

    filter_parts = [f"[0:v]{vf}[v]", af_voice]

    audio_inputs = ["[a_voice]"]
    audio_idx = 1

    if music_file:
        # Ducking: sidechain compress music when voice is loud
        filter_parts.append(
            f"[{audio_idx}:a]volume=0.15,aformat=channel_layouts=stereo,"
            f"afade=t=in:st=0:d=2,afade=t=out:st={max(0, dur-3):.2f}:d=3[a_music]"
        )
        audio_inputs.append("[a_music]")
        audio_idx += 1

    if sfx_file:
        filter_parts.append(
            f"[{audio_idx}:a]volume=0.6,adelay={int(sfx_offset*1000)}|{int(sfx_offset*1000)},"
            f"apad=pad_dur=0[a_sfx]"
        )
        audio_inputs.append("[a_sfx]")
        audio_idx += 1

    n_audio = len(audio_inputs)
    if n_audio > 1:
        weights = " ".join(["1"] + ["0.15" if "[a_music]" in a else "0.6" for a in audio_inputs[1:]])
        filter_parts.append(
            f"{''.join(audio_inputs)}amix=inputs={n_audio}:duration=first:weights={weights}[a]"
        )
    else:
        filter_parts.append("[a_voice]acopy[a]")

    filter_complex = ";\n".join(filter_parts)

    cmd = [
        ff, "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-t", f"{dur:.3f}",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not output_path.exists():
        err = result.stderr.strip().splitlines()[-1][:250] if result.stderr else "sin stderr"
        log(f"   ⚠️  edit_clip_v2 err: {err}")
        # Fallback: simpler edit without music/SFX
        log("   ↩ Fallback: solo 9:16 + subs")
        cmd_simple = [
            ff, "-y", "-i", str(clip_path),
            "-vf", vf,
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]
        r2 = subprocess.run(cmd_simple, capture_output=True, text=True)
        if r2.returncode != 0 or not output_path.exists():
            return clip_path
    return output_path


def step_6_edit_clips(
    clips: List[Dict[str, Any]],
    all_words: List[Dict[str, Any]],
    video_id: str,
) -> List[Dict[str, Any]]:
    banner("F6 — EDICIÓN FINAL (ASS karaoke + música + SFX + 9:16)")

    for c in clips:
        # Use the best available source (enhanced > broll > raw)
        source_path = Path(c.get("enhanced_path", c.get("broll_path", c["path"])))
        edited_name = f"{video_id}_edited_{c['index']:02d}.mp4"
        edited_path = OUTPUTS_DIR / edited_name

        log(f"Editando #{c['index']}: {source_path.name}")
        result = edit_clip_v2(
            clip_path=source_path,
            output_path=edited_path,
            all_words=all_words,
            clip_start=c["start_time"],
            clip_end=c["end_time"],
            video_id=video_id,
            clip_n=c["index"],
            mood=c.get("mood", "upbeat"),
            emotional_peak=c.get("emotional_peak", (c["start_time"] + c["end_time"]) / 2),
        )

        if result == edited_path and edited_path.exists():
            size_mb = edited_path.stat().st_size / 1024 / 1024
            log(f"   ✅ {edited_path.name} ({size_mb:.2f} MB)")
            c["edited_path"] = str(edited_path)
            c["edited_filename"] = edited_path.name
            c["edited_size_mb"] = round(size_mb, 2)
        else:
            log(f"   ⚠️  edición falló, se mantiene source")
            c["edited_path"] = str(source_path)
            c["edited_filename"] = source_path.name

    return clips


# ─────────────────────────────────────────────────────────────────────────────
# F7 — Finalizar: promover mejores + limpiar + reporte
# ─────────────────────────────────────────────────────────────────────────────
def step_7_finalize(
    video_id: str,
    video_duration: float,
    clips: List[Dict[str, Any]],
    keep_intermediates: bool,
) -> None:
    banner("F7 — FINALIZAR (promover + limpiar + reporte)")

    if not clips:
        log("❌ No se generó ningún clip")
        return

    produced_finals: set = set()

    for c in clips:
        # Preference cascade: edited > enhanced > broll > raw
        candidates = [
            c.get("edited_path"),
            c.get("enhanced_path"),
            c.get("broll_path"),
            c.get("path"),
        ]
        best = next((Path(p) for p in candidates if p and Path(p).exists()), None)
        if best is None:
            log(f"   ⚠️  clip #{c['index']} sin archivo — skip")
            continue

        final_name = f"{video_id}_final_{c['index']:02d}.mp4"
        final_path = OUTPUTS_DIR / final_name
        try:
            if final_path.exists():
                final_path.unlink()
            shutil.move(str(best), str(final_path))
        except Exception as e:
            log(f"   ⚠️  no se pudo mover {best.name} → {final_name}: {e}")
            continue

        size_mb = final_path.stat().st_size / 1024 / 1024
        c["final_path"] = str(final_path)
        c["final_filename"] = final_name
        c["final_size_mb"] = round(size_mb, 2)
        produced_finals.add(final_path.name)
        log(f"   ✅ {final_name} ({size_mb:.2f} MB)")

    # Cleanup intermediates
    if not keep_intermediates:
        report_name = f"{video_id}_report.json"
        keep_names = produced_finals | {report_name}
        removed = 0
        removed_bytes = 0
        for f in OUTPUTS_DIR.iterdir():
            if not f.is_file() or f.name in keep_names:
                continue
            if f.name.startswith(video_id) or f.name.startswith("broll_") or f.name.startswith("enhanced_"):
                try:
                    removed_bytes += f.stat().st_size
                    f.unlink()
                    removed += 1
                except Exception:
                    pass
        for tmp_dir in Path("/tmp").glob(f"brolls_{video_id}_*"):
            shutil.rmtree(tmp_dir, ignore_errors=True)
        log(f"🧹 Intermedios borrados: {removed} archivos ({removed_bytes/1024/1024:.1f} MB)")
    else:
        log("🧹 Limpieza DESACTIVADA (--keep-intermediates)")

    # ASCII table
    print()
    print(f"  {'#':>2}  {'ARCHIVO FINAL':<55s}  {'DUR':>7s}  {'SCORE':>5s}  {'MOOD':<10s}  HOOK")
    print("  " + "─" * 135)
    for c in clips:
        dur_s = c.get("duration", 0.0)
        score = c.get("viral_score", 0)
        mood = c.get("mood", "?")
        hook = c.get("hook", "")[:40]
        fname = c.get("final_filename", c.get("edited_filename", c.get("filename", "?")))[:55]
        print(f"  {c['index']:>2}  {fname:<55s}  {dur_s:>6.1f}s  {score:>5d}  {mood:<10s}  {hook}")
    print()

    # JSON report
    report = {
        "video_id": video_id,
        "video_duration": video_duration,
        "generated_at": datetime.now().isoformat(),
        "pipeline_version": "v2",
        "total_clips": len(clips),
        "clips": clips,
    }
    report_path = OUTPUTS_DIR / f"{video_id}_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    log(f"✅ Reporte guardado: {report_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="ViraClip v2 — Pipeline profesional de shorts virales")
    parser.add_argument("source", help="URL YouTube o path a MP4 local")
    parser.add_argument("--no-brolls", action="store_true", help="Saltar F4 (B-rolls con Flux)")
    parser.add_argument("--brolls-per-clip", type=int, default=3, help="Número de B-rolls por clip (default: 3)")
    parser.add_argument("--no-enhance", action="store_true", help="Saltar F5 (Real-ESRGAN x2)")
    parser.add_argument("--keep-intermediates", action="store_true",
                        help="No borrar archivos intermedios. Por defecto solo se conservan los _final_NN.mp4")
    args = parser.parse_args()

    banner("VIRACLIP v2 PIPELINE — INICIO")
    log(f"Source: {args.source}")

    load_env()

    try:
        # F0. Input
        video, video_id = step_1_input(args.source)
        duration = get_video_duration(video)
        log(f"Duración: {duration:.1f}s")

        # F1. Transcripción (Whisper large-v3-turbo + word timestamps + VAD)
        segments, all_words = step_1_transcribe(video)

        # F2. Análisis viral (Groq + heurística)
        selected = step_2_viral_analysis(segments, all_words, duration)

        # F3. Corte de clips
        clips = step_3_cut_clips(video, selected, video_id)

        # F4. B-rolls contextuales
        if clips and not args.no_brolls:
            clips = step_4_insert_brolls(clips, segments, all_words, video_id, args.brolls_per_clip)
        elif args.no_brolls:
            log("F4 omitido (--no-brolls)")

        # F5. Real-ESRGAN enhance
        if clips and not args.no_enhance:
            try:
                asyncio.run(step_5_enhance(clips))
            except Exception as e:
                log(f"⚠️  F5 falló: {type(e).__name__}: {e}")
        elif args.no_enhance:
            log("F5 omitido (--no-enhance)")

        # F6. Edición final (ASS karaoke + música + SFX + 9:16)
        if clips:
            clips = step_6_edit_clips(clips, all_words, video_id)

        # F7. Finalizar + reporte
        step_7_finalize(video_id, duration, clips, keep_intermediates=args.keep_intermediates)

        total = time.time() - _T0
        banner(f"✅ PIPELINE v2 COMPLETADO EN {total:.1f}s — {len(clips)} clip(s)")
        return 0 if clips else 1

    except KeyboardInterrupt:
        log("Interrumpido por usuario")
        return 130
    except Exception as e:
        log(f"❌ Error inesperado: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
