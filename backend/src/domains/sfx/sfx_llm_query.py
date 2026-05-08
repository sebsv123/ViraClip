"""
SFX LLM Query Generator — uses DeepSeek/Groq to generate contextual
sound effect search queries for Freesound based on transcript analysis.
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROMPT_SFX_ANALYSIS = """You are a professional video editor specializing in viral short-form content (TikTok/Reels).

Analyze this transcript segment and the video context, then generate
precise sound effect search queries for Freesound.org.

VIDEO CONTEXT:
- Topic: {video_topic}
- Mood: {mood}
- Energy level: {energy} (0.0-1.0)
- Speaker emotion: {emotion}

TRANSCRIPT SEGMENT:
"{transcript_text}"

EVENTS IN THIS SEGMENT:
- Jump cuts at: {jump_cut_times}
- Key moment type: {moment_type}  (hook/climax/transition/cta/data_reveal)

Generate a JSON response with sound effects for this segment.
Rules:
1. Maximum {max_sfx} sound effects total
2. Minimum {min_gap}s between effects
3. Never overlap speech — SFX must be between words or on jump cuts
4. Use Freesound search query syntax (2-4 keywords, specific)
5. Duration must be short (0.3-2.5 seconds max)
6. Think like a top TikTok editor — what makes THIS moment pop?

Current trending SFX styles in viral content (2025-2026):
- Whoosh/swipe sounds on transitions
- "Brainrot" glitch effects on surprising moments
- Vinyl scratch on topic changes
- Deep bass impact on key stats/numbers
- Notification ping on CTAs
- Cinematic riser on hooks

Respond ONLY with valid JSON:
{{
  "sfx_plan": [
    {{
      "time_offset": 0.2,
      "freesound_query": "cinematic riser tension build short",
      "category": "suspense",
      "volume_db": -16,
      "fade_out_ms": 300,
      "reason": "hook opening — build tension before first word"
    }}
  ]
}}
"""


def _detect_emotion(text: str) -> str:
    """Simple keyword-based emotion detection."""
    text_lower = text.lower()
    if any(w in text_lower for w in ["urgent", "danger", "warning", "cuidado", "peligro"]):
        return "urgent"
    if any(w in text_lower for w in ["increible", "amazing", "wow", "dios", "genial"]):
        return "excited"
    if any(w in text_lower for w in ["triste", "sad", "lament", "perder"]):
        return "sad"
    if any(w in text_lower for w in ["secreto", "secret", "nadie", "nunca"]):
        return "curious"
    return "neutral"


def _classify_moment(text: str) -> str:
    """Classify the type of moment based on transcript content."""
    text_lower = text.lower()
    if any(w in text_lower for w in ["numero", "number", "dato", "stat", "cifra", "million"]):
        return "data_reveal"
    if any(w in text_lower for w in ["suscrib", "follow", "like", "comparte", "dale"]):
        return "cta"
    if any(w in text_lower for w in ["pero", "but", "sin embargo", "however", "entonces"]):
        return "transition"
    if any(w in text_lower for w in ["introduc", "empecemos", "vamos", "hoy"]):
        return "hook"
    return "climax"


def _join_segments(segments: List[Dict[str, Any]]) -> str:
    """Join transcript segments into a single text."""
    if isinstance(segments, str):
        return segments[:500]
    texts = []
    for s in segments:
        if isinstance(s, dict):
            texts.append(s.get("text", s.get("transcript", "")))
        elif isinstance(s, str):
            texts.append(s)
    return " ".join(texts)[:500]


async def generate_sfx_plan(
    transcript_segments: List[Dict[str, Any]],
    jump_cuts: List[float],
    video_topic: str = "",
    mood: str = "neutral",
    energy: float = 0.5,
    clip_duration: float = 60.0,
    llm_client: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """
    Generate SFX plan using LLM (DeepSeek first, Groq fallback).
    Returns list of SFX dicts with time_offset, freesound_query, category, etc.
    """
    max_sfx = int(os.getenv("SFX_MAX_PER_CLIP", "4"))
    min_gap = int(os.getenv("SFX_MIN_GAP_SECONDS", "8"))

    prompt = PROMPT_SFX_ANALYSIS.format(
        video_topic=video_topic or "general",
        mood=mood,
        energy=energy,
        emotion=_detect_emotion(_join_segments(transcript_segments)),
        transcript_text=_join_segments(transcript_segments),
        jump_cut_times=[round(t, 2) for t in (jump_cuts or [])[:5]],
        moment_type=_classify_moment(_join_segments(transcript_segments)),
        max_sfx=max_sfx,
        min_gap=min_gap,
    )

    # Try DeepSeek first, fallback to Groq
    llm_config = os.getenv("LLM", "groq:llama-3.3-70b-versatile")
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    groq_key = os.getenv("GROQ_API_KEY", "")

    providers = []
    if deepseek_key:
        providers.append(("deepseek", "https://api.deepseek.com/v1/chat/completions", deepseek_key, "deepseek-chat"))
    if groq_key:
        providers.append(("groq", "https://api.groq.com/openai/v1/chat/completions", groq_key, "llama-3.3-70b-versatile"))

    import httpx

    for provider_name, api_url, api_key, model in providers:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    api_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                        "response_format": {"type": "json_object"},
                    },
                )
                if resp.status_code != 200:
                    logger.warning(f"[SFX-LLM] {provider_name} error {resp.status_code}: {resp.text[:100]}")
                    continue

                content = resp.json()["choices"][0]["message"]["content"]
                data = json.loads(content)
                plan = data.get("sfx_plan", [])
                logger.info(f"[SFX-LLM] {provider_name} generated {len(plan)} SFX")
                return plan

        except Exception as e:
            logger.warning(f"[SFX-LLM] {provider_name} failed: {e}")
            continue

    logger.warning("[SFX-LLM] No LLM available — returning empty plan")
    return []
