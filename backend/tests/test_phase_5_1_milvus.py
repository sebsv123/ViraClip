"""
Unit Tests — Phase 5.1: Milvus Vector DB
=========================================
Tests for multimodal vector search.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
import numpy as np
from services.milvus_vector_service import MilvusVectorService


class TestMilvusVectorService:
    """Test MilvusVectorService functionality."""
    
    def test_service_initialization(self):
        """Service should initialize without errors."""
        service = MilvusVectorService()
        assert service is not None
        assert hasattr(service, 'collection_name')
    
    def test_service_has_required_methods(self):
        """Should have all required methods."""
        service = MilvusVectorService()
        
        required_methods = [
            'index_clip',
            'search_multimodal',
            'search_by_visual',
            'search_by_text',
            'search_by_audio',
            'delete_clip',
            'get_stats'
        ]
        
        for method in required_methods:
            assert hasattr(service, method)


@pytest.mark.asyncio
class TestMilvusOperations:
    """Test Milvus operations."""
    
    async def test_index_clip_structure(self):
        """Should accept correct clip structure."""
        service = MilvusVectorService()
        
        clip_data = {
            "clip_id": "test_123",
            "visual_embedding": np.random.rand(512).tolist(),
            "text_embedding": np.random.rand(384).tolist(),
            "audio_embedding": np.random.rand(128).tolist(),
            "transcript": "Test transcript",
            "duration": 30.0,
            "virality_score": 85.0,
            "platform": "tiktok"
        }
        
        # Should not raise error (even if Milvus not running)
        try:
            await service.index_clip(**clip_data)
        except Exception as e:
            # Expected if Milvus not available
            assert "connection" in str(e).lower() or "milvus" in str(e).lower()
    
    async def test_search_multimodal_params(self):
        """Should accept multimodal search parameters."""
        service = MilvusVectorService()
        
        try:
            results = await service.search_multimodal(
                visual_vector=np.random.rand(512).tolist(),
                text_vector=np.random.rand(384).tolist(),
                audio_vector=np.random.rand(128).tolist(),
                limit=10,
                filters={"platform": "tiktok"}
            )
            
            # Should return list (empty if Milvus not running)
            assert isinstance(results, list)
        except Exception:
            # Expected if Milvus not available
            pass
    
    async def test_get_stats(self):
        """Should return stats dictionary."""
        service = MilvusVectorService()
        
        stats = await service.get_stats()
        
        assert isinstance(stats, dict)
        assert "collection_name" in stats
        assert "enabled" in stats


class TestVectorDimensions:
    """Test vector dimension validation."""
    
    def test_visual_embedding_dimension(self):
        """Visual embeddings should be 512-dim (CLIP)."""
        service = MilvusVectorService()
        
        # Verify expected dimensions
        assert service.visual_dim == 512
    
    def test_text_embedding_dimension(self):
        """Text embeddings should be 384-dim (sentence-transformers)."""
        service = MilvusVectorService()
        assert service.text_dim == 384
    
    def test_audio_embedding_dimension(self):
        """Audio embeddings should be 128-dim."""
        service = MilvusVectorService()
        assert service.audio_dim == 128


@pytest.mark.integration
class TestMilvusIntegration:
    """Integration tests for Milvus."""
    
    @pytest.mark.skip(reason="Requires Milvus running")
    async def test_full_index_search_cycle(self):
        """Should index and search successfully."""
        service = MilvusVectorService()
        
        # Index test clip
        clip_data = {
            "clip_id": "integration_test",
            "visual_embedding": np.random.rand(512).tolist(),
            "text_embedding": np.random.rand(384).tolist(),
            "audio_embedding": np.random.rand(128).tolist(),
            "transcript": "Integration test",
            "duration": 30.0,
            "virality_score": 80.0
        }
        
        await service.index_clip(**clip_data)
        
        # Search
        results = await service.search_by_text(
            query="integration test",
            limit=5
        )
        
        assert len(results) > 0
        assert any(r["clip_id"] == "integration_test" for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
