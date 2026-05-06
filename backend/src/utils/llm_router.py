"""
LLM Router Inteligente — Asigna el modelo correcto según la fase del pipeline.

Fast (Groq llama-3.3-70b): tareas que requieren velocidad
Creative (DeepSeek V3): tareas que requieren razonamiento profundo
"""

import os
import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class LLMTask(Enum):
    """Cada fase del pipeline con su perfil de velocidad vs creatividad."""
    TRANSCRIPTION_ANALYSIS = "fast"
    SEMANTIC_PLANNING      = "fast"
    HOOK_SCORING           = "creative"
    VIRAL_ANALYSIS         = "creative"
    BROLL_PROMPT_GEN       = "creative"
    MASTER_DIRECTOR        = "creative"
    CAPTION_STYLE          = "fast"
    KEYWORD_EXTRACTION     = "fast"
    CONTENT_CLASSIFICATION = "fast"


def get_llm_for_task(task: LLMTask) -> str:
    """
    Retorna el modelo/configuración LLM apropiado para la tarea.
    
    Args:
        task: Tipo de tarea del pipeline
        
    Returns:
        String con formato "proveedor:modelo" (ej: "groq:llama-3.3-70b-versatile")
    """
    if task.value == "creative":
        return os.getenv("LLM_CREATIVE", "deepseek:deepseek-chat")
    return os.getenv("LLM_FAST", "groq:llama-3.3-70b-versatile")


def get_deepseek_client():
    """
    Retorna un cliente AsyncOpenAI configurado para DeepSeek.
    """
    from openai import AsyncOpenAI
    
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        logger.warning("[LLMRouter] DEEPSEEK_API_KEY not set — DeepSeek unavailable")
        return None
    
    return AsyncOpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com/v1"
    )


def get_groq_client():
    """
    Retorna un cliente AsyncOpenAI configurado para Groq.
    """
    from openai import AsyncOpenAI
    
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.warning("[LLMRouter] GROQ_API_KEY not set — Groq unavailable")
        return None
    
    return AsyncOpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1"
    )


def get_client_for_task(task: LLMTask):
    """
    Retorna el cliente LLM apropiado para la tarea.
    
    Para tareas "fast" → Groq
    Para tareas "creative" → DeepSeek (con fallback a Groq)
    """
    llm_config = get_llm_for_task(task)
    
    if llm_config.startswith("deepseek"):
        client = get_deepseek_client()
        if client:
            return client, "deepseek-chat"
        logger.warning("[LLMRouter] DeepSeek unavailable, falling back to Groq")
    
    client = get_groq_client()
    if client:
        return client, "llama-3.3-70b-versatile"
    
    logger.error("[LLMRouter] No LLM available (neither DeepSeek nor Groq)")
    return None, None


# ── Prompts especializados por fase ──────────────────────────────────────────

BROLL_SYSTEM_PROMPT = """
You are a cinematographer generating prompts for LTX-Video AI.
Your prompts must produce PHOTOREALISTIC footage, never animated.

Rules:
- Always include: "photorealistic, 4K, cinematic, real footage"
- Always include lighting: "natural lighting" or "studio lighting"
- Always include camera: "shot on Sony A7S III" or "DSLR footage"
- Always exclude: "cartoon, anime, CGI, illustration, drawing"
- Be specific: "close-up of hands typing on MacBook Pro" not "person working"
- Duration hint: "smooth 3-second shot, no cuts"
- Style: "documentary b-roll, professional production"
"""

VIRAL_SCORING_SYSTEM_PROMPT = """
You are a viral content analyst. Analyze the transcript and score each segment
for viral potential. Return a JSON object with:
- segments: array of {start, end, text, hook_strength (0-10),
  emotional_peak (0-10), shareability (0-10), retention (0-10),
  viral_score (0-10), reason}
- viral_potential: 'low' | 'medium' | 'high'

Scoring criteria:
1. First 3 seconds: strong hook? (question, shocking statement, number)
2. Information density per second
3. Tension/resolution moments
4. Natural vs forced CTA
5. Emotional triggers (fear, surprise, curiosity, aspiration)
"""


async def call_llm(
    task: LLMTask,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 1000,
    temperature: float = 0.3,
) -> Optional[str]:
    """
    Llamada unificada al LLM apropiado según la tarea.
    
    Args:
        task: Tipo de tarea (determina fast vs creative)
        system_prompt: Prompt del sistema
        user_prompt: Prompt del usuario
        max_tokens: Máximo de tokens en la respuesta
        temperature: Temperatura (0.0-1.0)
        
    Returns:
        Texto de la respuesta, o None si falla
    """
    client, model = get_client_for_task(task)
    if not client:
        return None
    
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"[LLMRouter] Error calling {model}: {e}")
        return None
