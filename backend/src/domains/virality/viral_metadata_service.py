"""
Viral Metadata Service — generates platform-optimised hashtags, SEO titles,
and short descriptions using the configured LLM.

Called as a post-clip step in video_service.py; output stored in
GeneratedClip.clip_metadata (JSON column).
"""
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PLATFORM_HASHTAG_COUNT = {
    "tiktok":    30,
    "reels":     20,
    "shorts":    15,
    "universal": 20,
}

_PROMPT_TEMPLATE = """\
You are an expert viral content strategist. Given a video transcript excerpt and target platform, generate:
1. A punchy SEO-optimised title (max 60 chars, no hashtags)
2. A hook description (1-2 sentences, max 150 chars)
3. A list of {hashtag_count} relevant hashtags (without # prefix)

Platform: {platform}
Transcript excerpt: {text}

Reply ONLY with a valid JSON object in this exact format:
{{
  "title": "...",
  "description": "...",
  "hashtags": ["tag1", "tag2", ...]
}}"""


async def generate_viral_metadata(
    text: str,
    platform: str = "tiktok",
    llm_client=None,
) -> Dict[str, Any]:
    """
    Generate viral metadata for a clip using the configured LLM.

    Falls back to a keyword-based heuristic when the LLM is unavailable.

    Returns dict with keys: title, description, hashtags
    """
    hashtag_count = _PLATFORM_HASHTAG_COUNT.get(platform, 20)
    text_excerpt  = text[:500].strip()

    # Try LLM generation
    try:
        if llm_client is None:
            from ...domains.ai.llm_service import LLMService
            llm_client = LLMService()

        prompt = _PROMPT_TEMPLATE.format(
            platform=platform,
            hashtag_count=hashtag_count,
            text=text_excerpt,
        )

        raw = await llm_client.generate(prompt, max_tokens=300, temperature=0.4)
        if raw:
            # Strip markdown code fences if present
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw.strip())
            result = {
                "title":       str(data.get("title",       ""))[:60],
                "description": str(data.get("description", ""))[:150],
                "hashtags":    [str(h).lstrip("#") for h in data.get("hashtags", [])][:hashtag_count],
                "platform":    platform,
            }
            logger.info(
                f"[meta] Generated: '{result['title']}' | "
                f"{len(result['hashtags'])} hashtags"
            )
            return result
    except Exception as exc:
        logger.debug(f"[meta] LLM metadata generation failed: {exc}")

    # Fallback: extract keywords and format as hashtags
    return _keyword_fallback(text_excerpt, platform, hashtag_count)


def _keyword_fallback(text: str, platform: str, hashtag_count: int) -> Dict[str, Any]:
    """Simple keyword extraction fallback when LLM is unavailable."""
    stopwords = {
        # English
        "the", "a", "an", "is", "are", "was", "were", "i", "you", "he",
        "she", "it", "we", "they", "and", "or", "but", "in", "on", "at",
        "to", "of", "for", "with", "this", "that", "so", "just", "like",
        "about", "what", "when", "how", "why", "from", "my", "your", "have",
        "been", "will", "can", "could", "would", "should", "than", "then",
        # Spanish
        "que", "de", "en", "el", "la", "los", "las", "un", "una", "unos",
        "unas", "por", "para", "con", "sin", "sobre", "este", "esta", "estos",
        "estas", "ese", "esa", "esos", "esas", "como", "pero", "sino", "cuando",
        "donde", "quien", "cual", "cuales", "hay", "ser", "estar", "tiene",
        "tienen", "tener", "hacer", "hace", "hacen", "todo", "toda", "todos",
        "todas", "muy", "mas", "mas", "porque", "aunque", "tambien", "cada",
        "cual", "algo", "alguien", "aqui", "ahi", "alla", "siempre", "nunca",
        "solo", "bien", "mal", "ya", "aun", "antes", "despues", "entre",
        "desde", "hasta", "hacia", "durante", "mediante", "segun", "vez",
        "puedes", "puede", "pueden", "vamos", "vamos", "decir", "decirte",
        "nuestro", "nuestra", "nuestros", "nuestras", "vuestra", "vuestro",
        "mismo", "misma", "mismos", "mismas", "otro", "otra", "otros", "otras",
    }
    words = [
        w.strip(".,!?\"';:()¿¡").lower()
        for w in text.split()
        if len(w.strip(".,!?\"';:()¿¡")) > 3
    ]
    keywords = list(dict.fromkeys(
        w for w in words
        if w not in stopwords and w.replace("-", "").isalpha()
    ))

    title_words = [w.capitalize() for w in keywords[:6]]
    title = " ".join(title_words)[:60] or "Viral Clip"

    # Build a clean description from the top keywords — not raw transcript
    top_kw = [w.capitalize() for w in keywords[:8]]
    description = f"{'  '.join(top_kw)}"[:150] if top_kw else "Watch this viral clip"

    hashtags = [w.lower().replace(" ", "") for w in keywords[:hashtag_count]]
    platform_tags: List[str] = {
        "tiktok":  ["tiktok", "viral", "fyp", "foryoupage", "trending"],
        "reels":   ["reels", "viral", "instagram", "trending", "explore"],
        "shorts":  ["shorts", "viral", "youtube", "trending"],
    }.get(platform, ["viral", "trending"])

    for tag in platform_tags:
        if tag not in hashtags:
            hashtags.append(tag)

    return {
        "title":       title,
        "description": description,
        "hashtags":    hashtags[:hashtag_count],
        "platform":    platform,
    }
