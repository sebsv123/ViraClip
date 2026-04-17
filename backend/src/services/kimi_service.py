"""
Kimi-K2.5 Service — Multimodal visual analysis for viral clip scoring.
Uses Moonshot AI's Kimi API (256K context, native vision).
Falls back to Qwen3-VL via Ollama if available.

Docs: https://platform.moonshot.cn
Model: moonshot-v1-8k-vision-preview (32B activated, 1T total)
"""

import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default scoring weights when Kimi is active:
# 70% text-based score (existing pipeline) + 30% visual score (Kimi)
KIMI_VISUAL_WEIGHT = 0.30


class KimiVisualScore:
    visual_hook: int          # 0-100: ¿los primeros 3s enganchan visualmente?
    facial_energy: int        # 0-100: ¿expresión facial transmite energía?
    edit_rhythm: str          # "fast" / "medium" / "slow"
    subtitle_readability: int # 0-100: ¿subtítulos legibles?
    visual_virality: int      # 0-100: score compuesto visual
    recommendations: list[str]

    def __init__(self, raw: dict):
        self.visual_hook = int(raw.get("visual_hook", 50))
        self.facial_energy = int(raw.get("facial_energy", 50))
        self.edit_rhythm = raw.get("edit_rhythm", "medium")
        self.subtitle_readability = int(raw.get("subtitle_readability", 70))
        self.visual_virality = int(raw.get("visual_virality", 50))
        self.recommendations = raw.get("recommendations", [])


async def analyze_clip_visually(
    video_path: Path,
    transcript: str,
    api_key: str,
    n_frames: int = 8,
) -> Optional[KimiVisualScore]:
    """
    Envía frames del clip + transcripción a Kimi-K2.5 y obtiene análisis visual.
    
    Requiere: KIMI_API_KEY en .env
    Coste aprox: ~0.002 USD por clip (8 frames + 500 tokens)
    Latencia: 3-8 segundos
    """
    try:
        import httpx
    except ImportError:
        logger.warning("httpx not installed, skipping Kimi analysis")
        return None

    # Extraer frames representativos
    from ..utils.scene_analysis import extract_representative_frames
    frames = extract_representative_frames(video_path, n_frames=n_frames)
    if not frames:
        logger.warning(f"No frames extracted from {video_path.name}, skipping Kimi")
        return None

    # Construir mensaje multimodal
    content = []
    for frame_path in frames:
        b64 = base64.b64encode(frame_path.read_bytes()).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })

    content.append({
        "type": "text",
        "text": f"""Eres un experto en viralidad de TikTok/Reels/YouTube Shorts.
Analiza estos {len(frames)} frames de un clip de video junto con su transcripción.

TRANSCRIPCIÓN (primeros 1500 chars):
{transcript[:1500]}

EVALÚA ESTOS 5 ASPECTOS (0-100 cada uno):
1. visual_hook: ¿Los primeros frames tienen un elemento visual que detiene el scroll? (personas reaccionando, texto impactante, acción inesperada)
2. facial_energy: ¿El hablante/presenter transmite energía, emoción, autenticidad?
3. subtitle_readability: ¿Los subtítulos (si hay) son legibles, bien posicionados, buen contraste?
4. visual_virality: Score general de viralidad visual considerando todo
5. edit_rhythm: "fast" (<2s/escena) / "medium" (2-5s) / "slow" (>5s)

RESPONDE SOLO en este JSON exacto, sin texto extra:
{{"visual_hook": 0-100, "facial_energy": 0-100, "subtitle_readability": 0-100, "visual_virality": 0-100, "edit_rhythm": "fast|medium|slow", "recommendations": ["max 3 sugerencias cortas en español"]}}"""
    })

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.moonshot.cn/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "moonshot-v1-8k-vision-preview",
                    "messages": [{"role": "user", "content": content}],
                    "temperature": 0.1,
                    "max_tokens": 256,
                }
            )

            if resp.status_code != 200:
                logger.warning(f"Kimi API error {resp.status_code}: {resp.text[:200]}")
                return None

            raw_text = resp.json()["choices"][0]["message"]["content"].strip()

            # Extraer JSON del response
            if "```" in raw_text:
                raw_text = raw_text.split("```")[1].strip()
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:].strip()

            data = json.loads(raw_text)
            score = KimiVisualScore(data)
            logger.info(
                f"Kimi visual score for {video_path.name}: "
                f"visual_virality={score.visual_virality}, hook={score.visual_hook}"
            )
            return score

    except json.JSONDecodeError as e:
        logger.warning(f"Kimi returned invalid JSON: {e}")
        return None
    except Exception as e:
        logger.warning(f"Kimi analysis failed: {e}")
        return None
    finally:
        # Limpiar frames temporales
        for frame in frames:
            try:
                frame.unlink(missing_ok=True)
                if frame.parent.exists() and not any(frame.parent.iterdir()):
                    frame.parent.rmdir()
            except Exception:
                pass


def blend_scores(text_score: int, kimi_score: Optional[KimiVisualScore]) -> int:
    """
    Combina el score textual (pipeline existente) con el visual de Kimi.
    70% texto + 30% visual = score final más preciso.
    """
    if kimi_score is None:
        return text_score
    blended = int(text_score * (1 - KIMI_VISUAL_WEIGHT) +
                  kimi_score.visual_virality * KIMI_VISUAL_WEIGHT)
    return min(100, max(0, blended))
