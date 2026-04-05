"""
Tests for LLM ops endpoints and clip thumbs rating.

Covers:
  - GET  /llm-ops/dataset/stats
  - GET  /llm-ops/routing/status
  - GET  /llm-ops/rust-agent/status
  - POST /llm-ops/dataset/export/dspy       (400 when not enough examples)
  - POST /llm-ops/dataset/export/finetuning (400 when not enough examples)
  - POST /llm-ops/optimize/dspy             (400 when not enough examples)
  - POST /clips/{id}/thumbs                 (happy path + dataset side-effect)
  - POST /clips/{id}/rating                 (new optional task_id field)
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_dataset_dir(tmp_path):
    """Create a temporary dataset directory with a few examples."""
    ds_file = tmp_path / "viraclip_llm_training.jsonl"
    examples = [
        {
            "id": f"ex{i:04d}",
            "task_id": f"task_{i}",
            "timestamp": "2026-04-04T00:00:00",
            "transcript": f"Sample transcript {i}",
            "llm_output": {"segments": [{"start": "0:10", "end": "0:40", "score": 80}]},
            "user_rating": "positive" if i % 3 != 0 else "negative",
            "metadata": {},
        }
        for i in range(10)
    ]
    ds_file.write_text("\n".join(json.dumps(e) for e in examples))
    return str(tmp_path)


@pytest.fixture
def tmp_dataset_dir_dspy_ready(tmp_path):
    """Dataset with 60 examples — past DSPy threshold."""
    ds_file = tmp_path / "viraclip_llm_training.jsonl"
    examples = [
        {
            "id": f"ex{i:04d}",
            "task_id": f"task_{i}",
            "timestamp": "2026-04-04T00:00:00",
            "transcript": f"Sample transcript {i}",
            "llm_output": {"segments": [{"start": "0:10", "end": "0:40", "score": 80}]},
            "user_rating": "positive",
            "metadata": {},
        }
        for i in range(60)
    ]
    ds_file.write_text("\n".join(json.dumps(e) for e in examples))
    return str(tmp_path)


# ─────────────────────────────────────────────────────────────────────────────
# DatasetCollector unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDatasetCollector:
    @pytest.mark.asyncio
    async def test_get_stats_empty(self, tmp_path):
        from src.services.dataset_collector import DatasetCollector
        collector = DatasetCollector(str(tmp_path))
        stats = await collector.get_stats()
        assert stats["total_examples"] == 0
        assert stats["ready_for_dspy"] is False
        assert stats["ready_for_finetuning"] is False

    @pytest.mark.asyncio
    async def test_get_stats_with_examples(self, tmp_dataset_dir):
        from src.services.dataset_collector import DatasetCollector
        collector = DatasetCollector(tmp_dataset_dir)
        stats = await collector.get_stats()
        assert stats["total_examples"] == 10
        assert stats["positive"] == 6   # indices where i%3 != 0 → 1,2,4,5,7,8
        assert stats["negative"] == 4
        assert stats["ready_for_dspy"] is False       # 10 < 50
        assert stats["ready_for_finetuning"] is False  # 10 < 200

    @pytest.mark.asyncio
    async def test_dspy_ready_threshold(self, tmp_dataset_dir_dspy_ready):
        from src.services.dataset_collector import DatasetCollector
        collector = DatasetCollector(tmp_dataset_dir_dspy_ready)
        stats = await collector.get_stats()
        assert stats["total_examples"] == 60
        assert stats["ready_for_dspy"] is True
        assert stats["ready_for_finetuning"] is False  # 60 < 200

    @pytest.mark.asyncio
    async def test_record_interaction(self, tmp_path):
        from src.services.dataset_collector import DatasetCollector
        collector = DatasetCollector(str(tmp_path))

        example_id = await collector.record_interaction(
            task_id="task_001",
            transcript="Test transcript",
            llm_output={"segments": []},
            user_rating="positive",
        )

        assert len(example_id) == 16  # sha256 truncated
        stats = await collector.get_stats()
        assert stats["total_examples"] == 1

    @pytest.mark.asyncio
    async def test_add_user_feedback_updates_rating(self, tmp_dataset_dir):
        from src.services.dataset_collector import DatasetCollector
        collector = DatasetCollector(tmp_dataset_dir)

        # task_3 was "negative" (3 % 3 == 0)
        await collector.add_user_feedback(
            task_id="task_3",
            clip_id="clip_abc",
            rating="thumbs_up",
        )

        stats = await collector.get_stats()
        # Should now be positive (thumbs_up overwrites); was 6, now 7
        assert stats["positive"] == 7

    @pytest.mark.asyncio
    async def test_export_for_dspy(self, tmp_dataset_dir_dspy_ready, tmp_path):
        from src.services.dataset_collector import DatasetCollector
        collector = DatasetCollector(tmp_dataset_dir_dspy_ready)
        out = str(tmp_path / "dspy_out.json")
        exported = await collector.export_for_dspy(out)

        assert Path(exported).exists()
        with open(exported) as f:
            data = json.load(f)
        assert len(data) == 60  # all positive


# ─────────────────────────────────────────────────────────────────────────────
# LLM Router unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMRouter:
    @pytest.mark.asyncio
    async def test_selects_groq_below_threshold(self):
        from src.services.llm_router import LLMRouter, LLMBackend
        router = LLMRouter()
        backend = await router.select_backend(dataset_size=10)
        assert backend == LLMBackend.GROQ

    @pytest.mark.asyncio
    async def test_selects_groq_when_dspy_not_available(self):
        from src.services.llm_router import LLMRouter, LLMBackend
        router = LLMRouter()
        router.dspy_available = False
        backend = await router.select_backend(dataset_size=100)
        assert backend == LLMBackend.GROQ  # dspy_available=False → fallback

    @pytest.mark.asyncio
    async def test_selects_ollama_dspy_when_available(self):
        from src.services.llm_router import LLMRouter, LLMBackend
        router = LLMRouter()
        router.dspy_available = True
        backend = await router.select_backend(dataset_size=60, language="en")
        assert backend == LLMBackend.OLLAMA_DSPY

    @pytest.mark.asyncio
    async def test_selects_finetuned_when_available(self):
        from src.services.llm_router import LLMRouter, LLMBackend
        router = LLMRouter()
        router.dspy_available = True
        router.finetuned_available = True
        backend = await router.select_backend(dataset_size=250, language="en")
        assert backend == LLMBackend.OLLAMA_FINETUNED

    @pytest.mark.asyncio
    async def test_force_backend_override(self):
        from src.services.llm_router import LLMRouter, LLMBackend
        router = LLMRouter()
        router.finetuned_available = True
        backend = await router.select_backend(
            dataset_size=300,
            force_backend=LLMBackend.GROQ
        )
        assert backend == LLMBackend.GROQ

    @pytest.mark.asyncio
    async def test_unsupported_language_falls_back_to_groq(self):
        from src.services.llm_router import LLMRouter, LLMBackend
        router = LLMRouter()
        router.dspy_available = True
        # "zh" not in supported list
        backend = await router.select_backend(dataset_size=100, language="zh")
        assert backend == LLMBackend.GROQ

    @pytest.mark.asyncio
    async def test_get_routing_stats(self):
        from src.services.llm_router import LLMRouter
        router = LLMRouter()
        stats = await router.get_routing_stats()
        assert "current_backend" in stats
        assert stats["thresholds"]["dspy_minimum"] == 50
        assert stats["thresholds"]["finetuning_minimum"] == 200


# ─────────────────────────────────────────────────────────────────────────────
# Config unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigNewFields:
    def test_rust_agent_url_default(self, monkeypatch):
        monkeypatch.delenv("RUST_AGENT_URL", raising=False)
        from src.config import Config
        cfg = Config()
        assert cfg.rust_agent_url == "http://rust-agent:8001"

    def test_rust_agent_url_from_env(self, monkeypatch):
        monkeypatch.setenv("RUST_AGENT_URL", "http://custom-agent:9999")
        from src.config import Config
        cfg = Config()
        assert cfg.rust_agent_url == "http://custom-agent:9999"

    def test_rust_agent_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("RUST_AGENT_ENABLED", raising=False)
        from src.config import Config
        cfg = Config()
        assert cfg.rust_agent_enabled is False

    def test_llm_routing_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("LLM_ROUTING_ENABLED", raising=False)
        from src.config import Config
        cfg = Config()
        assert cfg.llm_routing_enabled is False

    def test_dataset_dir_default(self, monkeypatch):
        monkeypatch.delenv("DATASET_DIR", raising=False)
        from src.config import Config
        cfg = Config()
        assert cfg.dataset_dir == "/app/datasets"


# ─────────────────────────────────────────────────────────────────────────────
# Clips endpoint tests
# ─────────────────────────────────────────────────────────────────────────────

class TestClipsThumbsEndpoint:
    """Unit-test the thumbs endpoint logic without a real DB."""

    @pytest.mark.asyncio
    async def test_thumbs_up_calls_dataset_collector(self, tmp_path):
        from src.api.routes.clips import thumbs_clip, ThumbsRequest

        mock_db = AsyncMock()
        mock_clip = MagicMock()
        mock_clip.id = "clip_001"

        with patch(
            "src.repositories.clip_repository.ClipRepository.update_clip_rating",
            new=AsyncMock(return_value=mock_clip),
        ), patch(
            "src.services.dataset_collector.get_dataset_collector"
        ) as mock_get_collector, patch(
            "src.config.get_config"
        ) as mock_config:
            mock_config.return_value.dataset_dir = str(tmp_path)
            mock_collector = AsyncMock()
            mock_collector.add_user_feedback = AsyncMock()
            mock_collector.get_stats = AsyncMock(return_value={
                "total_examples": 1,
                "ready_for_dspy": False,
                "ready_for_finetuning": False,
            })
            mock_get_collector.return_value = mock_collector

            result = await thumbs_clip(
                clip_id="clip_001",
                body=ThumbsRequest(rating="thumbs_up", task_id="task_abc"),
                db=mock_db,
            )

        assert result["rating"] == "thumbs_up"
        assert result["recorded_for_training"] is True
        mock_collector.add_user_feedback.assert_called_once_with(
            task_id="task_abc",
            clip_id="clip_001",
            rating="thumbs_up",
            feedback_text=None,
        )

    @pytest.mark.asyncio
    async def test_thumbs_without_task_id_skips_dataset(self, tmp_path):
        from src.api.routes.clips import thumbs_clip, ThumbsRequest

        mock_db = AsyncMock()
        mock_clip = MagicMock()

        with patch(
            "src.repositories.clip_repository.ClipRepository.update_clip_rating",
            new=AsyncMock(return_value=mock_clip),
        ), patch(
            "src.services.dataset_collector.get_dataset_collector"
        ) as mock_get_collector:
            result = await thumbs_clip(
                clip_id="clip_002",
                body=ThumbsRequest(rating="thumbs_down"),  # no task_id
                db=mock_db,
            )

        assert result["recorded_for_training"] is False
        mock_get_collector.assert_not_called()

    @pytest.mark.asyncio
    async def test_thumbs_clip_not_found_raises_404(self):
        from fastapi import HTTPException
        from src.api.routes.clips import thumbs_clip, ThumbsRequest

        mock_db = AsyncMock()

        with patch(
            "src.repositories.clip_repository.ClipRepository.update_clip_rating",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await thumbs_clip(
                    clip_id="nonexistent",
                    body=ThumbsRequest(rating="thumbs_up", task_id="t1"),
                    db=mock_db,
                )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_star_rating_maps_to_thumbs_correctly(self, tmp_path):
        """4-5 stars → thumbs_up, 1-2 stars → thumbs_down, 3 stars → neutral."""
        from src.api.routes.clips import rate_clip, RatingRequest

        mock_db = AsyncMock()
        mock_clip = MagicMock()

        for rating, expected_thumbs in [(5, "thumbs_up"), (4, "thumbs_up"),
                                         (3, "neutral"),
                                         (2, "thumbs_down"), (1, "thumbs_down")]:
            with patch(
                "src.repositories.clip_repository.ClipRepository.update_clip_rating",
                new=AsyncMock(return_value=mock_clip),
            ), patch(
                "src.services.dataset_collector.get_dataset_collector"
            ) as mock_get_collector, patch(
                "src.config.get_config"
            ) as mock_config:
                mock_config.return_value.dataset_dir = str(tmp_path)
                mock_collector = AsyncMock()
                mock_collector.add_user_feedback = AsyncMock()
                mock_get_collector.return_value = mock_collector

                await rate_clip(
                    clip_id="clip_001",
                    body=RatingRequest(rating=rating, task_id="task_x"),
                    db=mock_db,
                )

                call_kwargs = mock_collector.add_user_feedback.call_args
                assert call_kwargs.kwargs["rating"] == expected_thumbs, (
                    f"star={rating} should map to {expected_thumbs}, "
                    f"got {call_kwargs.kwargs['rating']}"
                )


# ─────────────────────────────────────────────────────────────────────────────
# LLM ops endpoint integration tests (no DB, mocked services)
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMOpsRoutes:
    @pytest.mark.asyncio
    async def test_dataset_stats_returns_counts(self, tmp_dataset_dir):
        from src.api.routes.llm_ops import dataset_stats

        with patch("src.config.get_config") as mock_cfg, \
             patch("src.services.dataset_collector.get_dataset_collector") as mock_gc:
            mock_cfg.return_value.dataset_dir = tmp_dataset_dir
            mock_collector = AsyncMock()
            mock_collector.get_stats = AsyncMock(return_value={
                "total_examples": 10,
                "positive": 7,
                "negative": 3,
                "neutral": 0,
                "ready_for_dspy": False,
                "ready_for_finetuning": False,
            })
            mock_gc.return_value = mock_collector

            result = await dataset_stats()

        assert result["total_examples"] == 10
        assert result["ready_for_dspy"] is False

    @pytest.mark.asyncio
    async def test_export_dspy_raises_400_below_threshold(self, tmp_dataset_dir):
        from fastapi import HTTPException
        from src.api.routes.llm_ops import export_dspy

        with patch("src.config.get_config") as mock_cfg, \
             patch("src.services.dataset_collector.get_dataset_collector") as mock_gc:
            mock_cfg.return_value.dataset_dir = tmp_dataset_dir
            mock_collector = AsyncMock()
            mock_collector.get_stats = AsyncMock(return_value={
                "total_examples": 10,
                "ready_for_dspy": False,
                "ready_for_finetuning": False,
            })
            mock_gc.return_value = mock_collector

            with pytest.raises(HTTPException) as exc:
                await export_dspy()

        assert exc.value.status_code == 400
        assert "50" in exc.value.detail

    @pytest.mark.asyncio
    async def test_export_finetuning_raises_400_below_threshold(self, tmp_dataset_dir):
        from fastapi import HTTPException
        from src.api.routes.llm_ops import export_finetuning

        with patch("src.config.get_config") as mock_cfg, \
             patch("src.services.dataset_collector.get_dataset_collector") as mock_gc:
            mock_cfg.return_value.dataset_dir = tmp_dataset_dir
            mock_collector = AsyncMock()
            mock_collector.get_stats = AsyncMock(return_value={
                "total_examples": 10,
                "ready_for_dspy": False,
                "ready_for_finetuning": False,
                "positive": 10,
            })
            mock_gc.return_value = mock_collector

            with pytest.raises(HTTPException) as exc:
                await export_finetuning()

        assert exc.value.status_code == 400
        assert "200" in exc.value.detail

    @pytest.mark.asyncio
    async def test_routing_status_returns_backend_info(self):
        from src.api.routes.llm_ops import routing_status

        with patch("src.config.get_config") as mock_cfg, \
             patch("src.services.llm_router.get_llm_router") as mock_router, \
             patch("src.services.dataset_collector.get_dataset_collector") as mock_gc:
            mock_cfg.return_value.dataset_dir = "/tmp/ds"
            mock_cfg.return_value.llm_routing_enabled = False

            mock_r = AsyncMock()
            mock_r.get_routing_stats = AsyncMock(return_value={
                "current_backend": "groq",
                "thresholds": {"dspy_minimum": 50, "finetuning_minimum": 200},
                "dspy_available": False,
                "finetuned_available": False,
            })
            mock_router.return_value = mock_r

            mock_collector = AsyncMock()
            mock_collector.get_stats = AsyncMock(return_value={
                "total_examples": 5,
                "ready_for_dspy": False,
                "ready_for_finetuning": False,
            })
            mock_gc.return_value = mock_collector

            result = await routing_status()

        assert result["current_backend"] == "groq"
        assert result["routing_enabled"] is False

    @pytest.mark.asyncio
    async def test_rust_agent_status_unavailable(self):
        from src.api.routes.llm_ops import rust_agent_status

        with patch("src.services.rust_bridge.get_rust_bridge") as mock_rb:
            mock_bridge = AsyncMock()
            mock_bridge.base_url = "http://rust-agent:8001"
            mock_bridge.health_check = AsyncMock(return_value=False)
            mock_rb.return_value = mock_bridge

            result = await rust_agent_status()

        assert result["available"] is False
        assert "rust-agent" in result["url"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
