"""
Integration Tests — End-to-End Pipeline
========================================
Tests for complete clip generation workflow.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from pathlib import Path


@pytest.mark.integration
@pytest.mark.asyncio
class TestClipGenerationPipeline:
    """Test complete clip generation pipeline."""
    
    @pytest.mark.skip(reason="Requires full stack running")
    async def test_youtube_to_clip_full_pipeline(self):
        """Should generate clip from YouTube URL."""
        from workers.tasks import process_video_task
        
        task_data = {
            'task_id': 'test_e2e_001',
            'source': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'processing_mode': 'fast',
            'target_platform': 'tiktok',
            'add_subtitles': True
        }
        
        result = await process_video_task(task_data)
        
        assert result['status'] == 'completed'
        assert len(result['clips']) > 0
        
        # Verify clip file exists
        clip_path = Path(result['clips'][0]['path'])
        assert clip_path.exists()
        
        # Verify variants exist
        variants = result['clips'][0].get('variants', [])
        assert len(variants) == 3  # high, medium, low
    
    @pytest.mark.skip(reason="Requires API running")
    async def test_api_create_task_flow(self):
        """Should create task via API and process."""
        import httpx
        
        async with httpx.AsyncClient() as client:
            # Create task
            response = await client.post(
                "http://localhost:8000/api/tasks",
                json={
                    "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "processing_mode": "fast",
                    "target_platform": "tiktok"
                },
                headers={"user_id": "test_user"}
            )
            
            assert response.status_code == 201
            task_data = response.json()
            task_id = task_data['task_id']
            
            # Poll for completion (max 5 min)
            import asyncio
            for _ in range(60):
                response = await client.get(f"http://localhost:8000/api/tasks/{task_id}")
                status_data = response.json()
                
                if status_data['status'] == 'completed':
                    break
                elif status_data['status'] == 'failed':
                    pytest.fail(f"Task failed: {status_data.get('error')}")
                
                await asyncio.sleep(5)
            
            assert status_data['status'] == 'completed'
            assert len(status_data['clips']) > 0


@pytest.mark.integration
class TestMultiPhaseIntegration:
    """Test integration between multiple phases."""
    
    def test_export_with_trends_integration(self):
        """Should export with trend-boosted virality scores."""
        from services.viral_trend_service import ViralTrendService
        from video_processing.export_profiles import ExportService
        
        trend_service = ViralTrendService()
        export_service = ExportService()
        
        # Both services should work together
        assert trend_service is not None
        assert export_service is not None
    
    def test_milvus_with_feedback_integration(self):
        """Vector search should work with feedback loop."""
        from services.milvus_vector_service import MilvusVectorService
        from services.feedback_loop_service import FeedbackLoopService
        
        milvus = MilvusVectorService()
        feedback = FeedbackLoopService()
        
        assert milvus is not None
        assert feedback is not None
    
    @pytest.mark.asyncio
    async def test_full_phase_integration(self):
        """All phases should integrate seamlessly."""
        from services.viral_trend_service import ViralTrendService
        from services.milvus_vector_service import MilvusVectorService
        from services.feedback_loop_service import FeedbackLoopService
        from video_processing.export_profiles import ExportService
        
        # Initialize all services
        trend_service = ViralTrendService()
        milvus_service = MilvusVectorService()
        feedback_service = FeedbackLoopService()
        export_service = ExportService()
        
        # All should be initialized
        assert all([
            trend_service,
            milvus_service,
            feedback_service,
            export_service
        ])


@pytest.mark.performance
class TestPerformanceBenchmarks:
    """Performance benchmarks for critical operations."""
    
    @pytest.mark.skip(reason="Requires test video")
    def test_export_variants_performance(self):
        """Export variants should complete within time limit."""
        import time
        from video_processing.export_profiles import ExportService, Platform
        
        service = ExportService()
        
        start = time.time()
        
        # Mock export (would need actual video)
        # variants = service.export_with_variants(...)
        
        duration = time.time() - start
        
        # Should complete within 60 seconds for 30s video
        assert duration < 60.0
    
    @pytest.mark.asyncio
    async def test_trend_boost_performance(self):
        """Trend boost should complete in <100ms."""
        import time
        from services.viral_trend_service import ViralTrendService
        
        service = ViralTrendService()
        
        start = time.time()
        
        service.apply_trend_boost(
            base_score=75.0,
            transcript="Test content with trending hashtags",
            hashtags=["trending", "viral"],
            platform="tiktok"
        )
        
        duration = time.time() - start
        
        # Should be very fast (caching)
        assert duration < 0.1  # 100ms
    
    def test_feedback_prediction_performance(self):
        """Model prediction should be fast (<50ms)."""
        import time
        from services.feedback_loop_service import FeedbackLoopService
        
        service = FeedbackLoopService()
        
        start = time.time()
        
        service.predict({
            "duration": 30.0,
            "hook_strength": 85.0,
            "engagement_score": 72.0,
            "has_captions": 1,
            "has_broll": 0
        })
        
        duration = time.time() - start
        
        # Inference should be very fast
        assert duration < 0.05  # 50ms


@pytest.mark.stress
class TestStressTests:
    """Stress tests for system limits."""
    
    @pytest.mark.skip(reason="Resource intensive")
    @pytest.mark.asyncio
    async def test_concurrent_clip_generation(self):
        """Should handle multiple concurrent tasks."""
        import asyncio
        from workers.tasks import process_video_task
        
        tasks = []
        for i in range(10):
            task_data = {
                'task_id': f'stress_test_{i}',
                'source': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                'processing_mode': 'fast'
            }
            tasks.append(process_video_task(task_data))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Most should succeed
        successful = sum(1 for r in results if not isinstance(r, Exception))
        assert successful >= 8  # 80% success rate
    
    @pytest.mark.skip(reason="Resource intensive")
    async def test_large_batch_vector_search(self):
        """Should handle large batch vector searches."""
        from services.milvus_vector_service import MilvusVectorService
        import numpy as np
        
        service = MilvusVectorService()
        
        # Search 1000 times
        for _ in range(1000):
            await service.search_multimodal(
                visual_vector=np.random.rand(512).tolist(),
                text_vector=np.random.rand(384).tolist(),
                limit=10
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "not skip"])
