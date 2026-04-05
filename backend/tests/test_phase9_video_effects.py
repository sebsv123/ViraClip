"""
Tests for Phase 9.10/9.11 — video_effects.py and updated creative_pipeline wiring.
All FFmpeg subprocess calls are mocked; no real video files required.
"""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_preset(zoom_punch=True, extra_filters=None, resolution=(1080, 1920), fps=30):
    p = MagicMock()
    p.zoom_punch_enabled = zoom_punch
    p.extra_vf_filters = extra_filters or ["vignette=PI/6", "eq=saturation=1.1"]
    p.resolution = resolution
    p.fps = fps
    p.name = "TikTok Viral"
    return p


def _make_event(t=1.5, etype="audio_peak", strength=0.8, duration=0.3):
    from src.services.multimodal_detector import TimelineEvent
    return TimelineEvent(t=t, type=etype, strength=strength, duration=duration)


# ── _build_zoompan ────────────────────────────────────────────────────────────

class TestBuildZoompan:
    def test_single_peak(self):
        from src.services.video_effects import _build_zoompan
        peaks = [_make_event(t=2.0)]
        preset = _make_preset()
        result = _build_zoompan(peaks, preset)
        assert "zoompan=" in result
        assert "between(t,2.0,2.25)" in result
        assert "1080x1920" in result

    def test_multiple_peaks(self):
        from src.services.video_effects import _build_zoompan
        peaks = [_make_event(t=1.0), _make_event(t=4.0), _make_event(t=7.0)]
        preset = _make_preset()
        result = _build_zoompan(peaks, preset)
        assert "between(t,1.0" in result
        assert "between(t,4.0" in result
        assert "between(t,7.0" in result

    def test_caps_at_max_punches(self):
        from src.services.video_effects import _build_zoompan, _MAX_PUNCHES
        peaks = [_make_event(t=float(i)) for i in range(_MAX_PUNCHES + 3)]
        preset = _make_preset()
        result = _build_zoompan(peaks, preset)
        # Only up to _MAX_PUNCHES "between" occurrences
        assert result.count("between(t,") == _MAX_PUNCHES

    def test_zoom_factor_present(self):
        from src.services.video_effects import _build_zoompan, _PUNCH_ZOOM
        peaks = [_make_event(t=1.0)]
        preset = _make_preset()
        result = _build_zoompan(peaks, preset)
        assert str(_PUNCH_ZOOM) in result

    def test_center_pan(self):
        from src.services.video_effects import _build_zoompan
        peaks = [_make_event(t=1.0)]
        preset = _make_preset()
        result = _build_zoompan(peaks, preset)
        assert "iw/2-(iw/zoom/2)" in result
        assert "ih/2-(ih/zoom/2)" in result


# ── apply_preset_effects ──────────────────────────────────────────────────────

class TestApplyPresetEffects:
    @pytest.mark.asyncio
    async def test_no_effects_returns_none(self, tmp_path):
        from src.services.video_effects import apply_preset_effects
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 1000)
        preset = _make_preset(zoom_punch=False, extra_filters=[])
        result = await apply_preset_effects(clip, preset, [], tmp_path / "out.mp4")
        assert result is None

    @pytest.mark.asyncio
    async def test_color_grade_only_no_peaks(self, tmp_path):
        from src.services.video_effects import apply_preset_effects
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 1000)
        preset = _make_preset(zoom_punch=False, extra_filters=["eq=saturation=1.1"])
        out = tmp_path / "out.mp4"

        mock_proc = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            # output file won't exist — simulate FFmpeg failure → returns None
            result = await apply_preset_effects(clip, preset, [], out)
        assert result is None  # out doesn't actually exist

    @pytest.mark.asyncio
    async def test_returns_output_path_on_success(self, tmp_path):
        from src.services.video_effects import apply_preset_effects
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 1000)
        preset = _make_preset(zoom_punch=True, extra_filters=["vignette=PI/6"])
        peaks = [_make_event(t=1.0, strength=0.8)]

        mock_proc = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        async def fake_exec(*args, **kwargs):
            # Write output file to simulate FFmpeg success
            out_path = Path(args[-1])
            out_path.write_bytes(b"y" * 2000)
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await apply_preset_effects(
                clip, preset, peaks, tmp_path / "out.mp4"
            )
        assert result is not None
        assert result.exists()

    @pytest.mark.asyncio
    async def test_zoom_punch_skips_weak_peaks(self, tmp_path):
        """Weak peaks (strength < 0.65) should not trigger zoom punch."""
        from src.services.video_effects import apply_preset_effects
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 1000)
        preset = _make_preset(zoom_punch=True, extra_filters=[])
        weak_peaks = [_make_event(t=1.0, strength=0.4)]  # below 0.65 threshold

        # With only weak peaks and no extra_vf_filters, nothing to apply
        result = await apply_preset_effects(clip, preset, weak_peaks, tmp_path / "out.mp4")
        assert result is None

    @pytest.mark.asyncio
    async def test_ffmpeg_timeout_returns_none(self, tmp_path):
        from src.services.video_effects import apply_preset_effects
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 1000)
        preset = _make_preset(zoom_punch=True, extra_filters=["vignette=PI/6"])
        peaks = [_make_event(t=1.0, strength=0.9)]

        mock_proc = MagicMock()
        mock_proc.wait = AsyncMock(side_effect=asyncio.TimeoutError)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await apply_preset_effects(clip, preset, peaks, tmp_path / "out.mp4")
        assert result is None


# ── overlay_broll_clips ───────────────────────────────────────────────────────

class TestOverlayBrollClips:
    @pytest.mark.asyncio
    async def test_empty_pairs_returns_none(self, tmp_path):
        from src.services.video_effects import overlay_broll_clips
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 1000)
        result = await overlay_broll_clips(clip, [], tmp_path / "out.mp4")
        assert result is None

    @pytest.mark.asyncio
    async def test_single_broll_builds_filtergraph(self, tmp_path):
        from src.services.video_effects import overlay_broll_clips
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 1000)

        event = _make_event(t=5.0, etype="keyword", duration=2.0)
        asset = MagicMock()
        asset.path = str(tmp_path / "broll.mp4")
        (tmp_path / "broll.mp4").write_bytes(b"b" * 1000)

        captured_args = {}

        async def fake_exec(*args, **kwargs):
            captured_args["args"] = args
            out_path = Path(args[-1])
            out_path.write_bytes(b"y" * 2000)
            proc = MagicMock()
            proc.wait = AsyncMock(return_value=0)
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await overlay_broll_clips(clip, [(event, asset)], tmp_path / "out.mp4")

        assert result is not None
        cmd_args = " ".join(str(a) for a in captured_args["args"])
        assert "-filter_complex" in cmd_args
        assert "overlay" in cmd_args
        assert "between(t,5.0" in cmd_args

    @pytest.mark.asyncio
    async def test_caps_at_broll_max(self, tmp_path):
        from src.services.video_effects import overlay_broll_clips, _BROLL_MAX
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 1000)

        pairs = []
        for i in range(_BROLL_MAX + 2):
            event = _make_event(t=float(i * 10), etype="keyword", duration=2.0)
            asset = MagicMock()
            broll_f = tmp_path / f"broll{i}.mp4"
            broll_f.write_bytes(b"b" * 500)
            asset.path = str(broll_f)
            pairs.append((event, asset))

        captured_args = {}

        async def fake_exec(*args, **kwargs):
            captured_args["args"] = args
            out_path = Path(args[-1])
            out_path.write_bytes(b"y" * 2000)
            proc = MagicMock()
            proc.wait = AsyncMock(return_value=0)
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            await overlay_broll_clips(clip, pairs, tmp_path / "out.mp4")

        # Should have used at most _BROLL_MAX inputs (main + _BROLL_MAX b-rolls)
        input_flags = [a for a in captured_args["args"] if a == "-i"]
        assert len(input_flags) == _BROLL_MAX + 1  # main + capped b-rolls

    @pytest.mark.asyncio
    async def test_overlay_enable_expression_correct(self, tmp_path):
        from src.services.video_effects import overlay_broll_clips
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 1000)

        event = _make_event(t=10.0, etype="keyword", duration=3.0)
        asset = MagicMock()
        asset.path = str(tmp_path / "broll.mp4")
        (tmp_path / "broll.mp4").write_bytes(b"b" * 500)

        captured = {}

        async def fake_exec(*args, **kwargs):
            captured["args"] = args
            out = Path(args[-1])
            out.write_bytes(b"y" * 2000)
            proc = MagicMock()
            proc.wait = AsyncMock(return_value=0)
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            await overlay_broll_clips(clip, [(event, asset)], tmp_path / "out.mp4")

        # t_start=10.0, t_end=10.0 + (3.0+1.0) = 14.0
        cmd_str = " ".join(str(a) for a in captured["args"])
        assert "between(t,10.0,14.0)" in cmd_str


# ── creative_pipeline integration (new steps 5 + 6) ──────────────────────────

class TestCreativePipelineNewSteps:
    @pytest.mark.asyncio
    async def test_broll_count_in_meta(self, tmp_path):
        from src.services.creative_pipeline import CreativePipeline
        from src.services.multimodal_detector import TimelineEvent
        from src.services.virality_engine import ViralityPrediction
        from src.services.smart_templates import PRESETS
        from src.services.hook_engine import HookResult
        from src.services.contextual_broll import BrollAsset

        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 5000)
        source = tmp_path / "source.mp4"
        source.write_bytes(b"s" * 10000)

        broll_file = tmp_path / "broll.mp4"
        broll_file.write_bytes(b"b" * 3000)

        keyword_event = TimelineEvent(
            t=5.0, type="keyword", strength=0.9, duration=2.0,
            payload={"word": "ocean", "category": "hook"},
        )

        pipeline = CreativePipeline()

        with (
            patch("src.services.multimodal_detector.get_multimodal_detector") as m_det,
            patch("src.services.virality_engine.get_virality_engine") as m_eng,
            patch("src.services.smart_templates.get_template_selector") as m_tmpl,
            patch("src.services.hook_engine.get_hook_engine") as m_hook,
            patch("src.services.contextual_broll.get_contextual_broll") as m_broll,
            patch("src.services.video_effects.overlay_broll_clips", new_callable=AsyncMock) as m_overlay,
            patch("src.services.video_effects.apply_preset_effects", new_callable=AsyncMock) as m_vfx,
            patch("src.services.smart_audio.get_smart_audio") as m_audio,
            patch("src.services.learning_loop.get_learning_loop") as m_qa,
        ):
            m_det.return_value.generate_timeline = AsyncMock(return_value=[keyword_event])

            pred = ViralityPrediction(
                score=70.0, hook_score=75.0, pacing_score=65.0, emotion_score=70.0,
                improvements=[], marked_for_enhancement=False,
            )
            m_eng.return_value.predict = AsyncMock(return_value=pred)
            m_tmpl.return_value.select = MagicMock(return_value=PRESETS["tiktok_viral"])
            m_hook.return_value.find_best_hook = MagicMock(
                return_value=HookResult(0.0, 0.5, "ocean", 0.8, False, True)
            )

            asset = BrollAsset(path=str(broll_file), source="local", keyword="ocean", duration=3.0)
            m_broll.return_value.get_for_timeline = AsyncMock(
                return_value=[(keyword_event, asset)]
            )

            # Overlay "succeeds" — writes a valid file then returns it
            brolled = tmp_path / f"broll_{clip.name}"
            brolled.write_bytes(b"v" * 5500)
            m_overlay.return_value = brolled

            # VFX returns None (no peaks strong enough after B-roll)
            m_vfx.return_value = None

            m_audio.return_value.master = AsyncMock(return_value=clip)

            manifest = MagicMock()
            manifest.qa_passed = True
            manifest.qa_issues = []
            m_qa.return_value.post_render_analysis = AsyncMock(return_value=manifest)

            meta = await pipeline.enhance(
                clip_path=clip,
                source_video=source,
                segment={"start_time": 0.0, "end_time": 30.0,
                         "transcript": "ocean waves are beautiful"},
                words=[],
                audio_features={"energy": 0.5},
                task_id="t1",
                clip_index=0,
                platform="tiktok",
            )

        assert meta["broll_overlays"] == 1
        assert meta["creative_enhanced"] is True

    @pytest.mark.asyncio
    async def test_meta_has_new_vfx_keys(self, tmp_path):
        """zoom_punch_applied and color_grade_applied must always be present."""
        from src.services.creative_pipeline import CreativePipeline

        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 5000)
        source = tmp_path / "src.mp4"

        pipeline = CreativePipeline()

        with (
            patch("src.services.multimodal_detector.get_multimodal_detector",
                  side_effect=Exception("skip")),
        ):
            meta = await pipeline.enhance(
                clip_path=clip,
                source_video=source,
                segment={"start_time": 0.0, "end_time": 30.0, "transcript": "test"},
                words=[],
                audio_features={},
                task_id="t2",
                clip_index=0,
                platform="tiktok",
            )

        assert "broll_overlays" in meta
        assert "zoom_punch_applied" in meta
        assert "color_grade_applied" in meta

    @pytest.mark.asyncio
    async def test_broll_failure_does_not_break_pipeline(self, tmp_path):
        """B-roll step failure must not prevent audio mastering or QA."""
        from src.services.creative_pipeline import CreativePipeline

        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 5000)
        source = tmp_path / "src.mp4"
        source.write_bytes(b"y" * 10000)

        pipeline = CreativePipeline()

        with (
            patch("src.services.multimodal_detector.get_multimodal_detector",
                  side_effect=Exception("no timeline")),
            patch("src.services.contextual_broll.get_contextual_broll",
                  side_effect=Exception("broll service down")),
        ):
            meta = await pipeline.enhance(
                clip_path=clip,
                source_video=source,
                segment={"start_time": 0.0, "end_time": 30.0, "transcript": "test"},
                words=[],
                audio_features={},
                task_id="t3",
                clip_index=0,
                platform="tiktok",
            )

        # Pipeline must finish and return all keys
        assert "broll_overlays" in meta
        assert "sfx_injected" in meta
        assert "qa_passed" in meta
