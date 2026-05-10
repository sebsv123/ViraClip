"""
Clip mood/energy auto-tagger using Groq LLM.
Runs async after transcript generation.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

VALID_MOODS = {
    "motivational", "educational", "entertaining",
    "storytelling", "humorous", "emotional",
    "controversial", "inspirational", "tutorial",
}

VALID_ENERGY_LEVELS = {"high_energy", "calm", "intense", "balanced"}

MOOD_OPTIMAL_POSTING_HOURS = {
    "motivational":  [6, 7, 8],
    "educational":   [12, 13, 19, 20],
    "entertaining":  [20, 21, 22, 23],
    "humorous":      [12, 18, 21],
    "emotional":     [20, 21, 22],
    "storytelling":  [19, 20, 21],
    "controversial": [10, 14, 18],
    "inspirational": [7, 8, 20, 21],
    "tutorial":      [10, 11, 19, 20],
}

MOOD_TAG_PROMPT = """
Analyze this video transcript and return ONLY valid JSON.
No explanation, no markdown, just JSON.

Return:
{
  "moods": ["mood1", "mood2"],
  "energy_level": "high_energy|calm|intense|balanced",
  "target_emotion": "one word describing the main emotion triggered",
  "hook_type": "question|statement|shocking_fact|story|challenge|other",
  "reasoning": "one sentence max"
}

Valid moods (pick 1-3): motivational, educational, entertaining,
storytelling, humorous, emotional, controversial, inspirational, tutorial.

Transcript:
{transcript}
"""


def _get_optimal_hours(moods: list[str]) -> list[int]:
    hours = set()
    for mood in moods:
        hours.update(MOOD_OPTIMAL_POSTING_HOURS.get(mood, [20, 21]))
    return sorted(hours)


def _default_mood_result() -> dict:
    return {
        "moods": ["entertaining"],
        "energy_level": "balanced",
        "hook_type": "other",
        "target_emotion": "",
        "optimal_hours": [20, 21],
    }


async def tag_clip_mood(
    clip_id: str,
    transcript_text: str,
    groq_client,
    db,
) -> dict:
    """Classify clip mood and energy using Groq LLM."""
    if not transcript_text or len(transcript_text.strip()) < 20:
        return _default_mood_result()

    try:
        prompt = MOOD_TAG_PROMPT.format(transcript=transcript_text[:1500])
        response = await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are a video content analyst. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=200,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        data = json.loads(raw)

        moods = [m for m in (data.get("moods") or []) if m in VALID_MOODS][:3]
        energy = data.get("energy_level", "balanced")
        if energy not in VALID_ENERGY_LEVELS:
            energy = "balanced"

        hook_type = data.get("hook_type", "other")
        target_emotion = (data.get("target_emotion") or "")[:50]

        result = {
            "moods": moods or ["entertaining"],
            "energy_level": energy,
            "hook_type": hook_type,
            "target_emotion": target_emotion,
            "optimal_hours": _get_optimal_hours(moods),
        }

        await db.update_clip(clip_id, {
            "mood_tags": json.dumps(moods),
            "energy_level": energy,
            "hook_type": hook_type,
            "target_emotion": target_emotion,
            "optimal_post_hours": json.dumps(_get_optimal_hours(moods)),
        })

        logger.info("[MoodTag] Clip %s: moods=%s energy=%s", clip_id, moods, energy)
        return result

    except Exception as exc:
        logger.warning("[MoodTag] Failed for %s: %s", clip_id, exc)
        return _default_mood_result()
