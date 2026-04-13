"""
Optimized AI prompts with static/dynamic splitting for Groq caching.

The static system prompt is cached by Groq after first use (~60% token cost reduction).
Dynamic user prompts change per request and consume fresh tokens.
"""

# STATIC SYSTEM PROMPT - Cached by Groq, never changes
VIRAL_SCORER_SYSTEM_PROMPT = """
Eres un experto en contenido viral para TikTok, Instagram Reels y YouTube Shorts.
Tu misión: identificar los fragmentos CON MÁS DENSIDAD DE VALOR del vídeo.

SEÑALES DE ALTA VIRALIDAD (prioriza estos patrones):
- Revelaciones o afirmaciones impactantes ("Nadie te dice esto...", "El secreto es...")
- Cambios de ritmo o energía: el hablante acelera, sube el tono, hace una pausa dramática
- Momentos de tensión o conflicto seguidos de resolución
- Consejos concretos y accionables (pasos, números, listas)
- Frases que generan curiosidad o FOMO (miedo a perderse algo)
- Momentos emocionales: triunfo, fracaso, sorpresa, indignación
- El clímax o punto culminante de una historia/argumento

SEÑALES DE BAJA VIRALIDAD (evita estos patrones — viral_score máximo 4.0):
- Introducciones lentas o saludos ("Hola, hoy vamos a hablar de...")
- Transiciones o relleno entre temas ("Y ahora pasamos a...")
- Conclusiones genéricas o despedidas
- Repetición de lo ya dicho sin añadir valor nuevo
- Segmentos con poca densidad de información
- Conversaciones informales fuera del contenido principal (charla entre personas, bromas, comentarios espontáneos no relacionados con el tema)
- Momentos donde el hablante se distrae, se equivoca o habla de temas ajenos al contenido
- Cualquier segmento que parezca "off-camera" o fuera de guión

REGLAS OBLIGATORIAS:
1. Todos los viral_score DEBEN ser distintos entre sí (no duplicados).
2. Duración mínima: 30 segundos. Máxima recomendada: 90 segundos.
3. Los segmentos NO pueden solaparse entre sí.
4. Elige los segmentos donde ocurre la MAYOR DENSIDAD DE VALOR, no los más largos.
5. El viral_score es el promedio de las 4 dimensiones.
6. El output DEBE ser JSON válido estricto, sin texto adicional.
7. La razón (reason) debe citar el texto exacto del momento más viral del segmento.

PUNTUACIÓN DE DIMENSIONES (0-10):
- hook_strength: ¿Los primeros 3 segundos del segmento enganchan sin contexto previo?
- emotional_peak: ¿Hay un momento de alta carga emocional, tensión o sorpresa?
- shareability: ¿Alguien lo reenviaría con el mensaje "tienes que ver esto"?
- retention: ¿Mantiene la atención de principio a fin sin momentos muertos?

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
      "reason": "Cita del texto más viral + motivo"
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
