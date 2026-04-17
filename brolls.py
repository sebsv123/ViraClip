#!/usr/bin/env python3
"""
B-rolls contextuales — Flux GGUF + Pexels fallback + Ken Burns.

Flujo:
    1. Groq analiza el transcript (con palabras exactas de all_words) y genera
       prompts visuales contextuales con timestamps.
    2. ComfyUI (Flux Dev GGUF Q4_K_S) genera imagen vertical 720x1280.
       → POST /free entre cada imagen para liberar VRAM.
    3. Si Flux falla → Pexels fallback (video stock 9:16).
    4. ffmpeg anima imagen con Ken Burns → mp4 1080x1920.
    5. ffmpeg compone B-rolls sobre clip base con overlay + alpha fade.
       Audio del clip principal NUNCA se corta.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import time
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


# ─────────────────────────────────────────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────────────────────────────────────────
COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://localhost:8188")

# Flux GGUF: UNET quantizado para caber en 8GB VRAM (calidad ~99% del FP8)
FLUX_UNET_GGUF = "flux1-dev-Q4_K_S.gguf"
FLUX_CLIP_L = "clip_l.safetensors"
FLUX_T5 = "t5xxl_fp8_e4m3fn.safetensors"
FLUX_VAE = "ae.safetensors"

FLUX_STEPS = 20
FLUX_CFG = 1.0
FLUX_GUIDANCE = 3.5
FLUX_SAMPLER = "euler"
FLUX_SCHEDULER = "simple"
BROLL_WIDTH = 720
BROLL_HEIGHT = 1280
FINAL_WIDTH = 1080
FINAL_HEIGHT = 1920
FINAL_FPS = 30

# Prompt negativo suave
NEG_PROMPT = ""

# Groq
GROQ_MODEL = "llama-3.3-70b-versatile"

# Pexels API
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
PEXELS_API_URL = "https://api.pexels.com/videos/search"

# ComfyUI output dir en el host (mapeado por docker-compose)
COMFY_OUTPUT_HOST = Path.home() / "proyectos" / "ViraClip" / "outputs"


# ─────────────────────────────────────────────────────────────────────────────
# Tipos
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class BrollSpec:
    """Especificación de un B-roll a generar."""
    index: int                  # 1-based dentro del clip
    timestamp: float            # segundos desde el inicio del clip
    duration: float             # segundos que dura el B-roll en pantalla
    prompt: str                 # prompt visual en inglés
    keywords: List[str]         # keywords extraídas del transcript
    pexels_query: str = ""      # fallback query for Pexels video search

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# PASO A — Groq genera prompts visuales contextuales
# ─────────────────────────────────────────────────────────────────────────────
_GROQ_BROLL_PROMPT = """Eres un director visual experto en contenido viral corto (TikTok, Reels, Shorts).

A partir del fragmento hablado de un clip vertical de {duration:.1f} segundos, diseña EXACTAMENTE {n_brolls} B-rolls.

PALABRAS EXACTAS que dice el speaker en este clip (con tiempos relativos al clip):
{word_timeline}

TRANSCRIPT POR FRASES:
{transcript}

REGLAS OBLIGATORIAS:
- Los B-rolls NO reemplazan la voz: el audio del clip se mantiene siempre.
- Cada B-roll dura entre 2.0 y 3.0 segundos.
- Los timestamps no pueden solaparse y deben estar entre 1.0s y {max_ts:.1f}s.
- Reparte los B-rolls a lo largo del clip (aprox cada {gap:.1f}s).
- CRUCIAL: El prompt debe ilustrar LITERALMENTE las palabras que se dicen en ese timestamp.
  Ejemplo: si el speaker dice "el mercado se derrumbó" → prompt: "cinematic shot of stock market crash, red arrows falling"
- Cada prompt: EN INGLÉS, fotorrealista, vertical 9:16, cinematic shallow depth of field.
- EVITA texto en imágenes, logos, caras famosas.
- Incluye "pexels_query" con 2-3 palabras inglesas para búsqueda de video stock como fallback.

Devuelve SOLO JSON válido (sin markdown):
{{"brolls": [{{"timestamp": 1.5, "duration": 2.5, "keywords": ["word1","word2"], "pexels_query": "market crash", "prompt": "cinematic shot of..."}}]}}
"""


def _relative_segments(segments: List[Dict[str, Any]], clip_start: float, clip_end: float) -> List[Dict[str, Any]]:
    """Segmentos con timestamps re-basados al inicio del clip."""
    dur = clip_end - clip_start
    out = []
    for s in segments:
        rs = s["start"] - clip_start
        re = s["end"] - clip_start
        if re <= 0 or rs >= dur:
            continue
        out.append({
            "start": max(0.0, rs),
            "end": min(dur, re),
            "text": s.get("text", "").strip(),
        })
    return out


def generate_broll_prompts(
    segments: List[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
    n_brolls: int = 3,
    all_words: Optional[List[Dict[str, Any]]] = None,
) -> List[BrollSpec]:
    """Pide a Groq que genere specs de B-roll para un clip.
    Usa all_words para proveer contexto exacto palabra por palabra.
    Fallback: specs uniformes con prompts genéricos si Groq falla."""
    duration = clip_end - clip_start
    rel_segs = _relative_segments(segments, clip_start, clip_end)
    transcript = "\n".join(
        f"[{s['start']:5.1f}-{s['end']:5.1f}] {s['text']}" for s in rel_segs
    )

    # Build word timeline for context-aware prompts
    word_timeline = ""
    if all_words:
        clip_words = [
            f"[{w['start']-clip_start:5.1f}s] {w['text']}"
            for w in all_words
            if clip_start <= w["start"] <= clip_end
        ]
        word_timeline = " | ".join(clip_words[:80])  # cap at 80 words
    if not word_timeline:
        word_timeline = "(no word-level data available)"

    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key or len(groq_key) < 10:
        return _fallback_specs(rel_segs, duration, n_brolls, all_words, clip_start)

    try:
        from groq import Groq
    except ImportError:
        return _fallback_specs(rel_segs, duration, n_brolls, all_words, clip_start)

    prompt = _GROQ_BROLL_PROMPT.format(
        duration=duration,
        n_brolls=n_brolls,
        max_ts=max(1.0, duration - 3.0),
        gap=duration / max(1, n_brolls),
        transcript=transcript,
        word_timeline=word_timeline,
    )

    try:
        client = Groq(api_key=groq_key)
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
            temperature=0.6,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or ""
        data = json.loads(raw)
        raw_brolls = data.get("brolls", [])

        specs: List[BrollSpec] = []
        for i, b in enumerate(raw_brolls[:n_brolls], 1):
            try:
                ts = max(0.5, min(duration - 2.5, float(b["timestamp"])))
                dur_b = max(1.5, min(3.5, float(b.get("duration", 2.5))))
                if ts + dur_b > duration - 0.5:
                    dur_b = max(1.5, duration - 0.5 - ts)
                specs.append(BrollSpec(
                    index=i,
                    timestamp=ts,
                    duration=dur_b,
                    prompt=str(b.get("prompt", "")).strip()[:500],
                    keywords=[str(k) for k in b.get("keywords", [])][:5],
                    pexels_query=str(b.get("pexels_query", "")).strip()[:50],
                ))
            except (KeyError, ValueError, TypeError):
                continue

        # Evitar solapamientos (ordenar por ts y separar si se tocan)
        specs.sort(key=lambda s: s.timestamp)
        for i in range(1, len(specs)):
            min_start = specs[i-1].timestamp + specs[i-1].duration + 0.3
            if specs[i].timestamp < min_start:
                specs[i].timestamp = min(duration - 2.0, min_start)

        # Filtrar specs que ya no quepan
        specs = [s for s in specs if s.timestamp + s.duration < duration - 0.3]

        if not specs:
            return _fallback_specs(rel_segs, duration, n_brolls, all_words, clip_start)
        return specs

    except Exception as e:
        print(f"   ⚠️  Groq broll prompts err: {type(e).__name__}: {e}")
        return _fallback_specs(rel_segs, duration, n_brolls, all_words, clip_start)


def _fallback_specs(
    rel_segs: List[Dict[str, Any]],
    duration: float,
    n_brolls: int,
    all_words: Optional[List[Dict[str, Any]]] = None,
    clip_start: float = 0.0,
) -> List[BrollSpec]:
    """Genera specs uniformes usando palabras exactas del speaker."""
    specs = []
    if duration < 10:
        return specs
    gap = duration / (n_brolls + 1)
    for i in range(n_brolls):
        ts = gap * (i + 1) - 1.25
        ts = max(1.0, min(duration - 3.0, ts))

        # Use exact words near this timestamp
        words = []
        pexels_q = ""
        if all_words:
            abs_ts = ts + clip_start
            nearby = [
                w["text"] for w in all_words
                if abs(w["start"] - abs_ts) < 3.0
            ]
            words = [w for w in nearby if len(w) > 3][:5]
            pexels_q = " ".join(words[:3])

        if not words:
            nearest = min(rel_segs, key=lambda s: abs(((s["start"] + s["end"]) / 2) - ts), default=None)
            text = nearest["text"] if nearest else "abstract cinematic scene"
            words = [w for w in text.split() if len(w) > 4][:4]
            pexels_q = " ".join(words[:3])

        specs.append(BrollSpec(
            index=i + 1,
            timestamp=ts,
            duration=2.5,
            prompt=(
                "cinematic vertical shot, shallow depth of field, warm lighting, "
                f"35mm film, subject: {' '.join(words) or 'abstract concept'}, "
                "no text, no logos, photorealistic"
            ),
            keywords=words,
            pexels_query=pexels_q or "cinematic abstract",
        ))
    return specs


# ─────────────────────────────────────────────────────────────────────────────
# PASO B — ComfyUI Flux Dev FP8: generar imagen por prompt
# ─────────────────────────────────────────────────────────────────────────────
def _build_flux_workflow(prompt: str, seed: int) -> Dict[str, Any]:
    """Workflow ComfyUI API-format para Flux Dev GGUF (compatible con 8 GB VRAM).
    Usa UnetLoaderGGUF + DualCLIPLoader + VAELoader (4 componentes separados)."""
    return {
        "prompt": {
            # 1) UNET (Flux Dev quantizado GGUF Q4_K_S ~6.5 GB VRAM)
            "10": {
                "class_type": "UnetLoaderGGUF",
                "inputs": {"unet_name": FLUX_UNET_GGUF},
            },
            # 2) CLIPs: DualCLIPLoader carga CLIP-L + T5-XXL para Flux
            "11": {
                "class_type": "DualCLIPLoader",
                "inputs": {
                    "clip_name1": FLUX_T5,
                    "clip_name2": FLUX_CLIP_L,
                    "type": "flux",
                },
            },
            # 3) VAE
            "12": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": FLUX_VAE},
            },
            # 4) Positive prompt
            "20": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["11", 0]},
            },
            # 5) Negative (Flux lo ignora pero KSampler lo requiere)
            "21": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": NEG_PROMPT, "clip": ["11", 0]},
            },
            # 6) FluxGuidance (inyecta guidance embebido de Flux)
            "22": {
                "class_type": "FluxGuidance",
                "inputs": {"conditioning": ["20", 0], "guidance": FLUX_GUIDANCE},
            },
            # 7) Empty latent 9:16
            "30": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": BROLL_WIDTH,
                    "height": BROLL_HEIGHT,
                    "batch_size": 1,
                },
            },
            # 8) Sampler
            "40": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": FLUX_STEPS,
                    "cfg": FLUX_CFG,
                    "sampler_name": FLUX_SAMPLER,
                    "scheduler": FLUX_SCHEDULER,
                    "denoise": 1.0,
                    "model": ["10", 0],
                    "positive": ["22", 0],
                    "negative": ["21", 0],
                    "latent_image": ["30", 0],
                },
            },
            # 9) VAE decode
            "50": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["40", 0], "vae": ["12", 0]},
            },
            # 10) Save
            "60": {
                "class_type": "SaveImage",
                "inputs": {"images": ["50", 0], "filename_prefix": "broll"},
            },
        }
    }


def generate_broll_image(prompt: str, seed: Optional[int] = None, timeout: float = 300.0) -> Optional[Path]:
    """Envía workflow Flux a ComfyUI y devuelve la ruta de la imagen generada.
    Devuelve None si falla."""
    if seed is None:
        seed = random.randint(1, 2**31 - 1)

    workflow = _build_flux_workflow(prompt, seed)

    try:
        r = requests.post(f"{COMFYUI_URL}/prompt", json=workflow, timeout=30)
        if r.status_code != 200:
            print(f"      ❌ /prompt {r.status_code}: {r.text[:300]}")
            return None
        prompt_id = r.json().get("prompt_id")
        if not prompt_id:
            return None
    except Exception as e:
        print(f"      ❌ POST /prompt: {e}")
        return None

    # Polling
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(2)
        try:
            h = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10).json()
        except Exception:
            continue
        if prompt_id not in h:
            continue
        entry = h[prompt_id]
        if entry.get("status", {}).get("status_str") == "error":
            print(f"      ❌ ComfyUI error: {entry.get('status')}")
            return None
        outputs = entry.get("outputs", {})
        if not outputs:
            continue
        save_node = outputs.get("60", {}) or outputs.get("8", {})
        images = save_node.get("images", [])
        if not images:
            continue
        img_info = images[0]
        filename = img_info["filename"]
        subfolder = img_info.get("subfolder", "")
        host_path = (COMFY_OUTPUT_HOST / subfolder / filename) if subfolder else (COMFY_OUTPUT_HOST / filename)
        if host_path.exists():
            return host_path
        # si no aparece en host, descargar via /view
        try:
            url = f"{COMFYUI_URL}/view?filename={filename}&subfolder={subfolder}&type=output"
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200:
                dest = COMFY_OUTPUT_HOST / filename
                dest.write_bytes(resp.content)
                return dest
        except Exception:
            pass
        return None

    print(f"      ⚠️  timeout tras {timeout}s")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# VRAM helper (free ComfyUI between images)
# ─────────────────────────────────────────────────────────────────────────────
def _free_comfyui_vram() -> None:
    try:
        r = requests.post(
            f"{COMFYUI_URL}/free",
            json={"unload_models": True, "free_memory": True},
            timeout=10,
        )
        print(f"      🧹 ComfyUI VRAM free: HTTP {r.status_code}")
    except Exception as e:
        print(f"      ⚠  free VRAM: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# PASO B2 — Pexels fallback: descargar video stock vertical
# ─────────────────────────────────────────────────────────────────────────────
def _pexels_download_video(
    query: str,
    out_path: Path,
    duration: float = 2.5,
) -> Optional[Path]:
    """Search Pexels for a vertical video and download a clip of `duration` seconds."""
    api_key = PEXELS_API_KEY or os.environ.get("PEXELS_API_KEY", "")
    if not api_key or len(api_key) < 10:
        print("      ⚠  PEXELS_API_KEY no configurada, sin fallback Pexels")
        return None

    try:
        r = requests.get(
            PEXELS_API_URL,
            headers={"Authorization": api_key},
            params={"query": query, "orientation": "portrait", "per_page": 5, "size": "medium"},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"      ⚠  Pexels API {r.status_code}")
            return None
        data = r.json()
        videos = data.get("videos", [])
        if not videos:
            print(f"      ⚠  Pexels: sin resultados para '{query}'")
            return None

        # Pick a random video from top results
        video = random.choice(videos[:3])
        # Find best HD file
        files = video.get("video_files", [])
        # Prefer portrait HD
        best = None
        for f in files:
            if f.get("height", 0) >= 720:
                best = f
                break
        if not best:
            best = files[0] if files else None
        if not best:
            return None

        dl_url = best["link"]
        print(f"      📥 Pexels: descargando {dl_url[:80]}...")
        resp = requests.get(dl_url, timeout=60)
        if resp.status_code != 200:
            return None

        raw_video = out_path.with_suffix(".pexels.mp4")
        raw_video.write_bytes(resp.content)

        # Trim to duration and scale to 1080x1920
        cmd = [
            "ffmpeg", "-y",
            "-i", str(raw_video),
            "-t", f"{duration:.2f}",
            "-vf", f"scale={FINAL_WIDTH}:{FINAL_HEIGHT}:force_original_aspect_ratio=increase,"
                   f"crop={FINAL_WIDTH}:{FINAL_HEIGHT}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-an",
            "-movflags", "+faststart",
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        raw_video.unlink(missing_ok=True)
        if result.returncode == 0 and out_path.exists():
            print(f"      ✅ Pexels video: {out_path.name}")
            return out_path
        return None

    except Exception as e:
        print(f"      ⚠  Pexels fallback error: {type(e).__name__}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# PASO C — Imagen → video con Ken Burns
# ─────────────────────────────────────────────────────────────────────────────
def image_to_broll_video(image_path: Path, out_mp4: Path, duration: float = 2.5) -> Optional[Path]:
    """Convierte imagen a video vertical 1080x1920 con Ken Burns (zoom+pan) y fade."""
    total_frames = max(30, int(duration * FINAL_FPS))

    # Alternar dirección zoom (in/out) y pan (left/right) entre llamadas (pseudo-aleatorio)
    zoom_in = random.random() < 0.65  # sesgado a zoom-in (más usado)
    pan_x_dir = random.choice([-1, 0, 1])
    pan_y_dir = random.choice([-1, 0, 1])

    if zoom_in:
        z_expr = f"min(zoom+0.0012,1.25)"
    else:
        z_expr = f"if(lte(on,1),1.25,max(zoom-0.0012,1.0))"

    # Movimiento de cámara sutil
    if pan_x_dir == 1:
        x_expr = "iw/2-(iw/zoom/2)+on*0.8"
    elif pan_x_dir == -1:
        x_expr = "iw/2-(iw/zoom/2)-on*0.8"
    else:
        x_expr = "iw/2-(iw/zoom/2)"

    if pan_y_dir == 1:
        y_expr = "ih/2-(ih/zoom/2)+on*0.5"
    elif pan_y_dir == -1:
        y_expr = "ih/2-(ih/zoom/2)-on*0.5"
    else:
        y_expr = "ih/2-(ih/zoom/2)"

    # Fade alpha para crossfade con el overlay posterior
    fade_in_d = 0.25
    fade_out_st = max(0.0, duration - 0.25)
    fade_out_d = 0.25

    vf = (
        # primero escalar muy alto para que zoompan tenga margen de subpixel
        f"scale=2880:5120:flags=lanczos,"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':"
        f"d={total_frames}:s={FINAL_WIDTH}x{FINAL_HEIGHT}:fps={FINAL_FPS},"
        f"format=yuva420p,"
        f"fade=t=in:st=0:d={fade_in_d}:alpha=1,"
        f"fade=t=out:st={fade_out_st:.2f}:d={fade_out_d}:alpha=1"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-vf", vf,
        "-t", f"{duration:.3f}",
        "-r", str(FINAL_FPS),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuva420p",
        "-movflags", "+faststart",
        str(out_mp4),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out_mp4.exists():
        # fallback: sin yuva (pix_fmt no soportado por x264), usar yuv420p y aplicar fade sin alpha
        vf2 = (
            f"scale=2880:5120:flags=lanczos,"
            f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':"
            f"d={total_frames}:s={FINAL_WIDTH}x{FINAL_HEIGHT}:fps={FINAL_FPS},"
            f"fade=t=in:st=0:d={fade_in_d},"
            f"fade=t=out:st={fade_out_st:.2f}:d={fade_out_d}"
        )
        cmd2 = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(image_path),
            "-vf", vf2,
            "-t", f"{duration:.3f}",
            "-r", str(FINAL_FPS),
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(out_mp4),
        ]
        r2 = subprocess.run(cmd2, capture_output=True, text=True)
        if r2.returncode != 0 or not out_mp4.exists():
            print(f"      ❌ Ken Burns falló: {r2.stderr[-200:]}")
            return None
    return out_mp4


# ─────────────────────────────────────────────────────────────────────────────
# PASO D — Componer B-rolls sobre el clip base con overlay + alpha fade
# ─────────────────────────────────────────────────────────────────────────────
def overlay_brolls_on_clip(
    base_clip: Path,
    brolls: List[Dict[str, Any]],  # [{"path": Path, "start": float, "duration": float}]
    out_path: Path,
) -> Optional[Path]:
    """Compone los B-rolls sobre el clip base usando overlay con alpha fade.
    Mantiene intacto el audio del clip base."""
    if not brolls:
        # No hay brolls → copiar el clip base al destino
        shutil.copy2(base_clip, out_path)
        return out_path

    # Ordenar por start
    brolls_sorted = sorted(brolls, key=lambda b: b["start"])

    inputs = ["-i", str(base_clip)]
    for b in brolls_sorted:
        inputs += ["-i", str(b["path"])]

    # Construir filter_complex
    # [0:v] = base; [1:v], [2:v], ... = brolls (ya con alpha fade en yuva420p)
    # Cada broll: [Nv] overlay sobre el acumulado habilitado con between(t, start, start+dur)
    parts = []
    # Asegurar que la base está en formato compatible
    parts.append(f"[0:v]format=yuv420p[base]")
    prev = "base"
    for i, b in enumerate(brolls_sorted, start=1):
        start = b["start"]
        end = start + b["duration"]
        # Asegurar formato del broll (si vino en yuv420p del fallback, convertir)
        # y retrasar con setpts para que empiece en t=start
        parts.append(
            f"[{i}:v]format=yuva420p,setpts=PTS-STARTPTS+{start}/TB[b{i}]"
        )
        out_lbl = f"v{i}"
        parts.append(
            f"[{prev}][b{i}]overlay="
            f"enable='between(t,{start},{end})':"
            f"format=auto:x=0:y=0[{out_lbl}]"
        )
        prev = out_lbl

    filter_complex = ";".join(parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", f"[{prev}]",
        "-map", "0:a?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_path),
    ]

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out_path.exists():
        last_err = r.stderr.strip().splitlines()[-1] if r.stderr else "sin stderr"
        print(f"      ❌ overlay_brolls err: {last_err[:250]}")
        # Fallback: devolver el clip base sin brolls
        shutil.copy2(base_clip, out_path)
        return out_path
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# Orquestador del paso 4.6
# ─────────────────────────────────────────────────────────────────────────────
def _list_from_api(spec: Any) -> List[str]:
    """Parsea el nuevo formato COMBO de ComfyUI: 
    - formato viejo: [[opt1, opt2, ...]]
    - formato nuevo: ["COMBO", {"options": [...]}]"""
    if not isinstance(spec, list):
        return []
    if len(spec) > 0 and isinstance(spec[0], list):
        return spec[0]
    if len(spec) > 1 and isinstance(spec[1], dict):
        return list(spec[1].get("options", []))
    return []


def check_comfyui_has_flux() -> bool:
    """Verifica que ComfyUI tenga TODOS los componentes Flux GGUF descargados."""
    checks = [
        ("UnetLoaderGGUF", "unet_name", FLUX_UNET_GGUF),
        ("DualCLIPLoader", "clip_name1", FLUX_T5),
        ("DualCLIPLoader", "clip_name2", FLUX_CLIP_L),
        ("VAELoader", "vae_name", FLUX_VAE),
    ]
    try:
        for node, field, expected in checks:
            r = requests.get(f"{COMFYUI_URL}/object_info/{node}", timeout=5)
            if r.status_code != 200:
                print(f"   [check_flux] nodo {node} no disponible")
                return False
            info = r.json().get(node, {})
            spec = info.get("input", {}).get("required", {}).get(field, [])
            available = _list_from_api(spec)
            if expected not in available:
                print(f"   [check_flux] {node}.{field}: falta '{expected}'")
                print(f"                disponibles: {available}")
                return False
        return True
    except Exception as e:
        print(f"   [check_flux] error: {e}")
        return False


def insert_brolls_in_clip(
    clip_path: Path,
    segments: List[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
    video_id: str,
    clip_n: int,
    n_brolls: int = 3,
    workdir: Optional[Path] = None,
    all_words: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Pipeline completo de B-rolls para UN clip.
    Usa all_words para contexto exacto + Pexels fallback + VRAM freeing.
    Devuelve dict con 'final_path' y 'brolls' (lista de specs usados).
    """
    workdir = workdir or Path(f"/tmp/brolls_{video_id}_{clip_n:02d}")
    workdir.mkdir(parents=True, exist_ok=True)

    # A. Generar specs con Groq (context-aware con all_words)
    specs = generate_broll_prompts(
        segments, clip_start, clip_end, n_brolls=n_brolls, all_words=all_words,
    )
    if not specs:
        print(f"      ⚠️  sin specs de broll, se mantiene clip sin brolls")
        return {"final_path": clip_path, "brolls": []}

    print(f"      → {len(specs)} B-rolls planeados:")
    for s in specs:
        print(f"         #{s.index} t={s.timestamp:.1f}s d={s.duration:.1f}s "
              f"pexels='{s.pexels_query}' prompt={s.prompt[:70]}...")

    # B+C. Generar imagen + animar (o Pexels fallback)
    broll_videos = []
    for s in specs:
        broll_mp4 = workdir / f"broll_{clip_n:02d}_{s.index:02d}.mp4"

        # Attempt 1: Flux via ComfyUI
        t0 = time.time()
        print(f"      🖼️  Generando imagen #{s.index} con Flux Dev...")
        img_path = generate_broll_image(s.prompt)
        gen_s = time.time() - t0

        if img_path and img_path.exists():
            print(f"         ✅ imagen {img_path.name} ({gen_s:.1f}s)")
            video = image_to_broll_video(img_path, broll_mp4, duration=s.duration)
            if video:
                print(f"         ✅ video {broll_mp4.name}")
                broll_videos.append({
                    "path": broll_mp4,
                    "start": s.timestamp,
                    "duration": s.duration,
                    "spec": s.to_dict(),
                    "source": "flux",
                })
                # Free VRAM between images to stay under 6 GB
                _free_comfyui_vram()
                continue

        # Attempt 2: Pexels fallback
        print(f"         ⚠  Flux falló, intentando Pexels: '{s.pexels_query}'...")
        pexels_result = _pexels_download_video(
            query=s.pexels_query or " ".join(s.keywords[:3]) or "cinematic",
            out_path=broll_mp4,
            duration=s.duration,
        )
        if pexels_result:
            broll_videos.append({
                "path": broll_mp4,
                "start": s.timestamp,
                "duration": s.duration,
                "spec": s.to_dict(),
                "source": "pexels",
            })
            continue

        print(f"         ❌ Skip B-roll #{s.index} (Flux + Pexels fallaron)")

    # D. Overlay sobre el clip base
    if not broll_videos:
        return {"final_path": clip_path, "brolls": []}

    final_name = clip_path.stem + "_broll.mp4"
    final_path = clip_path.with_name(final_name)
    print(f"      🎬 Componiendo overlay con {len(broll_videos)} B-roll(s) "
          f"(Flux: {sum(1 for b in broll_videos if b['source']=='flux')}, "
          f"Pexels: {sum(1 for b in broll_videos if b['source']=='pexels')})")
    result = overlay_brolls_on_clip(clip_path, broll_videos, final_path)
    if not result or not final_path.exists():
        return {"final_path": clip_path, "brolls": []}

    size_mb = final_path.stat().st_size / 1024 / 1024
    print(f"      ✅ {final_name} ({size_mb:.2f} MB)")

    return {
        "final_path": final_path,
        "brolls": [b["spec"] for b in broll_videos],
    }
