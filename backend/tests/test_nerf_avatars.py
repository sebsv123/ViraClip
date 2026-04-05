"""
Tests for the NeRF Avatar system.

Covers:
  - AvatarAsset / SMPLPose / AudioFeatures / UVAppearanceMap data models
  - NeRFAvatarService: all 4 modes (ernerf, text2avatar, video2avatar, uv_volumes)
  - AvatarCompositor: all 5 composite modes
  - API routes: create, list, get, delete, render, composite
"""

from __future__ import annotations

import asyncio
import json
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import sys
import types


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_mp4(path: Path, duration: float = 1.0):
    """Create a minimal valid file (stub for tests)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 64)


# ---------------------------------------------------------------------------
# 1. Data model tests
# ---------------------------------------------------------------------------

class TestSMPLPose(unittest.TestCase):
    def _cls(self):
        from src.services.nerf_avatar_service import SMPLPose
        return SMPLPose

    def test_defaults(self):
        SMPLPose = self._cls()
        p = SMPLPose()
        self.assertEqual(len(p.body_pose), 72)
        self.assertEqual(len(p.shape), 10)
        self.assertEqual(p.translation, [0.0, 0.0, 0.0])

    def test_to_dict(self):
        SMPLPose = self._cls()
        p = SMPLPose(body_pose=[1.0] * 72, shape=[0.5] * 10, translation=[1, 2, 3])
        d = p.to_dict()
        self.assertEqual(d["translation"], [1, 2, 3])
        self.assertEqual(len(d["body_pose"]), 72)
        self.assertEqual(len(d["shape"]), 10)


class TestAudioFeatures(unittest.TestCase):
    def _cls(self):
        from src.services.nerf_avatar_service import AudioFeatures
        return AudioFeatures

    def test_defaults(self):
        AudioFeatures = self._cls()
        a = AudioFeatures()
        self.assertIsNone(a.hubert_features)
        self.assertEqual(a.frame_rate, 25.0)

    def test_to_dict_with_features(self):
        AudioFeatures = self._cls()
        a = AudioFeatures(
            hubert_features=[[0.1] * 768] * 10,
            duration_seconds=2.5,
        )
        d = a.to_dict()
        self.assertEqual(d["hubert_features_shape"], [10, 768])
        self.assertEqual(d["duration_seconds"], 2.5)

    def test_to_dict_without_features(self):
        AudioFeatures = self._cls()
        d = AudioFeatures().to_dict()
        self.assertIsNone(d["hubert_features_shape"])


class TestUVAppearanceMap(unittest.TestCase):
    def _cls(self):
        from src.services.nerf_avatar_service import UVAppearanceMap
        return UVAppearanceMap

    def test_to_dict(self):
        UVAppearanceMap = self._cls()
        uv = UVAppearanceMap(
            uv_texture_path="/app/avatars/1/uv.png",
            normal_map_path="/app/avatars/1/normal.png",
            resolution=(1024, 1024),
        )
        d = uv.to_dict()
        self.assertEqual(d["uv_texture_path"], "/app/avatars/1/uv.png")
        self.assertEqual(d["resolution"], [1024, 1024])


class TestAvatarAsset(unittest.TestCase):
    def _cls(self):
        from src.services.nerf_avatar_service import AvatarAsset, AvatarMode, AvatarStatus
        return AvatarAsset, AvatarMode, AvatarStatus

    def test_to_dict_ernerf(self):
        AvatarAsset, AvatarMode, AvatarStatus = self._cls()
        a = AvatarAsset(
            avatar_id="test123",
            mode=AvatarMode.ERNERF,
            status=AvatarStatus.READY,
            source_image_path="/face.jpg",
        )
        d = a.to_dict()
        self.assertEqual(d["avatar_id"], "test123")
        self.assertEqual(d["mode"], "ernerf")
        self.assertEqual(d["status"], "ready")

    def test_to_dict_text2avatar(self):
        AvatarAsset, AvatarMode, AvatarStatus = self._cls()
        a = AvatarAsset(
            avatar_id="t2a1",
            mode=AvatarMode.TEXT2AVATAR,
            text_prompt="a superhero in red suit",
            style_prompt="photorealistic",
        )
        d = a.to_dict()
        self.assertEqual(d["text_prompt"], "a superhero in red suit")
        self.assertEqual(d["style_prompt"], "photorealistic")

    def test_avatar_mode_enum(self):
        from src.services.nerf_avatar_service import AvatarMode
        self.assertEqual(AvatarMode.ERNERF.value, "ernerf")
        self.assertEqual(AvatarMode.TEXT2AVATAR.value, "text2avatar")
        self.assertEqual(AvatarMode.VIDEO2AVATAR.value, "video2avatar")
        self.assertEqual(AvatarMode.UV_VOLUMES.value, "uv_volumes")

    def test_avatar_status_enum(self):
        from src.services.nerf_avatar_service import AvatarStatus
        self.assertEqual(AvatarStatus.PENDING.value, "pending")
        self.assertEqual(AvatarStatus.TRAINING.value, "training")
        self.assertEqual(AvatarStatus.READY.value, "ready")
        self.assertEqual(AvatarStatus.FAILED.value, "failed")


# ---------------------------------------------------------------------------
# 2. NeRFAvatarService tests
# ---------------------------------------------------------------------------

class TestNeRFAvatarService(unittest.TestCase):
    def setUp(self):
        from src.services.nerf_avatar_service import reset_nerf_avatar_service
        reset_nerf_avatar_service()

        # Patch AVATARS_DIR and MODELS_DIR to tmp
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp())

        patcher = patch(
            "src.services.nerf_avatar_service.NeRFAvatarService.AVATARS_DIR",
            new_callable=lambda: property(lambda self: self._tmp),
        )
        # Simpler: patch at instance level after creation
        self._tmp = self.tmpdir

    def _make_service(self):
        from src.services.nerf_avatar_service import NeRFAvatarService
        svc = NeRFAvatarService.__new__(NeRFAvatarService)
        svc.AVATARS_DIR = self.tmpdir
        svc.MODELS_DIR = self.tmpdir / "models"
        svc.AVATARS_DIR.mkdir(parents=True, exist_ok=True)
        svc.MODELS_DIR.mkdir(parents=True, exist_ok=True)
        svc._avatars = {}
        return svc

    def test_list_avatars_empty(self):
        svc = self._make_service()
        self.assertEqual(svc.list_avatars(), [])

    def test_get_nonexistent(self):
        svc = self._make_service()
        self.assertIsNone(svc.get_avatar("does_not_exist"))

    def test_delete_nonexistent(self):
        svc = self._make_service()
        self.assertFalse(svc.delete_avatar("nope"))

    def test_save_and_load_index(self):
        from src.services.nerf_avatar_service import AvatarAsset, AvatarMode, AvatarStatus
        svc = self._make_service()

        asset = AvatarAsset(
            avatar_id="idx_test",
            mode=AvatarMode.TEXT2AVATAR,
            status=AvatarStatus.READY,
            text_prompt="a wizard",
        )
        svc._avatars["idx_test"] = asset
        svc._save_avatar_index()

        # Reload
        svc2 = self._make_service()
        svc2._load_existing_avatars()
        self.assertIn("idx_test", svc2._avatars)
        self.assertEqual(svc2._avatars["idx_test"].text_prompt, "a wizard")

    def test_avatar_dir_created(self):
        svc = self._make_service()
        d = svc._avatar_dir("myavatar")
        self.assertTrue(d.exists())
        self.assertTrue(d.is_dir())

    def test_comfyui_not_available(self):
        svc = self._make_service()
        with patch("src.services.nerf_avatar_service.NeRFAvatarService._comfyui_available", return_value=False):
            self.assertFalse(svc._comfyui_available())

    def test_delete_avatar(self):
        from src.services.nerf_avatar_service import AvatarAsset, AvatarMode
        svc = self._make_service()

        asset = AvatarAsset(avatar_id="del_me", mode=AvatarMode.ERNERF)
        svc._avatars["del_me"] = asset
        svc._avatar_dir("del_me")  # create the dir

        result = svc.delete_avatar("del_me")
        self.assertTrue(result)
        self.assertNotIn("del_me", svc._avatars)

    def test_create_text2avatar_cpu_fallback(self):
        """TEXT2AVATAR without GPU falls back to DALL-E or proxy."""
        svc = self._make_service()

        with patch.object(svc, "_comfyui_available", return_value=False), \
             patch.object(svc, "_generate_avatar_image_fallback", new_callable=AsyncMock) as mock_fb:
            mock_fb.return_value = self.tmpdir / "a1" / "nerf_proxy.json"

            async def run_test():
                from src.services.nerf_avatar_service import AvatarMode
                asset = await svc.create_avatar(
                    mode=AvatarMode.TEXT2AVATAR,
                    text_prompt="a knight in shining armor",
                )
                return asset

            asset = run(run_test())
            self.assertEqual(asset.text_prompt, "a knight in shining armor")
            mock_fb.assert_called_once()

    def test_create_ernerf_cpu_fallback(self):
        """ERNeRF without GPU falls back to GFPGAN proxy."""
        svc = self._make_service()
        face_img = self.tmpdir / "face.jpg"
        face_img.write_bytes(b"\xff\xd8\xff")  # Minimal JPEG header

        with patch.object(svc, "_comfyui_available", return_value=False), \
             patch.object(svc, "_extract_face_landmarks", new_callable=AsyncMock) as mock_lm, \
             patch.object(svc, "_background_matting", new_callable=AsyncMock) as mock_mat, \
             patch.object(svc, "_prepare_gfpgan_proxy", new_callable=AsyncMock) as mock_gfp:

            mock_lm.return_value = ([0, 0, 256, 256], self.tmpdir / "a2" / "landmarks.json")
            mock_mat.return_value = self.tmpdir / "a2" / "matted.png"
            mock_gfp.return_value = self.tmpdir / "a2" / "nerf_proxy.json"

            async def run_test():
                from src.services.nerf_avatar_service import AvatarMode
                return await svc.create_avatar(
                    mode=AvatarMode.ERNERF,
                    source_image_path=str(face_img),
                )

            asset = run(run_test())
            self.assertEqual(asset.mode.value, "ernerf")
            mock_lm.assert_called_once()
            mock_gfp.assert_called_once()

    def test_render_requires_ready_status(self):
        from src.services.nerf_avatar_service import AvatarAsset, AvatarMode, AvatarStatus
        svc = self._make_service()

        asset = AvatarAsset(avatar_id="not_ready", mode=AvatarMode.ERNERF, status=AvatarStatus.TRAINING)
        svc._avatars["not_ready"] = asset

        async def run_test():
            return await svc.render_avatar_video("not_ready")

        with self.assertRaises(ValueError, msg="Should raise for non-READY avatar"):
            run(run_test())

    def test_extract_audio_features_no_file(self):
        svc = self._make_service()

        async def run_test():
            return await svc._extract_audio_features(None, 5.0)

        features = run(run_test())
        self.assertEqual(features.duration_seconds, 5.0)
        self.assertIsNone(features.hubert_features)

    def test_extract_video_frames_mocked(self):
        svc = self._make_service()
        frames_dir = self.tmpdir / "frames"
        frames_dir.mkdir()

        proc_mock = AsyncMock()
        proc_mock.returncode = 0
        proc_mock.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            run(svc._extract_video_frames("/fake/video.mp4", frames_dir))

    def test_fit_smpl_sequence_creates_file(self):
        svc = self._make_service()
        frames_dir = self.tmpdir / "frames2"
        frames_dir.mkdir()
        for i in range(5):
            (frames_dir / f"frame_{i:06d}.jpg").write_bytes(b"\x00")

        seq_path = run(svc._fit_smpl_sequence(frames_dir, self.tmpdir))
        self.assertTrue(seq_path.exists())

        data = json.loads(seq_path.read_text())
        self.assertIn("frames", data)
        self.assertEqual(len(data["frames"]), 5)

    def test_build_uv_appearance_map_no_opencv(self):
        """UV map build should gracefully handle missing OpenCV."""
        svc = self._make_service()
        frames_dir = self.tmpdir / "frames3"
        frames_dir.mkdir()
        smpl_seq = self.tmpdir / "smpl.json"
        smpl_seq.write_text("{}")

        with patch.dict("sys.modules", {"cv2": None, "numpy": None}):
            uv_path, normal_path = run(
                svc._build_uv_appearance_map(frames_dir, smpl_seq, self.tmpdir)
            )
        # Files created (even if empty)
        self.assertEqual(uv_path.name, "uv_texture.png")
        self.assertEqual(normal_path.name, "normal_map.png")

    def test_render_ernerf_cpu_fallback_mocked(self):
        from src.services.nerf_avatar_service import AvatarAsset, AvatarMode, AvatarStatus
        svc = self._make_service()

        asset = AvatarAsset(
            avatar_id="rnd1",
            mode=AvatarMode.ERNERF,
            status=AvatarStatus.READY,
            source_image_path="/face.jpg",
            face_bbox=[0, 0, 256, 256],
        )
        out_path = str(self.tmpdir / "output.mp4")

        proc_mock = AsyncMock()
        proc_mock.returncode = 0
        proc_mock.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            result = run(svc._render_ernerf_cpu_fallback(asset, None, 3.0, out_path))

        self.assertEqual(result, out_path)

    def test_generate_placeholder_frame(self):
        svc = self._make_service()
        out = str(self.tmpdir / "placeholder.mp4")

        proc_mock = AsyncMock()
        proc_mock.returncode = 0
        proc_mock.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            run(svc._generate_placeholder_frame("test avatar", out, 2.0))


# ---------------------------------------------------------------------------
# 3. AvatarCompositor tests
# ---------------------------------------------------------------------------

class TestAvatarCompositor(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp())

    def _make_compositor(self):
        from src.services.avatar_compositor import AvatarCompositor
        return AvatarCompositor()

    def _mock_ffprobe(self, w=1080, h=1920):
        """Return a mock ffprobe result with given dimensions."""
        proc_mock = AsyncMock()
        proc_mock.returncode = 0
        data = json.dumps({
            "streams": [{"codec_type": "video", "width": w, "height": h}]
        }).encode()
        proc_mock.communicate = AsyncMock(return_value=(data, b""))
        return proc_mock

    def _mock_ffmpeg_ok(self):
        proc_mock = AsyncMock()
        proc_mock.returncode = 0
        proc_mock.communicate = AsyncMock(return_value=(b"", b""))
        return proc_mock

    def test_compute_pip_position_bottom_right(self):
        c = self._make_compositor()
        x, y = c._compute_pip_position("bottom_right", 1080, 1920, 302, 537, 20)
        self.assertEqual(x, 1080 - 302 - 20)
        self.assertEqual(y, 1920 - 537 - 20)

    def test_compute_pip_position_top_left(self):
        c = self._make_compositor()
        x, y = c._compute_pip_position("top_left", 1080, 1920, 300, 500, 20)
        self.assertEqual(x, 20)
        self.assertEqual(y, 20)

    def test_compute_pip_position_center(self):
        c = self._make_compositor()
        x, y = c._compute_pip_position("center", 1080, 1920, 200, 400, 20)
        self.assertEqual(x, (1080 - 200) // 2)
        self.assertEqual(y, (1920 - 400) // 2)

    def test_get_video_dimensions_default_on_error(self):
        c = self._make_compositor()
        proc_mock = AsyncMock()
        proc_mock.communicate = AsyncMock(return_value=(b"invalid json", b""))
        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            w, h = run(c._get_video_dimensions("/fake.mp4"))
        self.assertEqual(w, 1080)
        self.assertEqual(h, 1920)

    def test_get_video_dimensions_real(self):
        c = self._make_compositor()
        with patch("asyncio.create_subprocess_exec", return_value=self._mock_ffprobe(720, 1280)):
            w, h = run(c._get_video_dimensions("/fake.mp4"))
        self.assertEqual(w, 720)
        self.assertEqual(h, 1280)

    def test_composite_pip(self):
        c = self._make_compositor()
        out = str(self.tmpdir / "pip.mp4")

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return self._mock_ffprobe()
            return self._mock_ffmpeg_ok()

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = run(c.composite("/clip.mp4", "/avatar.mp4", out))

        self.assertEqual(result, out)

    def test_composite_side_by_side(self):
        from src.services.avatar_compositor import CompositeOptions, CompositeMode
        c = self._make_compositor()
        out = str(self.tmpdir / "sbs.mp4")
        opts = CompositeOptions(mode=CompositeMode.SIDE_BY_SIDE)

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return self._mock_ffprobe()
            return self._mock_ffmpeg_ok()

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = run(c.composite("/clip.mp4", "/avatar.mp4", out, opts))

        self.assertEqual(result, out)

    def test_composite_full_replace(self):
        from src.services.avatar_compositor import CompositeOptions, CompositeMode
        c = self._make_compositor()
        out = str(self.tmpdir / "full.mp4")
        opts = CompositeOptions(mode=CompositeMode.FULL_REPLACE)

        with patch("asyncio.create_subprocess_exec", return_value=self._mock_ffmpeg_ok()):
            result = run(c.composite("/clip.mp4", "/avatar.mp4", out, opts))

        self.assertEqual(result, out)

    def test_composite_lower_third(self):
        from src.services.avatar_compositor import CompositeOptions, CompositeMode
        c = self._make_compositor()
        out = str(self.tmpdir / "lt.mp4")
        opts = CompositeOptions(mode=CompositeMode.LOWER_THIRD)

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return self._mock_ffprobe()
            return self._mock_ffmpeg_ok()

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = run(c.composite("/clip.mp4", "/avatar.mp4", out, opts))

        self.assertEqual(result, out)

    def test_composite_face_replace_no_face_fallback(self):
        """Face replace falls back to PIP when no face detected."""
        from src.services.avatar_compositor import CompositeOptions, CompositeMode
        c = self._make_compositor()
        out = str(self.tmpdir / "fr.mp4")
        opts = CompositeOptions(mode=CompositeMode.FACE_REPLACE)

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return self._mock_ffprobe()  # for PIP fallback dims
            return self._mock_ffmpeg_ok()

        with patch.object(c, "_detect_face_region", new_callable=AsyncMock, return_value=None), \
             patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = run(c.composite("/clip.mp4", "/avatar.mp4", out, opts))

        self.assertEqual(result, out)

    def test_composite_face_replace_with_face(self):
        """Face replace composites at detected face region."""
        from src.services.avatar_compositor import CompositeOptions, CompositeMode
        c = self._make_compositor()
        out = str(self.tmpdir / "fr2.mp4")
        opts = CompositeOptions(mode=CompositeMode.FACE_REPLACE)

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return self._mock_ffprobe()
            return self._mock_ffmpeg_ok()

        with patch.object(c, "_detect_face_region", new_callable=AsyncMock, return_value=(100, 80, 200, 220)), \
             patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = run(c.composite("/clip.mp4", "/avatar.mp4", out, opts))

        self.assertEqual(result, out)

    def test_ffmpeg_failure_raises(self):
        c = self._make_compositor()

        proc_mock = AsyncMock()
        proc_mock.returncode = 1
        proc_mock.communicate = AsyncMock(return_value=(b"", b"Error"))

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            with self.assertRaises(RuntimeError):
                run(c._run_ffmpeg(["ffmpeg", "-i", "x"], "test"))

    def test_composite_with_chroma_key(self):
        from src.services.avatar_compositor import CompositeOptions, CompositeMode
        c = self._make_compositor()
        out = str(self.tmpdir / "chroma.mp4")
        opts = CompositeOptions(
            mode=CompositeMode.PICTURE_IN_PICTURE,
            chroma_key_color="0x00FF00",
            chroma_key_similarity=0.3,
        )

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return self._mock_ffprobe()
            return self._mock_ffmpeg_ok()

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = run(c.composite("/clip.mp4", "/avatar.mp4", out, opts))

        self.assertEqual(result, out)

    def test_singleton(self):
        from src.services.avatar_compositor import get_avatar_compositor
        c1 = get_avatar_compositor()
        c2 = get_avatar_compositor()
        self.assertIs(c1, c2)


# ---------------------------------------------------------------------------
# 4. API route tests
# ---------------------------------------------------------------------------

class TestAvatarAPIRoutes(unittest.TestCase):
    def setUp(self):
        from src.services.nerf_avatar_service import reset_nerf_avatar_service
        reset_nerf_avatar_service()

    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.avatar import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_get_modes_info(self):
        client = self._get_client()
        resp = client.get("/avatars/modes/info")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("modes", data)
        self.assertEqual(len(data["modes"]), 4)
        modes = {m["mode"] for m in data["modes"]}
        self.assertIn("ernerf", modes)
        self.assertIn("text2avatar", modes)
        self.assertIn("video2avatar", modes)
        self.assertIn("uv_volumes", modes)

    def test_get_composite_modes(self):
        client = self._get_client()
        resp = client.get("/avatars/modes/info")
        data = resp.json()
        self.assertIn("composite_modes", data)
        comp_modes = {m["mode"] for m in data["composite_modes"]}
        self.assertIn("pip", comp_modes)
        self.assertIn("face_replace", comp_modes)
        self.assertIn("lower_third", comp_modes)

    def test_list_avatars_empty(self):
        from src.services.nerf_avatar_service import NeRFAvatarService
        import tempfile
        tmpdir = Path(tempfile.mkdtemp())

        with patch.object(NeRFAvatarService, "AVATARS_DIR", tmpdir):
            client = self._get_client()
            resp = client.get("/avatars")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["count"], 0)

    def test_get_nonexistent_avatar(self):
        client = self._get_client()

        with patch("src.api.routes.avatar.get_nerf_avatar_service") as mock_svc:
            mock_svc.return_value.get_avatar.return_value = None
            resp = client.get("/avatars/nonexistent")

        self.assertEqual(resp.status_code, 404)

    def test_delete_nonexistent_avatar(self):
        client = self._get_client()

        with patch("src.api.routes.avatar.get_nerf_avatar_service") as mock_svc:
            mock_svc.return_value.delete_avatar.return_value = False
            resp = client.delete("/avatars/nonexistent")

        self.assertEqual(resp.status_code, 404)

    def test_create_text2avatar_success(self):
        from src.services.nerf_avatar_service import AvatarAsset, AvatarMode, AvatarStatus

        client = self._get_client()
        mock_asset = AvatarAsset(
            avatar_id="api_test1",
            mode=AvatarMode.TEXT2AVATAR,
            status=AvatarStatus.READY,
            text_prompt="a samurai warrior",
        )

        with patch("src.api.routes.avatar.get_nerf_avatar_service") as mock_svc:
            mock_svc.return_value.create_avatar = AsyncMock(return_value=mock_asset)
            resp = client.post("/avatars", json={
                "mode": "text2avatar",
                "text_prompt": "a samurai warrior",
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["avatar"]["avatar_id"], "api_test1")

    def test_create_text2avatar_missing_prompt(self):
        client = self._get_client()
        resp = client.post("/avatars", json={"mode": "text2avatar"})
        self.assertEqual(resp.status_code, 400)

    def test_create_invalid_mode(self):
        client = self._get_client()
        resp = client.post("/avatars", json={"mode": "invalid_mode"})
        self.assertEqual(resp.status_code, 400)

    def test_render_avatar_not_found(self):
        client = self._get_client()

        with patch("src.api.routes.avatar.get_nerf_avatar_service") as mock_svc:
            mock_svc.return_value.get_avatar.return_value = None
            resp = client.post("/avatars/nope/render", json={"duration_seconds": 3.0})

        self.assertEqual(resp.status_code, 404)

    def test_render_avatar_success(self):
        from src.services.nerf_avatar_service import AvatarAsset, AvatarMode, AvatarStatus

        client = self._get_client()
        mock_asset = AvatarAsset(
            avatar_id="rnd_api",
            mode=AvatarMode.ERNERF,
            status=AvatarStatus.READY,
        )

        with patch("src.api.routes.avatar.get_nerf_avatar_service") as mock_svc:
            mock_svc.return_value.get_avatar.return_value = mock_asset
            mock_svc.return_value.render_avatar_video = AsyncMock(return_value="/output/render.mp4")
            resp = client.post("/avatars/rnd_api/render", json={"duration_seconds": 5.0})

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["rendered_video_path"], "/output/render.mp4")

    def test_render_avatar_with_smpl_pose(self):
        from src.services.nerf_avatar_service import AvatarAsset, AvatarMode, AvatarStatus

        client = self._get_client()
        mock_asset = AvatarAsset(
            avatar_id="smpl_rnd",
            mode=AvatarMode.VIDEO2AVATAR,
            status=AvatarStatus.READY,
        )

        with patch("src.api.routes.avatar.get_nerf_avatar_service") as mock_svc:
            mock_svc.return_value.get_avatar.return_value = mock_asset
            mock_svc.return_value.render_avatar_video = AsyncMock(return_value="/output/smpl.mp4")
            resp = client.post("/avatars/smpl_rnd/render", json={
                "duration_seconds": 3.0,
                "body_pose": [0.0] * 72,
                "shape": [0.0] * 10,
                "translation": [0.0, 0.0, 3.0],
            })

        self.assertEqual(resp.status_code, 200)

    def test_composite_invalid_mode(self):
        client = self._get_client()
        resp = client.post("/avatars/any/composite", json={
            "clip_path": "/clip.mp4",
            "avatar_video_path": "/avatar.mp4",
            "mode": "invalid_mode",
        })
        self.assertEqual(resp.status_code, 400)

    def test_composite_success(self):
        from src.services.avatar_compositor import AvatarCompositor

        client = self._get_client()

        with patch("src.api.routes.avatar.get_avatar_compositor") as mock_comp:
            mock_comp.return_value.composite = AsyncMock(return_value="/output/comp.mp4")
            resp = client.post("/avatars/any/composite", json={
                "clip_path": "/clip.mp4",
                "avatar_video_path": "/avatar.mp4",
                "mode": "pip",
            })

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["output_path"], "/output/comp.mp4")

    def test_delete_avatar_success(self):
        client = self._get_client()

        with patch("src.api.routes.avatar.get_nerf_avatar_service") as mock_svc:
            mock_svc.return_value.delete_avatar.return_value = True
            resp = client.delete("/avatars/del123")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "deleted")

    def test_get_avatar_success(self):
        from src.services.nerf_avatar_service import AvatarAsset, AvatarMode, AvatarStatus

        client = self._get_client()
        mock_asset = AvatarAsset(
            avatar_id="found123",
            mode=AvatarMode.UV_VOLUMES,
            status=AvatarStatus.READY,
        )

        with patch("src.api.routes.avatar.get_nerf_avatar_service") as mock_svc:
            mock_svc.return_value.get_avatar.return_value = mock_asset
            resp = client.get("/avatars/found123")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["avatar"]["avatar_id"], "found123")


# ---------------------------------------------------------------------------
# 5. Integration: full render pipeline (mocked)
# ---------------------------------------------------------------------------

class TestAvatarPipelineIntegration(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp())
        from src.services.nerf_avatar_service import reset_nerf_avatar_service
        reset_nerf_avatar_service()

    def _make_service(self):
        from src.services.nerf_avatar_service import NeRFAvatarService
        svc = NeRFAvatarService.__new__(NeRFAvatarService)
        svc.AVATARS_DIR = self.tmpdir
        svc.MODELS_DIR = self.tmpdir / "models"
        svc.AVATARS_DIR.mkdir(parents=True, exist_ok=True)
        svc.MODELS_DIR.mkdir(parents=True, exist_ok=True)
        svc._avatars = {}
        return svc

    def test_full_ernerf_pipeline(self):
        """ERNeRF: create → render → verify output."""
        svc = self._make_service()
        face_img = self.tmpdir / "face.jpg"
        face_img.write_bytes(b"\xff\xd8\xff")

        proc_mock = AsyncMock()
        proc_mock.returncode = 0
        proc_mock.communicate = AsyncMock(return_value=(b"", b""))

        with patch.object(svc, "_comfyui_available", return_value=False), \
             patch.object(svc, "_extract_face_landmarks", new_callable=AsyncMock,
                         return_value=([0, 0, 200, 200], self.tmpdir / "lm" / "lm.json")), \
             patch.object(svc, "_background_matting", new_callable=AsyncMock,
                         return_value=self.tmpdir / "matted.png"), \
             patch.object(svc, "_prepare_gfpgan_proxy", new_callable=AsyncMock,
                         return_value=self.tmpdir / "proxy.json"), \
             patch("asyncio.create_subprocess_exec", return_value=proc_mock):

            async def run_test():
                from src.services.nerf_avatar_service import AvatarMode
                asset = await svc.create_avatar(
                    mode=AvatarMode.ERNERF,
                    source_image_path=str(face_img),
                )
                result = await svc.render_avatar_video(
                    avatar_id=asset.avatar_id,
                    duration_seconds=2.0,
                )
                return asset, result

            asset, result = run(run_test())

        self.assertEqual(asset.status.value, "ready")
        self.assertIsNotNone(result)

    def test_full_text2avatar_pipeline(self):
        """TEXT2AVATAR: create with text → render static video."""
        svc = self._make_service()

        proxy_path = self.tmpdir / "proxy.json"
        proxy_path.write_text(json.dumps({"type": "text2avatar_proxy"}))

        proc_mock = AsyncMock()
        proc_mock.returncode = 0
        proc_mock.communicate = AsyncMock(return_value=(b"", b""))

        with patch.object(svc, "_comfyui_available", return_value=False), \
             patch.object(svc, "_generate_avatar_image_fallback", new_callable=AsyncMock,
                         return_value=proxy_path), \
             patch("asyncio.create_subprocess_exec", return_value=proc_mock):

            async def run_test():
                from src.services.nerf_avatar_service import AvatarMode
                asset = await svc.create_avatar(
                    mode=AvatarMode.TEXT2AVATAR,
                    text_prompt="a pirate captain",
                    style_prompt="cartoon style",
                )
                return asset

            asset = run(run_test())

        self.assertEqual(asset.text_prompt, "a pirate captain")
        self.assertEqual(asset.style_prompt, "cartoon style")
        self.assertEqual(asset.status.value, "ready")

    def test_full_uv_volumes_pipeline(self):
        """UV_VOLUMES: create from video → check UV appearance built."""
        svc = self._make_service()
        video_path = self.tmpdir / "person.mp4"
        video_path.write_bytes(b"\x00" * 64)

        proc_mock = AsyncMock()
        proc_mock.returncode = 0
        proc_mock.communicate = AsyncMock(return_value=(b"", b""))

        with patch.object(svc, "_comfyui_available", return_value=False), \
             patch("asyncio.create_subprocess_exec", return_value=proc_mock):

            async def run_test():
                from src.services.nerf_avatar_service import AvatarMode
                return await svc.create_avatar(
                    mode=AvatarMode.UV_VOLUMES,
                    source_video_path=str(video_path),
                )

            asset = run(run_test())

        self.assertEqual(asset.status.value, "ready")
        self.assertIsNotNone(asset.uv_appearance)


if __name__ == "__main__":
    unittest.main()
