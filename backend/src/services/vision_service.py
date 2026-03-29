"""
Vision Service — Multimodal visual analysis for viral clip scoring.
100% local inference via Ollama + Qwen3-VL-8B (open-source, no API keys).

Architecture:
  Video clip → extract 8-10 representative frames (ffmpeg)
             → Ollama Qwen3-VL-8B (local) analyzes frames + transcript
             → Returns structured VisionScore
             → Blended 70/30 with existing text-based virality score

Model options (configured via OLLAMA_VISION_MODEL env var):
  - qwen3-vl:8b         → Best quality, ~7GB VRAM (recommended RTX 3080+)
  - qwen3-vl:4b         → Good quality, ~4GB VRAM (budget GPUs)
  - internvl2:8b        → Alternative to Qwen, similar VRAM
  - moondream:v2        → Ultralight ~2GB, reduced accuracy (CPU fallback)
  - llava:13b           → Older but stable fallback

Docs: https://ollama.com/library/qwen3-vl
      https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct
"""

import asyncio
import base64
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Weight blend: 70% text-based (existing AI pipeline) + 30% visual (Qwen3-VL)
VISUAL_WEIGHT = 0.30

# Ollama default endpoint (used when running inside Docker)
_OLLAMA_DEFAULT = "http://ollama:11434"


@dataclass
class VisionScore:
    """Structured output from the local vision model analysis."""
    visual_hook: int = 50           # 0-100: ¿los primeros frames enganchan?
    facial_energy: int = 50         # 0-100: ¿expresión facial con energía?
    subtitle_readability: int = 70  # 0-100: ¿subtítulos legibles?
    visual_virality: int = 50       # 0-100: score compuesto visual
    edit_rhythm: str = "medium"     # "fast" / "medium" / "slow"
    recommendations: list = field(default_factory=list)
    model_used: str = "none"        # qué modelo respondió

    @classmethod
    def from_dict(cls, raw: dict, model: str = "unknown") -> "VisionScore":
        return cls(
            visual_hook=int(raw.get("visual_hook", 50)),
            facial_energy=int(raw.get("facial_energy", 50)),
            subtitle_readability=int(raw.get("subtitle_readability", 70)),
            visual_virality=int(raw.get("visual_virality", 50)),
            edit_rhythm=raw.get("edit_rhythm", "medium"),
            recommendations=raw.get("recommendations", []),
            model_used=model,
        )

    @classmethod
    def unavailable(cls) -> "VisionScore":
        """Returned when Ollama is not available — pipeline continues normally."""
        return cls(model_used="unavailable")


# ─────────────────────────────────────────────────────────────────────────────
#  Ollama availability check (cached per process)
# ─────────────────────────────────────────────────────────────────────────────
_ollama_available: Optional[bool] = None
_ollama_vision_model: Optional[str] = None


async def _get_ollama_endpoint() -> str:
    from ..config import get_config
    cfg = get_config()
    return getattr(cfg, "ollama_base_url", _OLLAMA_DEFAULT).rstrip("/")


async def _check_ollama() -> tuple[bool, str]:
    """Check if Ollama is running and has a vision model available. Cached."""
    global _ollama_available, _ollama_vision_model
    if _ollama_available is not None:
        return _ollama_available, _ollama_vision_model or ""

    try:
        import httpx
        from ..config import get_config
        cfg = get_config()
        endpoint = await _get_ollama_endpoint()
        vision_model = getattr(cfg, "ollama_vision_model", "qwen3-vl:8b")

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{endpoint}/api/tags")
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                # Check exact match or prefix match (e.g. "qwen3-vl:8b" vs "qwen3-vl:8b-instruct-q4_k_m")
                found = any(
                    m == vision_model or m.startswith(vision_model.split(":")[0])
                    for m in models
                )
                if found:
                    _ollama_available = True
                    _ollama_vision_model = vision_model
                    logger.info(f"✅ Ollama vision model ready: {vision_model}")
                else:
                    logger.warning(
                        f"⚠️  Ollama running but vision model '{vision_model}' not found. "
                        f"Available: {models}. Run: ollama pull {vision_model}"
                    )
                    _ollama_available = False
                    _ollama_vision_model = None
            else:
                _ollama_available = False
                _ollama_vision_model = None

    except Exception as e:
        logger.debug(f"Ollama not reachable ({e}), visual analysis disabled")
        _ollama_available = False
        _ollama_vision_model = None

    return _ollama_available, _ollama_vision_model or ""


# ─────────────────────────────────────────────────────────────────────────────
#  Core analysis function
# ─────────────────────────────────────────────────────────────────────────────

async def analyze_clip_visually(
    video_path: Path,
    transcript: str,
    n_frames: int = 8,
) -> VisionScore:
    """
    Analyzes video frames locally with Qwen3-VL-8B via Ollama.
    Completely free, no API keys. Runs on GPU if available, CPU fallback.

    Falls back gracefully if Ollama is not running — does NOT raise exceptions.

    Args:
        video_path: Path to the rendered clip
        transcript: Full clip transcript text
        n_frames: Number of representative frames to extract (default 8)

    Returns:
        VisionScore — filled if Ollama available, default values if not
    """
    available, model = await _check_ollama()
    if not available:
        return VisionScore.unavailable()

    # Extract representative frames
    from ..utils.scene_analysis import extract_representative_frames
    frames = extract_representative_frames(video_path, n_frames=n_frames)
    if not frames:
        logger.warning(f"No frames extracted from {video_path.name}")
        return VisionScore.unavailable()

    # Encode frames as base64
    images_b64 = []
    for frame_path in frames:
        try:
            b64 = base64.b64encode(frame_path.read_bytes()).decode()
            images_b64.append(b64)
        except Exception:
            pass

    if not images_b64:
        return VisionScore.unavailable()

    prompt = _build_prompt(transcript, len(images_b64))

    try:
        import httpx
        endpoint = await _get_ollama_endpoint()

        # Ollama multimodal format: images array in the message
        payload = {
            "model": model,
            "prompt": prompt,
            "images": images_b64,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 300,
            },
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{endpoint}/api/generate", json=payload)

        if resp.status_code != 200:
            logger.warning(f"Ollama returned {resp.status_code}: {resp.text[:200]}")
            return VisionScore.unavailable()

        raw_text = resp.json().get("response", "").strip()
        score = _parse_response(raw_text, model)
        logger.info(
            f"🎯 Vision score [{model}] for {video_path.name}: "
            f"visual={score.visual_virality} hook={score.visual_hook} "
            f"energy={score.facial_energy} rhythm={score.edit_rhythm}"
        )
        return score

    except Exception as e:
        logger.warning(f"Vision analysis failed: {e}")
        return VisionScore.unavailable()

    finally:
        # Clean up temp frames
        for fp in frames:
            try:
                fp.unlink(missing_ok=True)
                if fp.parent.exists() and not any(fp.parent.iterdir()):
                    fp.parent.rmdir()
            except Exception:
                pass


def _build_prompt(transcript: str, n_frames: int) -> str:
    return f"""Eres experto en viralidad para TikTok, Reels y YouTube Shorts.
Analiza estos {n_frames} frames de un clip de video junto con su transcripción.

TRANSCRIPCIÓN (primeros 1200 chars):
{transcript[:1200]}

EVALÚA estos aspectos del clip (escala 0-100):
- visual_hook: ¿Los primeros frames tienen algo que detiene el scroll? (reacción fuerte, texto impactante, acción sorpresiva)
- facial_energy: ¿El presentador/hablante transmite energía, emoción y autenticidad?
- subtitle_readability: ¿Los subtítulos (si los hay) son legibles, con buen contraste y posición?
- visual_virality: Score general de viralidad visual considerando todos los factores
- edit_rhythm: Ritmo de edición observado ("fast" <2s/escena, "medium" 2-5s, "slow" >5s)
- recommendations: Lista de 2-3 mejoras concretas y cortas en español

RESPONDE SOLO con este JSON exacto, sin texto adicional:
{{"visual_hook": 75, "facial_energy": 80, "subtitle_readability": 90, "visual_virality": 78, "edit_rhythm": "medium", "recommendations": ["Añadir hook visual en el primer segundo", "Aumentar velocidad de cortes"]}}"""


def _parse_response(raw_text: str, model: str) -> VisionScore:
    """Parse JSON from model response, with multiple extraction strategies."""
    # Strategy 1: direct JSON parse
    try:
        return VisionScore.from_dict(json.loads(raw_text), model)
    except json.JSONDecodeError:
        pass

    # Strategy 2: extract JSON block from markdown
    for marker in ["```json", "```"]:
        if marker in raw_text:
            parts = raw_text.split(marker)
            for part in parts[1:]:
                candidate = part.split("```")[0].strip()
                try:
                    return VisionScore.from_dict(json.loads(candidate), model)
                except json.JSONDecodeError:
                    continue

    # Strategy 3: find first { ... } block
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end > start:
        try:
            return VisionScore.from_dict(json.loads(raw_text[start:end + 1]), model)
        except json.JSONDecodeError:
            pass

    logger.warning(f"Could not parse vision model JSON response: {raw_text[:200]}")
    return VisionScore.unavailable()


# ─────────────────────────────────────────────────────────────────────────────
#  Score blending
# ─────────────────────────────────────────────────────────────────────────────

def blend_with_text_score(text_score: int, vision: VisionScore) -> int:
    """
    Blends existing text-based virality score with visual score.
    Formula: 70% text (AssemblyAI + LLM analysis) + 30% visual (Qwen3-VL).
    If vision is unavailable, returns text_score unchanged.
    """
    if vision.model_used in ("unavailable", "none"):
        return text_score
    blended = int(text_score * (1 - VISUAL_WEIGHT) + vision.visual_virality * VISUAL_WEIGHT)
    return min(100, max(0, blended))


# ─────────────────────────────────────────────────────────────────────────────
#  Ollama model pull helper (called on startup if model not present)
# ─────────────────────────────────────────────────────────────────────────────

async def ensure_vision_model_pulled(model: str) -> bool:
    """
    Pulls the vision model from Ollama registry if not already available.
    Called once on backend startup. Non-blocking — runs in background.

    Returns True if model is ready, False if pull failed.
    """
    try:
        import httpx
        endpoint = await _get_ollama_endpoint()

        # Check if already available
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{endpoint}/api/tags")
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                if any(m.startswith(model.split(":")[0]) for m in models):
                    logger.info(f"✅ Vision model '{model}' already available in Ollama")
                    return True

        logger.info(f"📥 Pulling Ollama vision model '{model}'... (this may take several minutes first time)")

        async with httpx.AsyncClient(timeout=600.0) as client:
            # Streaming pull
            async with client.stream("POST", f"{endpoint}/api/pull",
                                     json={"name": model, "stream": True}) as stream:
                async for line in stream.aiter_lines():
                    if line:
                        data = json.loads(line)
                        status = data.get("status", "")
                        if "pulling" in status.lower() or "verifying" in status.lower():
                            logger.debug(f"Ollama pull: {status}")
                        if data.get("error"):
                            logger.error(f"Ollama pull error: {data['error']}")
                            return False

        logger.info(f"✅ Vision model '{model}' pulled successfully")
        global _ollama_available, _ollama_vision_model
        _ollama_available = True
        _ollama_vision_model = model
        return True

    except Exception as e:
        logger.warning(f"Could not pull vision model '{model}': {e}")
        return False
