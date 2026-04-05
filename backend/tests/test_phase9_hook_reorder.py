"""
Tests for Phase 9.12 — hook_reorder.py and creative_pipeline step 4.5.
All FFmpeg calls are mocked.
"""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ── prepend_hook_flash ────────────────────────────────────────────────────────

class TestPrependHookFlash:
    @pytest.mark.asyncio
    async def test_hook_inside_window_returns_none(self, tmp_path):
        """Hooks already in the first 3s should not be reordered."""
        from src.services.hook_reorder import prepend_hook_flash, HOOK_WINDOW_S
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 1000)
        result = await prepend_hook_flash(clip, hook_start=2.0, hook_end=2.5,
                                          output_path=tmp_path / "out.mp4")
        assert result is None

    @pytest.mark.asyncio
    async def test_hook_at_boundary_skipped(self, tmp_path):
        """hook_start == HOOK_WINDOW_S must also be skipped."""
        from src.services.hook_reorder import prepend_hook_flash, HOOK_WINDOW_S
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 1000)
        result = await prepend_hook_flash(clip, hook_start=3.0, hook_end=3.5,
                                          output_path=tmp_path / "out.mp4")
        assert result is None

    @pytest.mark.asyncio
    async def test_successful_prepend(self, tmp_path):
        """When hook is beyond 3s and FFmpeg succeeds, returns output_path."""
        from src.services.hook_reorder import prepend_hook_flash
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 1000)
        out = tmp_path / "out.mp4"

        async def fake_exec(*args, **kwargs):
            # Write output to simulate successful FFmpeg
            Path(args[-1]).write_bytes(b"y" * 2000)
            proc = MagicMock()
            proc.wait = AsyncMock(return_value=0)
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await prepend_hook_flash(clip, hook_start=15.0, hook_end=15.5,
                                              output_path=out)
        assert result == out
        assert out.exists()

    @pytest.mark.asyncio
    async def test_ffmpeg_failure_returns_none(self, tmp_path):
        """When FFmpeg produces no output, returns None."""
        from src.services.hook_reorder import prepend_hook_flash
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 1000)

        mock_proc = MagicMock()
        mock_proc.wait = AsyncMock(return_value=1)  # exit code 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await prepend_hook_flash(clip, hook_start=10.0, hook_end=10.5,
                                              output_path=tmp_path / "out.mp4")
        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self, tmp_path):
        from src.services.hook_reorder import prepend_hook_flash
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 1000)

        mock_proc = MagicMock()
        mock_proc.wait = AsyncMock(side_effect=asyncio.TimeoutError)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await prepend_hook_flash(clip, hook_start=10.0, hook_end=10.5,
                                              output_path=tmp_path / "out.mp4")
        assert result is None

    @pytest.mark.asyncio
    async def test_filtergraph_structure(self, tmp_path):
        """Verify the FFmpeg filtergraph contains concat with flash + full segments."""
        from src.services.hook_reorder import prepend_hook_flash, FLASH_DURATION_S
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 1000)

        captured = {}

        async def fake_exec(*args, **kwargs):
            captured["args"] = args
            out = Path(args[-1])
            out.write_bytes(b"y" * 2000)
            proc = MagicMock()
            proc.wait = AsyncMock(return_value=0)
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            await prepend_hook_flash(clip, hook_start=20.0, hook_end=20.5,
                                     output_path=tmp_path / "out.mp4")

        cmd = " ".join(str(a) for a in captured["args"])
        assert "concat=n=2:v=1:a=1" in cmd
        assert "filter_complex" in cmd
        # flash segment trim should reference hook_start - FLASH_PRE_PAD
        assert "trim" in cmd
        assert "atrim" in cmd

    @pytest.mark.asyncio
    async def test_pre_pad_clamps_at_zero(self, tmp_path):
        """When hook_start is very early (but > 3s), flash_start should not go negative."""
        from src.services.hook_reorder import prepend_hook_flash, FLASH_PRE_PAD_S
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 1000)

        captured = {}

        async def fake_exec(*args, **kwargs):
            captured["args"] = args
            out = Path(args[-1])
            out.write_bytes(b"y" * 2000)
            proc = MagicMock()
            proc.wait = AsyncMock(return_value=0)
            return proc

        hook_start = 3.1  # very close to boundary but > 3.0
        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await prepend_hook_flash(clip, hook_start=hook_start, hook_end=3.6,
                                              output_path=tmp_path / "out.mp4")

        if result:  # only check if FFmpeg was called
            cmd = " ".join(str(a) for a in captured["args"])
            # flash_start = max(0, 3.1 - 0.25) = 2.85 — must be non-negative
            assert "start=-" not in cmd  # no negative start value


# ── creative_pipeline step 4.5 ────────────────────────────────────────────────

class TestCreativePipelineHookReorder:
    @pytest.mark.asyncio
    async def test_hook_reorder_applied_flag(self, tmp_path):
        """When hook reorder is suggested and hook is beyond 3s, flag should be True."""
        from src.services.creative_pipeline import CreativePipeline
        from src.services.multimodal_detector import TimelineEvent
        from src.services.virality_engine import ViralityPrediction
        from src.services.smart_templates import PRESETS
        from src.services.hook_engine import HookResult

        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 5000)
        source = tmp_path / "src.mp4"
        source.write_bytes(b"s" * 10000)

        pipeline = CreativePipeline()

        words = [{"word": "secreto", "start": 15.0, "end": 15.5}]

        with (
            patch("src.services.multimodal_detector.get_multimodal_detector") as m_det,
            patch("src.services.virality_engine.get_virality_engine") as m_eng,
            patch("src.services.smart_templates.get_template_selector") as m_tmpl,
            patch("src.services.hook_engine.get_hook_engine") as m_hook,
            patch("src.services.hook_reorder.prepend_hook_flash",
                  new_callable=AsyncMock) as m_reorder,
            patch("src.services.contextual_broll.get_contextual_broll") as m_broll,
            patch("src.services.video_effects.apply_preset_effects",
                  new_callable=AsyncMock, return_value=None),
            patch("src.services.smart_audio.get_smart_audio") as m_audio,
            patch("src.services.learning_loop.get_learning_loop") as m_qa,
        ):
            m_det.return_value.generate_timeline = AsyncMock(return_value=[])
            pred = ViralityPrediction(
                score=65.0, hook_score=60.0, pacing_score=65.0, emotion_score=60.0,
                improvements=[], marked_for_enhancement=False,
            )
            m_eng.return_value.predict = AsyncMock(return_value=pred)
            m_tmpl.return_value.select = MagicMock(return_value=PRESETS["tiktok_viral"])
            m_hook.return_value.find_best_hook = MagicMock(
                return_value=HookResult(
                    hook_start=15.0, hook_end=15.5,
                    hook_text="secreto", hook_score=0.9,
                    reorder=True, already_optimized=False,
                )
            )

            # Simulate successful reorder — write a new file
            reordered = tmp_path / f"hook_{clip.name}"
            reordered.write_bytes(b"r" * 6000)
            m_reorder.return_value = reordered

            m_broll.return_value.get_for_timeline = AsyncMock(return_value=[])
            m_audio.return_value.master = AsyncMock(return_value=clip)

            manifest = MagicMock()
            manifest.qa_passed = True
            manifest.qa_issues = []
            m_qa.return_value.post_render_analysis = AsyncMock(return_value=manifest)

            meta = await pipeline.enhance(
                clip_path=clip,
                source_video=source,
                segment={"start_time": 0.0, "end_time": 60.0,
                         "transcript": "el secreto que nadie te contó"},
                words=words,
                audio_features={"energy": 0.6},
                task_id="t-hook",
                clip_index=0,
                platform="tiktok",
            )

        assert "hook_reorder_applied" in meta
        assert meta["hook_reorder_applied"] is True

    @pytest.mark.asyncio
    async def test_hook_reorder_not_applied_when_already_optimized(self, tmp_path):
        """When hook is already in first 3s, no reorder should be attempted."""
        from src.services.creative_pipeline import CreativePipeline
        from src.services.virality_engine import ViralityPrediction
        from src.services.smart_templates import PRESETS
        from src.services.hook_engine import HookResult

        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 5000)
        source = tmp_path / "src.mp4"

        pipeline = CreativePipeline()

        with (
            patch("src.services.multimodal_detector.get_multimodal_detector",
                  side_effect=Exception("no timeline")),
            patch("src.services.virality_engine.get_virality_engine") as m_eng,
            patch("src.services.smart_templates.get_template_selector") as m_tmpl,
            patch("src.services.hook_engine.get_hook_engine") as m_hook,
            patch("src.services.hook_reorder.prepend_hook_flash",
                  new_callable=AsyncMock) as m_reorder,
            patch("src.services.contextual_broll.get_contextual_broll") as m_broll,
            patch("src.services.video_effects.apply_preset_effects",
                  new_callable=AsyncMock, return_value=None),
            patch("src.services.smart_audio.get_smart_audio") as m_audio,
            patch("src.services.learning_loop.get_learning_loop") as m_qa,
        ):
            pred = ViralityPrediction(
                score=80.0, hook_score=85.0, pacing_score=75.0, emotion_score=80.0,
                improvements=[], marked_for_enhancement=False,
            )
            m_eng.return_value.predict = AsyncMock(return_value=pred)
            m_tmpl.return_value.select = MagicMock(return_value=PRESETS["tiktok_viral"])
            m_hook.return_value.find_best_hook = MagicMock(
                return_value=HookResult(
                    hook_start=1.0, hook_end=1.5,
                    hook_text="secreto", hook_score=0.9,
                    reorder=False, already_optimized=True,  # ← already optimized
                )
            )
            m_broll.return_value.get_for_timeline = AsyncMock(return_value=[])
            m_audio.return_value.master = AsyncMock(return_value=clip)
            manifest = MagicMock()
            manifest.qa_passed = True
            manifest.qa_issues = []
            m_qa.return_value.post_render_analysis = AsyncMock(return_value=manifest)

            meta = await pipeline.enhance(
                clip_path=clip,
                source_video=source,
                segment={"start_time": 0.0, "end_time": 60.0,
                         "transcript": "el secreto"},
                words=[{"word": "secreto", "start": 1.0, "end": 1.5}],
                audio_features={},
                task_id="t-opt",
                clip_index=0,
                platform="tiktok",
            )

        # prepend_hook_flash should NOT have been called
        m_reorder.assert_not_called()
        assert meta.get("hook_reorder_applied") is False

    @pytest.mark.asyncio
    async def test_hook_reorder_key_always_in_meta(self, tmp_path):
        """hook_reorder_applied must always be present in output meta."""
        from src.services.creative_pipeline import CreativePipeline

        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 1000)
        source = tmp_path / "src.mp4"

        pipeline = CreativePipeline()

        with patch("src.services.multimodal_detector.get_multimodal_detector",
                   side_effect=Exception("fail all")):
            meta = await pipeline.enhance(
                clip_path=clip,
                source_video=source,
                segment={"start_time": 0.0, "end_time": 30.0, "transcript": "test"},
                words=[],
                audio_features={},
                task_id="t-keys",
                clip_index=0,
                platform="tiktok",
            )

        assert "hook_reorder_applied" in meta
