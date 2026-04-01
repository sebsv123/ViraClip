"""
Virality Scoring Fine-Tuning Module
Optimizes virality scoring based on performance feedback.
"""

from typing import Dict, Any, List
import json
from pathlib import Path

class ViralityScoringTuner:
    """Fine-tunes virality scoring weights based on performance."""
    
    # Base weights for virality components
    DEFAULT_WEIGHTS = {
        "hook_score": 0.30,
        "engagement_score": 0.25,
        "value_score": 0.25,
        "shareability_score": 0.20,
    }
    
    # Performance thresholds
    VIEW_THRESHOLDS = {
        "viral": 100000,      # 100k+ views
        "high": 50000,        # 50k+ views
        "good": 10000,        # 10k+ views
        "average": 1000,      # 1k+ views
    }
    
    def __init__(self, weights_file: Path = None):
        self.weights = self.DEFAULT_WEIGHTS.copy()
        self.performance_history = []
        if weights_file and weights_file.exists():
            self.load_weights(weights_file)
    
    def load_weights(self, path: Path):
        """Load tuned weights from file."""
        with open(path) as f:
            data = json.load(f)
            self.weights = data.get("weights", self.DEFAULT_WEIGHTS)
            self.performance_history = data.get("history", [])
    
    def save_weights(self, path: Path):
        """Save current weights to file."""
        with open(path, 'w') as f:
            json.dump({
                "weights": self.weights,
                "history": self.performance_history[-100:],  # Keep last 100
            }, f, indent=2)
    
    def record_performance(self, clip_id: str, predicted_score: float, 
                          actual_views: int, completion_rate: float):
        """Record clip performance for learning."""
        tier = self._get_view_tier(actual_views)
        self.performance_history.append({
            "clip_id": clip_id,
            "predicted": predicted_score,
            "actual_views": actual_views,
            "completion_rate": completion_rate,
            "tier": tier,
        })
    
    def _get_view_tier(self, views: int) -> str:
        """Categorize performance tier."""
        for tier, threshold in sorted(self.VIEW_THRESHOLDS.items(), 
                                     key=lambda x: x[1], reverse=True):
            if views >= threshold:
                return tier
        return "low"
    
    def tune_weights(self) -> Dict[str, float]:
        """Optimize weights based on performance history."""
        if len(self.performance_history) < 10:
            return self.weights
        
        # Find high performers and analyze their patterns
        viral_clips = [p for p in self.performance_history 
                      if p["tier"] in ["viral", "high"]]
        
        if len(viral_clips) < 5:
            return self.weights
        
        # Adjust weights based on patterns
        # (Simplified - full implementation would use ML optimization)
        avg_completion = sum(p["completion_rate"] for p in viral_clips) / len(viral_clips)
        
        # Boost engagement weight if completion rates are high
        if avg_completion > 0.7:
            self.weights["engagement_score"] = min(0.35, self.weights["engagement_score"] + 0.02)
        
        # Boost hook weight for viral hits
        viral_with_strong_hooks = sum(1 for p in viral_clips if p["predicted"] > 25)
        if viral_with_strong_hooks / len(viral_clips) > 0.6:
            self.weights["hook_score"] = min(0.40, self.weights["hook_score"] + 0.02)
        
        # Normalize to ensure sum = 1.0
        total = sum(self.weights.values())
        self.weights = {k: v/total for k, v in self.weights.items()}
        
        return self.weights
    
    def calculate_virality_score(self, hook: float, engagement: float, 
                                value: float, shareability: float) -> float:
        """Calculate weighted virality score."""
        return (
            hook * self.weights["hook_score"] +
            engagement * self.weights["engagement_score"] +
            value * self.weights["value_score"] +
            shareability * self.weights["shareability_score"]
        ) * 10  # Scale to 0-40 range


# Global tuner instance
_tuner = None

def get_tuner(weights_file: Path = None) -> ViralityScoringTuner:
    """Get global tuner instance."""
    global _tuner
    if _tuner is None:
        _tuner = ViralityScoringTuner(weights_file)
    return _tuner
