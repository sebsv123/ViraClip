"""
Test ComfyUIIntegration - Lazy imports y mocking
Updated: 2026-04-23
"""
import pytest
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, Mock


class TestComfyUILazyImports:
    """Test that comfyui_integration can be imported without ComfyUI installed."""

    def test_import_without_comfyui_dependencies(self):
        """Test that module imports work even when ComfyUI deps are missing."""
        # Clear any cached imports
        import sys
        to_remove = [k for k in sys.modules.keys() if "comfyui" in k]
        for mod in to_remove:
            del sys.modules[mod]
        
        # Mock the orchestrator import to simulate missing ComfyUI
        with patch.dict("sys.modules", {"backend.src.services.comfyui.orchestrator": None}):
            # Should still be able to import the module
            from backend.src.services.comfyui_integration import ComfyUIIntegrationService
            
            # Should be able to instantiate
            service = ComfyUIIntegrationService()
            assert service is not None
            assert service.enabled is True  # Default

    @pytest.mark.asyncio
    async def test_lazy_orchestrator_loading(self):
        """Test that orchestrator is loaded only when methods are called."""
        from backend.src.services.comfyui_integration import ComfyUIIntegrationService, _get_orchestrator
        
        # Create mock orchestrator
        mock_orch = MagicMock()
        mock_orch.subtitles = AsyncMock(return_value="/tmp/output.mp4")
        
        with patch("backend.src.services.comfyui_integration._comfyui_orchestrator", None):
            with patch("backend.src.services.comfyui_integration.comfyui_orchestrator", mock_orch):
                orchestrator = _get_orchestrator()
                assert orchestrator is mock_orch

    @pytest.mark.asyncio
    async def test_process_with_comfyui_disabled(self):
        """Test that disabled ComfyUI returns None gracefully."""
        from backend.src.services.comfyui_integration import ComfyUIIntegrationService
        
        service = ComfyUIIntegrationService()
        service.enabled = False
        
        result = await service.process_with_comfyui(
            task_id="test_001",
            video_path=Path("/tmp/input.mp4"),
            operation="subtitles"
        )
        
        assert result is None


class TestComfyUIMocking:
    """Test ComfyUI operations with mocked orchestrator."""

    @pytest.fixture
    def mock_orchestrator(self):
        """Mock orchestrator for testing."""
        mock = MagicMock()
        mock.subtitles = AsyncMock(return_value="/tmp/output.mp4")
        mock.reframe_9_16 = AsyncMock(return_value="/tmp/reframed.mp4")
        mock.thumbnail = AsyncMock(return_value="/tmp/thumb.jpg")
        mock.add_broll_transition = AsyncMock(return_value="/tmp/transition.mp4")
        mock.health_check = AsyncMock(return_value={"status": "ok"})
        return mock

    @pytest.mark.asyncio
    async def test_subtitles_operation(self, mock_orchestrator):
        """Test subtitles operation with mocked orchestrator."""
        from backend.src.services.comfyui_integration import ComfyUIIntegrationService
        
        with patch.object(Path, "exists", return_value=True):
            with patch("backend.src.services.comfyui_integration._get_orchestrator", return_value=mock_orchestrator):
                service = ComfyUIIntegrationService()
                service.enabled = True
                
                # Create input file mock
                with patch("shutil.copy2"):
                    result = await service.process_with_comfyui(
                        task_id="test_001",
                        video_path=Path("/tmp/input.mp4"),
                        operation="subtitles"
                    )
                
                assert result is not None
                mock_orchestrator.subtitles.assert_called_once()

    @pytest.mark.asyncio
    async def test_reframe_operation(self, mock_orchestrator):
        """Test reframe operation with mocked orchestrator."""
        from backend.src.services.comfyui_integration import ComfyUIIntegrationService
        
        with patch.object(Path, "exists", return_value=True):
            with patch("backend.src.services.comfyui_integration._get_orchestrator", return_value=mock_orchestrator):
                service = ComfyUIIntegrationService()
                service.enabled = True
                
                with patch("shutil.copy2"):
                    result = await service.process_with_comfyui(
                        task_id="test_002",
                        video_path=Path("/tmp/input.mp4"),
                        operation="reframe_9_16",
                        chunk_size=300
                    )
                
                mock_orchestrator.reframe_9_16.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_orchestrator):
        """Test health check returns True when ComfyUI is healthy."""
        from backend.src.services.comfyui_integration import ComfyUIIntegrationService
        
        with patch("backend.src.services.comfyui_integration._get_orchestrator", return_value=mock_orchestrator):
            service = ComfyUIIntegrationService()
            
            result = await service.health_check()
            
            assert result is True
            mock_orchestrator.health_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """Test health check returns False on error."""
        from backend.src.services.comfyui_integration import ComfyUIIntegrationService
        
        mock_orch = MagicMock()
        mock_orch.health_check = AsyncMock(side_effect=Exception("Connection refused"))
        
        with patch("backend.src.services.comfyui_integration._get_orchestrator", return_value=mock_orch):
            service = ComfyUIIntegrationService()
            
            result = await service.health_check()
            
            assert result is False

    @pytest.mark.asyncio
    async def test_broll_transition_with_video(self, mock_orchestrator):
        """Test B-roll transition with provided B-roll video."""
        from backend.src.services.comfyui_integration import ComfyUIIntegrationService
        
        with patch.object(Path, "exists", return_value=True):
            with patch("backend.src.services.comfyui_integration._get_orchestrator", return_value=mock_orchestrator):
                with patch("shutil.copy2"):
                    service = ComfyUIIntegrationService()
                    service.enabled = True
                    
                    result = await service.process_with_comfyui(
                        task_id="test_003",
                        video_path=Path("/tmp/input.mp4"),
                        operation="broll_transition",
                        broll_path="/tmp/broll.mp4",
                        transition_type="fade",
                        duration=1.5
                    )
                    
                    mock_orchestrator.add_broll_transition.assert_called_once()


class TestComfyUIErrorHandling:
    """Test error handling in ComfyUI operations."""

    @pytest.mark.asyncio
    async def test_unknown_operation(self):
        """Test handling of unknown operation."""
        from backend.src.services.comfyui_integration import ComfyUIIntegrationService
        
        mock_orch = MagicMock()
        
        with patch("backend.src.services.comfyui_integration._get_orchestrator", return_value=mock_orch):
            with patch.object(Path, "exists", return_value=True):
                with patch("shutil.copy2"):
                    service = ComfyUIIntegrationService()
                    service.enabled = True
                    
                    result = await service.process_with_comfyui(
                        task_id="test_004",
                        video_path=Path("/tmp/input.mp4"),
                        operation="unknown_op"
                    )
                    
                    assert result is None

    @pytest.mark.asyncio
    async def test_exception_during_processing(self):
        """Test graceful handling of exceptions during processing."""
        from backend.src.services.comfyui_integration import ComfyUIIntegrationService
        
        mock_orch = MagicMock()
        mock_orch.subtitles = AsyncMock(side_effect=Exception("Processing failed"))
        
        with patch("backend.src.services.comfyui_integration._get_orchestrator", return_value=mock_orch):
            with patch.object(Path, "exists", return_value=True):
                with patch("shutil.copy2"):
                    service = ComfyUIIntegrationService()
                    service.enabled = True
                    
                    # Should not raise, should return None
                    result = await service.process_with_comfyui(
                        task_id="test_005",
                        video_path=Path("/tmp/input.mp4"),
                        operation="subtitles"
                    )
                    
                    assert result is None
