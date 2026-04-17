from typing import Any, Dict
from .base_agent import BaseAgent
from .prompts import EDIT_DECISION_SYSTEM_PROMPT


class EditDecisionAgent(BaseAgent):
    def __init__(self, llm_service=None):
        super().__init__("EditDecisionAgent", llm_service)

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        mood = context.get("mood", "inspirational")
        hook_strength = context.get("hook_strength", 5)
        transcript = context.get("transcript", "")

        user_msg = (
            f"mood: {mood}\n"
            f"hook_strength: {hook_strength}\n"
            f"transcript: {transcript}"
        )

        if self.llm_service:
            raw = await self.llm_service.complete(
                system=EDIT_DECISION_SYSTEM_PROMPT,
                user=user_msg,
            )
            return self._parse_json_response(raw)

        # Fallback defaults
        return {
            "speed_ramp_style": "cinematic" if mood == "inspirational" else "dramatic",
            "sfx_mood": mood,
            "lut": "golden_hour" if mood == "inspirational" else "teal_orange",
            "zoom_punch_at": [],
            "cut_pace": "medium",
            "text_overlay_style": "bold_center",
        }
