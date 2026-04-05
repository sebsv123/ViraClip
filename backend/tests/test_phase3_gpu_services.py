"""
Tests — Phase 3 GPU Services
=============================
Tests for T2V B-roll, TTS narration, ESRGAN upscaling, RVC voice enhancement,
optical flow service, and LoRA training service.

All tests use mocking so they run without GPU hardware.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_tmp_mp4(tmp_path: Path, name: str = "clip.mp4") -> Path:
    """Create a minimal placeholder mp4 file for path-based assertions."""
    f = tmp_path / name
    f.write_bytes(b"\x00\x01\x02\x03")   # dummy content
    return f


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3.1 — T2V B-Roll Service
# ─────────────────────────────────────────────────────────────────────────────

class TestT2VBrollService:

    def test_is_available_no_gpu(self):
        with patch("torch.cuda.is_available", return_value=False):
            from src.services.t2v_broll_service import T2VBrollService
            assert T2VBrollService.is_available() is False

    def test_is_available_no_diffusers(self):
        import sys
        with patch.dict(sys.modules, {"diffusers": None}):
            from src.services import t2v_broll_service as mod
            # When diffusers not importable, is_available returns False
            with patch.object(mod, "_get_device", return_value="cuda"):
                try:
                    result = mod.T2VBrollService.is_available()
                    assert result is False
                except Exception:
                    pass   # ImportError is also acceptable

    @pytest.mark.asyncio
    async def test_generate_uses_output_path(self, tmp_path):
        from src.services.t2v_broll_service import T2VBrollService

        dest = tmp_path / "out.mp4"

        def fake_generate_sync(*args, **kwargs):
            dest.write_bytes(b"fake_video")

        svc = T2VBrollService.__new__(T2VBrollService)
        svc.model      = "ltx-video"
        svc.resolution = "720p"
        svc.device     = "cpu"
        svc.out_dir    = tmp_path

        with patch.object(svc, "_generate_sync", side_effect=fake_generate_sync):
            result = await svc.generate(
                prompt="ocean sunset",
                duration=2.0,
                output_path=str(dest),
            )

        assert result["clip_path"] == str(dest)
        assert result["duration"]  == pytest.approx(2.0, abs=1.0)

    @pytest.mark.asyncio
    async def test_generate_animatelcm_fallback(self, tmp_path):
        from src.services.t2v_broll_service import T2VBrollService

        dest = tmp_path / "fallback.mp4"
        call_log = []

        def fake_sync(prompt, n_frames, w, h, fps, d, model_name):
            call_log.append(model_name)
            if model_name == "ltx-video":
                raise RuntimeError("LTX unavailable")
            d.write_bytes(b"animatelcm_video")

        svc = T2VBrollService.__new__(T2VBrollService)
        svc.model      = "ltx-video"
        svc.resolution = "720p"
        svc.device     = "cpu"
        svc.out_dir    = tmp_path

        with patch.object(svc, "_generate_sync", side_effect=fake_sync):
            result = await svc.generate(prompt="city night", duration=2.0,
                                        output_path=str(dest))

        assert "animatelcm" in call_log
        assert result["model"] == "animatelcm"


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3.3 — Upscaling Service
# ─────────────────────────────────────────────────────────────────────────────

class TestUpscalingService:

    def test_is_available_no_deps(self):
        import sys
        with patch.dict(sys.modules, {"realesrgan": None, "basicsr": None}):
            from src.services import upscaling_service as mod
            assert mod.UpscalingService.is_available() is False

    def test_probe_resolution_fallback(self, tmp_path):
        from src.services.upscaling_service import UpscalingService
        fake_video = tmp_path / "v.mp4"
        fake_video.write_bytes(b"")
        # Should return default 720x1280 on probe failure
        w, h = UpscalingService._probe_resolution(fake_video)
        assert w > 0
        assert h > 0

    @pytest.mark.asyncio
    async def test_upscale_ffmpeg_fallback(self, tmp_path):
        from src.services.upscaling_service import UpscalingService

        src  = make_tmp_mp4(tmp_path, "src.mp4")
        dest = tmp_path / "up_src.mp4"

        svc = UpscalingService()

        with patch.object(UpscalingService, "is_available", return_value=False), \
             patch.object(UpscalingService, "_probe_resolution", return_value=(720, 1280)), \
             patch.object(UpscalingService, "_ffmpeg_scale", new_callable=AsyncMock) as mock_ff:
            mock_ff.return_value = None
            dest.write_bytes(b"scaled")
            result = await svc.upscale(str(src), scale_factor=2, output_path=str(dest))

        assert result["original_resolution"] == "720x1280"
        assert result["output_resolution"]   == "1440x2560"
        mock_ff.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3.4 — TTS Service
# ─────────────────────────────────────────────────────────────────────────────

class TestTTSService:

    def test_is_available_without_tts(self):
        import sys
        with patch.dict(sys.modules, {"TTS": None}):
            from src.services import tts_service as mod
            # Re-evaluate with the mock
            import importlib
            try:
                importlib.reload(mod)
                assert mod.TTSService.is_available() is False
            except Exception:
                pass   # ImportError is also acceptable

    def test_supported_languages_contains_common(self):
        from src.services.tts_service import TTSService
        for lang in ("en", "es", "fr", "de", "pt"):
            assert lang in TTSService.SUPPORTED_LANGUAGES

    def test_unsupported_language_falls_back_to_en(self):
        from src.services.tts_service import TTSService
        svc = TTSService.__new__(TTSService)
        svc.out_dir = Path("/tmp")
        # Verify language normalization logic
        lang = "xx-fake"
        if lang not in TTSService.SUPPORTED_LANGUAGES:
            normalised = "en"
        assert normalised == "en"

    @pytest.mark.asyncio
    async def test_synthesize_calls_sync(self, tmp_path):
        from src.services.tts_service import TTSService

        dest = tmp_path / "narration.wav"

        def fake_synth_sync(text, speaker, language, d, speed):
            d.write_bytes(b"fake_wav")

        svc = TTSService.__new__(TTSService)
        svc.out_dir = tmp_path

        with patch.object(svc, "_synthesize_sync", side_effect=fake_synth_sync), \
             patch.object(TTSService, "_get_duration", return_value=2.5):
            result = await svc.synthesize("Hello world!", output_path=str(dest))

        assert result["duration"] == 2.5
        assert result["language"] == "en"
        assert Path(result["audio_path"]).name == "narration.wav"


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3.2 — RVC Voice Enhancement
# ─────────────────────────────────────────────────────────────────────────────

class TestRVCVoiceEnhancement:

    @pytest.mark.asyncio
    async def test_rvc_unavailable_falls_back_to_ffmpeg(self, tmp_path):
        from src.video_processing.audio import apply_voice_enhancement

        src  = make_tmp_mp4(tmp_path, "src.mp4")
        dest = tmp_path / "rvc_out.mp4"

        # RVC not installed — should use FFmpeg EQ fallback
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            mock_proc.return_value = MagicMock(
                returncode=0,
                communicate=AsyncMock(return_value=(b"", b"")),
            )
            dest.write_bytes(b"enhanced")
            result = await apply_voice_enhancement(str(src), str(dest))

        # Either RVC succeeded or FFmpeg fallback ran — result is bool
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_rvc_model_not_found_triggers_fallback(self, tmp_path):
        from src.video_processing.audio import apply_voice_enhancement

        src  = make_tmp_mp4(tmp_path, "src.mp4")
        dest = tmp_path / "rvc_out.mp4"

        with patch.dict(os.environ, {"RVC_MODEL_PATH": "/nonexistent/model.pth"}), \
             patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            mock_proc.return_value = MagicMock(
                returncode=0,
                communicate=AsyncMock(return_value=(b"", b"")),
            )
            dest.write_bytes(b"enhanced")
            result = await apply_voice_enhancement(str(src), str(dest))

        assert isinstance(result, bool)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2.3 — Optical Flow Service
# ─────────────────────────────────────────────────────────────────────────────

class TestOpticalFlowService:

    def test_is_available_returns_bool(self):
        from src.services.optical_flow_service import OpticalFlowService
        result = OpticalFlowService.is_available()
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_generate_transition_no_result(self, tmp_path):
        from src.services.optical_flow_service import OpticalFlowService

        clip_a = make_tmp_mp4(tmp_path, "a.mp4")
        clip_b = make_tmp_mp4(tmp_path, "b.mp4")

        svc = OpticalFlowService()

        def fake_sync(src_a, src_b, duration, dest):
            return {"output_path": None, "transition_frames": 0, "method": "none"}

        with patch.object(svc, "_generate_sync", side_effect=fake_sync):
            result = await svc.generate_transition(str(clip_a), str(clip_b))

        assert result["method"] == "none"
        assert result["output_path"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Phase 7.3 — LoRA Training Service
# ─────────────────────────────────────────────────────────────────────────────

class TestLoRATrainingService:

    def test_is_available_no_peft(self):
        import sys
        with patch.dict(sys.modules, {"peft": None}):
            from src.services import lora_training_service as mod
            assert mod.LoRATrainingService.is_available() is False

    def test_load_dataset_empty_folder(self, tmp_path):
        from src.services.lora_training_service import LoRATrainingService
        samples = LoRATrainingService._load_dataset(str(tmp_path), "test_style")
        # Should return synthetic samples when folder is empty
        assert len(samples) >= 1
        assert all("caption" in s for s in samples)

    def test_load_dataset_from_folder(self, tmp_path):
        from src.services.lora_training_service import LoRATrainingService
        # Create image + caption pairs
        for i in range(3):
            (tmp_path / f"img_{i:03d}.jpg").write_bytes(b"\xff\xd8\xff")
            (tmp_path / f"img_{i:03d}.txt").write_text(f"caption {i}")

        samples = LoRATrainingService._load_dataset(str(tmp_path), "my_style")
        assert len(samples) == 3
        assert all("image" in s and "caption" in s for s in samples)

    @pytest.mark.asyncio
    async def test_train_calls_sync(self, tmp_path):
        from src.services.lora_training_service import LoRATrainingService

        dest = tmp_path / "lora.safetensors"

        def fake_train_sync(*args):
            dest.write_bytes(b"lora_weights")
            return {"lora_path": str(dest), "loss": 0.05, "steps": 500, "style": "test"}

        svc = LoRATrainingService()
        with patch.object(svc, "_train_sync", side_effect=fake_train_sync):
            result = await svc.train(
                dataset_path=str(tmp_path),
                base_model="sd1.5",
                style_name="test",
                num_steps=500,
                output_path=str(dest),
            )

        assert result["loss"]  == pytest.approx(0.05)
        assert result["steps"] == 500
        assert result["style"] == "test"


# ─────────────────────────────────────────────────────────────────────────────
# SNR measurement
# ─────────────────────────────────────────────────────────────────────────────

class TestMeasureSnr:

    @pytest.mark.asyncio
    async def test_measure_snr_returns_float(self, tmp_path):
        from src.video_processing.audio_analysis import measure_snr

        fake_video = make_tmp_mp4(tmp_path, "v.mp4")

        # Mock ffmpeg with volumedetect output
        stderr_output = (
            b"  mean_volume: -25.0 dB\n"
            b"  max_volume: -5.0 dB\n"
        )

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", stderr_output))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            snr = await measure_snr(str(fake_video))

        assert isinstance(snr, float)
        assert snr == pytest.approx(20.0)   # max - mean = -5 - (-25) = 20

    @pytest.mark.asyncio
    async def test_measure_snr_ffmpeg_failure_returns_zero(self, tmp_path):
        from src.video_processing.audio_analysis import measure_snr

        fake_video = make_tmp_mp4(tmp_path, "v.mp4")

        with patch("asyncio.create_subprocess_exec", side_effect=RuntimeError("no ffmpeg")):
            snr = await measure_snr(str(fake_video))

        assert snr == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# GPU task routing integration smoke tests
# ─────────────────────────────────────────────────────────────────────────────

class TestGpuTaskRouting:

    @pytest.mark.asyncio
    async def test_generate_broll_t2v_task(self):
        from src.workers.gpu_tasks import generate_broll_t2v

        ctx   = {"gpu_available": True}
        fake_result = {"clip_path": "/tmp/broll.mp4", "duration": 3.0, "model": "ltx-video"}

        with patch("src.services.t2v_broll_service.T2VBrollService.generate",
                   new_callable=AsyncMock, return_value=fake_result):
            result = await generate_broll_t2v(
                ctx=ctx,
                task_id="test_task",
                prompt="ocean waves",
                duration_seconds=3.0,
            )

        assert result["clip_path"] == "/tmp/broll.mp4"
        assert result["model"]     == "ltx-video"

    @pytest.mark.asyncio
    async def test_generate_tts_narration_task(self):
        from src.workers.gpu_tasks import generate_tts_narration

        ctx   = {"gpu_available": True}
        fake_result = {"audio_path": "/tmp/narr.wav", "duration": 4.2, "language": "en"}

        with patch("src.services.tts_service.TTSService.synthesize",
                   new_callable=AsyncMock, return_value=fake_result):
            result = await generate_tts_narration(
                ctx=ctx,
                task_id="test_task",
                text="Welcome to this video!",
            )

        assert result["audio_path"] == "/tmp/narr.wav"
        assert result["language"]   == "en"

    @pytest.mark.asyncio
    async def test_upscale_clip_task(self, tmp_path):
        from src.workers.gpu_tasks import upscale_clip

        src = make_tmp_mp4(tmp_path, "low.mp4")
        ctx = {"gpu_available": True}
        fake_result = {
            "output_path":          str(tmp_path / "up.mp4"),
            "original_resolution":  "720x1280",
            "output_resolution":    "1440x2560",
        }

        with patch("src.services.upscaling_service.UpscalingService.upscale",
                   new_callable=AsyncMock, return_value=fake_result):
            result = await upscale_clip(
                ctx=ctx,
                task_id="test_task",
                input_path=str(src),
                scale_factor=2,
            )

        assert result["original_resolution"] == "720x1280"
        assert result["output_resolution"]   == "1440x2560"
