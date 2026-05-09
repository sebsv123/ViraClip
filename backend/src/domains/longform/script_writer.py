"""
Script Writer — generates structured YouTube scripts via DeepSeek/Groq.
"""
import json
import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ScriptSection:
    index: int
    heading: str
    narration_text: str
    estimated_duration: float  # len(words) / 2.5
    broll_keywords: List[str] = field(default_factory=list)
    is_intro: bool = False
    is_outro: bool = False


@dataclass
class ScriptResult:
    title: str
    sections: List[ScriptSection]
    total_estimated_duration: float
    language: str = "es"


async def write_script(topic: str, target_duration_seconds: int = 600) -> Optional[ScriptResult]:
    """Generate a structured YouTube script using DeepSeek (primary) or Groq (fallback)."""
    system_prompt = (
        "Eres un guionista experto en contenido viral para YouTube. "
        "Escribes guiones claros, directos y con gancho emocional. "
        "Estructura: intro impactante → desarrollo por secciones → CTA final. "
        "Responde SIEMPRE en JSON válido con el schema indicado."
    )
    sections_count = 6  # default, will be adjusted by LLM
    min_words = int(target_seconds / sections_count * 1.8)
    max_words = int(target_seconds / sections_count * 3.5)
    user_prompt = (
        f"Escribe un guión de {target_seconds}s sobre: {topic}\n\n"
        "IMPORTANTE: El guión debe durar exactamente {target_seconds} segundos.\n"
        f"Cada sección debe tener entre {min_words} y {max_words} palabras.\n\n"
        "Devuelve JSON con esta estructura exacta:\n"
        "{\n"
        "  'title': 'título del video',\n"
        "  'language': 'es' o 'en',\n"
        "  'sections': [\n"
        "    {\n"
        "      'index': 0,\n"
        "      'heading': 'título de sección',\n"
        "      'narration_text': 'texto completo que leerá el narrador',\n"
        "      'broll_keywords': ['keyword1', 'keyword2'],\n"
        "      'is_intro': true/false,\n"
        "      'is_outro': true/false\n"
        "    }\n"
        "  ]\n"
        "}"
    )

    # Try DeepSeek first
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if deepseek_key:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {deepseek_key}", "Content-Type": "application/json"},
                    json={
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.4,
                        "max_tokens": 4096,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = json.loads(data["choices"][0]["message"]["content"])
                result = _parse_script_result(content)
                return _validate_and_adjust_script(result, target_duration_seconds)
        except Exception as e:
            logger.warning(f"[ScriptWriter] DeepSeek failed: {e}, falling back to Groq")

    # Fallback to Groq
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}"},
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.4,
                        "max_tokens": 4096,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = json.loads(data["choices"][0]["message"]["content"])
                return _parse_script_result(content)
        except Exception as e:
            logger.error(f"[ScriptWriter] Groq also failed: {e}")

    logger.error("[ScriptWriter] All LLM providers failed")
    return None


def _validate_and_adjust_script(
    result: ScriptResult,
    target_seconds: int,
    tolerance: float = 0.20,
) -> ScriptResult:
    """
    Verifica que la duración total está en [target*(1-tol), target*(1+tol)].
    Si no → recorta secciones de desarrollo (no intro/outro).
    """
    total = sum(s.estimated_duration for s in result.sections)
    min_ok = target_seconds * (1 - tolerance)
    max_ok = target_seconds * (1 + tolerance)

    if min_ok <= total <= max_ok:
        return result

    if total > max_ok:
        # Script demasiado largo: elimina secciones de desarrollo
        sections = result.sections
        while sum(s.estimated_duration for s in sections) > max_ok:
            dev = [s for s in sections if not s.is_intro and not s.is_outro]
            if not dev:
                break
            shortest = min(dev, key=lambda s: s.estimated_duration)
            sections = [s for s in sections if s.index != shortest.index]
        result.sections = sections
    else:
        logger.warning(
            "[ScriptWriter] Script too short: %.0fs vs target %ds. "
            "Consider increasing section count in prompt.",
            total, target_seconds,
        )

    result.total_estimated_duration = sum(s.estimated_duration for s in result.sections)
    logger.info(
        "[ScriptWriter] Duration adjusted: %.0fs → %.0fs (target: %ds)",
        total, result.total_estimated_duration, target_seconds,
    )
    return result


def _parse_script_result(content: dict) -> ScriptResult:
    """Parse LLM response into ScriptResult."""
    sections = []
    total_duration = 0.0
    for s in content.get("sections", []):
        text = s.get("narration_text", "")
        words = len(text.split())
        est_dur = words / 2.5  # ~2.5 words per second
        section = ScriptSection(
            index=s.get("index", 0),
            heading=s.get("heading", ""),
            narration_text=text,
            estimated_duration=est_dur,
            broll_keywords=s.get("broll_keywords", []),
            is_intro=s.get("is_intro", False),
            is_outro=s.get("is_outro", False),
        )
        sections.append(section)
        total_duration += est_dur

    return ScriptResult(
        title=content.get("title", topic),
        sections=sections,
        total_estimated_duration=total_duration,
        language=content.get("language", "es"),
    )
