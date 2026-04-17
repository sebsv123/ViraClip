"""
Machine Learning Virality Prediction System
Advanced ML models to predict and improve virality scoring accuracy.
"""

import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import pickle
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MLFeatureSet:
    """Feature set for virality prediction."""
    # Content features
    duration_seconds: float
    has_hook: bool
    hook_strength: float
    emotional_valence: float
    pattern_match_score: float
    
    # Audio features
    audio_energy: float
    speech_clarity: float
    silence_ratio: float
    
    # Visual features
    motion_intensity: float
    face_presence: float
    scene_changes: int
    
    # Text features
    word_count: int
    sentiment_score: float
    readability_score: float
    keyword_density: float
    
    # Historical features
    similar_content_avg_views: float
    niche_performance_score: float
    time_of_day_factor: float


@dataclass
class ViralityPrediction:
    """ML virality prediction result."""
    predicted_score: float
    confidence: float
    feature_importance: Dict[str, float]
    model_version: str
    prediction_time: str
    recommendation: str


class MLViralityPredictor:
    """
    Machine learning predictor for virality scoring.
    """
    
    def __init__(self, model_path: Optional[Path] = None):
        self.model_path = model_path or Path("/app/data/ml_models")
        self.model_path.mkdir(parents=True, exist_ok=True)
        
        self.model_version = "v1.0.0"
        self._training_data: List[Tuple[MLFeatureSet, float]] = []
        self._feature_weights = self._initialize_weights()
        
        # Load existing model if available
        self._load_model()
    
    def _initialize_weights(self) -> Dict[str, float]:
        """Initialize feature weights based on domain knowledge."""
        return {
            "duration_seconds": 0.10,
            "has_hook": 0.15,
            "hook_strength": 0.20,
            "emotional_valence": 0.12,
            "pattern_match_score": 0.10,
            "audio_energy": 0.05,
            "speech_clarity": 0.05,
            "silence_ratio": -0.03,  # Negative - too much silence is bad
            "motion_intensity": 0.08,
            "face_presence": 0.05,
            "scene_changes": 0.03,
            "word_count": 0.02,
            "sentiment_score": 0.04,
            "readability_score": 0.03,
            "keyword_density": 0.02,
            "similar_content_avg_views": 0.15,
            "niche_performance_score": 0.10,
            "time_of_day_factor": 0.05
        }
    
    def _load_model(self) -> None:
        """Load trained model from disk."""
        model_file = self.model_path / f"virality_model_{self.model_version}.pkl"
        
        if model_file.exists():
            try:
                with open(model_file, 'rb') as f:
                    saved = pickle.load(f)
                    self._feature_weights = saved.get('weights', self._feature_weights)
                    self._training_data = saved.get('training_data', [])
                logger.info(f"Loaded ML model version {self.model_version}")
            except Exception as e:
                logger.warning(f"Failed to load model: {e}")
    
    def _save_model(self) -> None:
        """Save trained model to disk."""
        model_file = self.model_path / f"virality_model_{self.model_version}.pkl"
        
        try:
            with open(model_file, 'wb') as f:
                pickle.dump({
                    'weights': self._feature_weights,
                    'training_data': self._training_data,
                    'version': self.model_version,
                    'saved_at': datetime.now().isoformat()
                }, f)
            logger.info(f"Saved ML model version {self.model_version}")
        except Exception as e:
            logger.error(f"Failed to save model: {e}")
    
    def extract_features(
        self,
        clip_data: Dict[str, Any],
        transcript: str,
        audio_analysis: Optional[Dict] = None,
        visual_analysis: Optional[Dict] = None
    ) -> MLFeatureSet:
        """
        Extract ML features from clip data.
        
        Args:
            clip_data: Clip metadata and analysis results
            transcript: Video transcript
            audio_analysis: Optional audio feature analysis
            visual_analysis: Optional visual feature analysis
        """
        # Content features
        duration = clip_data.get("duration", 0)
        has_hook = clip_data.get("has_hook", False)
        hook_strength = clip_data.get("hook_strength", 0.5)
        emotional_valence = clip_data.get("emotional_valence", 0.5)
        pattern_match = clip_data.get("pattern_match_score", 0.5)
        
        # Audio features (with defaults if not provided)
        audio_energy = audio_analysis.get("energy", 0.5) if audio_analysis else 0.5
        speech_clarity = audio_analysis.get("clarity", 0.7) if audio_analysis else 0.7
        silence_ratio = audio_analysis.get("silence_ratio", 0.1) if audio_analysis else 0.1
        
        # Visual features
        motion = visual_analysis.get("motion_intensity", 0.5) if visual_analysis else 0.5
        face_presence = visual_analysis.get("face_presence", 0.5) if visual_analysis else 0.5
        scene_changes = visual_analysis.get("scene_changes", 3) if visual_analysis else 3
        
        # Text features
        words = transcript.split()
        word_count = len(words)
        sentiment = self._calculate_sentiment(transcript)
        readability = self._calculate_readability(transcript)
        keyword_density = self._calculate_keyword_density(transcript)
        
        # Historical features (from clip data or defaults)
        similar_views = clip_data.get("similar_content_avg_views", 1000)
        niche_score = clip_data.get("niche_performance_score", 0.5)
        time_factor = clip_data.get("time_of_day_factor", 1.0)
        
        return MLFeatureSet(
            duration_seconds=duration,
            has_hook=has_hook,
            hook_strength=hook_strength,
            emotional_valence=emotional_valence,
            pattern_match_score=pattern_match,
            audio_energy=audio_energy,
            speech_clarity=speech_clarity,
            silence_ratio=silence_ratio,
            motion_intensity=motion,
            face_presence=face_presence,
            scene_changes=scene_changes,
            word_count=word_count,
            sentiment_score=sentiment,
            readability_score=readability,
            keyword_density=keyword_density,
            similar_content_avg_views=similar_views,
            niche_performance_score=niche_score,
            time_of_day_factor=time_factor
        )
    
    def _calculate_sentiment(self, text: str) -> float:
        """Calculate sentiment score from text."""
        # Simple sentiment analysis
        positive_words = ['amazing', 'great', 'excellent', 'love', 'best', 'awesome', 'fantastic']
        negative_words = ['hate', 'terrible', 'awful', 'worst', 'bad', 'horrible']
        
        text_lower = text.lower()
        pos_count = sum(1 for word in positive_words if word in text_lower)
        neg_count = sum(1 for word in negative_words if word in text_lower)
        
        total = pos_count + neg_count
        if total == 0:
            return 0.5  # Neutral
        
        return pos_count / total
    
    def _calculate_readability(self, text: str) -> float:
        """Calculate readability score (0-1)."""
        words = text.split()
        if not words:
            return 0.5
        
        avg_word_length = sum(len(w) for w in words) / len(words)
        
        # Normalize: shorter words = more readable
        score = max(0, min(1, 1.5 - (avg_word_length / 10)))
        return score
    
    def _calculate_keyword_density(self, text: str) -> float:
        """Calculate viral keyword density."""
        viral_keywords = [
            'viral', 'trending', 'hack', 'secret', 'revealed',
            'shocking', 'must watch', 'you won\'t believe'
        ]
        
        text_lower = text.lower()
        matches = sum(1 for kw in viral_keywords if kw in text_lower)
        
        # Normalize by text length
        word_count = len(text.split())
        if word_count == 0:
            return 0
        
        return min(1.0, matches / (word_count / 50))  # Cap at 1.0
    
    def predict_virality(self, features: MLFeatureSet) -> ViralityPrediction:
        """
        Predict virality score using ML model.
        
        Args:
            features: Extracted feature set
            
        Returns:
            Virality prediction with confidence and recommendations
        """
        # Convert features to vector
        feature_vector = self._features_to_vector(features)
        
        # Calculate weighted score
        score = 0
        max_possible = 0
        
        for feature_name, value in feature_vector.items():
            weight = self._feature_weights.get(feature_name, 0)
            normalized_value = self._normalize_feature(feature_name, value)
            
            score += normalized_value * weight
            max_possible += abs(weight)
        
        # Normalize to 0-100 scale
        if max_possible > 0:
            normalized_score = (score / max_possible) * 100
        else:
            normalized_score = 50
        
        # Clip to valid range
        predicted_score = max(0, min(100, normalized_score))
        
        # Calculate confidence based on data quality
        confidence = self._calculate_confidence(features)
        
        # Get feature importance
        importance = self._get_feature_importance(features)
        
        # Generate recommendation
        recommendation = self._generate_recommendation(features, predicted_score, importance)
        
        return ViralityPrediction(
            predicted_score=predicted_score,
            confidence=confidence,
            feature_importance=importance,
            model_version=self.model_version,
            prediction_time=datetime.now().isoformat(),
            recommendation=recommendation
        )
    
    def _features_to_vector(self, features: MLFeatureSet) -> Dict[str, float]:
        """Convert feature set to dictionary."""
        return {
            "duration_seconds": float(features.duration_seconds),
            "has_hook": 1.0 if features.has_hook else 0.0,
            "hook_strength": features.hook_strength,
            "emotional_valence": features.emotional_valence,
            "pattern_match_score": features.pattern_match_score,
            "audio_energy": features.audio_energy,
            "speech_clarity": features.speech_clarity,
            "silence_ratio": features.silence_ratio,
            "motion_intensity": features.motion_intensity,
            "face_presence": features.face_presence,
            "scene_changes": float(features.scene_changes),
            "word_count": float(features.word_count),
            "sentiment_score": features.sentiment_score,
            "readability_score": features.readability_score,
            "keyword_density": features.keyword_density,
            "similar_content_avg_views": features.similar_content_avg_views,
            "niche_performance_score": features.niche_performance_score,
            "time_of_day_factor": features.time_of_day_factor
        }
    
    def _normalize_feature(self, name: str, value: float) -> float:
        """Normalize feature value to 0-1 range."""
        # Feature-specific normalization
        if name == "duration_seconds":
            # Optimal: 15-60 seconds
            if 15 <= value <= 60:
                return 1.0
            elif value < 15:
                return 0.5 + (value / 30)
            else:
                return max(0, 1.0 - ((value - 60) / 120))
        
        elif name == "scene_changes":
            # 3-8 scene changes is optimal
            if 3 <= value <= 8:
                return 1.0
            elif value < 3:
                return 0.5 + (value / 6)
            else:
                return max(0, 1.0 - ((value - 8) / 10))
        
        elif name == "similar_content_avg_views":
            # Log scale normalization
            import math
            if value <= 0:
                return 0
            log_val = math.log10(value)
            return min(1.0, log_val / 6)  # 1M views = 1.0
        
        # Default: assume already normalized
        return max(0, min(1, value))
    
    def _calculate_confidence(self, features: MLFeatureSet) -> float:
        """Calculate prediction confidence."""
        # Higher confidence with more complete data
        confidence = 0.7  # Base confidence
        
        # Boost for complete data
        if features.audio_energy != 0.5:
            confidence += 0.05
        if features.motion_intensity != 0.5:
            confidence += 0.05
        if features.similar_content_avg_views > 100:
            confidence += 0.1
        
        return min(0.95, confidence)
    
    def _get_feature_importance(self, features: MLFeatureSet) -> Dict[str, float]:
        """Get importance ranking of features for this prediction."""
        vector = self._features_to_vector(features)
        
        # Calculate contribution of each feature
        contributions = {}
        
        for name, value in vector.items():
            weight = self._feature_weights.get(name, 0)
            normalized = self._normalize_feature(name, value)
            contributions[name] = abs(normalized * weight)
        
        # Normalize to sum to 1
        total = sum(contributions.values())
        if total > 0:
            contributions = {k: v/total for k, v in contributions.items()}
        
        # Sort and return top 5
        return dict(sorted(contributions.items(), key=lambda x: x[1], reverse=True)[:5])
    
    def _generate_recommendation(
        self,
        features: MLFeatureSet,
        score: float,
        importance: Dict[str, float]
    ) -> str:
        """Generate improvement recommendation."""
        if score >= 80:
            return "High virality potential. Focus on distribution timing and hashtags."
        
        # Find weakest important feature
        weakest = None
        lowest_normalized = 1.0
        
        vector = self._features_to_vector(features)
        for name, weight in importance.items():
            if weight > 0.05:  # Significant feature
                normalized = self._normalize_feature(name, vector[name])
                if normalized < lowest_normalized:
                    lowest_normalized = normalized
                    weakest = name
        
        recommendations = {
            "has_hook": "Add a stronger hook in the first 3 seconds",
            "hook_strength": "Improve hook clarity and emotional impact",
            "duration_seconds": "Optimize clip length to 15-60 seconds",
            "emotional_valence": "Increase emotional intensity",
            "pattern_match_score": "Align with trending content patterns",
            "audio_energy": "Boost audio levels and clarity",
            "motion_intensity": "Add more visual movement and dynamics",
            "silence_ratio": "Reduce silent pauses",
            "sentiment_score": "Balance positive sentiment",
            "keyword_density": "Include more viral keywords naturally"
        }
        
        return recommendations.get(weakest, "Review and optimize content structure")
    
    def train(
        self,
        features: MLFeatureSet,
        actual_virality_score: float
    ) -> None:
        """
        Train model with actual performance data.
        
        Args:
            features: Feature set used for prediction
            actual_virality_score: Actual virality score achieved (0-100)
        """
        self._training_data.append((features, actual_virality_score))
        
        # Keep only recent data (last 1000 samples)
        if len(self._training_data) > 1000:
            self._training_data = self._training_data[-1000:]
        
        # Periodically update weights based on training data
        if len(self._training_data) % 100 == 0:
            self._update_weights()
        
        logger.info(f"Added training sample. Total: {len(self._training_data)}")
    
    def _update_weights(self) -> None:
        """Update feature weights based on training data."""
        if len(self._training_data) < 50:
            return
        
        # Simple gradient descent adjustment
        # This is a simplified version - production would use proper optimization
        
        learning_rate = 0.01
        
        for features, actual in self._training_data[-100:]:
            predicted = self.predict_virality(features)
            error = actual - predicted.predicted_score
            
            # Adjust weights based on error
            vector = self._features_to_vector(features)
            for name, value in vector.items():
                normalized = self._normalize_feature(name, value)
                gradient = error * normalized * learning_rate
                
                # Update weight
                self._feature_weights[name] = self._feature_weights.get(name, 0) + gradient
        
        # Normalize weights
        total = sum(abs(w) for w in self._feature_weights.values())
        if total > 0:
            self._feature_weights = {
                k: v/total for k, v in self._feature_weights.items()
            }
        
        self._save_model()
        logger.info("Updated model weights based on training data")
    
    def get_model_stats(self) -> Dict[str, Any]:
        """Get model statistics."""
        return {
            "version": self.model_version,
            "training_samples": len(self._training_data),
            "feature_weights": self._feature_weights,
            "last_updated": datetime.now().isoformat(),
            "accuracy_estimate": self._estimate_accuracy()
        }
    
    def _estimate_accuracy(self) -> float:
        """Estimate model accuracy based on recent predictions."""
        if len(self._training_data) < 10:
            return 0.0
        
        # Calculate mean absolute error on recent samples
        recent = self._training_data[-50:]
        errors = []
        
        for features, actual in recent:
            predicted = self.predict_virality(features)
            errors.append(abs(actual - predicted.predicted_score))
        
        mae = sum(errors) / len(errors)
        
        # Convert to accuracy (100 - MAE)
        return max(0, 100 - mae)


# Global instance
_ml_predictor: Optional[MLViralityPredictor] = None


def get_ml_predictor() -> MLViralityPredictor:
    """Get global ML predictor instance."""
    global _ml_predictor
    if _ml_predictor is None:
        _ml_predictor = MLViralityPredictor()
    return _ml_predictor


# Convenience functions
def predict_virality_ml(
    clip_data: Dict[str, Any],
    transcript: str,
    audio_analysis: Optional[Dict] = None,
    visual_analysis: Optional[Dict] = None
) -> ViralityPrediction:
    """Predict virality using ML model."""
    predictor = get_ml_predictor()
    features = predictor.extract_features(clip_data, transcript, audio_analysis, visual_analysis)
    return predictor.predict_virality(features)


def train_virality_model(features: Dict[str, Any], actual_score: float) -> None:
    """Train model with actual performance data."""
    predictor = get_ml_predictor()
    feature_set = predictor.extract_features(features, features.get("transcript", ""))
    predictor.train(feature_set, actual_score)
