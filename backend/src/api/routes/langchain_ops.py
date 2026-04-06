"""
LangChain Operations API Routes
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services.langchain_service import get_langchain_service

router = APIRouter(prefix="/langchain", tags=["LangChain AI"])

# In-memory chat sessions (keyed by session_id)
_sessions: Dict[str, Any] = {}


class ViralityRequest(BaseModel):
    transcript: str = Field(..., min_length=1)
    platform: str = Field("tiktok", pattern="^(tiktok|reels|youtube_shorts|twitter|linkedin)$")
    duration: float = Field(30.0, gt=0, le=600)


class MetadataRequest(BaseModel):
    transcript: str = Field(..., min_length=1)
    platform: str = Field("tiktok", pattern="^(tiktok|reels|youtube_shorts|twitter|linkedin)$")
    niche: str = Field("general", min_length=1)


class HookRewriteRequest(BaseModel):
    hook_text: str = Field(..., min_length=1, max_length=500)
    platform: str = Field("tiktok", pattern="^(tiktok|reels|youtube_shorts|twitter|linkedin)$")
    content_type: str = Field("talking_head", pattern="^(talking_head|tutorial|reaction|vlog|explainer)$")


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)


class NewSessionRequest(BaseModel):
    session_id: str = Field(..., min_length=1)


@router.get("/info")
async def get_info() -> Dict[str, Any]:
    """Get LangChain service availability and configured providers."""
    svc = get_langchain_service()
    return svc.get_info()


@router.post("/analyze/virality")
async def analyze_virality(body: ViralityRequest) -> Dict[str, Any]:
    """Analyze transcript virality using a LangChain structured output chain."""
    svc = get_langchain_service()
    try:
        result = await svc.analyze_virality(
            transcript=body.transcript,
            platform=body.platform,
            duration=body.duration,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate/metadata")
async def generate_metadata(body: MetadataRequest) -> Dict[str, Any]:
    """Generate viral metadata (title, description, hashtags, CTA) via LangChain."""
    svc = get_langchain_service()
    try:
        result = await svc.generate_metadata(
            transcript=body.transcript,
            platform=body.platform,
            niche=body.niche,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rewrite/hook")
async def rewrite_hook(body: HookRewriteRequest) -> Dict[str, Any]:
    """Rewrite a video hook for maximum retention using LangChain."""
    svc = get_langchain_service()
    try:
        result = await svc.rewrite_hook(
            hook_text=body.hook_text,
            platform=body.platform,
            content_type=body.content_type,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/session")
async def create_chat_session(body: NewSessionRequest) -> Dict[str, Any]:
    """Create a new multi-turn chat session with ViraClip AI."""
    svc = get_langchain_service()
    session = svc.new_chat_session()
    _sessions[body.session_id] = session
    return {"session_id": body.session_id, "created": True}


@router.post("/chat/message")
async def send_chat_message(body: ChatRequest) -> Dict[str, Any]:
    """Send a message in a chat session and get an AI response."""
    session = _sessions.get(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {body.session_id!r} not found. Create it first.")
    try:
        reply = await session.chat(body.message)
        return {
            "session_id": body.session_id,
            "message": body.message,
            "reply": reply,
            "turn": len(session.get_history()),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat/session/{session_id}/history")
async def get_chat_history(session_id: str) -> Dict[str, Any]:
    """Get full conversation history for a chat session."""
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return {"session_id": session_id, "history": session.get_history()}


@router.delete("/chat/session/{session_id}")
async def delete_chat_session(session_id: str) -> Dict[str, Any]:
    """Delete a chat session and clear its history."""
    if session_id in _sessions:
        del _sessions[session_id]
        return {"session_id": session_id, "deleted": True}
    raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
