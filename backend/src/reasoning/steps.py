"""
Reasoning Steps - Individual steps in the reasoning pipeline.

Each step follows a specific methodology:
- OBSERVE: Extract objective facts
- ANALYZE: Identify patterns and relationships
- HYPOTHESIZE: Generate theories about outcomes
- SCORE: Quantify dimensions with evidence
- RECOMMEND: Provide actionable suggestions
"""

import logging
import json
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class ReasoningStep(ABC):
    """Base class for reasoning steps."""
    
    def __init__(self, name: str):
        self.name = name
    
    @abstractmethod
    async def execute(
        self,
        context: Any,
        state: Dict[str, Any],
        llm_client: Optional[Any]
    ) -> Dict[str, Any]:
        """
        Execute reasoning step.
        
        Returns:
            Dict with 'prompt', 'response', 'state_update', 'confidence', 'tokens_used'
        """
        pass
    
    async def _call_llm(
        self,
        prompt: str,
        llm_client: Optional[Any],
        system_prompt: str = ""
    ) -> Dict[str, Any]:
        """Call LLM with prompt and parse response."""
        if llm_client is None:
            # Fallback to rule-based if no LLM
            return {
                "response": "{}",
                "tokens_used": 0
            }
        
        try:
            # Call LLM (implementation depends on client)
            if hasattr(llm_client, 'chat'):
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})
                
                response = await llm_client.chat(messages)
                
                return {
                    "response": response.get("content", ""),
                    "tokens_used": response.get("tokens", 0)
                }
            else:
                # Simple completion API
                full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
                response = await llm_client.complete(full_prompt)
                
                return {
                    "response": response,
                    "tokens_used": 0  # Unknown
                }
                
        except Exception as e:
            logger.error(f"[{self.name}] LLM call failed: {e}")
            return {
                "response": "{}",
                "tokens_used": 0
            }


class ObserveStep(ReasoningStep):
    """
    Step 1: OBSERVE
    
    Extract objective, verifiable facts from input data.
    No interpretation, just raw observations.
    """
    
    def __init__(self):
        super().__init__("OBSERVE")
    
    async def execute(
        self,
        context: Any,
        state: Dict[str, Any],
        llm_client: Optional[Any]
    ) -> Dict[str, Any]:
        """Extract facts from input."""
        
        prompt = self._build_prompt(context)
        system_prompt = """You are an objective observer. Extract only verifiable facts from the input. 
No opinions, no interpretations, just observable data points.
Return a JSON list of observations: {"observations": ["fact1", "fact2", ...]}"""
        
        llm_result = await self._call_llm(prompt, llm_client, system_prompt)
        
        # Parse observations
        try:
            parsed = json.loads(llm_result["response"])
            observations = parsed.get("observations", [])
        except json.JSONDecodeError:
            # Fallback: treat response as single observation
            observations = [llm_result["response"]]
        
        return {
            "prompt": prompt,
            "response": llm_result["response"],
            "state_update": {"observations": observations},
            "confidence": 1.0 if observations else 0.0,
            "tokens_used": llm_result["tokens_used"],
            "summary": f"Extracted {len(observations)} observations"
        }
    
    def _build_prompt(self, context: Any) -> str:
        """Build observation prompt from context."""
        data = context.input_data
        
        prompt_parts = ["Extract objective facts from this video content:"]
        
        if "transcript" in data:
            prompt_parts.append(f"\nTranscript: {data['transcript'][:500]}")
        
        if "duration" in data:
            prompt_parts.append(f"\nDuration: {data['duration']}s")
        
        if "word_count" in data:
            prompt_parts.append(f"\nWord count: {data['word_count']}")
        
        if "audio_features" in data:
            prompt_parts.append(f"\nAudio features: {json.dumps(data['audio_features'])}")
        
        prompt_parts.append("\nList all observable facts as JSON.")
        
        return "\n".join(prompt_parts)


class AnalyzeStep(ReasoningStep):
    """
    Step 2: ANALYZE
    
    Identify patterns, relationships, and structures in observations.
    """
    
    def __init__(self):
        super().__init__("ANALYZE")
    
    async def execute(
        self,
        context: Any,
        state: Dict[str, Any],
        llm_client: Optional[Any]
    ) -> Dict[str, Any]:
        """Analyze patterns in observations."""
        
        observations = state.get("observations", [])
        
        prompt = f"""Given these observations:
{json.dumps(observations, indent=2)}

Identify patterns, relationships, and structural elements:
- Recurring themes
- Cause-effect relationships
- Temporal patterns
- Anomalies or outliers

Return JSON: {{"patterns": ["pattern1", "pattern2", ...]}}"""
        
        system_prompt = "You are a pattern analyst. Identify meaningful patterns and relationships in data."
        
        llm_result = await self._call_llm(prompt, llm_client, system_prompt)
        
        # Parse patterns
        try:
            parsed = json.loads(llm_result["response"])
            patterns = parsed.get("patterns", [])
        except json.JSONDecodeError:
            patterns = [llm_result["response"]]
        
        return {
            "prompt": prompt,
            "response": llm_result["response"],
            "state_update": {"patterns": patterns},
            "confidence": 0.8 if patterns else 0.0,
            "tokens_used": llm_result["tokens_used"],
            "summary": f"Identified {len(patterns)} patterns"
        }


class HypothesizeStep(ReasoningStep):
    """
    Step 3: HYPOTHESIZE
    
    Generate theories about outcomes based on patterns.
    """
    
    def __init__(self):
        super().__init__("HYPOTHESIZE")
    
    async def execute(
        self,
        context: Any,
        state: Dict[str, Any],
        llm_client: Optional[Any]
    ) -> Dict[str, Any]:
        """Generate hypotheses from patterns."""
        
        patterns = state.get("patterns", [])
        task_type = context.task_type
        
        prompt = f"""Based on these patterns:
{json.dumps(patterns, indent=2)}

For task type: {task_type}

Generate hypotheses about likely outcomes:
- What will happen?
- Why will it happen?
- What evidence supports this?

Return JSON: {{"hypotheses": [{{"theory": "...", "evidence": "...", "confidence": 0.0-1.0}}]}}"""
        
        system_prompt = "You are a hypothesis generator. Create testable theories based on observed patterns."
        
        llm_result = await self._call_llm(prompt, llm_client, system_prompt)
        
        # Parse hypotheses
        try:
            parsed = json.loads(llm_result["response"])
            hypotheses = parsed.get("hypotheses", [])
        except json.JSONDecodeError:
            hypotheses = [{"theory": llm_result["response"], "evidence": "", "confidence": 0.5}]
        
        return {
            "prompt": prompt,
            "response": llm_result["response"],
            "state_update": {"hypotheses": hypotheses},
            "confidence": 0.7,
            "tokens_used": llm_result["tokens_used"],
            "summary": f"Generated {len(hypotheses)} hypotheses"
        }


class ScoreStep(ReasoningStep):
    """
    Step 4: SCORE
    
    Quantify dimensions with numerical scores and evidence.
    """
    
    def __init__(self, dimensions: list):
        """
        Initialize scoring step.
        
        Args:
            dimensions: List of dimensions to score (e.g., ["hook", "pacing", "emotion"])
        """
        super().__init__("SCORE")
        self.dimensions = dimensions
    
    async def execute(
        self,
        context: Any,
        state: Dict[str, Any],
        llm_client: Optional[Any]
    ) -> Dict[str, Any]:
        """Score content across dimensions."""
        
        hypotheses = state.get("hypotheses", [])
        
        prompt = f"""Based on these hypotheses:
{json.dumps(hypotheses, indent=2)}

Score the content on these dimensions (0-100):
{json.dumps(self.dimensions)}

For each dimension, provide:
- Score (0-100)
- Evidence (why this score?)
- Confidence (0.0-1.0)

Return JSON: {{"scores": {{"dimension": {{"score": 85, "evidence": "...", "confidence": 0.9}}}}}}"""
        
        system_prompt = "You are a content scorer. Provide numerical scores with evidence."
        
        llm_result = await self._call_llm(prompt, llm_client, system_prompt)
        
        # Parse scores
        try:
            parsed = json.loads(llm_result["response"])
            scores = parsed.get("scores", {})
        except json.JSONDecodeError:
            scores = {}
        
        # Calculate average confidence
        confidences = [s.get("confidence", 0.5) for s in scores.values()]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5
        
        return {
            "prompt": prompt,
            "response": llm_result["response"],
            "state_update": {"scores": scores},
            "confidence": avg_confidence,
            "tokens_used": llm_result["tokens_used"],
            "summary": f"Scored {len(scores)} dimensions"
        }


class RecommendStep(ReasoningStep):
    """
    Step 5: RECOMMEND
    
    Provide actionable suggestions based on scores and hypotheses.
    """
    
    def __init__(self):
        super().__init__("RECOMMEND")
    
    async def execute(
        self,
        context: Any,
        state: Dict[str, Any],
        llm_client: Optional[Any]
    ) -> Dict[str, Any]:
        """Generate recommendations."""
        
        scores = state.get("scores", {})
        hypotheses = state.get("hypotheses", [])
        
        prompt = f"""Based on these scores:
{json.dumps(scores, indent=2)}

And hypotheses:
{json.dumps(hypotheses, indent=2)}

Provide actionable recommendations to improve the content:
- What should be changed?
- Why will this improvement work?
- Priority (high/medium/low)

Return JSON: {{"recommendations": [{{"action": "...", "reason": "...", "priority": "high"}}]}}"""
        
        system_prompt = "You are an optimization advisor. Provide specific, actionable recommendations."
        
        llm_result = await self._call_llm(prompt, llm_client, system_prompt)
        
        # Parse recommendations
        try:
            parsed = json.loads(llm_result["response"])
            recommendations = parsed.get("recommendations", [])
        except json.JSONDecodeError:
            recommendations = [{"action": llm_result["response"], "reason": "", "priority": "medium"}]
        
        return {
            "prompt": prompt,
            "response": llm_result["response"],
            "state_update": {"recommendations": recommendations},
            "confidence": 0.8,
            "tokens_used": llm_result["tokens_used"],
            "summary": f"Generated {len(recommendations)} recommendations"
        }
