"""
Tests for the 9 newly wired service routes:
scene_detection, vector_search, vfx, video_polish,
onnx, kubernetes, image_gen, federated_learning, external_analytics
"""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_app(*routers):
    app = FastAPI()
    for r in routers:
        app.include_router(r)
    return app


# ══════════════════════════════════════════════════════════════════════════════
# Scene Detection
# ══════════════════════════════════════════════════════════════════════════════

class TestSceneDetectionRoutes(unittest.TestCase):

    def setUp(self):
        from src.api.routes.scene_detection import router
        self.app = _make_app(router)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def _mock_svc(self):
        svc = MagicMock()
        mock_scene = MagicMock()
        mock_scene.start_time = 0.0
        mock_scene.end_time = 5.0
        mock_scene.change_type = MagicMock(value="cut")
        mock_scene.confidence = 0.95
        svc.detect_scenes = AsyncMock(return_value=[mock_scene])
        svc.get_scene_statistics = MagicMock(return_value={"count": 1})

        mock_cut = MagicMock()
        mock_cut.timestamp = 2.5
        mock_cut.confidence = 0.8
        mock_cut.reason = "silence"
        mock_cut.suggested_transition = "jump_cut"
        svc.find_optimal_cut_points = AsyncMock(return_value=[mock_cut])
        svc.extract_keyframes = AsyncMock(return_value=[{"path": "/tmp/kf.jpg"}])
        svc.suggest_clip_boundaries = MagicMock(return_value=[{"start": 0.0, "end": 30.0}])
        return svc

    def test_detect_scenes_success(self):
        with patch("src.api.routes.scene_detection.get_scene_detection_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/scene/detect", json={"video_path": "/tmp/v.mp4"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["scene_count"], 1)
        self.assertEqual(data["scenes"][0]["change_type"], "cut")

    def test_detect_scenes_invalid_method(self):
        resp = self.client.post("/scene/detect",
                                json={"video_path": "/tmp/v.mp4", "method": "magic"})
        self.assertEqual(resp.status_code, 422)

    def test_cut_points_success(self):
        with patch("src.api.routes.scene_detection.get_scene_detection_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/scene/cut-points", json={"video_path": "/tmp/v.mp4"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["cut_point_count"], 1)

    def test_extract_keyframes_success(self):
        with patch("src.api.routes.scene_detection.get_scene_detection_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/scene/keyframes",
                                    json={"video_path": "/tmp/v.mp4", "timestamps": [1.0, 3.0]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["requested"], 2)

    def test_clip_boundaries_success(self):
        with patch("src.api.routes.scene_detection.get_scene_detection_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/scene/clip-boundaries", json={
                "cut_points": [{"timestamp": 2.5, "confidence": 0.8}],
                "target_duration": 30.0,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["suggestions"]), 1)

    def test_detect_scenes_service_error(self):
        svc = MagicMock()
        svc.detect_scenes = AsyncMock(side_effect=RuntimeError("ffmpeg failed"))
        with patch("src.api.routes.scene_detection.get_scene_detection_service",
                   return_value=svc):
            resp = self.client.post("/scene/detect", json={"video_path": "/tmp/v.mp4"})
        self.assertEqual(resp.status_code, 500)


# ══════════════════════════════════════════════════════════════════════════════
# Vector Search
# ══════════════════════════════════════════════════════════════════════════════

class TestVectorSearchRoutes(unittest.TestCase):

    def setUp(self):
        from src.api.routes.vector_search import router
        import src.api.routes.vector_search as mod
        mod._svc = None
        self.app = _make_app(router)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def _mock_svc(self):
        svc = MagicMock()
        svc.initialize = AsyncMock()
        svc.index_clip = AsyncMock(return_value={"keyframes": 3, "transcripts": 5})
        sr = MagicMock()
        sr.clip_id = "clip_1"
        sr.timestamp = 1.0
        sr.score = 0.9
        sr.modality = "text"
        sr.metadata = {}
        svc.search_multimodal = AsyncMock(return_value=[sr])
        svc.search_by_visual = AsyncMock(return_value=[{"clip_id": "clip_1"}])
        svc.search_by_text = AsyncMock(return_value=[{"clip_id": "clip_1"}])
        svc.delete_clip = AsyncMock()
        svc.get_stats = AsyncMock(return_value={"total_vectors": 10})
        return svc

    def test_index_clip(self):
        with patch("src.api.routes.vector_search.MilvusVectorService",
                   return_value=self._mock_svc()):
            resp = self.client.post("/vector/index", json={"clip_id": "clip_1"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("indexed", resp.json())

    def test_search_multimodal(self):
        with patch("src.api.routes.vector_search.MilvusVectorService",
                   return_value=self._mock_svc()):
            resp = self.client.post("/vector/search",
                                    json={"query": "ocean wave", "modality": "text"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["result_count"], 1)

    def test_search_invalid_modality(self):
        resp = self.client.post("/vector/search",
                                json={"query": "test", "modality": "audio"})
        self.assertEqual(resp.status_code, 422)

    def test_search_visual(self):
        with patch("src.api.routes.vector_search.MilvusVectorService",
                   return_value=self._mock_svc()):
            resp = self.client.post("/vector/search/visual", json={"query": "face"})
        self.assertEqual(resp.status_code, 200)

    def test_search_text(self):
        with patch("src.api.routes.vector_search.MilvusVectorService",
                   return_value=self._mock_svc()):
            resp = self.client.post("/vector/search/text", json={"query": "hello world"})
        self.assertEqual(resp.status_code, 200)

    def test_delete_clip(self):
        with patch("src.api.routes.vector_search.MilvusVectorService",
                   return_value=self._mock_svc()):
            resp = self.client.delete("/vector/clip/clip_1")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["deleted"])

    def test_get_stats(self):
        with patch("src.api.routes.vector_search.MilvusVectorService",
                   return_value=self._mock_svc()):
            resp = self.client.get("/vector/stats")
        self.assertEqual(resp.status_code, 200)


# ══════════════════════════════════════════════════════════════════════════════
# VFX
# ══════════════════════════════════════════════════════════════════════════════

class TestVFXRoutes(unittest.TestCase):

    def setUp(self):
        from src.api.routes.vfx import router
        self.app = _make_app(router)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_apply_generative_style(self):
        with patch("src.api.routes.vfx.VFXService.apply_generative_style",
                   new_callable=AsyncMock, return_value="/tmp/styled.mp4"):
            resp = self.client.post("/vfx/style", json={
                "video_path": "/tmp/v.mp4",
                "style_references": ["cinematic"],
                "intensity": 0.7,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["intensity"], 0.7)

    def test_apply_style_no_references(self):
        resp = self.client.post("/vfx/style", json={
            "video_path": "/tmp/v.mp4",
            "style_references": [],
        })
        self.assertEqual(resp.status_code, 422)

    def test_kling_swap(self):
        with patch("src.api.routes.vfx.VFXService.generate_kling_swap",
                   new_callable=AsyncMock, return_value="/tmp/swap.mp4"):
            resp = self.client.post("/vfx/kling-swap", json={
                "video_path": "/tmp/v.mp4",
                "swap_type": "wardrobe",
                "target_description": "red shirt",
            })
        self.assertEqual(resp.status_code, 200)

    def test_detect_viral_loops(self):
        with patch("src.api.routes.vfx.VFXService.detect_viral_loops",
                   new_callable=AsyncMock, return_value=[{"start": 0.0, "end": 3.0}]):
            resp = self.client.post("/vfx/viral-loops", json={"video_path": "/tmp/v.mp4"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["loop_count"], 1)

    def test_elite_branding(self):
        with patch("src.api.routes.vfx.VFXService.generate_elite_branding",
                   new_callable=AsyncMock, return_value="/tmp/branded.mp4"):
            resp = self.client.post("/vfx/branding", json={
                "video_path": "/tmp/v.mp4",
                "brand_dna": {"color": "#ff0000"},
            })
        self.assertEqual(resp.status_code, 200)

    def test_vfx_service_error(self):
        with patch("src.api.routes.vfx.VFXService.detect_viral_loops",
                   new_callable=AsyncMock, side_effect=Exception("gpu error")):
            resp = self.client.post("/vfx/viral-loops", json={"video_path": "/tmp/v.mp4"})
        self.assertEqual(resp.status_code, 500)


# ══════════════════════════════════════════════════════════════════════════════
# Video Polish
# ══════════════════════════════════════════════════════════════════════════════

class TestVideoPolishRoutes(unittest.TestCase):

    def setUp(self):
        from src.api.routes.video_polish import router
        import src.api.routes.video_polish as mod
        mod._svc = None
        self.app = _make_app(router)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def _mock_svc(self):
        svc = MagicMock()
        svc.auto_center_face = AsyncMock(return_value=True)
        svc.apply_eye_contact_correction = AsyncMock()
        svc.apply_pattern_interrupts = AsyncMock(return_value=True)
        return svc

    def test_auto_center_face(self):
        with patch("src.api.routes.video_polish.VideoPolishService",
                   return_value=self._mock_svc()):
            resp = self.client.post("/polish/auto-center-face", json={
                "input_path": "/tmp/in.mp4",
                "output_path": "/tmp/out.mp4",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    def test_eye_contact_correction(self):
        with patch("src.api.routes.video_polish.VideoPolishService",
                   return_value=self._mock_svc()):
            resp = self.client.post("/polish/eye-contact", json={
                "input_path": "/tmp/in.mp4",
                "output_path": "/tmp/out.mp4",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["applied"])

    def test_pattern_interrupts(self):
        with patch("src.api.routes.video_polish.VideoPolishService",
                   return_value=self._mock_svc()):
            resp = self.client.post("/polish/pattern-interrupts", json={
                "input_path": "/tmp/in.mp4",
                "output_path": "/tmp/out.mp4",
                "viral_cues": [{"t": 1.5, "type": "audio_peak"}],
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["cues_applied"], 1)


# ══════════════════════════════════════════════════════════════════════════════
# ONNX Inference
# ══════════════════════════════════════════════════════════════════════════════

class TestOnnxRoutes(unittest.TestCase):

    def setUp(self):
        from src.api.routes.onnx import router
        self.app = _make_app(router)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def _mock_svc(self):
        svc = MagicMock()
        svc.get_capabilities = MagicMock(return_value={
            "viral_scorer_onnx": False,
            "engagement_onnx": False,
        })
        svc.predict_virality = MagicMock(return_value=72)
        svc.is_viral_scorer_available = MagicMock(return_value=False)
        svc.predict_engagement = MagicMock(return_value={"engagement_curve": [0.8, 0.7, 0.6]})
        svc.is_engagement_available = MagicMock(return_value=False)
        return svc

    def test_capabilities(self):
        with patch("src.api.routes.onnx.get_onnx_service",
                   return_value=self._mock_svc()):
            resp = self.client.get("/onnx/capabilities")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("viral_scorer_onnx", resp.json())

    def test_predict_virality(self):
        with patch("src.api.routes.onnx.get_onnx_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/onnx/predict/virality", json={
                "transcript": "This is an amazing product you need to buy right now!",
                "duration": 20.0,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["virality_score"], 72)
        self.assertEqual(resp.json()["model"], "fallback")

    def test_predict_virality_missing_transcript(self):
        resp = self.client.post("/onnx/predict/virality", json={"duration": 20.0})
        self.assertEqual(resp.status_code, 422)

    def test_predict_engagement(self):
        with patch("src.api.routes.onnx.get_onnx_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/onnx/predict/engagement", json={
                "words": [{"text": "hello", "start": 0.0, "end": 0.5}],
            })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("engagement_curve", resp.json())


# ══════════════════════════════════════════════════════════════════════════════
# Kubernetes Scaling
# ══════════════════════════════════════════════════════════════════════════════

class TestKubernetesRoutes(unittest.TestCase):

    def setUp(self):
        from src.api.routes.kubernetes import router
        self.app = _make_app(router)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def _mock_svc(self):
        svc = MagicMock()
        svc.get_cluster_metrics = AsyncMock(return_value={"avg_cpu_utilization": 45.0, "queue_depth": 3})
        svc.get_worker_status = MagicMock(return_value=[{"pod_id": "w1", "status": "running"}])
        svc.get_scaling_history = MagicMock(return_value=[{"event_id": "e1", "action": "scale_up"}])
        svc.get_scaling_stats = MagicMock(return_value={"total_scale_events": 5})
        svc.evaluate_scaling_needs = AsyncMock(return_value=None)
        svc.predict_scaling_needs = AsyncMock(return_value={"prediction": "stable"})
        mock_event = MagicMock()
        mock_event.event_id = "e1"
        mock_event.timestamp = "2026-04-05T21:00:00"
        mock_event.action = "scale_up"
        svc.auto_scale = AsyncMock(return_value=None)
        svc.execute_scaling = AsyncMock(return_value=True)
        return svc

    def test_cluster_metrics(self):
        with patch("src.api.routes.kubernetes.get_kubernetes_scaling_service",
                   return_value=self._mock_svc()):
            resp = self.client.get("/kubernetes/metrics")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("avg_cpu_utilization", resp.json())

    def test_worker_status(self):
        with patch("src.api.routes.kubernetes.get_kubernetes_scaling_service",
                   return_value=self._mock_svc()):
            resp = self.client.get("/kubernetes/workers")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["worker_count"], 1)

    def test_scaling_history(self):
        with patch("src.api.routes.kubernetes.get_kubernetes_scaling_service",
                   return_value=self._mock_svc()):
            resp = self.client.get("/kubernetes/scaling/history")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["event_count"], 1)

    def test_scaling_stats(self):
        with patch("src.api.routes.kubernetes.get_kubernetes_scaling_service",
                   return_value=self._mock_svc()):
            resp = self.client.get("/kubernetes/scaling/stats")
        self.assertEqual(resp.status_code, 200)

    def test_evaluate_no_action_needed(self):
        with patch("src.api.routes.kubernetes.get_kubernetes_scaling_service",
                   return_value=self._mock_svc()):
            resp = self.client.get("/kubernetes/scaling/evaluate")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["action"], "none")

    def test_auto_scale_no_action(self):
        with patch("src.api.routes.kubernetes.get_kubernetes_scaling_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/kubernetes/scaling/auto")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["scaled"])

    def test_execute_scaling(self):
        with patch("src.api.routes.kubernetes.get_kubernetes_scaling_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/kubernetes/scaling/execute",
                                    json={"decision": {"action": "scale_up", "replicas": 5}})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["executed"])


# ══════════════════════════════════════════════════════════════════════════════
# Image Generation
# ══════════════════════════════════════════════════════════════════════════════

class TestImageGenRoutes(unittest.TestCase):

    def setUp(self):
        from src.api.routes.image_gen import router
        self.app = _make_app(router)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_generate_image_success(self):
        from pathlib import Path
        with patch("src.api.routes.image_gen.ImageGenService") as MockCls:
            inst = MagicMock()
            inst.generate_image = AsyncMock(return_value=Path("/tmp/gen.jpg"))
            MockCls.return_value = inst
            resp = self.client.post("/image-gen/generate", json={
                "prompt": "sunset over ocean cinematic 9:16",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("output_path", resp.json())

    def test_generate_image_unavailable(self):
        with patch("src.api.routes.image_gen.ImageGenService") as MockCls:
            inst = MagicMock()
            inst.generate_image = AsyncMock(return_value=None)
            MockCls.return_value = inst
            resp = self.client.post("/image-gen/generate", json={
                "prompt": "ocean",
            })
        self.assertEqual(resp.status_code, 503)

    def test_generate_image_invalid_aspect_ratio(self):
        resp = self.client.post("/image-gen/generate", json={
            "prompt": "test",
            "aspect_ratio": "3:4",
        })
        self.assertEqual(resp.status_code, 422)

    def test_ken_burns_prompt(self):
        with patch("src.api.routes.image_gen.ImageGenService") as MockCls:
            inst = MagicMock()
            inst.create_ken_burns_prompt = MagicMock(return_value="cinematic ocean sunset")
            MockCls.return_value = inst
            resp = self.client.post("/image-gen/ken-burns-prompt", json={
                "video_context": "outdoor interview",
                "transcript_segment": "the ocean was beautiful",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("generated_prompt", resp.json())


# ══════════════════════════════════════════════════════════════════════════════
# Federated Learning
# ══════════════════════════════════════════════════════════════════════════════

class TestFederatedLearningRoutes(unittest.TestCase):

    def setUp(self):
        from src.api.routes.federated_learning import router
        self.app = _make_app(router)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def _mock_svc(self):
        svc = MagicMock()
        svc.register_client = AsyncMock(return_value=True)
        svc.get_client_stats = MagicMock(return_value={"total_clients": 3, "active_clients": 2})

        mock_round = MagicMock()
        mock_round.round_id = "r_001"
        mock_round.model_type = MagicMock(value="virality_predictor")
        mock_round.status = MagicMock(value="collecting")
        mock_round.target_clients = 10
        svc.start_round = AsyncMock(return_value=mock_round)

        svc.get_round_status = MagicMock(return_value={"round_id": "r_001", "status": "collecting"})
        svc.submit_client_update = AsyncMock(return_value=True)
        svc.get_training_history = MagicMock(return_value=[{"round_id": "r_001"}])
        svc.get_model_performance = MagicMock(return_value={"accuracy": 0.87})
        return svc

    def test_register_client(self):
        with patch("src.api.routes.federated_learning.get_federated_learning_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/federated/clients/register", json={
                "client_id": "c_001",
                "model_types": ["virality_predictor"],
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["registered"])

    def test_register_invalid_model_type(self):
        with patch("src.api.routes.federated_learning.get_federated_learning_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/federated/clients/register", json={
                "client_id": "c_001",
                "model_types": ["nonexistent_model"],
            })
        self.assertEqual(resp.status_code, 422)

    def test_get_client_stats(self):
        with patch("src.api.routes.federated_learning.get_federated_learning_service",
                   return_value=self._mock_svc()):
            resp = self.client.get("/federated/clients/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total_clients"], 3)

    def test_start_round(self):
        with patch("src.api.routes.federated_learning.get_federated_learning_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/federated/rounds/start",
                                    json={"model_type": "virality_predictor"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["round_id"], "r_001")

    def test_start_round_invalid_type(self):
        with patch("src.api.routes.federated_learning.get_federated_learning_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/federated/rounds/start",
                                    json={"model_type": "fake_model"})
        self.assertEqual(resp.status_code, 422)

    def test_get_round_status(self):
        with patch("src.api.routes.federated_learning.get_federated_learning_service",
                   return_value=self._mock_svc()):
            resp = self.client.get("/federated/rounds/r_001/status")
        self.assertEqual(resp.status_code, 200)

    def test_get_round_status_not_found(self):
        svc = self._mock_svc()
        svc.get_round_status = MagicMock(return_value=None)
        with patch("src.api.routes.federated_learning.get_federated_learning_service",
                   return_value=svc):
            resp = self.client.get("/federated/rounds/missing_round/status")
        self.assertEqual(resp.status_code, 404)

    def test_submit_update(self):
        with patch("src.api.routes.federated_learning.get_federated_learning_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/federated/rounds/update", json={
                "round_id": "r_001",
                "client_id": "c_001",
                "weights": {"layer1": [0.1, 0.2, 0.3]},
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["accepted"])

    def test_get_history(self):
        with patch("src.api.routes.federated_learning.get_federated_learning_service",
                   return_value=self._mock_svc()):
            resp = self.client.get("/federated/history")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["event_count"], 1)

    def test_get_model_performance(self):
        with patch("src.api.routes.federated_learning.get_federated_learning_service",
                   return_value=self._mock_svc()):
            resp = self.client.get("/federated/models/virality_predictor/performance")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("accuracy", resp.json())


# ══════════════════════════════════════════════════════════════════════════════
# External Analytics
# ══════════════════════════════════════════════════════════════════════════════

class TestExternalAnalyticsRoutes(unittest.TestCase):

    def setUp(self):
        from src.api.routes.external_analytics import router
        self.app = _make_app(router)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def _mock_svc(self):
        svc = MagicMock()
        svc.get_provider_status = MagicMock(return_value={
            "configured_providers": ["mixpanel"],
            "active_providers": 1,
        })
        mock_config = MagicMock()
        mock_config.enabled = True
        svc.configure_provider = AsyncMock(return_value=mock_config)
        svc.track_event = AsyncMock(return_value=True)
        svc.identify_user = AsyncMock(return_value=True)
        svc.track_video_metrics = AsyncMock()
        svc.export_analytics_data = AsyncMock(return_value={"events": 100})
        return svc

    def test_get_provider_status(self):
        with patch("src.api.routes.external_analytics.get_external_analytics_service",
                   return_value=self._mock_svc()):
            resp = self.client.get("/external-analytics/providers/status")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("active_providers", resp.json())

    def test_configure_provider(self):
        with patch("src.api.routes.external_analytics.get_external_analytics_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/external-analytics/providers/configure", json={
                "provider": "mixpanel",
                "api_key": "test_key_123",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["configured"])

    def test_configure_invalid_provider(self):
        with patch("src.api.routes.external_analytics.get_external_analytics_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/external-analytics/providers/configure", json={
                "provider": "unknown_provider",
                "api_key": "key",
            })
        self.assertEqual(resp.status_code, 422)

    def test_track_event(self):
        with patch("src.api.routes.external_analytics.get_external_analytics_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/external-analytics/events/track", json={
                "event_name": "clip_created",
                "user_id": "u_001",
                "properties": {"clip_id": "c_001"},
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["sent"])

    def test_identify_user(self):
        with patch("src.api.routes.external_analytics.get_external_analytics_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/external-analytics/users/identify", json={
                "user_id": "u_001",
                "traits": {"plan": "pro", "country": "ES"},
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["identified"])

    def test_track_video_metrics(self):
        with patch("src.api.routes.external_analytics.get_external_analytics_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/external-analytics/video/track", json={
                "user_id": "u_001",
                "clip_id": "c_001",
                "metrics": {"views": 1000, "likes": 50},
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["tracked"])

    def test_export_analytics(self):
        with patch("src.api.routes.external_analytics.get_external_analytics_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/external-analytics/export", json={
                "start_date": "2026-03-01",
                "end_date": "2026-04-01",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("events", resp.json())


if __name__ == "__main__":
    unittest.main()
