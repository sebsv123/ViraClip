"""
Reasoning Engine - Core orchestration for structured reasoning.

Manages the 5-step reasoning pipeline and tracks reasoning traces.
"""

import logging
import json
import os
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ReasoningContext:
    """Input context for reasoning pipeline."""
    task_type: str  # "virality", "hook", "segment"
    input_data: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReasoningStep:
    """Single step in reasoning chain."""
    step_name: str
    step_number: int
    prompt: str
    response: str
    timestamp: float
    tokens_used: int = 0
    confidence: float = 0.0


@dataclass
class ReasoningResult:
    """Complete reasoning output with trace."""
    task_type: str
    conclusion: Dict[str, Any]
    reasoning_trace: List[ReasoningStep]
    total_steps: int
    total_tokens: int
    duration_seconds: float
    success: bool
    error: Optional[str] = None


class ReasoningEngine:
    """
    Orchestrates structured reasoning pipeline.
    
    Pipeline:
    1. OBSERVE - Extract facts
    2. ANALYZE - Find patterns
    3. HYPOTHESIZE - Generate theories
    4. SCORE - Quantify dimensions
    5. RECOMMEND - Actionable suggestions
    """
    
    def __init__(self, llm_client=None, save_traces: bool = None):
        """
        Initialize reasoning engine.
        
        Args:
            llm_client: LLM client for generating responses
            save_traces: Save reasoning traces to disk (defaults to env var)
        """
        self.llm_client = llm_client
        
        # Trace saving configuration
        if save_traces is None:
            save_traces = os.getenv("SAVE_REASONING_TRACES", "false").lower() == "true"
        self.save_traces = save_traces
        
        self.trace_dir = Path(os.getenv("REASONING_TRACE_DIR", "/app/data/reasoning_traces"))
        if self.save_traces:
            self.trace_dir.mkdir(parents=True, exist_ok=True)
        
        # Reasoning steps logging
        self.verbose = os.getenv("REASONING_STEPS_LOGGING", "false").lower() == "true"
        
    async def execute_pipeline(
        self,
        context: ReasoningContext,
        steps: List[Any]  # List of step classes
    ) -> ReasoningResult:
        """
        Execute full reasoning pipeline.
        
        Args:
            context: Input context
            steps: List of reasoning step instances
            
        Returns:
            ReasoningResult with conclusion and trace
        """
        start_time = datetime.now()
        reasoning_trace: List[ReasoningStep] = []
        total_tokens = 0
        
        # State accumulator
        state = {
            "observations": [],
            "patterns": [],
            "hypotheses": [],
            "scores": {},
            "recommendations": []
        }
        
        try:
            # Execute each step sequentially
            for idx, step in enumerate(steps, 1):
                if self.verbose:
                    logger.info(f"[Reasoning] Step {idx}/{len(steps)}: {step.name}")
                
                # Execute step
                step_result = await step.execute(context, state, self.llm_client)
                
                # Create trace entry
                trace_entry = ReasoningStep(
                    step_name=step.name,
                    step_number=idx,
                    prompt=step_result.get("prompt", ""),
                    response=step_result.get("response", ""),
                    timestamp=datetime.now().timestamp(),
                    tokens_used=step_result.get("tokens_used", 0),
                    confidence=step_result.get("confidence", 0.0)
                )
                
                reasoning_trace.append(trace_entry)
                total_tokens += trace_entry.tokens_used
                
                # Update state with step output
                state.update(step_result.get("state_update", {}))
                
                if self.verbose:
                    logger.debug(f"[Reasoning] {step.name} output: {step_result.get('summary', 'N/A')}")
            
            # Build final conclusion
            conclusion = self._build_conclusion(state)
            
            # Calculate duration
            duration = (datetime.now() - start_time).total_seconds()
            
            # Create result
            result = ReasoningResult(
                task_type=context.task_type,
                conclusion=conclusion,
                reasoning_trace=reasoning_trace,
                total_steps=len(reasoning_trace),
                total_tokens=total_tokens,
                duration_seconds=duration,
                success=True
            )
            
            # Save trace if enabled
            if self.save_traces:
                self._save_trace(result, context)
            
            return result
            
        except Exception as e:
            logger.error(f"[Reasoning] Pipeline failed: {e}")
            
            duration = (datetime.now() - start_time).total_seconds()
            
            return ReasoningResult(
                task_type=context.task_type,
                conclusion={},
                reasoning_trace=reasoning_trace,
                total_steps=len(reasoning_trace),
                total_tokens=total_tokens,
                duration_seconds=duration,
                success=False,
                error=str(e)
            )
    
    def _build_conclusion(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Build final conclusion from accumulated state."""
        return {
            "observations": state.get("observations", []),
            "key_patterns": state.get("patterns", []),
            "hypotheses": state.get("hypotheses", []),
            "scores": state.get("scores", {}),
            "recommendations": state.get("recommendations", []),
            "reasoning_mode": "structured_cot"
        }
    
    def _save_trace(self, result: ReasoningResult, context: ReasoningContext):
        """Save reasoning trace to disk for debugging."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{result.task_type}_{timestamp}.json"
            filepath = self.trace_dir / filename
            
            trace_data = {
                "context": asdict(context),
                "result": {
                    "task_type": result.task_type,
                    "conclusion": result.conclusion,
                    "total_steps": result.total_steps,
                    "total_tokens": result.total_tokens,
                    "duration_seconds": result.duration_seconds,
                    "success": result.success,
                    "error": result.error
                },
                "reasoning_trace": [asdict(step) for step in result.reasoning_trace]
            }
            
            with open(filepath, 'w') as f:
                json.dump(trace_data, f, indent=2)
            
            logger.debug(f"[Reasoning] Trace saved: {filepath}")
            
        except Exception as e:
            logger.warning(f"[Reasoning] Failed to save trace: {e}")


# Singleton instance
_reasoning_engine: Optional[ReasoningEngine] = None


def get_reasoning_engine(llm_client=None) -> ReasoningEngine:
    """Get or create singleton reasoning engine."""
    global _reasoning_engine
    if _reasoning_engine is None:
        _reasoning_engine = ReasoningEngine(llm_client=llm_client)
    return _reasoning_engine
