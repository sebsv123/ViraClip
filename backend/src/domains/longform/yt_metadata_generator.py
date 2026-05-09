"""
YouTube Metadata Generator — generates SEO-optimized title, description, tags via DeepSeek/Groq.
"""
import json
import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

import httpx

from .script_writer import ScriptResult

logger = logging.getLogger(__name__)


@dataclass
class YTMetadata:
    title: str
    description: str
    tags: List[str] = field(default_factory=list)
    category: str = "Education"
    chapters: List[str] = field(default_factory=list)


async def generate_yt_metadata(script: ScriptResult) -> Optional[YTMetadata]:
    """Generate SEO-optimized YouTube metadata using DeepSeek (primary) or Groq (fallback)."""
    sections_text = "\n".join(
        f"{s.index}. {s.heading} ({s.estimated_duration:.0f}s)" for s in script.sections
    )

    system_prompt = (
        "Eres un experto en SEO para YouTube. Generas títulos, descripciones y tags "
        "optimizados para maximizar CTR y retención. Respondes SIEMPRE en JSON válido."
    )
    user_prompt = (
        f"Genera metadata SEO para este video de YouTube:\n\n"
        f"Título: {script.title}\n"
        f"Duración total: {script.total_estimated_duration:.0f}s\n"
        f"Idioma: {script.language}\n\n"
        f"Secciones:\n{sections_text}\n\n"
        "Devuelve JSON con:\n"
        "{\n"
        "  'title': 'título SEO (max 100 chars)',\n"
        "  'description': 'descripción 300-500 chars con keywords',\n"
        "  'tags': ['tag1', 'tag2', ...] (10-15 tags),\n"
        "  'category': 'Education | HowTo | Entertainment | ...',\n"
        "  'chapters': ['00:00 Introducción', '02:30 Sección 1', ...]\n"
        "}"
    )

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
                        "temperature": 0.3,
                        "max_tokens": 2000,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = json.loads(data["choices"][0]["message"]["content"])
                return _parse_metadata(content)
        except Exception as e:
            logger.warning(f"[YTMeta] DeepSeek failed: {e}, falling back to Groq")

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
                        "temperature": 0.3,
                        "max_tokens": 2000,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = json.loads(data["choices"][0]["message"]["content"])
                return _parse_metadata(content)
        except Exception as e:
            logger.error(f"[YTMeta] Groq also failed: {e}")

    return None


def _parse_metadata(content: dict) -> YTMetadata:
    return YTMetadata(
        title=content.get("title", "")[:100],
        description=content.get("description", ""),
        tags=content.get("tags", [])[:15],
        category=content.get("category", "Education"),
        chapters=content.get("chapters", []),
    )
