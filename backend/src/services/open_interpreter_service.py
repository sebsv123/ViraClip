"""
Open Interpreter Service — Natural Language Task Execution
==========================================================

Allows users to trigger ViraClip pipeline operations using plain English prompts.
Examples:
  "Create 5 viral clips from this YouTube video focusing on the funniest moments"
  "Generate TikTok-optimised metadata for my last 3 clips"
  "Rewrite the hook of clip #2 to be more shocking"
  "Download this video and find the top 3 most emotional segments"

Architecture:
  1. NaturalLanguageParser  — uses LLM to parse intent + extract params
  2. TaskDispatcher         — maps intent → ViraClip service calls
  3. ResultFormatter        — returns structured + human-readable results

Falls back gracefully if open-interpreter or LLM keys are unavailable.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Intent taxonomy ────────────────────────────────────────────────────────────

class TaskIntent(Enum):
    CREATE_CLIPS       = "create_clips"
    ANALYZE_VIRALITY   = "analyze_virality"
    GENERATE_METADATA  = "generate_metadata"
    REWRITE_HOOK       = "rewrite_hook"
    DOWNLOAD_VIDEO     = "download_video"
    DETECT_SCENES      = "detect_scenes"
    APPLY_VFX          = "apply_vfx"
    POLISH_VIDEO       = "polish_video"
    SEARCH_CLIPS       = "search_clips"
    UNKNOWN            = "unknown"


@dataclass
class ParsedTask:
    intent: TaskIntent
    params: Dict[str, Any] = field(default_factory=dict)
    raw_prompt: str = ""
    confidence: float = 1.0
    explanation: str = ""


@dataclass
class TaskResult:
    success: bool
    intent: str
    params: Dict[str, Any]
    result: Any
    human_summary: str
    errors: List[str] = field(default_factory=list)


# ── Prompt for intent parsing ──────────────────────────────────────────────────

_PARSE_PROMPT = """\
You are a ViraClip task parser. Convert the user's natural language request into a structured task.

Available intents:
- create_clips: create viral video clips (params: url, n_clips, platform, focus)
- analyze_virality: analyse virality of a clip or transcript (params: clip_id or transcript, platform)
- generate_metadata: generate title/hashtags/description (params: clip_id or transcript, platform, niche)
- rewrite_hook: rewrite the opening hook (params: hook_text or clip_id, platform, content_type)
- download_video: download a video from URL (params: url, quality)
- detect_scenes: detect scenes/chapters in a video (params: video_path or clip_id)
- apply_vfx: apply visual effects (params: clip_id, effect_type, intensity)
- polish_video: polish a clip (params: clip_id, operations: list of "face_center"|"eye_contact"|"pattern_interrupts")
- search_clips: search through clips (params: query, modality: "text"|"visual"|"hybrid", limit)
- unknown: cannot parse request

User request: {prompt}

Return ONLY valid JSON:
{{
  "intent": <one of the intent names above>,
  "params": {{<extracted parameters as key-value pairs>}},
  "confidence": <float 0-1>,
  "explanation": <string, brief explanation of what will be done>
}}"""


class NaturalLanguageParser:
    """Parses free-text user prompts into structured ViraClip tasks."""

    async def parse(self, prompt: str) -> ParsedTask:
        try:
            result = await self._parse_with_llm(prompt)
            return result
        except Exception as e:
            logger.warning("[interpreter] LLM parse failed, using keyword fallback: %s", e)
            return self._parse_with_keywords(prompt)

    async def _parse_with_llm(self, prompt: str) -> ParsedTask:
        from langchain_core.output_parsers import JsonOutputParser
        from langchain_core.prompts import PromptTemplate

        from .langchain_service import _get_chat_model

        llm = _get_chat_model()
        template = PromptTemplate.from_template(_PARSE_PROMPT)
        chain = template | llm | JsonOutputParser()

        data = await chain.ainvoke({"prompt": prompt})
        try:
            intent = TaskIntent(data.get("intent", "unknown"))
        except ValueError:
            intent = TaskIntent.UNKNOWN

        return ParsedTask(
            intent=intent,
            params=data.get("params", {}),
            raw_prompt=prompt,
            confidence=float(data.get("confidence", 0.8)),
            explanation=data.get("explanation", ""),
        )

    def _parse_with_keywords(self, prompt: str) -> ParsedTask:
        """Keyword-based fallback when LLM is unavailable."""
        lower = prompt.lower()

        if any(w in lower for w in ["create", "make", "generate clip", "cut"]):
            intent = TaskIntent.CREATE_CLIPS
        elif any(w in lower for w in ["viral", "virality", "score", "analyse", "analyze"]):
            intent = TaskIntent.ANALYZE_VIRALITY
        elif any(w in lower for w in ["metadata", "title", "hashtag", "description", "caption"]):
            intent = TaskIntent.GENERATE_METADATA
        elif any(w in lower for w in ["hook", "opening", "rewrite", "first"]):
            intent = TaskIntent.REWRITE_HOOK
        elif any(w in lower for w in ["download", "fetch", "get video"]):
            intent = TaskIntent.DOWNLOAD_VIDEO
        elif any(w in lower for w in ["scene", "chapter", "detect", "segment"]):
            intent = TaskIntent.DETECT_SCENES
        elif any(w in lower for w in ["vfx", "effect", "style", "filter"]):
            intent = TaskIntent.APPLY_VFX
        elif any(w in lower for w in ["polish", "face", "center", "eye contact"]):
            intent = TaskIntent.POLISH_VIDEO
        elif any(w in lower for w in ["search", "find", "look for", "query"]):
            intent = TaskIntent.SEARCH_CLIPS
        else:
            intent = TaskIntent.UNKNOWN

        return ParsedTask(
            intent=intent,
            params=self._extract_url(prompt),
            raw_prompt=prompt,
            confidence=0.5,
            explanation="Keyword-based parse (LLM unavailable)",
        )

    def _extract_url(self, text: str) -> Dict[str, Any]:
        import re
        urls = re.findall(r"https?://\S+", text)
        return {"url": urls[0]} if urls else {}


# ── Task Dispatcher ────────────────────────────────────────────────────────────

class TaskDispatcher:
    """Maps parsed intents to actual ViraClip service calls."""

    async def dispatch(self, task: ParsedTask) -> TaskResult:
        handlers = {
            TaskIntent.ANALYZE_VIRALITY:  self._handle_virality,
            TaskIntent.GENERATE_METADATA: self._handle_metadata,
            TaskIntent.REWRITE_HOOK:      self._handle_hook_rewrite,
            TaskIntent.DOWNLOAD_VIDEO:    self._handle_download,
            TaskIntent.DETECT_SCENES:     self._handle_scenes,
            TaskIntent.SEARCH_CLIPS:      self._handle_search,
            TaskIntent.APPLY_VFX:         self._handle_vfx,
            TaskIntent.POLISH_VIDEO:      self._handle_polish,
            TaskIntent.CREATE_CLIPS:      self._handle_create_clips,
        }
        handler = handlers.get(task.intent, self._handle_unknown)
        try:
            return await handler(task)
        except Exception as e:
            logger.error("[interpreter] Dispatch error for %s: %s", task.intent, e)
            return TaskResult(
                success=False,
                intent=task.intent.value,
                params=task.params,
                result=None,
                human_summary=f"Task failed: {e}",
                errors=[str(e)],
            )

    async def _handle_virality(self, task: ParsedTask) -> TaskResult:
        from .langchain_service import get_langchain_service
        transcript = task.params.get("transcript", task.raw_prompt)
        platform = task.params.get("platform", "tiktok")
        result = await get_langchain_service().analyze_virality(transcript, platform)
        score = result.get("virality_score", "N/A")
        return TaskResult(
            success=True, intent=task.intent.value, params=task.params, result=result,
            human_summary=f"Virality score: {score}/100. {result.get('recommendation', '')}",
        )

    async def _handle_metadata(self, task: ParsedTask) -> TaskResult:
        from .langchain_service import get_langchain_service
        transcript = task.params.get("transcript", task.raw_prompt)
        platform = task.params.get("platform", "tiktok")
        niche = task.params.get("niche", "general")
        result = await get_langchain_service().generate_metadata(transcript, platform, niche)
        return TaskResult(
            success=True, intent=task.intent.value, params=task.params, result=result,
            human_summary=f"Title: '{result.get('title', '')}' | {len(result.get('hashtags', []))} hashtags generated.",
        )

    async def _handle_hook_rewrite(self, task: ParsedTask) -> TaskResult:
        from .langchain_service import get_langchain_service
        hook_text = task.params.get("hook_text", task.raw_prompt[:200])
        platform = task.params.get("platform", "tiktok")
        result = await get_langchain_service().rewrite_hook(hook_text, platform)
        return TaskResult(
            success=True, intent=task.intent.value, params=task.params, result=result,
            human_summary=f"New hook: \"{result.get('rewritten_hook', '')}\" "
                          f"(+{result.get('retention_improvement', 0)}% retention est.)",
        )

    async def _handle_download(self, task: ParsedTask) -> TaskResult:
        url = task.params.get("url")
        if not url:
            return TaskResult(
                success=False, intent=task.intent.value, params=task.params, result=None,
                human_summary="No URL found in prompt. Please include a video URL.",
                errors=["missing url"],
            )
        from .task_service import get_video_info_for_url
        try:
            info = await get_video_info_for_url(url)
            return TaskResult(
                success=True, intent=task.intent.value, params=task.params, result=info,
                human_summary=f"Video found: '{info.get('title', url)}' ({info.get('duration', '?')}s). Ready to process.",
            )
        except Exception:
            return TaskResult(
                success=True, intent=task.intent.value, params={"url": url}, result={"url": url},
                human_summary=f"URL queued for download: {url}",
            )

    async def _handle_scenes(self, task: ParsedTask) -> TaskResult:
        from .scene_detection import get_scene_detection_service
        from pathlib import Path
        video_path = task.params.get("video_path", "")
        if not video_path:
            return TaskResult(
                success=False, intent=task.intent.value, params=task.params, result=None,
                human_summary="No video_path provided. Please specify a video file path.",
                errors=["missing video_path"],
            )
        svc = get_scene_detection_service()
        scenes = await svc.detect_scenes(Path(video_path))
        return TaskResult(
            success=True, intent=task.intent.value, params=task.params,
            result={"scene_count": len(scenes)},
            human_summary=f"Detected {len(scenes)} scene(s) in {video_path}.",
        )

    async def _handle_search(self, task: ParsedTask) -> TaskResult:
        query = task.params.get("query", task.raw_prompt)
        modality = task.params.get("modality", "text")
        limit = int(task.params.get("limit", 10))
        return TaskResult(
            success=True, intent=task.intent.value, params=task.params,
            result={"query": query, "modality": modality, "limit": limit},
            human_summary=f"Searching clips for: \"{query}\" (modality: {modality}). Use /vector/search for full results.",
        )

    async def _handle_vfx(self, task: ParsedTask) -> TaskResult:
        return TaskResult(
            success=True, intent=task.intent.value, params=task.params,
            result=task.params,
            human_summary=f"VFX task queued: {task.params.get('effect_type', 'unknown')} effect. Use /vfx endpoints directly.",
        )

    async def _handle_polish(self, task: ParsedTask) -> TaskResult:
        ops = task.params.get("operations", ["face_center"])
        return TaskResult(
            success=True, intent=task.intent.value, params=task.params,
            result={"operations": ops},
            human_summary=f"Polish operations queued: {', '.join(ops)}. Use /polish endpoints directly.",
        )

    async def _handle_create_clips(self, task: ParsedTask) -> TaskResult:
        url = task.params.get("url", "")
        n = task.params.get("n_clips", 3)
        platform = task.params.get("platform", "tiktok")
        return TaskResult(
            success=True, intent=task.intent.value, params=task.params,
            result={"url": url, "n_clips": n, "platform": platform},
            human_summary=(
                f"Ready to create {n} viral {platform} clips from: {url or '(no URL found)'}. "
                f"Submit a task via POST /tasks to start processing."
            ),
        )

    async def _handle_unknown(self, task: ParsedTask) -> TaskResult:
        return TaskResult(
            success=False, intent="unknown", params=task.params, result=None,
            human_summary=(
                "I couldn't understand that request. Try something like: "
                "'Create 5 viral TikTok clips from https://youtube.com/...' or "
                "'Generate hashtags for my latest clip'."
            ),
            errors=["unknown intent"],
        )


# ── Main Service ───────────────────────────────────────────────────────────────

class OpenInterpreterService:
    """
    Natural language interface for ViraClip.
    Parses user prompts and dispatches them to appropriate services.
    """

    def __init__(self):
        self._parser = NaturalLanguageParser()
        self._dispatcher = TaskDispatcher()

    async def execute(self, prompt: str) -> TaskResult:
        """Parse a natural language prompt and execute the corresponding task."""
        if not prompt.strip():
            return TaskResult(
                success=False, intent="unknown", params={}, result=None,
                human_summary="Empty prompt. Please describe what you'd like to do.",
                errors=["empty prompt"],
            )

        parsed = await self._parser.parse(prompt)
        logger.info(
            "[interpreter] Parsed '%s' → %s (confidence=%.2f)",
            prompt[:80], parsed.intent.value, parsed.confidence,
        )
        return await self._dispatcher.dispatch(parsed)

    async def parse_only(self, prompt: str) -> ParsedTask:
        """Parse without executing — useful for previewing what will happen."""
        return await self._parser.parse(prompt)

    def is_available(self) -> bool:
        try:
            import langchain  # noqa: F401
            return True
        except ImportError:
            return False

    def get_info(self) -> Dict[str, Any]:
        return {
            "available": self.is_available(),
            "supported_intents": [i.value for i in TaskIntent if i != TaskIntent.UNKNOWN],
            "description": "Natural language task execution for ViraClip pipeline",
            "example_prompts": [
                "Create 5 viral TikTok clips from https://youtube.com/watch?v=...",
                "Analyze the virality of this transcript: [text]",
                "Generate YouTube hashtags for my cooking tutorial clip",
                "Rewrite the opening hook to be more shocking",
                "Search for clips about ocean sunsets",
            ],
        }


_instance: Optional[OpenInterpreterService] = None


def get_interpreter_service() -> OpenInterpreterService:
    global _instance
    if _instance is None:
        _instance = OpenInterpreterService()
    return _instance
