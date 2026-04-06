"""
Tests for Phase 2.1 — YOLOv10 visual grounding for contextual B-roll.

All tests mock ultralytics and FFmpeg so they run offline on CPU without
any model weights or real video files.
"""
import asyncio
import unittest
from pathlib import Path
from typing import Set
from unittest.mock import AsyncMock, MagicMock, patch


# ══════════════════════════════════════════════════════════════════════════════
# yolo_detector.py
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectObjectsInFrame(unittest.TestCase):

    def test_returns_empty_set_when_ultralytics_missing(self):
        import src.services.yolo_detector as yd
        orig = yd._model_cache
        try:
            yd._model_cache = None
            with patch.dict("sys.modules", {"ultralytics": None}):
                with patch("src.services.yolo_detector._get_model", return_value=None):
                    result = yd.detect_objects_in_frame(Path("/fake/frame.jpg"))
            self.assertEqual(result, set())
        finally:
            yd._model_cache = orig

    def test_returns_labels_above_threshold(self):
        from src.services.yolo_detector import detect_objects_in_frame
        mock_box = MagicMock()
        mock_box.cls = [0, 1]
        mock_box.conf = [0.9, 0.2]   # 0.2 below default threshold 0.35
        mock_result = MagicMock()
        mock_result.boxes = mock_box
        mock_result.names = {0: "person", 1: "car"}
        mock_model = MagicMock(return_value=[mock_result])
        with patch("src.services.yolo_detector._get_model", return_value=mock_model):
            labels = detect_objects_in_frame(Path("/fake/frame.jpg"))
        self.assertIn("person", labels)
        self.assertNotIn("car", labels)  # conf 0.2 < threshold

    def test_labels_are_lowercased(self):
        from src.services.yolo_detector import detect_objects_in_frame
        mock_box = MagicMock()
        mock_box.cls = [0]
        mock_box.conf = [0.95]
        mock_result = MagicMock()
        mock_result.boxes = mock_box
        mock_result.names = {0: "Dog"}
        mock_model = MagicMock(return_value=[mock_result])
        with patch("src.services.yolo_detector._get_model", return_value=mock_model):
            labels = detect_objects_in_frame(Path("/fake/frame.jpg"))
        self.assertIn("dog", labels)
        self.assertNotIn("Dog", labels)

    def test_exception_returns_empty_set(self):
        from src.services.yolo_detector import detect_objects_in_frame
        mock_model = MagicMock(side_effect=RuntimeError("CUDA OOM"))
        with patch("src.services.yolo_detector._get_model", return_value=mock_model):
            result = detect_objects_in_frame(Path("/fake/frame.jpg"))
        self.assertEqual(result, set())


class TestFilterKeywordsWithYolo(unittest.TestCase):

    def test_removes_already_visible_keyword(self):
        from src.services.yolo_detector import filter_keywords_with_yolo
        result = filter_keywords_with_yolo(
            ["person", "beach", "sunset"],
            detected_labels={"person", "chair"},
        )
        self.assertNotIn("person", result)
        self.assertIn("beach", result)
        self.assertIn("sunset", result)

    def test_returns_original_when_no_labels(self):
        from src.services.yolo_detector import filter_keywords_with_yolo
        keywords = ["mountain", "snow"]
        result = filter_keywords_with_yolo(keywords, detected_labels=set())
        self.assertEqual(result, keywords)

    def test_always_keeps_at_least_one_keyword(self):
        from src.services.yolo_detector import filter_keywords_with_yolo
        # All keywords visible — should still return at least one
        result = filter_keywords_with_yolo(
            ["person"],
            detected_labels={"person"},
        )
        self.assertEqual(len(result), 1)

    def test_substring_matching(self):
        from src.services.yolo_detector import filter_keywords_with_yolo
        # "sports car" contains "car"
        result = filter_keywords_with_yolo(
            ["sports car", "beach"],
            detected_labels={"car"},
        )
        self.assertNotIn("sports car", result)
        self.assertIn("beach", result)

    def test_no_false_positive_removal(self):
        from src.services.yolo_detector import filter_keywords_with_yolo
        result = filter_keywords_with_yolo(
            ["ocean", "whale"],
            detected_labels={"person", "chair"},
        )
        self.assertIn("ocean", result)
        self.assertIn("whale", result)


class TestGetVisualContext(unittest.IsolatedAsyncioTestCase):

    async def test_returns_empty_when_yolo_disabled(self):
        import src.services.yolo_detector as yd
        orig = yd.YOLO_ENABLED
        try:
            yd.YOLO_ENABLED = False
            result = await yd.get_visual_context(Path("/fake/clip.mp4"), 30.0)
            self.assertEqual(result["detected_labels"], set())
            self.assertEqual(result["frame_count"], 0)
        finally:
            yd.YOLO_ENABLED = orig

    async def test_returns_empty_when_video_not_found(self):
        from src.services.yolo_detector import get_visual_context
        result = await get_visual_context(Path("/nonexistent/clip.mp4"), 30.0)
        self.assertEqual(result["detected_labels"], set())

    async def test_aggregates_labels_across_frames(self):
        from src.services.yolo_detector import get_visual_context
        call_count = 0

        async def mock_extract(video_path, output_path, timestamp=0.5):
            nonlocal call_count
            output_path.touch()
            call_count += 1
            return True

        def mock_detect(frame_path):
            return {"dog"} if call_count == 1 else {"cat"}

        with patch("src.services.yolo_detector.YOLO_ENABLED", True), \
             patch("src.services.yolo_detector.extract_keyframe", new=mock_extract), \
             patch("src.services.yolo_detector.detect_objects_in_frame", side_effect=mock_detect):
            result = await get_visual_context(Path(__file__), 10.0)

        self.assertGreater(result["frame_count"], 0)

    async def test_samples_multiple_frames_for_long_clip(self):
        from src.services.yolo_detector import get_visual_context, _MAX_KEYFRAMES
        extracted_timestamps = []

        async def mock_extract(video_path, output_path, timestamp=0.5):
            extracted_timestamps.append(timestamp)
            output_path.touch()
            return True

        with patch("src.services.yolo_detector.YOLO_ENABLED", True), \
             patch("src.services.yolo_detector.extract_keyframe", new=mock_extract), \
             patch("src.services.yolo_detector.detect_objects_in_frame", return_value=set()):
            await get_visual_context(Path(__file__), 30.0)

        self.assertGreaterEqual(len(extracted_timestamps), 2)
        self.assertLessEqual(len(extracted_timestamps), _MAX_KEYFRAMES)


# ══════════════════════════════════════════════════════════════════════════════
# BrollService._apply_yolo_filter integration
# ══════════════════════════════════════════════════════════════════════════════

class TestBrollServiceYoloIntegration(unittest.IsolatedAsyncioTestCase):

    def _make_service(self):
        from unittest.mock import MagicMock
        from src.services.broll_service import BrollService
        cfg = MagicMock()
        cfg.temp_dir = "/tmp"
        cfg.pexels_api_key = ""
        with patch("src.services.broll_service.BrollService.__init__", lambda self, config=None: None):
            svc = BrollService.__new__(BrollService)
            svc.config = cfg
            from pathlib import Path
            svc.broll_dir = Path("/tmp/broll")
        return svc

    async def test_apply_yolo_filter_skips_without_video_path(self):
        svc = self._make_service()
        keywords = ["beach", "sunset"]
        result = await svc._apply_yolo_filter(keywords, None, 0.0)
        self.assertEqual(result, keywords)

    async def test_apply_yolo_filter_calls_visual_context(self):
        svc = self._make_service()
        keywords = ["person", "ocean"]
        mock_ctx = {"detected_labels": {"person"}, "frame_count": 1}

        with patch("src.services.yolo_detector.get_visual_context", new=AsyncMock(return_value=mock_ctx)):
            result = await svc._apply_yolo_filter(
                keywords, Path(__file__), clip_duration=10.0
            )
        self.assertNotIn("person", result)
        self.assertIn("ocean", result)

    async def test_apply_yolo_filter_falls_back_on_exception(self):
        svc = self._make_service()
        keywords = ["mountain", "snow"]

        with patch("src.services.yolo_detector.get_visual_context",
                   new=AsyncMock(side_effect=RuntimeError("model error"))):
            result = await svc._apply_yolo_filter(
                keywords, Path(__file__), clip_duration=10.0
            )
        self.assertEqual(result, keywords)

    async def test_extract_keywords_passes_video_path_to_filter(self):
        svc = self._make_service()
        svc.config = MagicMock()
        svc.config.temp_dir = "/tmp"

        # Patch GROQ_API_KEY as missing → uses fallback path
        with patch.dict("os.environ", {}, clear=False), \
             patch("os.getenv", side_effect=lambda k, d="": "" if k == "GROQ_API_KEY" else d):
            with patch.object(svc, "_apply_yolo_filter", new=AsyncMock(return_value=["nature"])) as mock_filter:
                result = await svc.extract_keywords(
                    "beautiful nature scene",
                    video_path=Path("/fake/clip.mp4"),
                    clip_duration=15.0,
                )
        mock_filter.assert_called_once()
        call_args = mock_filter.call_args
        self.assertEqual(call_args.args[1], Path("/fake/clip.mp4"))
        self.assertEqual(result, ["nature"])


# ══════════════════════════════════════════════════════════════════════════════
# Module contract
# ══════════════════════════════════════════════════════════════════════════════

class TestYoloDetectorContract(unittest.TestCase):

    def test_module_importable(self):
        import src.services.yolo_detector as yd
        self.assertTrue(callable(yd.detect_objects_in_frame))
        self.assertTrue(callable(yd.filter_keywords_with_yolo))
        self.assertTrue(asyncio.iscoroutinefunction(yd.get_visual_context))
        self.assertTrue(asyncio.iscoroutinefunction(yd.extract_keyframe))

    def test_yolo_enabled_env_respected(self):
        import importlib
        with patch.dict("os.environ", {"YOLO_ENABLED": "false"}):
            import src.services.yolo_detector as yd
            importlib.reload(yd)
            self.assertFalse(yd.YOLO_ENABLED)

    def test_constants_have_sensible_defaults(self):
        from src.services.yolo_detector import (
            _CONF_THRESHOLD, _MAX_KEYFRAMES, _YOLO_MODEL_NAME
        )
        self.assertGreater(_CONF_THRESHOLD, 0.0)
        self.assertLess(_CONF_THRESHOLD, 1.0)
        self.assertGreaterEqual(_MAX_KEYFRAMES, 1)
        self.assertIn("yolov10", _YOLO_MODEL_NAME.lower())
