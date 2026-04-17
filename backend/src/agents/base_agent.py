import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Base class for all ViraClip subagents."""

    def __init__(self, name: str, llm_service=None):
        self.name = name
        self.llm_service = llm_service

    @abstractmethod
    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the agent logic. Must return a dict."""
        pass

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """Parse JSON from LLM response, stripping markdown fences if present."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"[{self.name}] Failed to parse JSON: {e}\nRaw: {text}")
            return {}
