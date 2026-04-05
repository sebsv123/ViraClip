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

try:
    from ..utils.scene_analysis import extract_representative_frames
except ImportError:  # pragma: no cover
    extract_representative_frames = None  # type: ignore

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
    # Phase 2.4 extensions
    scene_context: dict = field(default_factory=dict)   # indoor/outdoor, mood, objects
    boring_frames: list = field(default_factory=list)   # indices of boring frames
    broll_keywords: list = field(default_factory=list)  # extracted B-roll search terms

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
            scene_context=raw.get("scene_context", {}),
            boring_frames=raw.get("boring_frames", []),
            broll_keywords=raw.get("broll_keywords", []),
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
    frames = extract_representative_frames(video_path, n_frames=n_frames) if extract_representative_frames else []
    if not frames:
        logger.warning(f"No frames extracted from {video_path.name}")
        return VisionScore.unavailable()

    # Encode frames as base64
    images_b64 = []
    for frame_path in frames:
        try:
            b64 = base64.b64encode(frame_path.read_bytes()).decode()
            images_b64.append(b64)
        except Exception as e:
            logger.warning(f"[VISION] Failed to encode frame {frame_path}: {e}")

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
            except Exception as e:
                logger.warning(f"[VISION] Failed to clean up temp frame {fp}: {e}")


def _build_prompt(transcript: str, n_frames: int) -> str:
    return f"""Eres experto en viralidad para TikTok, Reels y YouTube Shorts.
Analiza estos {n_frames} frames de un clip de video junto con su transcripción.

TRANSCRIPCIÓN (primeros 1200 chars):
{transcript[:1200]}

EVALÚA y extrae TODOS estos campos:
- visual_hook (0-100): ¿Los primeros frames detienen el scroll? (reacción fuerte, texto impactante, acción sorpresiva)
- facial_energy (0-100): ¿El presentador transmite energía, emoción y autenticidad?
- subtitle_readability (0-100): ¿Los subtítulos son legibles con buen contraste y posición?
- visual_virality (0-100): Score general de viralidad visual
- edit_rhythm: Ritmo observado ("fast" <2s/escena, "medium" 2-5s, "slow" >5s)
- recommendations: Lista de 2-3 mejoras concretas en español
- scene_context: Objeto con claves: "environment" (indoor/outdoor/studio/street/nature), "mood" (energetic/calm/dramatic/funny/educational), "objects" (lista de hasta 5 objetos/personas visibles principales)
- boring_frames: Lista de índices de frames (0-{n_frames-1}) que sean estáticos o sin acción (útiles para insertar B-roll). Lista vacía si todos son interesantes.
- broll_keywords: Lista de 3-5 palabras clave en inglés para buscar B-roll que complementen el contenido (ej: "coffee brewing", "city skyline", "person coding")

RESPONDE SOLO con JSON válido, sin texto adicional:
{{"visual_hook": 75, "facial_energy": 80, "subtitle_readability": 90, "visual_virality": 78, "edit_rhythm": "medium", "recommendations": ["Añadir hook en el primer segundo"], "scene_context": {{"environment": "indoor", "mood": "energetic", "objects": ["person", "desk", "laptop"]}}, "boring_frames": [3, 6], "broll_keywords": ["office work", "laptop screen", "productivity"]}}"""


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


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 2.4 — New capabilities
# ─────────────────────────────────────────────────────────────────────────────

async def detect_boring_frames(
    video_path: "Path",
    n_frames: int = 12,
) -> list[int]:
    """
    Detect which frames are static/boring using Qwen3-VL.
    Returns frame indices suitable for B-roll injection.

    Falls back to Laplacian variance (CPU-only) when Ollama is unavailable.
    """
    available, model = await _check_ollama()
    if not available:
        return _detect_boring_frames_laplacian(video_path, n_frames)

    frames = extract_representative_frames(video_path, n_frames=n_frames) if extract_representative_frames else []
    if not frames:
        return []

    images_b64 = []
    for fp in frames:
        try:
            images_b64.append(base64.b64encode(fp.read_bytes()).decode())
        except Exception:
            pass

    if not images_b64:
        return []

    prompt = (
        f"Look at these {len(images_b64)} frames from a short video clip. "
        "Return ONLY a JSON array of the 0-based indices of frames that are "
        "visually static, boring, or lack action (e.g. speaker not moving, "
        "blank background, camera still). Empty array if all frames are engaging. "
        f"Example: [2, 5, 8]. Indices must be between 0 and {len(images_b64) - 1}."
    )

    try:
        import httpx
        endpoint = await _get_ollama_endpoint()
        payload = {
            "model": model,
            "prompt": prompt,
            "images": images_b64,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 60},
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(f"{endpoint}/api/generate", json=payload)

        if resp.status_code == 200:
            raw = resp.json().get("response", "").strip()
            # Extract JSON array
            start = raw.find("[")
            end = raw.rfind("]")
            if start != -1 and end > start:
                indices = json.loads(raw[start:end + 1])
                valid = [i for i in indices if isinstance(i, int) and 0 <= i < len(images_b64)]
                logger.debug(f"[vision] Boring frames detected: {valid}")
                return valid
    except Exception as e:
        logger.warning(f"[vision] Boring frame detection failed: {e}")
    finally:
        for fp in frames:
            try:
                fp.unlink(missing_ok=True)
            except Exception:
                pass

    return []


def _detect_boring_frames_laplacian(video_path: "Path", n_frames: int) -> list[int]:
    """CPU fallback: flag frames below sharpness threshold as boring."""
    try:
        import cv2
        import numpy as np

        frames = extract_representative_frames(video_path, n_frames=n_frames) if extract_representative_frames else []
        scores = []
        for fp in frames:
            img = cv2.imread(str(fp), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                scores.append(cv2.Laplacian(img, cv2.CV_64F).var())
            else:
                scores.append(0.0)
            try:
                fp.unlink(missing_ok=True)
            except Exception:
                pass

        if not scores:
            return []

        threshold = float(np.percentile(scores, 30))  # bottom 30% = boring
        return [i for i, s in enumerate(scores) if s < threshold]

    except Exception as e:
        logger.warning(f"[vision] Laplacian fallback failed: {e}")
        return []


async def extract_scene_context(
    video_path: "Path",
    n_frames: int = 6,
) -> dict:
    """
    Extract scene context for improved B-roll keyword quality.

    Returns dict with:
        environment: "indoor" | "outdoor" | "studio" | "street" | "nature"
        mood:        "energetic" | "calm" | "dramatic" | "funny" | "educational"
        objects:     list of up to 5 main visible objects/persons
        broll_keywords: list of 3-5 English B-roll search terms

    Falls back to empty dict if Ollama unavailable.
    """
    available, model = await _check_ollama()
    if not available:
        return {}

    frames = extract_representative_frames(video_path, n_frames=n_frames) if extract_representative_frames else []
    if not frames:
        return {}

    images_b64 = []
    for fp in frames:
        try:
            images_b64.append(base64.b64encode(fp.read_bytes()).decode())
        except Exception:
            pass

    if not images_b64:
        return {}

    prompt = (
        "Analyze the scene in these video frames and respond ONLY with valid JSON "
        "containing these exact keys: "
        '"environment" (one of: indoor/outdoor/studio/street/nature), '
        '"mood" (one of: energetic/calm/dramatic/funny/educational), '
        '"objects" (array of up to 5 main visible objects or persons), '
        '"broll_keywords" (array of 3-5 English search terms for relevant B-roll footage). '
        'Example: {"environment": "indoor", "mood": "energetic", '
        '"objects": ["person", "desk", "laptop"], '
        '"broll_keywords": ["office work", "typing on keyboard", "productivity"]}'
    )

    try:
        import httpx
        endpoint = await _get_ollama_endpoint()
        payload = {
            "model": model,
            "prompt": prompt,
            "images": images_b64,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 150},
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(f"{endpoint}/api/generate", json=payload)

        if resp.status_code == 200:
            raw = resp.json().get("response", "").strip()
            # Extract JSON object
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end > start:
                context = json.loads(raw[start:end + 1])
                logger.debug(f"[vision] Scene context: {context}")
                return context

    except Exception as e:
        logger.warning(f"[vision] Scene context extraction failed: {e}")
    finally:
        for fp in frames:
            try:
                fp.unlink(missing_ok=True)
            except Exception:
                pass

    return {}


async def score_thumbnail_frame(frame_path: "Path") -> dict:
    """
    Score a single frame for thumbnail quality using Qwen3-VL.

    Returns dict with:
        score:       0-100 overall thumbnail quality
        has_face:    bool — whether a clear face is visible
        expression:  str  — "neutral" | "happy" | "surprised" | "serious"
        composition: str  — "centered" | "rule_of_thirds" | "close_up" | "wide"
        reason:      str  — one-sentence explanation

    Falls back to Laplacian sharpness score when Ollama is unavailable.
    """
    available, model = await _check_ollama()
    if not available:
        return _score_thumbnail_laplacian(frame_path)

    try:
        b64 = base64.b64encode(frame_path.read_bytes()).decode()
    except Exception as e:
        logger.warning(f"[vision] Could not read frame for thumbnail scoring: {e}")
        return {"score": 50}

    prompt = (
        "You are a social media thumbnail expert. Score this frame as a thumbnail "
        "and respond ONLY with valid JSON with these exact keys: "
        '"score" (0-100 overall quality as thumbnail), '
        '"has_face" (true/false), '
        '"expression" (neutral/happy/surprised/serious/other), '
        '"composition" (centered/rule_of_thirds/close_up/wide), '
        '"reason" (one short English sentence explaining the score). '
        'Example: {"score": 82, "has_face": true, "expression": "surprised", '
        '"composition": "close_up", "reason": "Strong facial expression with clear subject."}'
    )

    try:
        import httpx
        endpoint = await _get_ollama_endpoint()
        payload = {
            "model": model,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 100},
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{endpoint}/api/generate", json=payload)

        if resp.status_code == 200:
            raw = resp.json().get("response", "").strip()
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end > start:
                result = json.loads(raw[start:end + 1])
                result["score"] = min(100, max(0, int(result.get("score", 50))))
                logger.debug(
                    f"[vision] Thumbnail score: {result['score']} "
                    f"face={result.get('has_face')} expr={result.get('expression')}"
                )
                return result

    except Exception as e:
        logger.warning(f"[vision] Thumbnail scoring failed: {e}")

    return {"score": 50}


def _score_thumbnail_laplacian(frame_path: "Path") -> dict:
    """CPU fallback: use Laplacian variance as sharpness proxy for thumbnail score."""
    try:
        import cv2
        img = cv2.imread(str(frame_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return {"score": 50}
        sharpness = cv2.Laplacian(img, cv2.CV_64F).var()
        # Map sharpness 0-1000 → score 0-100 (clipped)
        score = min(100, int(sharpness / 10))
        return {"score": score, "has_face": False, "expression": "unknown",
                "composition": "unknown", "reason": "Laplacian sharpness fallback"}
    except Exception:
        return {"score": 50}
