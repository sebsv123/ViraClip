"""
Tests for:
  1. AI Inference Optimization API (/ai-inference/*)
  2. Data Migration API (/data-migration/*)
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_model_profile(model_id="whisper_large"):
    from src.services.ai_inference_optimization import (
        ModelProfile, ModelFormat, OptimizationLevel,
    )
    return ModelProfile(
        model_id=model_id,
        model_name="Whisper Large v3",
        original_format=ModelFormat.PYTORCH,
        optimized_format=ModelFormat.TENSORRT,
        input_shape=(1, 80, 3000),
        output_shape=(1, 1500, 51865),
        original_size_mb=1500.0,
        optimized_size_mb=380.0,
        original_latency_ms=420.0,
        optimized_latency_ms=52.0,
        throughput_improvement=8.1,
        accuracy_loss=0.002,
        optimization_level=OptimizationLevel.MAXIMUM,
    )


def _make_export_job(job_id="exp_001"):
    from src.services.data_migration import ExportJob, DataType, ExportFormat
    return ExportJob(
        job_id=job_id,
        user_id="user_001",
        data_types=[DataType.CLIPS, DataType.ANALYTICS],
        format=ExportFormat.ZIP,
        created_at="2026-01-01T00:00:00",
        status="pending",
        file_path=None,
        file_size=0,
        error_message=None,
    )


def _make_import_job(job_id="imp_001"):
    from src.services.data_migration import ImportJob
    return ImportJob(
        job_id=job_id,
        user_id="user_001",
        source_file=Path("/app/uploads/user_001_export.zip"),
        created_at="2026-01-01T00:00:00",
        status="pending",
        records_processed=0,
        records_failed=0,
        error_log=[],
    )


# ===========================================================================
# 1. AI Inference Optimization API
# ===========================================================================

class TestAIInferenceAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.ai_inference import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_optimize_model(self):
        client = self._get_client()
        profile = _make_model_profile()
        with patch(
            "src.services.ai_inference_optimization.AIInferenceOptimizationService.optimize_model",
            new_callable=AsyncMock,
            return_value=profile,
        ):
            resp = client.post("/ai-inference/optimize", json={
                "model_id": "whisper_large",
                "model_path": "/app/models/whisper_large.pt",
                "target_format": "tensorrt",
                "precision": "fp16",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "optimized")
        self.assertEqual(data["profile"]["optimized_format"], "tensorrt")
        self.assertAlmostEqual(data["profile"]["throughput_improvement"], 8.1)

    def test_run_inference(self):
        client = self._get_client()
        results = [{"prediction": "optimized", "confidence": 0.95}]
        with patch(
            "src.services.ai_inference_optimization.AIInferenceOptimizationService.infer_optimized",
            new_callable=AsyncMock,
            return_value=results,
        ):
            resp = client.post("/ai-inference/infer", json={
                "model_id": "whisper_large",
                "inputs": [[0.1, 0.2, 0.3]],
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["results"]), 1)

    def test_run_inference_empty_inputs(self):
        client = self._get_client()
        resp = client.post("/ai-inference/infer", json={
            "model_id": "whisper_large",
            "inputs": [],
        })
        self.assertEqual(resp.status_code, 400)

    def test_quantize_model(self):
        client = self._get_client()
        with patch(
            "src.services.ai_inference_optimization.AIInferenceOptimizationService.quantize_model",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/ai-inference/quantize", json={
                "model_id": "whisper_large",
                "bits": 8,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "quantized")

    def test_quantize_invalid_bits(self):
        client = self._get_client()
        resp = client.post("/ai-inference/quantize", json={
            "model_id": "whisper_large",
            "bits": 16,
        })
        self.assertEqual(resp.status_code, 400)

    def test_prune_model(self):
        client = self._get_client()
        with patch(
            "src.services.ai_inference_optimization.AIInferenceOptimizationService.prune_model",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/ai-inference/prune", json={
                "model_id": "whisper_large",
                "sparsity": 0.5,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "pruned")

    def test_prune_invalid_sparsity(self):
        client = self._get_client()
        resp = client.post("/ai-inference/prune", json={
            "model_id": "whisper_large",
            "sparsity": 1.5,
        })
        self.assertEqual(resp.status_code, 400)

    def test_get_profile(self):
        client = self._get_client()
        profile = _make_model_profile()
        with patch(
            "src.services.ai_inference_optimization.AIInferenceOptimizationService.get_model_profile",
            return_value=profile,
        ):
            resp = client.get("/ai-inference/profiles/whisper_large")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["model_id"], "whisper_large")

    def test_get_profile_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.ai_inference_optimization.AIInferenceOptimizationService.get_model_profile",
            return_value=None,
        ):
            resp = client.get("/ai-inference/profiles/missing_model")
        self.assertEqual(resp.status_code, 404)

    def test_list_profiles(self):
        client = self._get_client()
        with patch(
            "src.services.ai_inference_optimization.AIInferenceOptimizationService.get_all_profiles",
            return_value=[_make_model_profile()],
        ):
            resp = client.get("/ai-inference/profiles")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_stats(self):
        client = self._get_client()
        with patch(
            "src.services.ai_inference_optimization.AIInferenceOptimizationService.get_optimization_stats",
            return_value={"models_optimized": 3, "avg_speedup": 6.2},
        ):
            resp = client.get("/ai-inference/stats")
        self.assertEqual(resp.status_code, 200)


# ===========================================================================
# 2. Data Migration API
# ===========================================================================

class TestDataMigrationAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.data_migration import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_create_export(self):
        client = self._get_client()
        job = _make_export_job()
        with patch(
            "src.services.data_migration.DataMigrationService.create_export",
            new_callable=AsyncMock,
            return_value=job,
        ):
            resp = client.post("/data-migration/exports", json={
                "user_id": "user_001",
                "data_types": ["clips", "analytics"],
                "export_format": "zip",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "created")
        self.assertEqual(data["job"]["format"], "zip")

    def test_create_export_empty_types(self):
        client = self._get_client()
        resp = client.post("/data-migration/exports", json={
            "user_id": "user_001",
            "data_types": [],
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_export_invalid_type(self):
        client = self._get_client()
        resp = client.post("/data-migration/exports", json={
            "user_id": "user_001",
            "data_types": ["alien_data"],
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_export_invalid_format(self):
        client = self._get_client()
        resp = client.post("/data-migration/exports", json={
            "user_id": "user_001",
            "data_types": ["clips"],
            "export_format": "docx",
        })
        self.assertEqual(resp.status_code, 400)

    def test_export_status(self):
        client = self._get_client()
        status = {
            "job_id": "exp_001", "status": "completed",
            "file_size": 1048576, "error": None,
        }
        with patch(
            "src.services.data_migration.DataMigrationService.get_export_status",
            return_value=status,
        ):
            resp = client.get("/data-migration/exports/exp_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["job"]["status"], "completed")

    def test_export_status_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.data_migration.DataMigrationService.get_export_status",
            return_value=None,
        ):
            resp = client.get("/data-migration/exports/missing")
        self.assertEqual(resp.status_code, 404)

    def test_create_import(self):
        client = self._get_client()
        job = _make_import_job()
        with patch(
            "src.services.data_migration.DataMigrationService.create_import",
            new_callable=AsyncMock,
            return_value=job,
        ):
            resp = client.post("/data-migration/imports", json={
                "user_id": "user_001",
                "source_file": "/app/uploads/user_001_export.zip",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "created")
        self.assertEqual(data["job"]["status"], "pending")

    def test_import_status(self):
        client = self._get_client()
        status = {
            "job_id": "imp_001", "status": "completed",
            "records_processed": 145, "records_failed": 0,
        }
        with patch(
            "src.services.data_migration.DataMigrationService.get_import_status",
            return_value=status,
        ):
            resp = client.get("/data-migration/imports/imp_001")
        self.assertEqual(resp.status_code, 200)

    def test_import_status_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.data_migration.DataMigrationService.get_import_status",
            return_value=None,
        ):
            resp = client.get("/data-migration/imports/missing")
        self.assertEqual(resp.status_code, 404)

    def test_list_data_types(self):
        client = self._get_client()
        resp = client.get("/data-migration/data-types")
        self.assertEqual(resp.status_code, 200)
        types = resp.json()["data_types"]
        self.assertIn("clips", types)
        self.assertIn("analytics", types)

    def test_list_export_formats(self):
        client = self._get_client()
        resp = client.get("/data-migration/export-formats")
        self.assertEqual(resp.status_code, 200)
        fmts = resp.json()["formats"]
        self.assertIn("zip", fmts)
        self.assertIn("json", fmts)


if __name__ == "__main__":
    unittest.main()
