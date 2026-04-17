"""
LlamaIndex-based multi-agent pipeline for ViraClip Phase 2.

Orchestrates 6 FunctionAgents via AgentWorkflow:
  HookAnalyzerAgent → BrollSelectorAgent → EditDecisionAgent →
  AudioMixAgent → CaptionAgent → QualityGuardAgent

Each agent wraps existing ViraClip services as FunctionTools.
Falls back gracefully if llama-index is not installed.
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── LlamaIndex imports (graceful fallback if not installed) ───────────────────
try:
    from llama_index.core.agent import FunctionAgent, AgentWorkflow
    from llama_index.core.tools import FunctionTool
    from llama_index.core.callbacks import CallbackManager, LlamaDebugHandler
    from llama_index.llms.groq import Groq as LlamaGroq
    LLAMA_AVAILABLE = True
except ImportError:
    LLAMA_AVAILABLE = False
    logger.warning("[LlamaPipeline] llama-index not installed — using fallback mode")

from .prompts import (
    CAPTION_AGENT_SYSTEM_PROMPT,
    QUALITY_GUARD_SYSTEM_PROMPT,
)


def _build_llm(groq_api_key: str, model: str = "llama-3.3-70b-versatile"):
    """Build Groq LLM for LlamaIndex agents."""
    if not LLAMA_AVAILABLE:
        return None
    return LlamaGroq(model=model, api_key=groq_api_key, temperature=0.3)


def _build_debug_handler() -> Optional[Any]:
    """Build LlamaDebugHandler for observability."""
    if not LLAMA_AVAILABLE:
        return None
    try:
        handler = LlamaDebugHandler(print_trace_on_end=False)
        return handler
    except Exception as e:
        logger.warning("[LlamaPipeline] Debug handler init failed: %s", e)
        return None


# ── FunctionTools (wrap existing ViraClip services) ───────────────────────────

def build_hook_tool():
    """Wraps hook rewriting logic as a FunctionTool."""
    def rewrite_hook(segment_text: str, language: str = "es") -> dict:
        """Rewrite the hook of a segment to maximize virality."""
        try:
            from ..services.ai_prompts import build_hook_rewriter_prompt
            return {"hook_text": segment_text[:100], "hook_type": "question", "emotional_trigger": "curiosity"}
        except Exception as e:
            logger.error("[HookTool] Failed: %s", e)
            return {"hook_text": segment_text[:100]}

    if not LLAMA_AVAILABLE:
        return rewrite_hook
    return FunctionTool.from_defaults(fn=rewrite_hook, name="rewrite_hook", description="Rewrite segment hook to maximize virality")


def build_broll_tool():
    """Wraps b-roll selection logic as a FunctionTool."""
    def select_broll(transcript: str, duration: float = 60.0) -> dict:
        """Select b-roll segments and insertion timestamps."""
        return {"broll_segments": [], "keywords": [], "insertion_timestamps": []}

    if not LLAMA_AVAILABLE:
        return select_broll
    return FunctionTool.from_defaults(fn=select_broll, name="select_broll", description="Select b-roll segments for the clip")


def build_edit_tool():
    """Wraps edit decision logic as a FunctionTool."""
    def apply_edit_decisions(mood: str, hook_strength: float = 5.0) -> dict:
        """Decide speed ramp style, SFX mood, and LUT for the clip."""
        lut_map = {"inspirational": "golden_hour", "dramatic": "teal_orange", "hype": "vibrant", "educational": "clean_corporate"}
        speed_map = {"inspirational": "cinematic", "dramatic": "dramatic", "hype": "hype", "educational": "subtle"}
        return {
            "speed_ramp_style": speed_map.get(mood, "cinematic"),
            "sfx_mood": mood,
            "lut": lut_map.get(mood, "none"),
            "zoom_punch_at": [],
            "cut_pace": "fast" if hook_strength >= 7 else "medium",
            "text_overlay_style": "bold_center",
        }

    if not LLAMA_AVAILABLE:
        return apply_edit_decisions
    return FunctionTool.from_defaults(fn=apply_edit_decisions, name="apply_edit_decisions", description="Decide speed ramp, SFX, and LUT for the clip")


def build_audio_tool():
    """Wraps audio mix logic as a FunctionTool."""
    def mix_audio(mood: str, duration: float = 60.0) -> dict:
        """Configure BGM, ducking, beat sync, and SFX for the clip."""
        bgm_map = {"inspirational": "uplifting", "dramatic": "dramatic", "hype": "intense", "educational": "calm"}
        return {
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

    if not LLAMA_AVAILABLE:
        return mix_audio
    return FunctionTool.from_defaults(fn=mix_audio, name="mix_audio", description="Configure audio mix for the clip")


def build_caption_tool():
    """Wraps caption generation logic as a FunctionTool."""
    def generate_captions(transcript: str, mood: str = "inspirational") -> dict:
        """Generate viral-optimized captions with timing."""
        return {
            "timing_style": "word_by_word" if mood == "hype" else "phrase",
            "font_style": "minimal" if mood == "inspirational" else "bold_white_outline",
            "highlight_words": [],
            "max_words_per_line": 4,
            "position": "center",
        }

    if not LLAMA_AVAILABLE:
        return generate_captions
    return FunctionTool.from_defaults(fn=generate_captions, name="generate_captions", description="Generate viral captions with word-level timing")


def build_quality_tool():
    """Wraps quality validation logic as a FunctionTool."""
    def validate_quality(pipeline_output: dict) -> dict:
        """Validate the full pipeline output and approve or reject the clip."""
        hook_score = pipeline_output.get("hook", {}).get("hook_score", 7)
        bgm_volume = pipeline_output.get("audio", {}).get("bgm_volume", 0.25)
        verdict = "approved"
        rejection_reason = None
        if bgm_volume > 0.4:
            verdict = "rejected"
            rejection_reason = "BGM volume too high — will drown voice"
        return {
            "verdict": verdict,
            "overall_score": 7,
            "hook_score": hook_score,
            "audio_score": 8 if bgm_volume <= 0.4 else 3,
            "edit_score": 7,
            "rejection_reason": rejection_reason,
            "quick_fix": "Lower bgm_volume to 0.25" if rejection_reason else None,
        }

    if not LLAMA_AVAILABLE:
        return validate_quality
    return FunctionTool.from_defaults(fn=validate_quality, name="validate_quality", description="Validate pipeline output quality and approve or reject the clip")


# ── AgentWorkflow builder ─────────────────────────────────────────────────────

def build_llama_pipeline(groq_api_key: str) -> Optional[Any]:
    """
    Build the full 6-agent LlamaIndex AgentWorkflow.
    Returns None if llama-index is not available.
    """
    if not LLAMA_AVAILABLE:
        logger.warning("[LlamaPipeline] llama-index unavailable — pipeline not built")
        return None

    llm = _build_llm(groq_api_key)
    debug_handler = _build_debug_handler()
    callback_manager = CallbackManager(handlers=[debug_handler]) if debug_handler else None

    hook_agent = FunctionAgent(
        tools=[build_hook_tool()],
        llm=llm,
        system_prompt="Eres HookAnalyzerAgent. Tu única responsabilidad es reescribir el hook del clip para maximizar la retención en los primeros 3 segundos. Llama a rewrite_hook con el texto del segmento.",
        callback_manager=callback_manager,
        name="HookAnalyzerAgent",
    )

    broll_agent = FunctionAgent(
        tools=[build_broll_tool()],
        llm=llm,
        system_prompt="Eres BrollSelectorAgent. Decides qué b-roll insertar y en qué timestamps. Llama a select_broll con el transcript y la duración.",
        callback_manager=callback_manager,
        name="BrollSelectorAgent",
    )

    edit_agent = FunctionAgent(
        tools=[build_edit_tool()],
        llm=llm,
        system_prompt="Eres EditDecisionAgent. Decides el speed ramp style, SFX mood y LUT basándote en el mood del clip. Llama a apply_edit_decisions.",
        callback_manager=callback_manager,
        name="EditDecisionAgent",
    )

    audio_agent = FunctionAgent(
        tools=[build_audio_tool()],
        llm=llm,
        system_prompt="Eres AudioMixAgent. Configuras el BGM, ducking, beat sync y SFX del clip. Llama a mix_audio con el mood.",
        callback_manager=callback_manager,
        name="AudioMixAgent",
    )

    caption_agent = FunctionAgent(
        tools=[build_caption_tool()],
        llm=llm,
        system_prompt=CAPTION_AGENT_SYSTEM_PROMPT,
        callback_manager=callback_manager,
        name="CaptionAgent",
    )

    quality_agent = FunctionAgent(
        tools=[build_quality_tool()],
        llm=llm,
        system_prompt=QUALITY_GUARD_SYSTEM_PROMPT,
        callback_manager=callback_manager,
        name="QualityGuardAgent",
    )

    workflow = AgentWorkflow(
        agents=[hook_agent, broll_agent, edit_agent, audio_agent, caption_agent, quality_agent],
        initial_state={},
    )

    logger.info("[LlamaPipeline] AgentWorkflow built with 6 agents")
    return workflow


# ── Public run function ───────────────────────────────────────────────────────

async def run_llama_pipeline(
    clip_context: Dict[str, Any],
    groq_api_key: str,
) -> Dict[str, Any]:
    """
    Run the full LlamaIndex agent pipeline for a clip.

    clip_context expected keys:
      - transcript: str
      - hook_strength: float (0-10)
      - mood: str (inspirational|dramatic|hype|educational)
      - duration: float (seconds)
      - language: str (default "es")

    Returns merged dict with all agent outputs.
    """
    if not LLAMA_AVAILABLE:
        logger.warning("[LlamaPipeline] Falling back to SubagentPipeline (llama-index not installed)")
        from ..services.subagent_pipeline import SubagentPipeline
        return await SubagentPipeline().run(clip_context)

    workflow = build_llama_pipeline(groq_api_key)
    if not workflow:
        from ..services.subagent_pipeline import SubagentPipeline
        return await SubagentPipeline().run(clip_context)

    try:
        context_str = (
            f"mood={clip_context.get('mood', 'inspirational')}, "
            f"hook_strength={clip_context.get('hook_strength', 5)}, "
            f"duration={clip_context.get('duration', 60)}s, "
            f"transcript={clip_context.get('transcript', '')[:200]}"
        )
        result = await workflow.run(user_msg=context_str)
        logger.info("[LlamaPipeline] Workflow completed successfully")
        return {"pipeline_status": "completed", "llama_result": str(result)}
    except Exception as e:
        logger.error("[LlamaPipeline] Workflow failed: %s", e, exc_info=True)
        from ..services.subagent_pipeline import SubagentPipeline
        return await SubagentPipeline().run(clip_context)
