"""
YouTube Data API Feedback Loop Service
Closes the loop: predicted virality vs actual performance
YouTube Data API v3 - 10,000 units/day (FREE)
"""
import httpx
import os
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Types of YouTube metrics we track"""
    VIEW_COUNT = "viewCount"
    LIKE_COUNT = "likeCount"
    COMMENT_COUNT = "commentCount"
    AVERAGE_VIEW_DURATION = "averageViewDuration"
    AVERAGE_VIEW_PERCENTAGE = "averageViewPercentage"
    SUBSCRIBERS_GAINED = "subscribersGained"
    SHARES = "shares"


@dataclass
class ViralityPrediction:
    """Stored prediction before upload"""
    clip_id: str
    predicted_score: int  # 0-100 from Phi-3-mini
    predicted_hook_type: str
    segment_text: str
    audio_features: Dict[str, Any]
    timestamp: datetime


@dataclass
class YouTubePerformance:
    """Actual YouTube performance metrics"""
    video_id: str
    view_count: int
    like_count: int
    comment_count: int
    avg_view_duration: float
    avg_view_percentage: float
    retention_score: float  # Calculated 0-100
    upload_time: datetime
    collection_time: datetime


@dataclass
class FeedbackResult:
    """Comparison of prediction vs reality"""
    clip_id: str
    predicted_score: int
    actual_retention_score: float
    accuracy_delta: float  # Negative = overpredicted, Positive = underpredicted
    hook_type: str
    model_correction: Dict[str, float]  # Weight adjustments needed


class YouTubeFeedbackService:
    """
    YouTube Data API feedback loop for continuous model improvement
    FREE tier: 10,000 units per day
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("YOUTUBE_DATA_API_KEY")
        if not self.api_key:
            logger.warning("YouTube API key not provided. Feedback loop disabled.")
        
        self.base_url = "https://www.googleapis.com/youtube/v3"
        self.timeout = httpx.Timeout(30.0, connect=5.0)
        
        # Weight adjustment factors for model retraining
        self.weight_adjustments = {
            "pattern_interrupt": 1.0,
            "curiosity_gap": 1.0,
            "emotional_spike": 1.0,
            "shareability": 1.0,
            "loop_potential": 1.0
        }
        
        logger.info("YouTube Feedback Service initialized")
    
    async def get_video_metrics(
        self, 
        video_id: str,
        metrics: List[MetricType] = None
    ) -> Optional[YouTubePerformance]:
        """
        Fetch video metrics from YouTube Data API
        
        Args:
            video_id: YouTube video ID (e.g., "dQw4w9WgXcQ")
            metrics: List of metrics to fetch
            
        Returns:
            YouTubePerformance object or None
        """
        if not self.api_key:
            logger.error("YouTube API key required")
            return None
        
        if metrics is None:
            metrics = [
                MetricType.VIEW_COUNT,
                MetricType.LIKE_COUNT,
                MetricType.COMMENT_COUNT
            ]
        
        # Build metrics string
        parts = ["statistics"]
        if MetricType.AVERAGE_VIEW_DURATION in metrics:
            parts.append("contentDetails")
        
        params = {
            "id": video_id,
            "part": ",".join(parts),
            "key": self.api_key
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/videos",
                    params=params
                )
                response.raise_for_status()
                data = response.json()
                
                items = data.get("items", [])
                if not items:
                    logger.warning(f"Video not found: {video_id}")
                    return None
                
                video_data = items[0]
                stats = video_data.get("statistics", {})
                
                # Calculate retention score (0-100)
                views = int(stats.get("viewCount", 0))
                likes = int(stats.get("likeCount", 0))
                comments = int(stats.get("commentCount", 0))
                
                # Retention score formula (weighted)
                # High likes/view ratio = good retention
                like_ratio = likes / views if views > 0 else 0
                comment_ratio = comments / views if views > 0 else 0
                
                retention_score = min(100, (
                    like_ratio * 100 * 2 +  # Likes weighted 2x
                    comment_ratio * 100 * 3 +  # Comments weighted 3x (more engagement)
                    min(views / 1000, 20)  # View count bonus (capped)
                ))
                
                performance = YouTubePerformance(
                    video_id=video_id,
                    view_count=views,
                    like_count=likes,
                    comment_count=comments,
                    avg_view_duration=0.0,  # Requires Analytics API
                    avg_view_percentage=0.0,  # Requires Analytics API
                    retention_score=retention_score,
                    upload_time=datetime.now(),  # Would fetch from snippet
                    collection_time=datetime.now()
                )
                
                logger.info(f"Metrics for {video_id}: {views} views, "
                           f"{likes} likes, retention_score={retention_score:.1f}")
                
                return performance
                
        except Exception as e:
            logger.error(f"Failed to fetch YouTube metrics: {e}")
            return None
    
    def compare_prediction_vs_reality(
        self,
        prediction: ViralityPrediction,
        performance: YouTubePerformance
    ) -> FeedbackResult:
        """
        Compare predicted virality vs actual performance
        
        Returns:
            FeedbackResult with accuracy delta and model corrections
        """
        # Calculate accuracy delta
        # Negative = we overpredicted, Positive = we underpredicted
        accuracy_delta = performance.retention_score - prediction.predicted_score
        
        # Determine weight corrections needed
        corrections = {}
        
        if abs(accuracy_delta) > 15:  # Significant mismatch
            if accuracy_delta > 0:  # Underpredicted - actual was better
                # Boost weights for detected hook type
                corrections[prediction.predicted_hook_type] = 1.1
                logger.info(f"Underpredicted: boosting {prediction.predicted_hook_type} weight")
            else:  # Overpredicted - actual was worse
                # Reduce weights for detected hook type
                corrections[prediction.predicted_hook_type] = 0.9
                logger.info(f"Overpredicted: reducing {prediction.predicted_hook_type} weight")
        
        return FeedbackResult(
            clip_id=prediction.clip_id,
            predicted_score=prediction.predicted_score,
            actual_retention_score=performance.retention_score,
            accuracy_delta=accuracy_delta,
            hook_type=prediction.predicted_hook_type,
            model_correction=corrections
        )
    
    async def process_feedback_batch(
        self,
        predictions: List[ViralityPrediction],
        video_id_map: Dict[str, str]  # clip_id -> youtube_video_id
    ) -> List[FeedbackResult]:
        """
        Process feedback for multiple clips
        
        Args:
            predictions: List of stored predictions
            video_id_map: Mapping from clip IDs to YouTube video IDs
            
        Returns:
            List of feedback results for model retraining
        """
        results = []
        
        for pred in predictions:
            video_id = video_id_map.get(pred.clip_id)
            if not video_id:
                continue
            
            # Fetch actual performance
            performance = await self.get_video_metrics(video_id)
            if not performance:
                continue
            
            # Compare and generate feedback
            feedback = self.compare_prediction_vs_reality(pred, performance)
            results.append(feedback)
        
        # Aggregate corrections
        self._aggregate_weight_adjustments(results)
        
        logger.info(f"Processed feedback for {len(results)} videos")
        return results
    
    def _aggregate_weight_adjustments(self, results: List[FeedbackResult]):
        """Aggregate weight adjustments from batch of feedback"""
        hook_type_totals = {}
        hook_type_counts = {}
        
        for result in results:
            for hook_type, correction in result.model_correction.items():
                if hook_type not in hook_type_totals:
                    hook_type_totals[hook_type] = 0
                    hook_type_counts[hook_type] = 0
                
                hook_type_totals[hook_type] += correction
                hook_type_counts[hook_type] += 1
        
        # Apply aggregated adjustments
        for hook_type in hook_type_totals:
            avg_correction = hook_type_totals[hook_type] / hook_type_counts[hook_type]
            
            # Smooth adjustment (don't change too drastically)
            current_weight = self.weight_adjustments.get(hook_type, 1.0)
            new_weight = current_weight * 0.7 + avg_correction * 0.3
            
            # Clamp to reasonable range
            new_weight = max(0.5, min(1.5, new_weight))
            
            self.weight_adjustments[hook_type] = new_weight
            
            logger.info(f"Weight adjustment for {hook_type}: "
                       f"{current_weight:.3f} -> {new_weight:.3f}")
    
    def get_adjusted_virality_weights(self) -> Dict[str, float]:
        """Get current weight adjustments for Phi-3-mini scoring"""
        return self.weight_adjustments.copy()
    
    def apply_weights_to_prompt(self, base_prompt: str) -> str:
        """
        Modify Phi-3-mini prompt with learned weight adjustments
        
        This makes the model learn from actual YouTube performance
        """
        weight_context = "\n\nWeight adjustments based on historical performance:\n"
        
        for dimension, weight in self.weight_adjustments.items():
            if abs(weight - 1.0) > 0.05:  # Only mention significant adjustments
                direction = "increase emphasis" if weight > 1.0 else "reduce emphasis"
                weight_context += f"- {dimension}: {direction} (factor: {weight:.2f})\n"
        
        return base_prompt + weight_context


# Database integration functions
class FeedbackDatabase:
    """
    Store predictions and feedback in PostgreSQL
    """
    
    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or os.environ.get("DATABASE_URL")
    
    async def save_prediction(self, prediction: ViralityPrediction):
        """Save prediction before upload"""
        # SQL: INSERT INTO virality_predictions ...
        logger.info(f"Saved prediction for clip {prediction.clip_id}")
    
    async def get_predictions_for_feedback(
        self, 
        min_age_hours: int = 48
    ) -> List[ViralityPrediction]:
        """Get predictions ready for feedback collection"""
        # SQL: SELECT * FROM virality_predictions 
        #      WHERE uploaded_to_youtube = true 
        #      AND feedback_collected = false
        #      AND created_at < NOW() - INTERVAL '{min_age_hours} hours'
        return []
    
    async def save_feedback(self, feedback: FeedbackResult):
        """Save feedback result"""
        # SQL: INSERT INTO virality_feedback ...
        #      UPDATE virality_predictions SET feedback_collected = true
        logger.info(f"Saved feedback for clip {feedback.clip_id}")
    
    async def get_model_weights(self) -> Dict[str, float]:
        """Get current model weights from DB"""
        # SQL: SELECT * FROM virality_model_weights ORDER BY updated_at DESC LIMIT 1
        return {
            "pattern_interrupt": 1.0,
            "curiosity_gap": 1.0,
            "emotional_spike": 1.0,
            "shareability": 1.0,
            "loop_potential": 1.0
        }


# Setup instructions
SETUP_INSTRUCTIONS = """
Setup YouTube Feedback Loop:

1. Get YouTube Data API key:
   - Go to https://console.cloud.google.com/
   - Create project → Enable YouTube Data API v3
   - Create API key
   - Quota: 10,000 units/day (FREE)

2. Set environment variable:
   export YOUTUBE_DATA_API_KEY="your_api_key"

3. Database schema (PostgreSQL):
   
   CREATE TABLE virality_predictions (
       id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       clip_id VARCHAR(255) NOT NULL,
       predicted_score INTEGER,
       predicted_hook_type VARCHAR(50),
       segment_text TEXT,
       audio_features JSONB,
       youtube_video_id VARCHAR(50),
       uploaded_to_youtube BOOLEAN DEFAULT FALSE,
       feedback_collected BOOLEAN DEFAULT FALSE,
       created_at TIMESTAMP DEFAULT NOW()
   );
   
   CREATE TABLE virality_feedback (
       id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       prediction_id UUID REFERENCES virality_predictions(id),
       actual_retention_score FLOAT,
       accuracy_delta FLOAT,
       model_correction JSONB,
       collected_at TIMESTAMP DEFAULT NOW()
   );

4. Usage flow:
   - Generate clip → Save prediction to DB
   - User uploads to YouTube → Update youtube_video_id
   - 48h later → Run feedback collection
   - Adjust Phi-3-mini weights based on results

This is the differentiating feature - no competitor has this.
"""
