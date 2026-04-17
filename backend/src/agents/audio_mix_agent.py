from typing import Any, Dict
from .base_agent import BaseAgent
from .prompts import AUDIO_MIX_SYSTEM_PROMPT


class AudioMixAgent(BaseAgent):
    def __init__(self, llm_service=None):
        super().__init__("AudioMixAgent", llm_service)

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        mood = context.get("mood", "inspirational")
        duration = context.get("duration", 60)

        user_msg = f"mood: {mood}\nduration: {duration}s"

        if self.llm_service:
            raw = await self.llm_service.complete(
                system=AUDIO_MIX_SYSTEM_PROMPT,
                user=user_msg,
            )
            return self._parse_json_response(raw)

        return {
            "bgm_mood": "uplifting",
            "bgm_volume": 0.25,
            "music_energy": "medium",
            "beat_sync": False,
            "duck_at_speech": True,
            "voice_clarity_boost": False,
            "fade_in_ms": 500,
            "fade_out_ms": 800,
            "sfx_layer": "none",
            "sfx_timing": [],
        }
