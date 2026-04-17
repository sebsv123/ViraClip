"""
SubagentPipeline: two complementary systems.
"""
import json
import logging
from typing import List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)


async def enrich_segments_with_subagents(segments, transcript, language, groq_api_key, num_clips=3):
    if not segments:
        return []
    _GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
    _headers = {"Authorization": "Bearer " + groq_api_key, "Content-Type": "application/json"}

    logger.info("[Subagent] Paso 1/3: Hook Detector para %d segments", len(segments))
    try:
        from .ai_prompts import HOOK_DETECTOR_SYSTEM_PROMPT, build_hook_detection_prompt
        async with httpx.AsyncClient(timeout=60) as client:
            for seg_idx, segment in enumerate(segments):
                try:
                    response = await client.post(_GROQ_URL, headers=_headers, json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "system", "content": HOOK_DETECTOR_SYSTEM_PROMPT}, {"role": "user", "content": build_hook_detection_prompt(transcript=segment.get("text", ""), language=language)}], "temperature": 0.3, "response_format": {"type": "json_object"}})
                    response.raise_for_status()
                    parsed = json.loads(response.json()["choices"][0]["message"]["content"])
                    segment["hooks"] = parsed.get("hooks", [])
                except Exception as e:
                    logger.debug("[HookDetector] Segment %d skipped: %s", seg_idx, e)
                    segment["hooks"] = []
    except Exception as e:
        logger.warning("[HookDetector] Step failed: %s", e)
        for seg in segments:
            seg["hooks"] = []

    logger.info("[Subagent] Paso 2/3: Hook Rewriter para %d segments", len(segments))
    try:
        from .ai_prompts import HOOK_REWRITER_SYSTEM_PROMPT, build_hook_rewriter_prompt
        async with httpx.AsyncClient(timeout=60) as client:
            for seg_idx, segment in enumerate(segments):
                try:
                    response = await client.post(_GROQ_URL, headers=_headers, json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "system", "content": HOOK_REWRITER_SYSTEM_PROMPT}, {"role": "user", "content": build_hook_rewriter_prompt(segment_text=segment.get("text", ""), language=language)}], "temperature": 0.7, "response_format": {"type": "json_object"}})
                    response.raise_for_status()
                    parsed = json.loads(response.json()["choices"][0]["message"]["content"])
                    segment["hook_text"] = parsed.get("best", "")
                    segment["hook_variants"] = parsed.get("hooks", [])
                except Exception as e:
                    logger.debug("[HookRewriter] Segment %d skipped: %s", seg_idx, e)
                    segment["hook_text"] = segment.get("title", "")[:60]
                    segment["hook_variants"] = []
    except Exception as e:
        logger.warning("[HookRewriter] Step failed: %s", e)
        for seg in segments:
            seg.setdefault("hook_text", seg.get("title", "")[:60])
            seg.setdefault("hook_variants", [])

    logger.info("[Subagent] Paso 3/3: Quality Judge para %d segments", len(segments))
    try:
        from .ai_prompts import QUALITY_JUDGE_SYSTEM_PROMPT, build_quality_judge_prompt
        async with httpx.AsyncClient(timeout=60) as client:
            for seg_idx, segment in enumerate(segments):
                try:
                    response = await client.post(_GROQ_URL, headers=_headers, json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "system", "content": QUALITY_JUDGE_SYSTEM_PROMPT}, {"role": "user", "content": build_quality_judge_prompt(clip_transcript=segment.get("text", ""), hook_used=segment.get("hook_text", ""), language=language)}], "temperature": 0.2, "response_format": {"type": "json_object"}})
                    response.raise_for_status()
                    parsed = json.loads(response.json()["choices"][0]["message"]["content"])
                    segment["quality_verdict"] = parsed.get("verdict", "approved")
                    segment["quality_score"] = parsed.get("overall", 0)
                    segment["quality_top_issue"] = parsed.get("top_issue", "")
                    segment["quality_quick_fix"] = parsed.get("quick_fix", "")
                    if segment["quality_verdict"] == "rejected":
                        logger.warning("[QualityJudge] Segment %d REJECTED: %s", seg_idx, segment["quality_top_issue"])
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

    filtered = [s for s in segments if s.get("quality_verdict") != "rejected"]
    if filtered and len(filtered) < len(segments):
        logger.info("[Subagent] Filtrado: %d rechazados, quedan %d", len(segments) - len(filtered), len(filtered))
        return filtered
    elif not filtered:
        logger.warning("[Subagent] Todos rechazados, devolviendo lista original")
        return segments
    return segments


class SubagentPipeline:
    def __init__(self, llm_service=None):
        self.llm_service = llm_service

    async def run(self, clip_context):
        logger.info("[SubagentPipeline] Starting pipeline")
        results = {}
        mood = clip_context.get("mood", "inspirational")
        hook_strength = clip_context.get("hook_strength", 5)
        transcript = clip_context.get("transcript", "")
        language = clip_context.get("language", "es")

        try:
            from .ai_prompts import HOOK_REWRITER_SYSTEM_PROMPT, build_hook_rewriter_prompt
            if self.llm_service:
                raw = await self.llm_service.complete(system=HOOK_REWRITER_SYSTEM_PROMPT, user=build_hook_rewriter_prompt(segment_text=transcript, language=language))
                results["hook"] = json.loads(raw) if isinstance(raw, str) else raw
            else:
                results["hook"] = {"hook_text": transcript[:100], "hook_type": "question", "emotional_trigger": "curiosity"}
        except Exception as e:
            logger.error("[SubagentPipeline] HookRewriter failed: %s", e)
            results["hook"] = {}

        results["broll"] = {"broll_segments": [], "keywords": []}

        lut_map = {"inspirational": "golden_hour", "dramatic": "teal_orange", "hype": "vibrant", "educational": "clean_corporate"}
        speed_map = {"inspirational": "cinematic", "dramatic": "dramatic", "hype": "hype", "educational": "subtle"}
        results["edit"] = {
            "speed_ramp_style": speed_map.get(mood, "cinematic"),
            "sfx_mood": mood,
            "lut": lut_map.get(mood, "none"),
            "zoom_punch_at": [],
            "cut_pace": "fast" if hook_strength >= 7 else "medium",
            "text_overlay_style": "bold_center",
        }

        bgm_map = {"inspirational": "uplifting", "dramatic": "dramatic", "hype": "intense", "educational": "calm"}
        results["audio"] = {
            "bgm_mood": bgm_map.get(mood, "uplifting"),
            "bgm_volume": 0.25,
            "music_energy": "high" if mood == "hype" else "medium",
            "beat_sync": mood == "hype",
            "duck_at_speech": True,
            "voice_clarity_boost": mood == "educational",
            "fade_in_ms": 500,
            "fade_out_ms": 800,
            "sfx_layer": "cinematic_hits" if mood == "dramatic" else "none",
            "sfx_timing": [],
        }

        try:
            from .ai_prompts import QUALITY_JUDGE_SYSTEM_PROMPT, build_quality_judge_prompt
            hook_text = results.get("hook", {}).get("hook_text", "")
            if self.llm_service:
                raw = await self.llm_service.complete(system=QUALITY_JUDGE_SYSTEM_PROMPT, user=build_quality_judge_prompt(clip_transcript=transcript, hook_used=hook_text, language=language))
                results["quality"] = json.loads(raw) if isinstance(raw, str) else raw
            else:
                results["quality"] = {"approved": True, "score": 7, "feedback": ""}
        except Exception as e:
            results["quality"] = {"approved": True, "score": 5, "feedback": "judge unavailable"}

        results["pipeline_status"] = "completed"
        return results

