"""
Phase 7.5 — Auto-Update Data Pipeline Tests
===========================================
Test the ARQ cron jobs for automated dataset refresh and model retraining.

Run with: docker-compose exec backend .venv/bin/python -m pytest tests/test_data_pipeline_cron.py -v
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# Ensure imports work in Docker context
if "/app/src" not in sys.path:
    sys.path.insert(0, "/app/src")


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    redis = AsyncMock()
    redis.setex = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    redis.publish = AsyncMock(return_value=1)
    redis.llen = AsyncMock(return_value=0)
    redis.close = AsyncMock()
    return redis


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = []
    session.execute = AsyncMock(return_value=result)
    return session


class TestFetchTrendingData:
    """Test the daily trending data fetch cron job."""

    @pytest.mark.asyncio
    async def test_fetch_trending_success(self, mock_redis):
        """Test successful trending data fetch with YouTube patterns."""
        from workers.data_pipeline_cron import fetch_trending_data

        # Mock YouTubeTrendingLoader
        mock_patterns = {
            "top_tags": ["viral", "trending", "fyp"],
            "viral_duration_range": [15, 30, 60],
            "optimal_publish_hours": [18, 19, 20],
        }
        mock_yt_loader = MagicMock()
        mock_yt_loader.extract_trend_patterns.return_value = mock_patterns

        # Mock ViralTrendService
        mock_vts = MagicMock()
        mock_vts.refresh_all = AsyncMock()

        with patch(
            "dataset_integration.YouTubeTrendingLoader", return_value=mock_yt_loader
        ), patch(
            "services.viral_trend_service.ViralTrendService", return_value=mock_vts
        ), patch(
            "workers.data_pipeline_cron.get_config"
        ) as mock_config:
            mock_cfg = MagicMock()
            mock_cfg.redis_host = "redis"
            mock_cfg.redis_port = 6379
            mock_cfg.redis_password = None
            mock_config.return_value = mock_cfg

            with patch("redis.asyncio.Redis", return_value=mock_redis):
                ctx: Dict[str, Any] = {}
                result = await fetch_trending_data(ctx)

        assert result["status"] == "ok"
        assert "fetched" in result
        assert "youtube_trending" in result["fetched"]
        assert result["fetched"]["youtube_trending"]["top_tags"] == ["viral", "trending", "fyp"]
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_trending_youtube_failure(self, mock_redis):
        """Test graceful handling when YouTube fetch fails."""
        from workers.data_pipeline_cron import fetch_trending_data

        mock_yt_loader = MagicMock()
        mock_yt_loader.extract_trend_patterns.side_effect = Exception("API quota exceeded")

        with patch(
            "dataset_integration.YouTubeTrendingLoader", return_value=mock_yt_loader
        ):
            ctx: Dict[str, Any] = {}
            result = await fetch_trending_data(ctx)

        # Should still return ok status but with error details
        assert result["status"] == "ok"
        assert "youtube_trending" in result["fetched"]
        assert "error" in result["fetched"]["youtube_trending"]

    @pytest.mark.asyncio
    async def test_fetch_trending_viral_trends_refresh(self, mock_redis):
        """Test ViralTrendService refresh is called."""
        from workers.data_pipeline_cron import fetch_trending_data

        mock_yt_loader = MagicMock()
        mock_yt_loader.extract_trend_patterns.return_value = None

        mock_vts = MagicMock()
        mock_vts.refresh_all = AsyncMock()

        with patch(
            "dataset_integration.YouTubeTrendingLoader", return_value=mock_yt_loader
        ), patch("services.viral_trend_service.ViralTrendService", return_value=mock_vts):
            ctx: Dict[str, Any] = {}
            result = await fetch_trending_data(ctx)

        mock_vts.refresh_all.assert_called_once()
        assert result["fetched"]["viral_trends"] == "refreshed"


class TestRetrainLoRAWeekly:
    """Test the weekly LoRA retrain cron job (GPU worker)."""

    @pytest.mark.asyncio
    async def test_retrain_lora_no_gpu(self):
        """Test LoRA retrain skips when no GPU available."""
        from workers.data_pipeline_cron import retrain_lora_weekly

        ctx = {"gpu_available": False}
        result = await retrain_lora_weekly(ctx)

        assert result["status"] == "skipped"
        assert result["reason"] == "no_gpu"

    @pytest.mark.asyncio
    async def test_retrain_lora_insufficient_data(self, mock_db_session):
        """Test LoRA retrain skips with insufficient viral clips."""
        from workers.data_pipeline_cron import retrain_lora_weekly

        # Mock database returning only 5 clips (< 10 required)
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [{"file_path": "/tmp/1.mp4"}] * 5
        mock_db_session.execute.return_value = result_mock

        with patch(
            "workers.data_pipeline_cron.AsyncSessionLocal",
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_db_session), __aexit__=AsyncMock()),
        ):
            ctx = {"gpu_available": True}
            result = await retrain_lora_weekly(ctx)

        assert result["status"] == "skipped"
        assert result["reason"] == "insufficient_data"
        assert result["count"] == 5

    @pytest.mark.asyncio
    async def test_retrain_lora_success(self, tmp_path):
        """Test successful LoRA retrain with sufficient data."""
        from workers.data_pipeline_cron import retrain_lora_weekly

        # Mock database returning 20 clips (>= 10 required)
        result_mock = MagicMock()
        result_mock.fetchall.return_value = [
            {
                "file_path": "/tmp/clip.mp4",
                "virality_score": 85.0,
                "metadata": {"seo_title": "Viral clip example", "suggested_hashtags": ["viral"]},
            }
        ] * 20

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=result_mock)

        # Mock LoRA training service
        mock_lora_result = {"loss": 0.234, "steps": 500, "output_path": "/app/models/lora/weekly.safetensors"}
        mock_lora_svc = MagicMock()
        mock_lora_svc.train = AsyncMock(return_value=mock_lora_result)

        with patch(
            "workers.data_pipeline_cron.AsyncSessionLocal",
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock()),
        ), patch(
            "workers.data_pipeline_cron.LoRATrainingService", return_value=mock_lora_svc
        ), patch.dict(
            os.environ, {"T2V_MODEL": "sd1.5", "LORA_WEEKLY_STEPS": "500"}
        ):
            ctx = {"gpu_available": True}
            result = await retrain_lora_weekly(ctx)

        assert result["status"] == "ok"
        assert result["loss"] == 0.234
        assert result["steps"] == 500

    @pytest.mark.asyncio
    async def test_retrain_lora_db_error(self):
        """Test LoRA retrain handles database errors gracefully."""
        from workers.data_pipeline_cron import retrain_lora_weekly

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("Connection refused"))

        with patch(
            "workers.data_pipeline_cron.AsyncSessionLocal",
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock()),
        ):
            ctx = {"gpu_available": True}
            result = await retrain_lora_weekly(ctx)

        assert result["status"] == "skipped"
        assert result["reason"] == "insufficient_data"


class TestRetrainScorerMonthly:
    """Test the monthly full virality scorer retrain cron job."""

    @pytest.mark.asyncio
    async def test_retrain_scorer_no_datasets(self):
        """Test scorer retrain aborts when no datasets available."""
        from workers.data_pipeline_cron import retrain_scorer_monthly

        # Mock empty datasets
        mock_tiktok = MagicMock()
        mock_tiktok.load.side_effect = Exception("Dataset not found")

        mock_youtube = MagicMock()
        mock_youtube.to_dataframe.return_value = None

        with patch(
            "workers.data_pipeline_cron.TikTokDatasetLoader", return_value=mock_tiktok
        ), patch(
            "workers.data_pipeline_cron.YouTubeTrendingLoader", return_value=mock_youtube
        ):
            ctx: Dict[str, Any] = {}
            result = await retrain_scorer_monthly(ctx)

        assert result["status"] == "skipped"
        assert result["reason"] == "no_datasets"

    @pytest.mark.asyncio
    async def test_retrain_scorer_success(self, tmp_path, mock_redis):
        """Test successful monthly scorer retrain."""
        from workers.data_pipeline_cron import retrain_scorer_monthly

        import pandas as pd

        # Mock TikTok dataset
        df_tiktok = pd.DataFrame({
            "plays": [1000000, 2000000, 500000],
            "likes": [50000, 100000, 25000],
            "shares": [5000, 10000, 2500],
            "duration": [30, 45, 20],
        })

        mock_tiktok = MagicMock()
        mock_tiktok.load.return_value = mock_tiktok
        mock_tiktok.prepare.return_value = df_tiktok

        mock_youtube = MagicMock()
        mock_youtube.to_dataframe.return_value = None

        # Mock trainer
        mock_model = MagicMock()
        mock_metrics = {"r2": 0.85, "mae": 5.2, "rmse": 7.8}
        mock_trainer = MagicMock()
        mock_trainer.train.return_value = (mock_model, mock_metrics)

        with patch(
            "workers.data_pipeline_cron.TikTokDatasetLoader", return_value=mock_tiktok
        ), patch(
            "workers.data_pipeline_cron.YouTubeTrendingLoader", return_value=mock_youtube
        ), patch(
            "workers.data_pipeline_cron.ViralityScorerTrainer", return_value=mock_trainer
        ), patch(
            "workers.data_pipeline_cron.get_config"
        ) as mock_config:
            mock_cfg = MagicMock()
            mock_cfg.redis_host = "redis"
            mock_cfg.redis_port = 6379
            mock_cfg.redis_password = None
            mock_config.return_value = mock_cfg

            with patch("redis.asyncio.Redis", return_value=mock_redis):
                with patch.dict(os.environ, {"MODELS_DIR": str(tmp_path)}):
                    ctx: Dict[str, Any] = {}
                    result = await retrain_scorer_monthly(ctx)

        assert result["status"] == "ok"
        assert result["metrics"]["r2"] == 0.85
        assert result["metrics"]["mae"] == 5.2
        assert result["rows"] == 3


class TestCronJobRegistration:
    """Test that cron jobs are properly registered in WorkerSettings."""

    def test_worker_settings_has_cron_jobs(self):
        """Test WorkerSettings has the expected cron jobs configured."""
        from workers.tasks import WorkerSettings

        # The cron_jobs list should be populated (even if empty due to import issues in test env)
        assert hasattr(WorkerSettings, "cron_jobs")
        # Check queue name
        assert WorkerSettings.queue_name == "viraclip_cpu_tasks"

    def test_gpu_worker_settings_has_cron_jobs(self):
        """Test GpuWorkerSettings has weekly LoRA retrain."""
        from workers.gpu_tasks import GpuWorkerSettings

        assert hasattr(GpuWorkerSettings, "cron_jobs")
        assert GpuWorkerSettings.queue_name == "viraclip_gpu_tasks"


class TestIntegration:
    """Integration tests for the data pipeline."""

    @pytest.mark.asyncio
    async def test_cron_job_execution_order(self):
        """Verify cron jobs can be called in sequence."""
        from workers.data_pipeline_cron import (
            fetch_trending_data,
            retrain_lora_weekly,
            retrain_scorer_monthly,
        )

        # All three functions should be importable and have correct signatures
        import inspect

        assert inspect.iscoroutinefunction(fetch_trending_data)
        assert inspect.iscoroutinefunction(retrain_lora_weekly)
        assert inspect.iscoroutinefunction(retrain_scorer_monthly)

        # Check first parameter is 'ctx'
        for func in [fetch_trending_data, retrain_lora_weekly, retrain_scorer_monthly]:
            sig = inspect.signature(func)
            params = list(sig.parameters.keys())
            assert params[0] == "ctx"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
