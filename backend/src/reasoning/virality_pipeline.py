"""
Virality Reasoning Pipeline

Structured Chain-of-Thought reasoning for viral content analysis.
Replaces monolithic prompts with transparent 5-step pipeline.
"""

import logging
from typing import Dict, Any
from .engine import ReasoningEngine, ReasoningContext, ReasoningResult
from .steps import ObserveStep, AnalyzeStep, HypothesizeStep, ScoreStep, RecommendStep

logger = logging.getLogger(__name__)


# Viral content dimensions
VIRALITY_DIMENSIONS = [
    "pattern_interrupt",  # First 3 seconds hook
    "curiosity_gap",      # Unanswered questions
    "emotional_spike",    # Peak emotion intensity
    "shareability",       # "Send to friend" factor
    "loop_potential"      # Re-watch value
]


class ViralityReasoningPipeline:
    """
    5-step reasoning pipeline for virality scoring.
    
    Transparent alternative to monolithic prompts in phi3_virality_service.
    """
    
    def __init__(self, llm_client=None):
        self.engine = ReasoningEngine(llm_client=llm_client)
        self.llm_client = llm_client
    
    async def analyze_virality(
        self,
        transcript: str,
        duration: float,
        audio_features: Dict[str, Any] = None,
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Analyze content virality with structured reasoning.
        
        Args:
            transcript: Video transcript text
            duration: Video duration in seconds
            audio_features: Optional audio features (tempo, energy)
            metadata: Additional metadata
            
        Returns:
            Dict with scores, reasoning trace, and recommendations
        """
        # Prepare context
        context = ReasoningContext(
            task_type="virality",
            input_data={
                "transcript": transcript,
                "duration": duration,
                "word_count": len(transcript.split()),
                "audio_features": audio_features or {},
            },
            metadata=metadata or {}
        )
        
        # Build pipeline steps
        steps = [
            ObserveStep(),
            AnalyzeStep(),
            HypothesizeStep(),
            ScoreStep(dimensions=VIRALITY_DIMENSIONS),
            RecommendStep()
        ]
        
        # Execute pipeline
        result = await self.engine.execute_pipeline(context, steps)
        
        if not result.success:
            logger.error(f"Virality reasoning failed: {result.error}")
            return self._fallback_virality_score()
        
        # Extract scores
        scores = result.conclusion.get("scores", {})
        
        # Calculate total score (average of dimensions)
        dimension_scores = [
            scores.get(dim, {}).get("score", 50)
            for dim in VIRALITY_DIMENSIONS
        ]
        total_score = sum(dimension_scores) / len(dimension_scores) if dimension_scores else 50
        
        # Determine primary hook type (highest scoring dimension)
        primary_hook = max(
            VIRALITY_DIMENSIONS,
            key=lambda d: scores.get(d, {}).get("score", 0)
        )
        
        # Build response
        return {
            "pattern_interrupt": scores.get("pattern_interrupt", {}).get("score", 50),
            "curiosity_gap": scores.get("curiosity_gap", {}).get("score", 50),
            "emotional_spike": scores.get("emotional_spike", {}).get("score", 50),
            "shareability": scores.get("shareability", {}).get("score", 50),
            "loop_potential": scores.get("loop_potential", {}).get("score", 50),
            "total_score": int(total_score),
            "primary_hook_type": primary_hook,
            "scroll_stop_probability": total_score / 100.0,
            "recommended_duration": self._recommend_duration(duration, total_score),
            "edit_suggestions": self._extract_edit_suggestions(result.conclusion),
            "hashtag_themes": self._extract_hashtag_themes(result.conclusion),
            "reasoning_trace": [
                {
                    "step": step.step_name,
                    "summary": step.response[:200] if step.response else ""
                }
                for step in result.reasoning_trace
            ],
            "reasoning_mode": "structured_cot",
            "total_tokens": result.total_tokens
        }
    
    def _fallback_virality_score(self) -> Dict[str, Any]:
        """Fallback scores if reasoning fails."""
        return {
            "pattern_interrupt": 50,
            "curiosity_gap": 50,
            "emotional_spike": 50,
            "shareability": 50,
            "loop_potential": 50,
            "total_score": 50,
            "primary_hook_type": "emotional_spike",
            "scroll_stop_probability": 0.5,
            "recommended_duration": "15-25s",
            "edit_suggestions": ["fast_zoom", "caption_bounce"],
            "hashtag_themes": ["#viral", "#fyp"],
            "reasoning_mode": "fallback",
            "total_tokens": 0
        }
    
    def _recommend_duration(self, actual_duration: float, score: int) -> str:
        """Recommend optimal duration based on score."""
        if score >= 80:
            return "15-30s"  # High viral potential, keep it punchy
        elif score >= 60:
            return "20-40s"  # Medium potential, standard duration
        else:
            return "10-20s"  # Low potential, make it shorter
    
    def _extract_edit_suggestions(self, conclusion: Dict[str, Any]) -> list:
        """Extract edit suggestions from recommendations."""
        recommendations = conclusion.get("recommendations", [])
        
        suggestions = []
        for rec in recommendations:
            action = rec.get("action", "")
            
            # Map recommendations to edit tags
            if "zoom" in action.lower() or "punch" in action.lower():
                suggestions.append("fast_zoom")
            if "caption" in action.lower() or "text" in action.lower():
                suggestions.append("caption_bounce")
            if "cut" in action.lower() or "trim" in action.lower():
                suggestions.append("quick_cuts")
            if "transition" in action.lower():
                suggestions.append("smooth_transition")
        
        # Default suggestions if none found
        if not suggestions:
            suggestions = ["fast_zoom", "caption_bounce"]
        
        return suggestions[:3]  # Limit to top 3
    
    def _extract_hashtag_themes(self, conclusion: Dict[str, Any]) -> list:
        """Extract hashtag themes from patterns."""
        patterns = conclusion.get("key_patterns", [])
        
        themes = []
        for pattern in patterns:
            pattern_lower = pattern.lower() if isinstance(pattern, str) else ""
            
            # Map patterns to hashtag themes
            if "emotion" in pattern_lower:
                themes.append("#emotion")
            if "story" in pattern_lower or "narrative" in pattern_lower:
                themes.append("#storytime")
            if "motivat" in pattern_lower or "inspir" in pattern_lower:
                themes.append("#motivation")
            if "funny" in pattern_lower or "humor" in pattern_lower:
                themes.append("#comedy")
            if "teach" in pattern_lower or "educat" in pattern_lower:
                themes.append("#educational")
        
        # Default themes
        if not themes:
            themes = ["#viral", "#fyp"]
        
        return themes[:3]  # Limit to top 3


# Singleton instance
_virality_pipeline = None


def get_virality_pipeline(llm_client=None):
    """Get or create singleton virality pipeline."""
    global _virality_pipeline
    if _virality_pipeline is None:
        _virality_pipeline = ViralityReasoningPipeline(llm_client=llm_client)
    return _virality_pipeline
