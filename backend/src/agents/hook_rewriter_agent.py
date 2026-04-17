from typing import Any, Dict
from .base_agent import BaseAgent
from .prompts import HOOK_REWRITER_SYSTEM_PROMPT


class HookRewriterAgent(BaseAgent):
    def __init__(self, llm_service=None):
        super().__init__("HookRewriterAgent", llm_service)

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        transcript = context.get("transcript", "")
        hook_strength = context.get("hook_strength", 5)

        user_msg = f"Hook strength: {hook_strength}/10\nTranscript:\n{transcript}"

        if self.llm_service:
            raw = await self.llm_service.complete(
                system=HOOK_REWRITER_SYSTEM_PROMPT,
                user=user_msg,
            )
            return self._parse_json_response(raw)

        # Fallback stub
        return {
            "rewritten_hook": transcript[:100],
            "hook_type": "question",
            "emotional_trigger": "curiosity",
        }
