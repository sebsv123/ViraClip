"""
Tests for all cinematic feature additions:
  - VideoPolishService.auto_center_face (MediaPipe FaceMesh two-pass)
  - CaptionService (ASS karaoke + highlight)
  - LUTService (lut3d color grading)
  - BeatSyncService (librosa BPM + BGM)
  - API routes: /captions, /lut, /beat-sync
"""
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ══════════════════════════════════════════════════════════════════════════════
# VideoPolishService — FaceMesh face-tracking
# ══════════════════════════════════════════════════════════════════════════════

class TestVideoPolishFaceMesh(unittest.TestCase):

    def test_gaussian_smooth_flat_signal(self):
        from src.services.video_polish_service import VideoPolishService
        arr = np.full(100, 540.0, dtype=np.float32)
        smoothed = VideoPolishService._gaussian_smooth(arr, sigma=8.0)
        self.assertEqual(len(smoothed), 100)
        # Reflect-padding preserves edge values — whole array should be ≈540
        np.testing.assert_allclose(smoothed, 540.0, atol=1.0)

    def test_gaussian_smooth_step(self):
        from src.services.video_polish_service import VideoPolishService
        arr = np.concatenate([np.zeros(50), np.ones(50) * 200]).astype(np.float32)
        smoothed = VideoPolishService._gaussian_smooth(arr, sigma=4.0)
        self.assertLess(smoothed[0], 10)
        self.assertGreater(smoothed[-1], 190)
        # Mid-point should be between 0 and 200 (Gaussian blending)
        self.assertGreater(smoothed[50], 50)
        self.assertLess(smoothed[50], 150)

    def test_face_centroid_from_landmarks(self):
        from src.services.video_polish_service import VideoPolishService

        class FakeLandmark:
            def __init__(self, x, y):
                self.x = x
                self.y = y

        class FakeLandmarks:
            def __init__(self):
                self.landmark = [FakeLandmark(0.5, 0.4) for _ in range(478)]

        cx, cy = VideoPolishService._face_centroid_from_landmarks(
            FakeLandmarks(), img_w=1080, img_h=1920
        )
        self.assertAlmostEqual(cx, 540.0, delta=1.0)
        self.assertAlmostEqual(cy, 768.0, delta=1.0)

    def test_auto_center_face_fallback_on_missing_video(self):
        """Missing video file → copy fallback returns False."""
        import asyncio
        from src.services.video_polish_service import VideoPolishService
        import tempfile, os

        svc = VideoPolishService()
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "nonexistent.mp4"
            out = Path(tmp) / "out.mp4"

            async def run():
                return await svc.auto_center_face(inp, out)

            with patch("src.services.video_polish_service.cv2.VideoCapture") as mock_cap:
                mock_cap_inst = MagicMock()
                mock_cap_inst.isOpened.return_value = False
                mock_cap.return_value = mock_cap_inst
                with patch("shutil.copy"):
                    result = asyncio.run(run())
            self.assertFalse(result)

    def test_two_pass_with_no_face_detected(self):
        """All frames return no face → falls back to center crop, still writes output."""
        import asyncio, tempfile
        from src.services.video_polish_service import VideoPolishService

        svc = VideoPolishService()

        def fake_two_pass(inp, out, use_mp):
            import shutil
            # Simulate: no face detected → copy
            shutil.copy(inp, out) if inp.exists() else out.touch()
            return False

        with patch.object(svc, "_center_face_two_pass", side_effect=fake_two_pass):
            with tempfile.TemporaryDirectory() as tmp:
                inp = Path(tmp) / "vid.mp4"
                out = Path(tmp) / "out.mp4"
                inp.write_bytes(b"\x00" * 100)

                result = asyncio.run(svc.auto_center_face(inp, out))
        self.assertFalse(result)

    def test_oval_landmarks_count(self):
        from src.services.video_polish_service import VideoPolishService
        # Must be ≤ 478 (FaceMesh has 478 landmarks, indices 0-477)
        self.assertTrue(all(i < 478 for i in VideoPolishService._OVAL_LM))
        self.assertGreater(len(VideoPolishService._OVAL_LM), 10)


# ══════════════════════════════════════════════════════════════════════════════
# CaptionService
# ══════════════════════════════════════════════════════════════════════════════

class TestCaptionService(unittest.TestCase):

    def _words(self):
        return [
            {"text": "Stop", "start": 0.0, "end": 0.3},
            {"text": "scrolling", "start": 0.35, "end": 0.8},
            {"text": "right", "start": 0.85, "end": 1.1},
            {"text": "now", "start": 1.15, "end": 1.4},
        ]

    def test_segment_words_basic(self):
        from src.services.caption_service import segment_words_into_lines
        lines = segment_words_into_lines(self._words(), max_words_per_line=4)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].full_text, "Stop scrolling right now")

    def test_segment_words_split_on_max(self):
        from src.services.caption_service import segment_words_into_lines
        lines = segment_words_into_lines(self._words(), max_words_per_line=2)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].full_text, "Stop scrolling")

    def test_segment_words_gap_split(self):
        from src.services.caption_service import segment_words_into_lines
        words = [
            {"text": "Hello", "start": 0.0, "end": 0.5},
            {"text": "world", "start": 0.6, "end": 1.0},
            {"text": "Next", "start": 3.0, "end": 3.3},   # gap > 0.8 → new line
            {"text": "sentence", "start": 3.4, "end": 3.9},
        ]
        lines = segment_words_into_lines(words, gap_threshold=0.8)
        self.assertEqual(len(lines), 2)

    def test_ass_time_format(self):
        from src.services.caption_service import _ass_time
        self.assertEqual(_ass_time(0.0), "0:00:00.00")
        self.assertEqual(_ass_time(3661.5), "1:01:01.50")
        self.assertEqual(_ass_time(0.25), "0:00:00.25")

    def test_build_ass_script_tiktok(self):
        from src.services.caption_service import (
            build_ass_script, segment_words_into_lines
        )
        lines = segment_words_into_lines(self._words())
        ass = build_ass_script(lines, style="tiktok")
        self.assertIn("[Script Info]", ass)
        self.assertIn("[V4+ Styles]", ass)
        self.assertIn("[Events]", ass)
        self.assertIn("Dialogue:", ass)
        self.assertIn(r"\k", ass)

    def test_build_ass_script_karaoke(self):
        from src.services.caption_service import (
            build_ass_script, segment_words_into_lines
        )
        lines = segment_words_into_lines(self._words())
        ass = build_ass_script(lines, style="karaoke")
        # Karaoke style uses \k timing tags
        self.assertIn(r"\k", ass)

    def test_build_ass_script_highlight(self):
        from src.services.caption_service import (
            build_ass_script, segment_words_into_lines
        )
        lines = segment_words_into_lines(self._words())
        ass = build_ass_script(lines, style="highlight")
        # Highlight: one event per word
        dialogue_count = ass.count("Dialogue:")
        self.assertEqual(dialogue_count, len(self._words()))

    def test_uppercase_flag(self):
        from src.services.caption_service import (
            build_ass_script, segment_words_into_lines
        )
        lines = segment_words_into_lines(self._words())
        ass = build_ass_script(lines, style="tiktok", uppercase=True)
        self.assertIn("STOP", ass)
        self.assertIn("SCROLLING", ass)

    def test_word_duration_cs(self):
        from src.services.caption_service import WordTimestamp
        w = WordTimestamp("hello", 1.0, 1.5)
        self.assertEqual(w.duration_cs, 50)

    def test_segment_empty_words(self):
        from src.services.caption_service import segment_words_into_lines
        lines = segment_words_into_lines([])
        self.assertEqual(lines, [])

    def test_generate_ass_service(self):
        from src.services.caption_service import get_caption_service
        svc = get_caption_service()
        ass = svc.generate_ass(self._words(), style="minimal")
        self.assertIn("[Script Info]", ass)

    def test_get_styles(self):
        from src.services.caption_service import get_caption_service
        styles = get_caption_service().get_styles()
        self.assertIn("tiktok", styles)
        self.assertIn("karaoke", styles)
        self.assertIn("highlight", styles)

    def test_segment_words_service(self):
        from src.services.caption_service import get_caption_service
        svc = get_caption_service()
        result = svc.segment_words(self._words())
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        self.assertIn("text", result[0])
        self.assertIn("words", result[0])

    def test_singleton(self):
        from src.services.caption_service import get_caption_service
        self.assertIs(get_caption_service(), get_caption_service())


class TestCaptionBurnIn(unittest.IsolatedAsyncioTestCase):

    async def test_burn_empty_words_returns_false(self):
        from src.services.caption_service import burn_captions
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ok = await burn_captions(
                Path(tmp) / "v.mp4", Path(tmp) / "out.mp4", []
            )
        self.assertFalse(ok)

    async def test_burn_calls_ffmpeg(self):
        from src.services.caption_service import burn_captions
        import tempfile

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        words = [
            {"text": "Hello", "start": 0.0, "end": 0.5},
            {"text": "world", "start": 0.6, "end": 1.0},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                with patch("asyncio.wait_for", new=AsyncMock(return_value=(b"", b""))):
                    ok = await burn_captions(
                        Path(tmp) / "v.mp4",
                        Path(tmp) / "out.mp4",
                        words,
                        style="tiktok",
                    )
        self.assertTrue(ok)


# ══════════════════════════════════════════════════════════════════════════════
# LUTService
# ══════════════════════════════════════════════════════════════════════════════

class TestLUTService(unittest.TestCase):

    def test_list_available_luts(self):
        from src.services.lut_service import list_available_luts
        luts = list_available_luts()
        self.assertGreater(len(luts), 0)
        for lut in luts:
            self.assertIn("id", lut)
            self.assertIn("name", lut)
            self.assertIn("available", lut)
            self.assertIn("fallback_vf", lut)

    def test_get_lut_vf_unknown(self):
        from src.services.lut_service import get_lut_vf_filter
        self.assertIsNone(get_lut_vf_filter("does_not_exist"))

    def test_get_lut_vf_fallback(self):
        from src.services.lut_service import get_lut_vf_filter, LUT_DIR
        # .cube file won't exist in test env → should return fallback vf
        with patch("src.services.lut_service.LUT_DIR", LUT_DIR):
            vf = get_lut_vf_filter("teal_orange")
        self.assertIsNotNone(vf)
        self.assertIsInstance(vf, str)
        self.assertGreater(len(vf), 5)

    def test_get_lut_vf_cube_when_present(self):
        from src.services.lut_service import get_lut_vf_filter
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            cube = Path(tmp) / "teal_orange.cube"
            cube.write_text("TITLE test\nLUT_3D_SIZE 2\n")
            with patch("src.services.lut_service.LUT_DIR", Path(tmp)):
                vf = get_lut_vf_filter("teal_orange")
        self.assertIn("lut3d", vf)

    def test_write_identity_cube(self):
        from src.services.lut_service import _write_identity_cube
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "identity.cube"
            _write_identity_cube(path, size=2)
            content = path.read_text()
            self.assertIn("LUT_3D_SIZE 2", content)
            lines = [l for l in content.splitlines() if l and not l.startswith(("TITLE", "LUT"))]
            self.assertEqual(len(lines), 8)   # 2^3 entries

    def test_get_info_structure(self):
        from src.services.lut_service import get_lut_service
        info = get_lut_service().get_info()
        self.assertIn("lut_dir", info)
        self.assertIn("total_presets", info)
        self.assertIn("cube_files_present", info)
        self.assertIn("luts", info)

    def test_all_presets_have_fallback(self):
        from src.services.lut_service import _LUT_CATALOG
        for lut in _LUT_CATALOG:
            self.assertIn("fallback_vf", lut, f"LUT {lut['id']} missing fallback_vf")
            self.assertGreater(len(lut["fallback_vf"]), 0)

    def test_singleton(self):
        from src.services.lut_service import get_lut_service
        self.assertIs(get_lut_service(), get_lut_service())


class TestLUTApply(unittest.IsolatedAsyncioTestCase):

    async def test_apply_unknown_lut(self):
        from src.services.lut_service import apply_lut
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            result = await apply_lut(Path(tmp) / "v.mp4", Path(tmp) / "out.mp4", "unknown_lut")
        self.assertFalse(result)

    async def test_apply_with_mock_ffmpeg(self):
        from src.services.lut_service import apply_lut
        import tempfile

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.mp4"
            tmp_file = Path(tmp) / "tmp_file.mp4"
            tmp_file.write_bytes(b"\x00")
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                with patch("asyncio.wait_for", new=AsyncMock(return_value=(b"", b""))):
                    with patch("tempfile.mktemp", return_value=str(tmp_file)):
                        result = await apply_lut(Path(tmp) / "v.mp4", out, "teal_orange")
        self.assertTrue(result)


# ══════════════════════════════════════════════════════════════════════════════
# BeatSyncService
# ══════════════════════════════════════════════════════════════════════════════

class TestBeatSyncService(unittest.TestCase):

    def test_bpm_category_ranges(self):
        from src.services.beat_sync_service import bpm_category
        self.assertEqual(bpm_category(70), "slow")
        self.assertEqual(bpm_category(90), "midtempo")
        self.assertEqual(bpm_category(105), "upbeat")
        self.assertEqual(bpm_category(128), "hype")
        self.assertEqual(bpm_category(160), "fast")

    def test_bpm_distance_direct(self):
        from src.services.beat_sync_service import bpm_distance
        self.assertAlmostEqual(bpm_distance(120, 115), 5.0, delta=0.1)

    def test_bpm_distance_double_time(self):
        from src.services.beat_sync_service import bpm_distance
        # 120 BPM is a double-time match for 60 BPM
        self.assertAlmostEqual(bpm_distance(120, 60), 0.0, delta=0.1)

    def test_bpm_distance_half_time(self):
        from src.services.beat_sync_service import bpm_distance
        # 80 BPM is half of 160 BPM
        self.assertAlmostEqual(bpm_distance(80, 160), 0.0, delta=0.1)

    def test_estimate_bpm_from_filename(self):
        from src.services.beat_sync_service import _estimate_bpm_from_filename
        self.assertEqual(_estimate_bpm_from_filename("chill_95bpm_lofi.mp3"), 95.0)
        self.assertEqual(_estimate_bpm_from_filename("track-128-edm.wav"), 128.0)
        self.assertEqual(_estimate_bpm_from_filename("no_bpm_here.mp3"), 0.0)

    def test_select_bgm_no_tracks(self):
        from src.services.beat_sync_service import select_bgm
        result = select_bgm(95.0, tracks=[])
        self.assertIsNone(result)

    def test_select_bgm_picks_closest(self):
        from src.services.beat_sync_service import select_bgm, BGMTrack
        tracks = [
            BGMTrack(path=Path("a.mp3"), bpm=80.0, category="midtempo"),
            BGMTrack(path=Path("b.mp3"), bpm=95.0, category="midtempo"),
            BGMTrack(path=Path("c.mp3"), bpm=128.0, category="hype"),
        ]
        best = select_bgm(100.0, tracks=tracks)
        self.assertIsNotNone(best)
        self.assertEqual(best.path, Path("b.mp3"))

    def test_select_bgm_double_time_match(self):
        from src.services.beat_sync_service import select_bgm, BGMTrack, bpm_distance
        # Target 120 BPM → category "hype".
        # Only non-hype tracks available → falls back to full pool.
        # 60 BPM is a double-time match: bpm_distance(120, 60) = 0  (< distance to 80).
        tracks = [
            BGMTrack(path=Path("slow.mp3"), bpm=60.0, category="slow"),
            BGMTrack(path=Path("mid.mp3"),  bpm=80.0, category="midtempo"),
        ]
        best = select_bgm(120.0, tracks=tracks)
        self.assertIsNotNone(best)
        # Verify double-time math
        self.assertAlmostEqual(bpm_distance(120.0, 60.0), 0.0, delta=0.1)
        self.assertGreater(bpm_distance(120.0, 80.0), 0.0)
        self.assertEqual(best.path, Path("slow.mp3"))

    def test_analyse_bpm_fallback_when_no_librosa(self):
        from src.services.beat_sync_service import analyse_bpm
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with patch("builtins.__import__", side_effect=lambda n, *a, **k: (
                __import__(n, *a, **k) if n != "librosa" else (_ for _ in ()).throw(ImportError())
            )):
                # ffprobe fallback will also fail without real file → default 95 BPM
                result = analyse_bpm(Path(tmp) / "test.mp3", duration=5.0)
        self.assertIn("bpm", result)
        self.assertIn("category", result)
        self.assertIsInstance(result["bpm"], float)

    def test_build_speech_duck_filter_no_segments(self):
        from src.services.beat_sync_service import _build_speech_duck_filter
        vf = _build_speech_duck_filter([], 0.15, 1.5, 2.0)
        self.assertIn("afade", vf)
        self.assertIn("0.15", vf)

    def test_build_speech_duck_filter_with_segments(self):
        from src.services.beat_sync_service import _build_speech_duck_filter
        segs = [{"start": 1.0, "end": 3.0}, {"start": 5.0, "end": 8.0}]
        vf = _build_speech_duck_filter(segs, 0.15, 1.5, 2.0)
        self.assertIn("between", vf)
        self.assertIn("afade", vf)

    def test_get_info(self):
        from src.services.beat_sync_service import get_beat_sync_service
        info = get_beat_sync_service().get_info()
        self.assertIn("librosa_available", info)
        self.assertIn("track_count", info)
        self.assertIn("bpm_categories", info)

    def test_singleton(self):
        from src.services.beat_sync_service import get_beat_sync_service
        self.assertIs(get_beat_sync_service(), get_beat_sync_service())


class TestBeatSyncMix(unittest.IsolatedAsyncioTestCase):

    async def test_mix_no_library_returns_failure(self):
        from src.services.beat_sync_service import mix_bgm_beat_synced
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.services.beat_sync_service._scan_bgm_library", return_value=[]):
                result = await mix_bgm_beat_synced(
                    Path(tmp) / "v.mp4",
                    Path(tmp) / "out.mp4",
                    target_bpm=95.0,
                )
        self.assertFalse(result["success"])
        self.assertIn("no bgm tracks", result["reason"])

    async def test_mix_with_explicit_bgm_path(self):
        from src.services.beat_sync_service import mix_bgm_beat_synced
        import tempfile

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with tempfile.TemporaryDirectory() as tmp:
            bgm = Path(tmp) / "bgm.mp3"
            bgm.write_bytes(b"\x00")
            with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                with patch("asyncio.wait_for", new=AsyncMock(return_value=(b"", b""))):
                    result = await mix_bgm_beat_synced(
                        Path(tmp) / "v.mp4",
                        Path(tmp) / "out.mp4",
                        bgm_path=bgm,
                        target_bpm=95.0,
                    )
        self.assertTrue(result["success"])
        self.assertEqual(result["bpm"], 95.0)


# ══════════════════════════════════════════════════════════════════════════════
# Caption API Routes
# ══════════════════════════════════════════════════════════════════════════════

class TestCaptionRoutes(unittest.TestCase):

    def setUp(self):
        from src.api.routes.captions import router
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_list_styles(self):
        resp = self.client.get("/captions/styles")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("tiktok", resp.json()["styles"])

    def test_segment_words(self):
        resp = self.client.post("/captions/segment", json={
            "words": [
                {"text": "Stop", "start": 0.0, "end": 0.3},
                {"text": "now",  "start": 0.35, "end": 0.6},
            ],
            "max_words_per_line": 5,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(resp.json()["line_count"], 0)

    def test_segment_words_invalid_style(self):
        resp = self.client.post("/captions/segment", json={
            "words": [],
            "max_words_per_line": 0,  # < 1
        })
        self.assertEqual(resp.status_code, 422)

    def test_generate_ass(self):
        resp = self.client.post("/captions/generate", json={
            "words": [
                {"text": "Go",   "start": 0.0, "end": 0.3},
                {"text": "viral","start": 0.4, "end": 0.9},
            ],
            "style": "karaoke",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("[Script Info]", resp.json()["ass_script"])

    def test_generate_ass_invalid_style(self):
        resp = self.client.post("/captions/generate", json={
            "words": [{"text": "hi", "start": 0.0, "end": 0.5}],
            "style": "magic",
        })
        self.assertEqual(resp.status_code, 422)

    def test_burn_captions(self):
        from src.services.caption_service import CaptionService
        mock_svc = MagicMock(spec=CaptionService)
        mock_svc.burn = AsyncMock(return_value=True)
        with patch("src.api.routes.captions.get_caption_service", return_value=mock_svc):
            resp = self.client.post("/captions/burn", json={
                "video_path":  "/tmp/v.mp4",
                "output_path": "/tmp/out.mp4",
                "words": [{"text": "Hi", "start": 0.0, "end": 0.5}],
                "style": "tiktok",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])


# ══════════════════════════════════════════════════════════════════════════════
# LUT API Routes
# ══════════════════════════════════════════════════════════════════════════════

class TestLUTRoutes(unittest.TestCase):

    def setUp(self):
        from src.api.routes.lut import router
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app, raise_server_exceptions=False)

    def _mock_svc(self):
        from src.services.lut_service import LUTService
        svc = MagicMock(spec=LUTService)
        svc.get_info = MagicMock(return_value={
            "lut_dir": "/app/luts",
            "total_presets": 6,
            "cube_files_present": 0,
            "luts": [],
        })
        svc.list_luts = MagicMock(return_value=[])
        svc.get_vf_filter = MagicMock(return_value="eq=saturation=1.15")
        svc.apply = AsyncMock(return_value=True)
        svc.download_luts = AsyncMock(return_value={"success": True, "lut_count": 50})
        return svc

    def test_get_info(self):
        with patch("src.api.routes.lut.get_lut_service", return_value=self._mock_svc()):
            resp = self.client.get("/lut/info")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("total_presets", resp.json())

    def test_list_luts(self):
        with patch("src.api.routes.lut.get_lut_service", return_value=self._mock_svc()):
            resp = self.client.get("/lut/list")
        self.assertEqual(resp.status_code, 200)

    def test_get_vf_filter(self):
        with patch("src.api.routes.lut.get_lut_service", return_value=self._mock_svc()):
            resp = self.client.get("/lut/filter/teal_orange")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("vf_filter", resp.json())

    def test_get_vf_filter_not_found(self):
        svc = self._mock_svc()
        svc.get_vf_filter = MagicMock(return_value=None)
        with patch("src.api.routes.lut.get_lut_service", return_value=svc):
            resp = self.client.get("/lut/filter/nope_lut")
        self.assertEqual(resp.status_code, 404)

    def test_apply_lut(self):
        with patch("src.api.routes.lut.get_lut_service", return_value=self._mock_svc()):
            resp = self.client.post("/lut/apply", json={
                "video_path": "/tmp/v.mp4",
                "output_path": "/tmp/out.mp4",
                "lut_id": "teal_orange",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    def test_download_luts(self):
        with patch("src.api.routes.lut.get_lut_service", return_value=self._mock_svc()):
            resp = self.client.post("/lut/download")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])


# ══════════════════════════════════════════════════════════════════════════════
# Beat-Sync API Routes
# ══════════════════════════════════════════════════════════════════════════════

class TestBeatSyncRoutes(unittest.TestCase):

    def setUp(self):
        from src.api.routes.beat_sync import router
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app, raise_server_exceptions=False)

    def _mock_svc(self):
        from src.services.beat_sync_service import BeatSyncService
        svc = MagicMock(spec=BeatSyncService)
        svc.get_info = MagicMock(return_value={
            "librosa_available": True,
            "bgm_library_dir": "/app/sfx_library/bgm",
            "track_count": 8,
            "bpm_categories": ["slow", "midtempo", "upbeat", "hype", "fast"],
        })
        svc.list_library = MagicMock(return_value=[
            {"path": "/app/sfx/bgm/lofi-80.mp3", "name": "lofi-80", "bpm": 80.0, "category": "midtempo"},
        ])
        svc.analyse_bpm = MagicMock(return_value={
            "bpm": 95.0, "beat_times": [0.63, 1.26, 1.89],
            "category": "midtempo", "confidence": 0.87,
        })
        svc.select_bgm = MagicMock(return_value={
            "path": "/app/sfx/bgm/lofi-95.mp3", "name": "lofi-95",
            "bpm": 95.0, "category": "midtempo",
        })
        svc.mix = AsyncMock(return_value={
            "success": True, "bpm": 95.0, "category": "midtempo",
            "beat_count": 48, "bgm_used": "/app/sfx/bgm/lofi-95.mp3",
        })
        return svc

    def test_get_info(self):
        with patch("src.api.routes.beat_sync.get_beat_sync_service",
                   return_value=self._mock_svc()):
            resp = self.client.get("/beat-sync/info")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("librosa_available", resp.json())

    def test_list_library(self):
        with patch("src.api.routes.beat_sync.get_beat_sync_service",
                   return_value=self._mock_svc()):
            resp = self.client.get("/beat-sync/library")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_analyse_bpm(self):
        with patch("src.api.routes.beat_sync.get_beat_sync_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/beat-sync/analyse", json={
                "audio_path": "/tmp/audio.mp3",
                "duration": 30.0,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["bpm"], 95.0)
        self.assertIn("beat_times", resp.json())

    def test_select_bgm(self):
        with patch("src.api.routes.beat_sync.get_beat_sync_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/beat-sync/select", json={"target_bpm": 95.0})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["bpm"], 95.0)

    def test_select_bgm_no_tracks(self):
        svc = self._mock_svc()
        svc.select_bgm = MagicMock(return_value=None)
        with patch("src.api.routes.beat_sync.get_beat_sync_service", return_value=svc):
            resp = self.client.post("/beat-sync/select", json={"target_bpm": 120.0})
        self.assertEqual(resp.status_code, 404)

    def test_select_bgm_invalid_category(self):
        resp = self.client.post("/beat-sync/select", json={
            "target_bpm": 100.0,
            "prefer_category": "jazz",  # not in enum
        })
        self.assertEqual(resp.status_code, 422)

    def test_select_bgm_invalid_bpm(self):
        resp = self.client.post("/beat-sync/select", json={"target_bpm": 15.0})
        self.assertEqual(resp.status_code, 422)

    def test_mix_bgm(self):
        with patch("src.api.routes.beat_sync.get_beat_sync_service",
                   return_value=self._mock_svc()):
            resp = self.client.post("/beat-sync/mix", json={
                "video_path":  "/tmp/v.mp4",
                "output_path": "/tmp/out.mp4",
                "target_bpm":  95.0,
                "bgm_volume":  0.15,
                "speech_segments": [{"start": 1.0, "end": 4.0}],
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    def test_mix_invalid_volume(self):
        resp = self.client.post("/beat-sync/mix", json={
            "video_path":  "/tmp/v.mp4",
            "output_path": "/tmp/out.mp4",
            "bgm_volume":  1.5,   # > 1.0
        })
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
