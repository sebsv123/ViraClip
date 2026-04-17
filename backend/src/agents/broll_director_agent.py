from typing import Any, Dict
from .base_agent import BaseAgent
from .prompts import BROLL_DIRECTOR_SYSTEM_PROMPT


class BrollDirectorAgent(BaseAgent):
    def __init__(self, llm_service=None):
        super().__init__("BrollDirectorAgent", llm_service)

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        transcript = context.get("transcript", "")
        duration = context.get("duration", 60)

        user_msg = f"Duration: {duration}s\nTranscript:\n{transcript}"

        if self.llm_service:
            raw = await self.llm_service.complete(
                system=BROLL_DIRECTOR_SYSTEM_PROMPT,
                user=user_msg,
            )
            return self._parse_json_response(raw)

        return {"broll_segments": [], "keywords": []}
