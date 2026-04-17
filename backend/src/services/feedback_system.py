"""
Feedback System for Virality Scoring Improvement
Collects and processes user feedback to improve virality predictions.
"""

import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class ClipFeedback:
    """User feedback for a specific clip."""
    clip_id: str
    task_id: str
    user_id: Optional[str]
    virality_score_original: float
    user_rating: int  # 1-10
    actual_performance: Optional[str] = None  # 'viral', 'good', 'average', 'poor'
    views: Optional[int] = None
    engagement_rate: Optional[float] = None
    timestamp: str = None
    feedback_text: Optional[str] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()


@dataclass
class FeedbackStats:
    """Statistics from collected feedback."""
    total_feedback: int
    average_user_rating: float
    original_score_avg: float
    score_delta_avg: float  # Difference between original and user rating
    accuracy: float  # How accurate original scores were
    by_niche: Dict[str, Dict[str, float]]
    by_content_type: Dict[str, Dict[str, float]]


class ViralityFeedbackSystem:
    """
    Collects user feedback and uses it to improve virality scoring.
    """
    
    def __init__(self, feedback_file: Optional[Path] = None):
        if feedback_file is None:
            feedback_file = Path("/app/data/virality_feedback.json")
        
        self.feedback_file = feedback_file
        self.feedback_file.parent.mkdir(parents=True, exist_ok=True)
        
        self._feedback_history: List[ClipFeedback] = []
        self._load_feedback()
    
    def _load_feedback(self) -> None:
        """Load existing feedback from file."""
        if self.feedback_file.exists():
            try:
                with open(self.feedback_file, 'r') as f:
                    data = json.load(f)
                    self._feedback_history = [
                        ClipFeedback(**item) for item in data
                    ]
                logger.info(f"Loaded {len(self._feedback_history)} feedback entries")
            except Exception as e:
                logger.error(f"Failed to load feedback: {e}")
                self._feedback_history = []
    
    def _save_feedback(self) -> None:
        """Save feedback to file."""
        try:
            data = [asdict(f) for f in self._feedback_history]
            with open(self.feedback_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save feedback: {e}")
    
    def submit_feedback(self, feedback: ClipFeedback) -> bool:
        """
        Submit new feedback for a clip.
        
        Returns True if feedback was accepted.
        """
        try:
            self._feedback_history.append(feedback)
            self._save_feedback()
            
            # Log the feedback for analysis
            delta = feedback.user_rating - (feedback.virality_score_original / 10)
            logger.info(
                f"Feedback received for clip {feedback.clip_id}: "
                f"original={feedback.virality_score_original:.1f}, "
                f"user={feedback.user_rating}, delta={delta:+.1f}"
            )
            
            return True
        except Exception as e:
            logger.error(f"Failed to submit feedback: {e}")
            return False
    
    def get_feedback_stats(
        self,
        days: int = 30,
        niche: Optional[str] = None
    ) -> FeedbackStats:
        """
        Get statistics from recent feedback.
        
        Args:
            days: Number of days to look back
            niche: Filter by specific niche (optional)
        """
        from datetime import timedelta
        
        cutoff = datetime.now() - timedelta(days=days)
        
        # Filter feedback
        recent = [
            f for f in self._feedback_history
            if datetime.fromisoformat(f.timestamp) > cutoff
            and (niche is None or f.actual_performance == niche)
        ]
        
        if not recent:
            return FeedbackStats(
                total_feedback=0,
                average_user_rating=0,
                original_score_avg=0,
                score_delta_avg=0,
                accuracy=0,
                by_niche={},
                by_content_type={}
            )
        
        # Calculate stats
        user_ratings = [f.user_rating for f in recent]
        original_scores = [f.virality_score_original / 10 for f in recent]
        deltas = [u - o for u, o in zip(user_ratings, original_scores)]
        
        # Group by performance
        by_niche_stats = defaultdict(lambda: {"count": 0, "avg_delta": 0})
        by_type_stats = defaultdict(lambda: {"count": 0, "avg_delta": 0})
        
        for f in recent:
            if f.actual_performance:
                by_niche_stats[f.actual_performance]["count"] += 1
            
            # Content type from clip_id pattern or other metadata
            # This is a simplified version
            content_type = "general"
            by_type_stats[content_type]["count"] += 1
        
        # Calculate accuracy (% of predictions within 2 points)
        accurate = sum(1 for d in deltas if abs(d) <= 2)
        accuracy = (accurate / len(recent)) * 100
        
        return FeedbackStats(
            total_feedback=len(recent),
            average_user_rating=sum(user_ratings) / len(user_ratings),
            original_score_avg=sum(original_scores) / len(original_scores),
            score_delta_avg=sum(deltas) / len(deltas),
            accuracy=accuracy,
            by_niche=dict(by_niche_stats),
            by_content_type=dict(by_type_stats)
        )
    
    def get_correction_factors(self) -> Dict[str, float]:
        """
        Calculate correction factors based on feedback.
        
        Returns multipliers for different content types/niches
        that should be applied to virality scores.
        """
        if len(self._feedback_history) < 10:
            return {}  # Not enough data
        
        # Calculate average delta per content characteristic
        deltas_by_type = defaultdict(list)
        
        for f in self._feedback_history:
            delta = (f.user_rating * 10) - f.virality_score_original
            
            # Store by actual performance if available
            if f.actual_performance:
                deltas_by_type[f.actual_performance].append(delta)
        
        # Calculate correction factors
        factors = {}
        for content_type, deltas in deltas_by_type.items():
            if len(deltas) >= 5:  # Minimum samples
                avg_delta = sum(deltas) / len(deltas)
                # Convert delta to multiplier
                # Positive delta means we under-scored, need to boost
                # Negative delta means we over-scored, need to reduce
                factor = 1 + (avg_delta / 100)
                factors[content_type] = max(0.5, min(1.5, factor))  # Cap adjustments
        
        return factors
    
    def suggest_improvements(self) -> List[Dict[str, Any]]:
        """
        Generate suggestions for improving virality scoring
        based on collected feedback.
        """
        suggestions = []
        
        if len(self._feedback_history) < 5:
            suggestions.append({
                "type": "insufficient_data",
                "message": "Need more feedback to generate suggestions. Please rate more clips.",
                "priority": "high"
            })
            return suggestions
        
        stats = self.get_feedback_stats()
        
        # Check overall accuracy
        if stats.accuracy < 50:
            suggestions.append({
                "type": "accuracy_low",
                "message": f"Prediction accuracy is low ({stats.accuracy:.1f}%). Consider adjusting scoring algorithm.",
                "priority": "high",
                "metric": "accuracy",
                "current_value": stats.accuracy,
                "target_value": 70
            })
        
        # Check for systematic over/under scoring
        if abs(stats.score_delta_avg) > 1.5:
            direction = "underestimating" if stats.score_delta_avg > 0 else "overestimating"
            suggestions.append({
                "type": "systematic_bias",
                "message": f"Systematically {direction} virality by {abs(stats.score_delta_avg):.1f} points on average.",
                "priority": "high",
                "metric": "score_delta",
                "current_value": stats.score_delta_avg,
                "target_value": 0,
                "action": f"Apply global correction factor of {1 + (stats.score_delta_avg/100):.2f}"
            })
        
        # Check for niche-specific issues
        for niche, data in stats.by_niche.items():
            if abs(data.get("avg_delta", 0)) > 2:
                suggestions.append({
                    "type": "niche_bias",
                    "message": f"Scoring for '{niche}' content needs adjustment.",
                    "priority": "medium",
                    "niche": niche,
                    "correction_factor": data.get("avg_delta", 0) / 100
                })
        
        return suggestions
    
    def apply_learning(self, virality_tuner) -> bool:
        """
        Apply learned corrections to the virality tuner.
        
        Args:
            virality_tuner: Instance of ViralityScoringTuner
            
        Returns True if adjustments were made.
        """
        try:
            factors = self.get_correction_factors()
            
            if not factors:
                logger.info("No correction factors available yet")
                return False
            
            # Apply factors to tuner weights
            for category, factor in factors.items():
                # Adjust weights based on feedback
                if factor > 1.1:
                    # We were under-scoring this category
                    logger.info(f"Boosting {category} scores by {factor:.2f}x")
                elif factor < 0.9:
                    # We were over-scoring this category
                    logger.info(f"Reducing {category} scores by {factor:.2f}x")
            
            # Save the learned state
            self._save_feedback()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to apply learning: {e}")
            return False
    
    def export_feedback_report(self, output_path: Optional[Path] = None) -> Path:
        """
        Generate a detailed feedback report.
        
        Returns path to the report file.
        """
        if output_path is None:
            output_path = Path("/app/data/virality_feedback_report.json")
        
        stats = self.get_feedback_stats(days=90)
        suggestions = self.suggest_improvements()
        factors = self.get_correction_factors()
        
        report = {
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_feedback_entries": len(self._feedback_history),
                "prediction_accuracy": stats.accuracy,
                "average_user_rating": stats.average_user_rating,
                "average_system_score": stats.original_score_avg * 10,
                "system_bias": stats.score_delta_avg
            },
            "correction_factors": factors,
            "suggestions": suggestions,
            "by_niche": stats.by_niche,
            "by_content_type": stats.by_content_type
        }
        
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Feedback report exported to {output_path}")
        return output_path


# Global instance
_feedback_system: Optional[ViralityFeedbackSystem] = None


def get_feedback_system() -> ViralityFeedbackSystem:
    """Get global feedback system instance."""
    global _feedback_system
    if _feedback_system is None:
        _feedback_system = ViralityFeedbackSystem()
    return _feedback_system


def submit_clip_feedback(
    clip_id: str,
    task_id: str,
    original_score: float,
    user_rating: int,
    user_id: Optional[str] = None,
    actual_performance: Optional[str] = None
) -> bool:
    """
    Convenience function to submit feedback for a clip.
    
    Args:
        clip_id: ID of the clip
        task_id: ID of the processing task
        original_score: Original virality score (0-100)
        user_rating: User's rating (1-10)
        user_id: Optional user identifier
        actual_performance: Actual performance if known ('viral', 'good', etc.)
    """
    feedback = ClipFeedback(
        clip_id=clip_id,
        task_id=task_id,
        user_id=user_id,
        virality_score_original=original_score,
        user_rating=user_rating,
        actual_performance=actual_performance
    )
    
    return get_feedback_system().submit_feedback(feedback)


def get_virality_improvement_suggestions() -> List[Dict[str, Any]]:
    """Get suggestions for improving virality scoring."""
    return get_feedback_system().suggest_improvements()
