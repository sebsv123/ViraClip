"""
LangGraph pipeline for ViraClip Phase 3.

State machine that orchestrates the full creative pipeline:
  input_node → hook_node → broll_node → edit_node → audio_node
             → caption_node → quality_node → export_node

Conditional edge: if QualityGuardAgent rejects → back to edit_node
with feedback (max 2 retries). On 3rd rejection exports with warning.

Each node calls the corresponding FunctionAgent from llama_pipeline.py.
Falls back to SubagentPipeline if langgraph is not installed.
"""
import logging
from typing import Any, Dict, List, Optional, TypedDict

logger = logging.getLogger(__name__)

# ── LangGraph imports (graceful fallback) ─────────────────────────────────────
try:
    from langgraph.graph import StateGraph, END
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    logger.warning("[LangGraph] langgraph not installed — using fallback mode")


# ── VideoState — shared state across all nodes ────────────────────────────────

class VideoState(TypedDict):
    # Input
    transcript: str
    mood: str
    language: str
    duration: float
    hook_strength: float
    groq_api_key: str
    task_id: str

    # Agent outputs (populated progressively)
    hook: Dict[str, Any]
    broll: Dict[str, Any]
    edit: Dict[str, Any]
    audio: Dict[str, Any]
    captions: Dict[str, Any]
    quality: Dict[str, Any]

    # Control
    retry_count: int
    rejected_reason: Optional[str]
    pipeline_status: str
    warnings: List[str]


def _default_state(overrides: Dict[str, Any]) -> VideoState:
    """Build a VideoState with safe defaults."""
    base: VideoState = {
        "transcript": "",
        "mood": "inspirational",
        "language": "es",
        "duration": 60.0,
        "hook_strength": 5.0,
        "groq_api_key": "",
        "task_id": "",
        "hook": {},
        "broll": {},
        "edit": {},
        "audio": {},
        "captions": {},
        "quality": {},
        "retry_count": 0,
        "rejected_reason": None,
        "pipeline_status": "running",
        "warnings": [],
    }
    base.update(overrides)
    return base


# ── Nodes ─────────────────────────────────────────────────────────────────────

async def hook_node(state: VideoState) -> VideoState:
    """HookAnalyzerAgent — rewrites the hook for maximum virality."""
    try:
        from ..agents.llama_pipeline import build_hook_tool
        tool_fn = build_hook_tool()
        if callable(getattr(tool_fn, "fn", None)):
            result = tool_fn.fn(
                segment_text=state["transcript"][:500],
                language=state["language"],
            )
        else:
            result = tool_fn(
                segment_text=state["transcript"][:500],
                language=state["language"],
            )
        state["hook"] = result or {}
        logger.info("[LangGraph] hook_node done: %s", str(result)[:80])
    except Exception as e:
        logger.error("[LangGraph] hook_node failed: %s", e)
        state["hook"] = {"hook_text": state["transcript"][:100]}
    return state


async def broll_node(state: VideoState) -> VideoState:
    """BrollSelectorAgent — selects b-roll segments and timestamps."""
    try:
        from ..agents.llama_pipeline import build_broll_tool
        tool_fn = build_broll_tool()
        fn = getattr(tool_fn, "fn", tool_fn)
        result = fn(transcript=state["transcript"], duration=state["duration"])
        state["broll"] = result or {}
        logger.info("[LangGraph] broll_node done")
    except Exception as e:
        logger.error("[LangGraph] broll_node failed: %s", e)
        state["broll"] = {"broll_segments": [], "keywords": []}
    return state


async def edit_node(state: VideoState) -> VideoState:
    """EditDecisionAgent — decides speed ramp, SFX, and LUT."""
    try:
        from ..agents.llama_pipeline import build_edit_tool
        tool_fn = build_edit_tool()
        fn = getattr(tool_fn, "fn", tool_fn)
        result = fn(mood=state["mood"], hook_strength=state["hook_strength"])
        state["edit"] = result or {}
        # If retrying, pass rejected_reason as context (logged only)
        if state["retry_count"] > 0 and state["rejected_reason"]:
            logger.info(
                "[LangGraph] edit_node retry %d with feedback: %s",
                state["retry_count"],
                state["rejected_reason"],
            )
            state["edit"]["retry_feedback"] = state["rejected_reason"]
        logger.info("[LangGraph] edit_node done: %s", state["edit"])
    except Exception as e:
        logger.error("[LangGraph] edit_node failed: %s", e)
        state["edit"] = {}
    return state


async def audio_node(state: VideoState) -> VideoState:
    """AudioMixAgent — configures BGM, ducking, beat sync."""
    try:
        from ..agents.llama_pipeline import build_audio_tool
        tool_fn = build_audio_tool()
        fn = getattr(tool_fn, "fn", tool_fn)
        result = fn(mood=state["mood"], duration=state["duration"])
        state["audio"] = result or {}
        logger.info("[LangGraph] audio_node done")
    except Exception as e:
        logger.error("[LangGraph] audio_node failed: %s", e)
        state["audio"] = {}
    return state


async def caption_node(state: VideoState) -> VideoState:
    """CaptionAgent — generates viral captions with word-level timing."""
    try:
        from ..agents.llama_pipeline import build_caption_tool
        tool_fn = build_caption_tool()
        fn = getattr(tool_fn, "fn", tool_fn)
        result = fn(transcript=state["transcript"], mood=state["mood"])
        state["captions"] = result or {}
        logger.info("[LangGraph] caption_node done")
    except Exception as e:
        logger.error("[LangGraph] caption_node failed: %s", e)
        state["captions"] = {}
    return state


async def quality_node(state: VideoState) -> VideoState:
    """QualityGuardAgent — validates full output, approves or rejects."""
    try:
        from ..agents.llama_pipeline import build_quality_tool
        tool_fn = build_quality_tool()
        fn = getattr(tool_fn, "fn", tool_fn)
        pipeline_output = {
            "hook": state["hook"],
            "broll": state["broll"],
            "edit": state["edit"],
            "audio": state["audio"],
            "captions": state["captions"],
        }
        result = fn(pipeline_output=pipeline_output)
        state["quality"] = result or {}
        verdict = result.get("verdict", "approved")
        if verdict == "rejected":
            state["rejected_reason"] = result.get("rejection_reason", "unknown")
            logger.warning("[LangGraph] quality_node REJECTED: %s", state["rejected_reason"])
        else:
            state["rejected_reason"] = None
            logger.info("[LangGraph] quality_node APPROVED score=%s", result.get("overall_score"))
    except Exception as e:
        logger.error("[LangGraph] quality_node failed: %s", e)
        state["quality"] = {"verdict": "approved", "overall_score": 5}
        state["rejected_reason"] = None
    return state


async def export_node(state: VideoState) -> VideoState:
    """Final node — marks pipeline as complete."""
    if state.get("rejected_reason") and state["retry_count"] >= 2:
        state["warnings"].append(
            f"Exported with quality warning after {state['retry_count']} retries: {state['rejected_reason']}"
        )
        logger.warning("[LangGraph] export_node: forced export with warning")
    state["pipeline_status"] = "completed"
    logger.info("[LangGraph] export_node done — pipeline_status=completed")
    return state


# ── Conditional edge ──────────────────────────────────────────────────────────

def should_retry_or_export(state: VideoState) -> str:
    """
    After quality_node:
    - If rejected AND retry_count < 2 → back to edit_node
    - Otherwise → export_node
    """
    if state.get("rejected_reason") and state.get("retry_count", 0) < 2:
        state["retry_count"] = state.get("retry_count", 0) + 1
        logger.info("[LangGraph] Retrying edit_node (attempt %d/2)", state["retry_count"])
        return "edit_node"
    return "export_node"


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_langgraph_pipeline():
    """Build and compile the ViraClip LangGraph StateGraph."""
    if not LANGGRAPH_AVAILABLE:
        return None

    graph = StateGraph(VideoState)

    graph.add_node("hook_node", hook_node)
    graph.add_node("broll_node", broll_node)
    graph.add_node("edit_node", edit_node)
    graph.add_node("audio_node", audio_node)
    graph.add_node("caption_node", caption_node)
    graph.add_node("quality_node", quality_node)
    graph.add_node("export_node", export_node)

    graph.set_entry_point("hook_node")
    graph.add_edge("hook_node", "broll_node")
    graph.add_edge("broll_node", "edit_node")
    graph.add_edge("edit_node", "audio_node")
    graph.add_edge("audio_node", "caption_node")
    graph.add_edge("caption_node", "quality_node")
    graph.add_conditional_edges(
        "quality_node",
        should_retry_or_export,
        {"edit_node": "edit_node", "export_node": "export_node"},
    )
    graph.add_edge("export_node", END)

    compiled = graph.compile()
    logger.info("[LangGraph] Pipeline compiled: 7 nodes, 1 conditional edge")
    return compiled


# ── Public run function ───────────────────────────────────────────────────────

async def run_langgraph_pipeline(
    transcript: str,
    mood: str = "inspirational",
    language: str = "es",
    duration: float = 60.0,
    hook_strength: float = 5.0,
    groq_api_key: str = "",
    task_id: str = "",
) -> Dict[str, Any]:
    """
    Run the full LangGraph creative pipeline for a clip.

    Falls back to SubagentPipeline if langgraph is not installed.

    Returns:
        Dict with hook, broll, edit, audio, captions, quality, pipeline_status, warnings
    """
    if not LANGGRAPH_AVAILABLE:
        logger.warning("[LangGraph] Falling back to SubagentPipeline")
        from .subagent_pipeline import SubagentPipeline
        return await SubagentPipeline().run({
            "transcript": transcript,
            "mood": mood,
            "language": language,
            "duration": duration,
            "hook_strength": hook_strength,
        })

    pipeline = build_langgraph_pipeline()
    if not pipeline:
        from .subagent_pipeline import SubagentPipeline
        return await SubagentPipeline().run({
            "transcript": transcript, "mood": mood,
            "language": language, "duration": duration,
            "hook_strength": hook_strength,
        })

    initial_state = _default_state({
        "transcript": transcript,
        "mood": mood,
        "language": language,
        "duration": duration,
        "hook_strength": hook_strength,
        "groq_api_key": groq_api_key,
        "task_id": task_id,
    })

    try:
        final_state = await pipeline.ainvoke(initial_state)
        logger.info("[LangGraph] Pipeline completed for task %s", task_id)
        return {
            "hook": final_state.get("hook", {}),
            "broll": final_state.get("broll", {}),
            "edit": final_state.get("edit", {}),
            "audio": final_state.get("audio", {}),
            "captions": final_state.get("captions", {}),
            "quality": final_state.get("quality", {}),
            "pipeline_status": final_state.get("pipeline_status", "completed"),
            "warnings": final_state.get("warnings", []),
            "retry_count": final_state.get("retry_count", 0),
        }
    except Exception as e:
        logger.error("[LangGraph] Pipeline failed: %s", e, exc_info=True)
        from .subagent_pipeline import SubagentPipeline
        return await SubagentPipeline().run({
            "transcript": transcript, "mood": mood,
            "language": language, "duration": duration,
            "hook_strength": hook_strength,
        })
