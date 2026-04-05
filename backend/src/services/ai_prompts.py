"""
Optimized AI prompts with static/dynamic splitting for Groq caching.

The static system prompt is cached by Groq after first use (~60% token cost reduction).
Dynamic user prompts change per request and consume fresh tokens.
"""

# STATIC SYSTEM PROMPT - Cached by Groq, never changes
VIRAL_SCORER_SYSTEM_PROMPT = """
Eres un experto en contenido viral para TikTok, Instagram Reels y YouTube Shorts.
Evalúa segmentos de vídeo en 4 dimensiones (0-10 cada una):
- hook_strength: ¿Los primeros 3 segundos enganchan al espectador?
- emotional_peak: ¿Hay un momento emocional claro y potente?
- shareability: ¿El espectador lo enviaría a sus contactos?
- retention: ¿Mantiene la atención hasta el final sin caídas?

REGLAS OBLIGATORIAS:
1. Todos los viral_score DEBEN ser distintos entre sí (no duplicados).
2. Duración mínima de segmento: 30 segundos.
3. El viral_score es el promedio de las 4 dimensiones.
4. El output DEBE ser JSON válido estricto, sin texto adicional antes o después.
5. La razón (reason) debe ser 1 frase concisa explicando por qué es viral.

FORMATO DE OUTPUT:
{
  "segments": [
    {
      "start": "MM:SS",
      "end": "MM:SS",
      "hook_strength": 0-10,
      "emotional_peak": 0-10,
      "shareability": 0-10,
      "retention": 0-10,
      "viral_score": promedio_float,
      "reason": "1 frase explicando viralidad"
    }
  ]
}
""".strip()


def build_dynamic_user_prompt(transcript: str, language: str, num_clips: int, previous_error: str = None) -> str:
    """
    Build dynamic user prompt that changes per request.
    
    Args:
        transcript: Video transcript text
        language: Video language (es, en, etc.)
        num_clips: Number of clips requested
        previous_error: Optional validation error from previous attempt
        
    Returns:
        Dynamic prompt string for this specific request
    """
    error_context = ""
    if previous_error:
        error_context = f"\n⚠️ CORRECCIÓN NECESARIA - El intento anterior falló con este error:\n{previous_error}\n\nAsegúrate de corregir este problema en tu respuesta.\n"
    
    return f"""{error_context}
Vídeo en idioma: {language}
Clips requeridos: {num_clips}

Transcripción completa:
{transcript}

Devuelve exactamente {num_clips} segmentos en formato JSON con la estructura especificada.
Recuerda: todos los viral_score deben ser DISTINTOS entre sí.
""".strip()


# Alternative static prompt for hook detection (separate use case)
HOOK_DETECTOR_SYSTEM_PROMPT = """
Eres un experto en detectar hooks virales para contenido de formato corto.

Identifica los momentos exactos donde el vídeo engancha al espectador:
- Curiosity gaps (información incompleta que genera intriga)
- Bold claims (afirmaciones audaces o controversiales)
- Pattern interrupts (cambios inesperados que capturan atención)
- Emotional triggers (momentos de alta carga emocional)

Para cada hook encontrado, devuelve:
- timestamp: Segundo exacto donde ocurre (formato: "MM:SS")
- type: Tipo de hook (curiosity_gap, bold_claim, pattern_interrupt, emotional_trigger)
- strength: Potencia del hook (0-10)
- text: Texto exacto del hook (máximo 100 caracteres)

OUTPUT en JSON:
{
  "hooks": [
    {
      "timestamp": "MM:SS",
      "type": "curiosity_gap",
      "strength": 8.5,
      "text": "Texto del hook"
    }
  ]
}
""".strip()


def build_hook_detection_prompt(transcript: str, language: str) -> str:
    """Build prompt for hook detection (dynamic part)."""
    return f"""
Idioma del vídeo: {language}

Transcripción:
{transcript}

Identifica todos los hooks virales en esta transcripción.
Devuelve JSON con la lista de hooks encontrados.
""".strip()
