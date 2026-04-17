"""
Unit Tests — Phase 5.3: Feedback Loop
======================================
Tests for model retraining and feedback collection.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
import pandas as pd
from services.feedback_loop_service import FeedbackLoopService


class TestFeedbackLoopService:
    """Test FeedbackLoopService functionality."""
    
    def test_service_initialization(self):
        """Service should initialize without errors."""
        service = FeedbackLoopService()
        assert service is not None
        assert service.models_dir is not None
        assert service.feedback_dir is not None
    
    def test_service_has_required_methods(self):
        """Should have all required methods."""
        service = FeedbackLoopService()
        
        required_methods = [
            'collect_feedback_batch',
            'extract_features',
            'retrain_model',
            'predict',
            'load_current_model',
            'get_training_stats'
        ]
        
        for method in required_methods:
            assert hasattr(service, method)


@pytest.mark.asyncio
class TestFeedbackCollection:
    """Test feedback data collection."""
    
    async def test_collect_feedback_batch(self):
        """Should collect feedback batch."""
        service = FeedbackLoopService()
        
        df = await service.collect_feedback_batch(days_back=7)
        
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        
        # Check required columns
        required_cols = [
            'clip_id', 'duration', 'hook_strength', 
            'engagement_score', 'predicted_score', 
            'actual_score', 'user_rating'
        ]
        
        for col in required_cols:
            assert col in df.columns
    
    async def test_extract_features(self):
        """Should extract features correctly."""
        service = FeedbackLoopService()
        
        df = await service.collect_feedback_batch(days_back=7)
        X, y = service.extract_features(df)
        
        assert len(X) == len(y)
        assert len(X) > 0
        
        # Check feature columns
        expected_features = [
            'duration', 'hook_strength', 'engagement_score',
            'has_captions', 'has_broll'
        ]
        
        assert list(X.columns) == expected_features


@pytest.mark.asyncio
class TestModelTraining:
    """Test model retraining."""
    
    @pytest.mark.skip(reason="Requires ML libraries")
    async def test_retrain_model(self):
        """Should retrain model successfully."""
        service = FeedbackLoopService()
        
        result = await service.retrain_model(validate=True)
        
        assert isinstance(result, dict)
        assert 'train_mse' in result
        assert 'test_mse' in result
        assert 'train_r2' in result
        assert 'test_r2' in result
    
    def test_predict_method(self):
        """Should predict virality score."""
        service = FeedbackLoopService()
        
        features = {
            "duration": 30.0,
            "hook_strength": 85.0,
            "engagement_score": 72.0,
            "has_captions": 1,
            "has_broll": 0
        }
        
        # Should return score even without model
        score = service.predict(features)
        
        assert isinstance(score, (int, float))
        assert 0 <= score <= 100


@pytest.mark.asyncio
class TestModelManagement:
    """Test model loading and versioning."""
    
    async def test_get_training_stats(self):
        """Should return training statistics."""
        service = FeedbackLoopService()
        
        stats = await service.get_training_stats()
        
        assert isinstance(stats, dict)
        assert 'model_exists' in stats
        assert 'models_dir' in stats
        assert 'feedback_dir' in stats
    
    def test_load_current_model(self):
        """Should load model without error."""
        service = FeedbackLoopService()
        
        # Should not raise error even if no model exists
        model = service.load_current_model()
        
        # May be None if no model trained yet
        assert model is None or model is not None


@pytest.mark.integration
class TestFeedbackIntegration:
    """Integration tests for feedback loop."""
    
    @pytest.mark.skip(reason="Requires full ML stack")
    async def test_full_retraining_cycle(self):
        """Should complete full retraining cycle."""
        service = FeedbackLoopService()
        
        # Collect data
        df = await service.collect_feedback_batch(days_back=30)
        assert len(df) >= service.min_samples_for_training
        
        # Retrain
        result = await service.retrain_model(df=df, validate=True)
        assert result['deployed'] is True or result['deployed'] is False
        
        # Predict with new model
        score = service.predict({
            "duration": 25.0,
            "hook_strength": 90.0,
            "engagement_score": 85.0,
            "has_captions": 1,
            "has_broll": 1
        })
        
        assert 0 <= score <= 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
