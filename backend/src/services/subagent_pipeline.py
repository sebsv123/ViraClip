"""
Subagent Pipeline — Sequential enrichment of scored segments.

Called from coordinator.py between Phase 2.5 and Phase 3.
Orchestrates Hook Detector, Hook Rewriter, and Quality Judge subagents.
"""
import logging
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)


async def enrich_segments_with_subagents(
    segments: List[Dict[str, Any]],
    transcript: str,
    language: str,
    groq_api_key: str,
    num_clips: int = 3,
) -> List[Dict[str, Any]]:
    """
    Enrich segments with 3 subagent passes in sequence.

    Steps:
      1. Hook Detector — identifies viral hooks in each segment
      2. Hook Rewriter — generates optimized hook variants
      3. Quality Judge — filters out rejected segments

    Args:
        segments: Scored segments from _score_segments
        transcript: Full video transcript (context)
        language: Video language code
        groq_api_key: API key for Groq LLM
        num_clips: Target number of clips (for reference)

    Returns:
        Enriched and filtered segments list
    """
    if not segments:
        return []

    _GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
    _headers = {"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"}

    # ─────────────────────────────────────────────────────────────────────────
    # PASO 1: Hook Detector (Subagent 3)
    # ─────────────────────────────────────────────────────────────────────────
    logger.info("[Subagent] Paso 1/3: Hook Detector para %d segments", len(segments))

    try:
        from .ai_prompts import HOOK_DETECTOR_SYSTEM_PROMPT, build_hook_detection_prompt

        async with httpx.AsyncClient(timeout=60) as client:
            for seg_idx, segment in enumerate(segments):
                try:
                    response = await client.post(
                        _GROQ_URL,
                        headers=_headers,
                        json={
                            "model": "llama-3.3-70b-versatile",
                            "messages": [
                                {"role": "system", "content": HOOK_DETECTOR_SYSTEM_PROMPT},
                                {
                                    "role": "user",
                                    "content": build_hook_detection_prompt(
                                        transcript=segment.get("text", ""),
                                        language=language,
                                    ),
                                },
                            ],
                            "temperature": 0.3,
                            "response_format": {"type": "json_object"},
                        },
                    )
                    response.raise_for_status()
                    result = response.json()
                    raw = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                    import json

                    parsed = json.loads(raw)
                    segment["hooks"] = parsed.get("hooks", [])
                    logger.debug("[HookDetector] Segment %d: %d hooks found", seg_idx, len(segment["hooks"]))
                except Exception as e:
                    logger.debug("[HookDetector] Segment %d skipped: %s", seg_idx, e)
                    segment["hooks"] = []
    except Exception as e:
        logger.warning("[HookDetector] Step failed: %s", e)
        for seg in segments:
            seg["hooks"] = []

    # ─────────────────────────────────────────────────────────────────────────
    # PASO 2: Hook Rewriter (Subagent 4)
    # ─────────────────────────────────────────────────────────────────────────
    logger.info("[Subagent] Paso 2/3: Hook Rewriter para %d segments", len(segments))

    try:
        from .ai_prompts import HOOK_REWRITER_SYSTEM_PROMPT, build_hook_rewriter_prompt

        async with httpx.AsyncClient(timeout=60) as client:
            for seg_idx, segment in enumerate(segments):
                try:
                    response = await client.post(
                        _GROQ_URL,
                        headers=_headers,
                        json={
                            "model": "llama-3.3-70b-versatile",
                            "messages": [
                                {"role": "system", "content": HOOK_REWRITER_SYSTEM_PROMPT},
                                {
                                    "role": "user",
                                    "content": build_hook_rewriter_prompt(
                                        segment_text=segment.get("text", ""),
                                        language=language,
                                    ),
                                },
                            ],
                            "temperature": 0.7,
                            "response_format": {"type": "json_object"},
                        },
                    )
                    response.raise_for_status()
                    result = response.json()
                    raw = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                    import json

                    parsed = json.loads(raw)
                    segment["hook_text"] = parsed.get("best", "")
                    segment["hook_variants"] = parsed.get("hooks", [])
                    logger.debug(
                        "[HookRewriter] Segment %d: best hook '%s...'",
                        seg_idx,
                        segment["hook_text"][:30],
                    )
                except Exception as e:
                    logger.debug("[HookRewriter] Segment %d skipped: %s", seg_idx, e)
                    segment["hook_text"] = segment.get("title", "")[:60]
                    segment["hook_variants"] = []
    except Exception as e:
        logger.warning("[HookRewriter] Step failed: %s", e)
        for seg in segments:
            if "hook_text" not in seg:
                seg["hook_text"] = seg.get("title", "")[:60]
            if "hook_variants" not in seg:
                seg["hook_variants"] = []

    # ─────────────────────────────────────────────────────────────────────────
    # PASO 3: Quality Judge (Subagent 6)
    # ─────────────────────────────────────────────────────────────────────────
    logger.info("[Subagent] Paso 3/3: Quality Judge para %d segments", len(segments))

    rejected_count = 0
    try:
        from .ai_prompts import QUALITY_JUDGE_SYSTEM_PROMPT, build_quality_judge_prompt

        async with httpx.AsyncClient(timeout=60) as client:
            for seg_idx, segment in enumerate(segments):
                try:
                    response = await client.post(
                        _GROQ_URL,
                        headers=_headers,
                        json={
                            "model": "llama-3.3-70b-versatile",
                            "messages": [
                                {"role": "system", "content": QUALITY_JUDGE_SYSTEM_PROMPT},
                                {
                                    "role": "user",
                                    "content": build_quality_judge_prompt(
                                        clip_transcript=segment.get("text", ""),
                                        hook_used=segment.get("hook_text", ""),
                                        language=language,
                                    ),
                                },
                            ],
                            "temperature": 0.2,
                            "response_format": {"type": "json_object"},
                        },
                    )
                    response.raise_for_status()
                    result = response.json()
                    raw = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                    import json

                    parsed = json.loads(raw)
                    segment["quality_verdict"] = parsed.get("verdict", "approved")
                    segment["quality_score"] = parsed.get("overall", 0)
                    segment["quality_top_issue"] = parsed.get("top_issue", "")
                    segment["quality_quick_fix"] = parsed.get("quick_fix", "")
                    if segment["quality_verdict"] == "rejected":
                        rejected_count += 1
                        logger.warning(
                            "[QualityJudge] Segment %d REJECTED: %s",
                            seg_idx,
                            segment["quality_top_issue"],
                        )
                    else:
                        logger.debug("[QualityJudge] Segment %d approved", seg_idx)
                except Exception as e:
                    logger.debug("[QualityJudge] Segment %d skipped: %s", seg_idx, e)
                    segment["quality_verdict"] = "approved"
                    segment["quality_score"] = 0
                    segment["quality_top_issue"] = ""
                    segment["quality_quick_fix"] = ""
    except Exception as e:
        logger.warning("[QualityJudge] Step failed: %s", e)
        for seg in segments:
            seg["quality_verdict"] = "approved"
            seg["quality_score"] = 0
            seg["quality_top_issue"] = ""
            seg["quality_quick_fix"] = ""

    # ─────────────────────────────────────────────────────────────────────────
    # FILTRADO: Eliminar segments rechazados (si no todos son rechazados)
    # ─────────────────────────────────────────────────────────────────────────
    filtered = [s for s in segments if s.get("quality_verdict") != "rejected"]
    if filtered and len(filtered) < len(segments):
        logger.info(
            "[Subagent] Filtrado: %d segments rechazados, quedan %d",
            len(segments) - len(filtered),
            len(filtered),
        )
        return filtered
    elif not filtered:
        logger.warning("[Subagent] Todos los segments fueron rechazados, devolviendo lista original")
        return segments
    else:
        logger.info("[Subagent] Todos los segments aprobados (%d)", len(segments))

    return segments
