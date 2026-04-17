"""
Open Interpreter API Routes — Natural Language Task Execution
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services.open_interpreter_service import get_interpreter_service

router = APIRouter(prefix="/interpret", tags=["Open Interpreter"])


class ExecuteRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)


class ParseRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)


@router.get("/info")
async def get_info() -> Dict[str, Any]:
    """Get interpreter availability, supported intents, and example prompts."""
    svc = get_interpreter_service()
    return svc.get_info()


@router.post("/execute")
async def execute_prompt(body: ExecuteRequest) -> Dict[str, Any]:
    """
    Execute a natural language prompt as a ViraClip task.

    Examples:
    - "Create 5 viral TikTok clips from https://youtube.com/watch?v=..."
    - "Analyze the virality of this transcript: [text]"
    - "Generate YouTube hashtags for my cooking tutorial"
    - "Rewrite the opening hook to be more shocking"
    - "Search for clips about ocean sunsets"
    """
    svc = get_interpreter_service()
    try:
        result = await svc.execute(body.prompt)
        return {
            "prompt": body.prompt,
            "intent": result.intent,
            "params": result.params,
            "success": result.success,
            "summary": result.human_summary,
            "result": result.result,
            "errors": result.errors,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/parse")
async def parse_prompt(body: ParseRequest) -> Dict[str, Any]:
    """
    Parse a natural language prompt without executing it.
    Returns the detected intent and extracted parameters for preview.
    """
    svc = get_interpreter_service()
    try:
        parsed = await svc.parse_only(body.prompt)
        return {
            "prompt": body.prompt,
            "intent": parsed.intent.value,
            "params": parsed.params,
            "confidence": parsed.confidence,
            "explanation": parsed.explanation,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
