from typing import Any, Dict
from .base_agent import BaseAgent
from .prompts import QUALITY_JUDGE_SYSTEM_PROMPT


class QualityJudgeAgent(BaseAgent):
    def __init__(self, llm_service=None):
        super().__init__("QualityJudgeAgent", llm_service)

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        pipeline_output = context.get("pipeline_output", {})
        user_msg = f"Pipeline output to evaluate:\n{pipeline_output}"

        if self.llm_service:
            raw = await self.llm_service.complete(
                system=QUALITY_JUDGE_SYSTEM_PROMPT,
                user=user_msg,
            )
            return self._parse_json_response(raw)

        return {"approved": True, "score": 7, "feedback": ""}
