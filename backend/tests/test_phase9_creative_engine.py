"""
Tests for Phase 9 Creative Engine services.
All tests are CPU-only and mock external dependencies (FFmpeg subprocesses,
Phi-3 LLM, MLP scorer) so they run without hardware or network access.
"""

import asyncio
import json
import pytest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ── multimodal_detector ────────────────────────────────────────────────────────

class TestMultimodalDetector:
    def setup_method(self):
        from src.services.multimodal_detector import MultimodalDetector
        self.det = MultimodalDetector()

    def test_keyword_events_hook(self):
        words = [
            {"word": "Nunca", "start": 1.0, "end": 1.4, "confidence": 0.9},
            {"word": "verás", "start": 1.4, "end": 1.8, "confidence": 0.9},
        ]
        events = self.det._detect_keyword_events(words, segment_start=0.0)
        assert len(events) == 1
        assert events[0].type == "keyword"
        assert events[0].payload["category"] == "hook"
        assert events[0].strength == 0.9
        assert events[0].t == pytest.approx(1.0, abs=0.01)

    def test_keyword_events_impact(self):
        words = [{"word": "Top", "start": 2.0, "end": 2.3, "confidence": 0.85}]
        events = self.det._detect_keyword_events(words, segment_start=0.0)
        assert len(events) == 1
        assert events[0].payload["category"] == "impact"
        assert events[0].strength == 0.7

    def test_keyword_events_offset_by_segment_start(self):
        words = [{"word": "secreto", "start": 35.0, "end": 35.5, "confidence": 0.9}]
        events = self.det._detect_keyword_events(words, segment_start=30.0)
        assert events[0].t == pytest.approx(5.0, abs=0.01)

    def test_keyword_events_out_of_segment_ignored(self):
        # Word before segment start → t_rel < 0 → clamped to 0
        words = [{"word": "secreto", "start": 10.0, "end": 10.5, "confidence": 0.9}]
        events = self.det._detect_keyword_events(words, segment_start=20.0)
        # Still emitted but at t=0 (clamped)
        assert len(events) == 1
        assert events[0].t == 0.0

    def test_keyword_no_trigger_word(self):
        words = [{"word": "hola", "start": 1.0, "end": 1.2, "confidence": 0.8}]
        events = self.det._detect_keyword_events(words, segment_start=0.0)
        assert events == []

    def test_deduplicate_same_type_close(self):
        from src.services.multimodal_detector import TimelineEvent
        events = [
            TimelineEvent(t=1.00, type="audio_peak", strength=0.6, duration=0.2),
            TimelineEvent(t=1.05, type="audio_peak", strength=0.8, duration=0.2),
            TimelineEvent(t=2.00, type="audio_peak", strength=0.7, duration=0.2),
        ]
        result = self.det._deduplicate(events)
        assert len(result) == 2
        # The stronger one (0.8) should be kept
        assert result[0].strength == 0.8

    def test_deduplicate_different_types_preserved(self):
        from src.services.multimodal_detector import TimelineEvent
        events = [
            TimelineEvent(t=1.00, type="audio_peak", strength=0.7, duration=0.2),
            TimelineEvent(t=1.05, type="keyword",    strength=0.9, duration=0.3),
        ]
        result = self.det._deduplicate(events)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_generate_timeline_no_ffmpeg(self):
        """Without FFmpeg, audio peaks should return empty list gracefully."""
        with patch.object(self.det, "_ffmpeg_ok", False):
            events = await self.det.generate_timeline(
                video_path="/nonexistent.mp4",
                segment_start=0.0,
                segment_end=10.0,
                words=[{"word": "secreto", "start": 2.0, "end": 2.5, "confidence": 0.9}],
            )
        # keyword events still run; audio peaks skipped
        assert any(e.type == "keyword" for e in events)

    @pytest.mark.asyncio
    async def test_generate_timeline_sorted(self):
        """Events must be returned sorted by t."""
        with patch.object(self.det, "_ffmpeg_ok", False):
            words = [
                {"word": "top",     "start": 5.0, "end": 5.3, "confidence": 0.9},
                {"word": "secreto", "start": 2.0, "end": 2.5, "confidence": 0.9},
            ]
            events = await self.det.generate_timeline(
                video_path="/nonexistent.mp4",
                segment_start=0.0,
                segment_end=10.0,
                words=words,
            )
        ts = [e.t for e in events]
        assert ts == sorted(ts)


# ── virality_engine ───────────────────────────────────────────────────────────

class TestViralityEngine:
    def setup_method(self):
        from src.services.virality_engine import ViralityEngine
        self.engine = ViralityEngine()

    def test_hook_score_with_question(self):
        words = [{"word": "¿Nunca", "start": 0.0, "end": 0.5}]
        score = self.engine._score_hook(words)
        assert score > 60.0

    def test_hook_score_no_keywords(self):
        words = [{"word": "hola", "start": 0.0, "end": 0.3}]
        score = self.engine._score_hook(words)
        assert score == pytest.approx(45.0, abs=5.0)

    def test_pacing_score_empty(self):
        score = self.engine._score_pacing([])
        assert score == pytest.approx(45.0, abs=1.0)

    def test_pacing_score_optimal_density(self):
        from src.services.multimodal_detector import TimelineEvent
        events = [
            TimelineEvent(t=float(i), type="audio_peak", strength=0.7, duration=0.2)
            for i in range(10)
        ]
        score = self.engine._score_pacing(events)
        assert score > 70.0

    def test_emotion_score_high_energy(self):
        from src.services.multimodal_detector import TimelineEvent
        peaks = [
            TimelineEvent(t=float(i), type="audio_peak", strength=0.8, duration=0.2)
            for i in range(5)
        ]
        score = self.engine._score_emotion({"energy": 0.8}, peaks)
        assert score > 60.0

    @pytest.mark.asyncio
    async def test_predict_returns_valid_range(self):
        from src.services.multimodal_detector import TimelineEvent
        timeline = [TimelineEvent(t=1.0, type="audio_peak", strength=0.7, duration=0.2)]

        with patch("src.services.virality_engine.ViralityEngine._get_phi3_score", new_callable=AsyncMock) as mock_phi3:
            mock_phi3.return_value = 65.0
            pred = await self.engine.predict(
                transcript="Nunca verás esto. ¿Es increíble?",
                words=[{"word": "Nunca", "start": 0.0, "end": 0.4}],
                audio_features={"energy": 0.6},
                timeline_events=timeline,
            )

        assert 0.0 <= pred.score <= 100.0
        assert 0.0 <= pred.hook_score <= 100.0
        assert 0.0 <= pred.pacing_score <= 100.0
        assert 0.0 <= pred.emotion_score <= 100.0
        assert isinstance(pred.improvements, list)
        assert isinstance(pred.marked_for_enhancement, bool)

    @pytest.mark.asyncio
    async def test_predict_fallback_heuristic(self):
        """Should not raise even when all external scorers fail."""
        with patch("src.services.virality_engine.ViralityEngine._get_phi3_score", new_callable=AsyncMock) as mock_phi3:
            mock_phi3.side_effect = Exception("LLM unavailable")
            pred = await self.engine.predict(
                transcript="hello world",
                words=[],
                audio_features={},
                timeline_events=[],
            )
        assert 0.0 <= pred.score <= 100.0

    def test_improvements_when_hook_low(self):
        suggestions = self.engine._improvements(50.0, 30.0, 70.0, 70.0, [])
        assert any("hook" in s.lower() for s in suggestions)

    def test_improvements_publish_ready(self):
        from src.services.multimodal_detector import TimelineEvent
        peaks = [TimelineEvent(t=0.5, type="audio_peak", strength=0.8, duration=0.2)]
        suggestions = self.engine._improvements(80.0, 80.0, 80.0, 80.0, peaks)
        assert any("ready" in s.lower() or "✅" in s for s in suggestions)


# ── hook_engine ───────────────────────────────────────────────────────────────

class TestHookEngine:
    def setup_method(self):
        from src.services.hook_engine import HookEngine
        self.engine = HookEngine()

    def test_find_hook_at_start(self):
        words = [
            {"word": "¿Nunca", "start": 0.5, "end": 0.9},
            {"word": "has",    "start": 0.9, "end": 1.1},
            {"word": "visto",  "start": 1.1, "end": 1.5},
        ]
        result = self.engine.find_best_hook(words, segment_duration=30.0)
        assert result.hook_score > 0.0
        assert result.already_optimized is True
        assert result.reorder is False

    def test_find_hook_late_suggests_reorder(self):
        words = (
            [{"word": f"word{i}", "start": float(i), "end": float(i) + 0.3} for i in range(20)]
            + [{"word": "secreto", "start": 20.0, "end": 20.5}]
        )
        result = self.engine.find_best_hook(words, segment_duration=30.0)
        assert result.already_optimized is False
        assert result.reorder is True

    def test_empty_words(self):
        result = self.engine.find_best_hook([], segment_duration=30.0)
        assert result.hook_score == 0.0
        assert result.reorder is False

    def test_no_hook_signal(self):
        words = [
            {"word": "hola", "start": 0.0, "end": 0.3},
            {"word": "mundo", "start": 0.3, "end": 0.7},
        ]
        result = self.engine.find_best_hook(words, segment_duration=10.0)
        assert result.hook_score == 0.0


# ── smart_templates ───────────────────────────────────────────────────────────

class TestSmartTemplates:
    def setup_method(self):
        from src.services.smart_templates import SmartTemplateSelector
        self.selector = SmartTemplateSelector()

    def test_detect_tutorial(self):
        content = self.selector._detect("Primer paso: abre la aplicación. Segundo paso: configura.", 0.4)
        assert content == "tutorial"

    def test_detect_high_energy_from_audio(self):
        content = self.selector._detect("hola", 0.9)
        assert content == "high_energy"

    def test_detect_interview(self):
        content = self.selector._detect("Me dijiste que era imposible. Cuéntame más.", 0.4)
        assert content == "interview"

    def test_select_tiktok_default(self):
        preset = self.selector.select("tiktok", "genérico sin palabras clave", 55.0)
        assert preset.platform == "tiktok"
        assert preset.max_duration_s <= 60

    def test_select_youtube_shorts(self):
        preset = self.selector.select("shorts", "step by step tutorial how to", 55.0)
        # tutorial content overrides platform
        assert preset.name == "Tutorial"

    def test_select_reels_generic(self):
        preset = self.selector.select("reels", "contenido genérico", 55.0)
        assert "reel" in preset.name.lower() or preset.platform == "reels"

    def test_all_presets_have_valid_resolution(self):
        from src.services.smart_templates import PRESETS
        for key, preset in PRESETS.items():
            w, h = preset.resolution
            assert w > 0 and h > 0, f"Preset {key} has invalid resolution"

    def test_all_presets_have_positive_duration(self):
        from src.services.smart_templates import PRESETS
        for key, preset in PRESETS.items():
            assert preset.max_duration_s > 0, f"Preset {key} max_duration_s <= 0"


# ── learning_loop ─────────────────────────────────────────────────────────────

class TestLearningLoop:
    def setup_method(self):
        from src.services.learning_loop import LearningLoop
        self.loop = LearningLoop()

    @pytest.mark.asyncio
    async def test_qa_missing_file(self, tmp_path):
        missing = tmp_path / "nonexistent.mp4"
        source = tmp_path / "source.mp4"
        issues = await self.loop._qa(missing, source, duration=30.0, size=0, has_audio=True)
        assert any("not exist" in i for i in issues)

    @pytest.mark.asyncio
    async def test_qa_too_short(self, tmp_path):
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"x" * 1024)
        source = tmp_path / "source.mp4"
        source.write_bytes(b"y" * 2048)
        issues = await self.loop._qa(f, source, duration=1.0, size=1024, has_audio=True)
        assert any("short" in i.lower() for i in issues)

    @pytest.mark.asyncio
    async def test_qa_no_audio(self, tmp_path):
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"x" * 1024)
        source = tmp_path / "source.mp4"
        source.write_bytes(b"y" * 2048)
        issues = await self.loop._qa(f, source, duration=30.0, size=1024, has_audio=False)
        assert any("audio" in i.lower() for i in issues)

    @pytest.mark.asyncio
    async def test_qa_passes_valid_clip(self, tmp_path):
        from unittest.mock import AsyncMock, MagicMock
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"x" * 5000)
        source = tmp_path / "source.mp4"
        source.write_bytes(b"y" * 10000)
        mock_val = MagicMock()
        mock_result = MagicMock(passed=True, issues=[], warnings=[])
        mock_val.validate_output = AsyncMock(return_value=mock_result)
        with patch("src.services.clip_validator.get_clip_validator", return_value=mock_val):
            issues = await self.loop._qa(f, source, duration=30.0, size=5000, has_audio=True)
        assert issues == []

    @pytest.mark.asyncio
    async def test_qa_too_similar_to_source(self, tmp_path):
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"x" * 5000)
        source = tmp_path / "source.mp4"
        source.write_bytes(b"y" * 5000)  # same size → suspicious
        issues = await self.loop._qa(f, source, duration=30.0, size=5000, has_audio=True)
        assert any("source" in i.lower() or "size" in i.lower() for i in issues)

    @pytest.mark.asyncio
    async def test_post_render_saves_manifest(self, tmp_path):
        from src.services.learning_loop import LearningLoop, _MANIFEST_DIR

        loop = LearningLoop()

        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 8000)
        source = tmp_path / "source.mp4"
        source.write_bytes(b"y" * 20000)

        mock_pred = MagicMock()
        mock_pred.score = 72.5
        mock_pred.hook_score = 80.0
        mock_pred.pacing_score = 65.0
        mock_pred.emotion_score = 70.0
        mock_pred.improvements = ["test improvement"]

        mock_val = MagicMock()
        mock_val_result = MagicMock(passed=True, issues=[], warnings=[])
        mock_val.validate_output = AsyncMock(return_value=mock_val_result)
        with (
            patch.object(loop, "_probe", new_callable=AsyncMock) as mock_probe,
            patch.object(loop, "_save", new_callable=AsyncMock) as mock_save,
            patch("src.services.clip_validator.get_clip_validator", return_value=mock_val),
        ):
            mock_probe.return_value = (30.0, 8000, True)
            manifest = await loop.post_render_analysis(
                clip_path=clip,
                source_path=source,
                task_id="test-task",
                clip_index=0,
                virality_prediction=mock_pred,
                timeline_events=[],
                preset_name="tiktok_viral",
                sfx_count=2,
                broll_count=1,
                loudnorm_applied=True,
            )

        assert manifest.qa_passed is True
        assert manifest.viral_score == 72.5
        assert manifest.sfx_injected == 2
        assert manifest.loudnorm_applied is True
        mock_save.assert_called_once()


# ── creative_pipeline ─────────────────────────────────────────────────────────

class TestCreativePipeline:
    @pytest.mark.asyncio
    async def test_enhance_returns_metadata_keys(self, tmp_path):
        from src.services.creative_pipeline import CreativePipeline

        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 8000)
        source = tmp_path / "source.mp4"
        source.write_bytes(b"y" * 20000)

        pipeline = CreativePipeline()
        segment = {
            "start_time": 10.0,
            "end_time": 40.0,
            "transcript": "Nunca verás esto. Es increíble.",
            "text": "Nunca verás esto. Es increíble.",
        }
        words = [{"word": "Nunca", "start": 10.0, "end": 10.4, "confidence": 0.9}]

        with (
            patch("src.services.multimodal_detector.get_multimodal_detector") as mock_det,
            patch("src.services.virality_engine.get_virality_engine") as mock_eng,
            patch("src.services.smart_templates.get_template_selector") as mock_tmpl,
            patch("src.services.hook_engine.get_hook_engine") as mock_hook,
            patch("src.services.smart_audio.get_smart_audio") as mock_audio,
            patch("src.services.learning_loop.get_learning_loop") as mock_qa,
        ):
            from src.services.multimodal_detector import TimelineEvent
            mock_det.return_value.generate_timeline = AsyncMock(
                return_value=[TimelineEvent(t=0.0, type="keyword", strength=0.9, duration=0.4, payload={"word": "nunca", "category": "hook"})]
            )

            from src.services.virality_engine import ViralityPrediction
            mock_pred = ViralityPrediction(
                score=75.0, hook_score=80.0, pacing_score=70.0, emotion_score=65.0,
                improvements=["✅ Clip is publish-ready"], marked_for_enhancement=False,
            )
            mock_eng.return_value.predict = AsyncMock(return_value=mock_pred)

            from src.services.smart_templates import PRESETS
            mock_tmpl.return_value.select = MagicMock(return_value=PRESETS["tiktok_viral"])

            from src.services.hook_engine import HookResult
            mock_hook.return_value.find_best_hook = MagicMock(
                return_value=HookResult(0.0, 0.4, "Nunca", 0.88, False, True)
            )

            mock_audio.return_value.master = AsyncMock(return_value=clip)

            from src.services.learning_loop import RenderManifest
            mock_manifest = MagicMock()
            mock_manifest.qa_passed = True
            mock_manifest.qa_issues = []
            mock_qa.return_value.post_render_analysis = AsyncMock(return_value=mock_manifest)

            meta = await pipeline.enhance(
                clip_path=clip,
                source_video=source,
                segment=segment,
                words=words,
                audio_features={"energy": 0.6},
                task_id="test-123",
                clip_index=0,
                platform="tiktok",
            )

        assert "timeline_events" in meta
        assert "viral_score" in meta
        assert "preset_used" in meta
        assert "qa_passed" in meta
        assert meta["creative_enhanced"] is True
        assert meta["viral_score"] == 75.0
        assert meta["preset_used"] == "TikTok Viral"

    @pytest.mark.asyncio
    async def test_enhance_graceful_on_all_failures(self, tmp_path):
        """Even if every step throws, enhance() should return a metadata dict."""
        from src.services.creative_pipeline import CreativePipeline

        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x" * 500)
        source = tmp_path / "src.mp4"

        pipeline = CreativePipeline()

        with patch("src.services.multimodal_detector.get_multimodal_detector", side_effect=Exception("boom")):
            meta = await pipeline.enhance(
                clip_path=clip,
                source_video=source,
                segment={"start_time": 0.0, "end_time": 30.0, "transcript": "test"},
                words=[],
                audio_features={},
                task_id="err-task",
                clip_index=0,
                platform="tiktok",
            )

        assert isinstance(meta, dict)
        assert "creative_enhanced" in meta
        assert "timeline_events" in meta


# ── contextual_broll ──────────────────────────────────────────────────────────

class TestContextualBroll:
    def setup_method(self):
        from src.services.contextual_broll import ContextualBroll
        self.broll = ContextualBroll()

    def test_find_local_not_exists(self, tmp_path):
        self.broll._bank = tmp_path / "empty"
        result = self.broll._find_local("beach")
        assert result is None

    def test_find_local_by_filename(self, tmp_path):
        bank = tmp_path / "broll"
        bank.mkdir()
        asset = bank / "beach_001.mp4"
        asset.write_bytes(b"fake")
        self.broll._bank = bank
        result = self.broll._find_local("beach")
        assert result == asset

    @pytest.mark.asyncio
    async def test_get_for_keyword_local_found(self, tmp_path):
        bank = tmp_path / "broll"
        bank.mkdir()
        (bank / "ocean_clip.mp4").write_bytes(b"fake")
        self.broll._bank = bank
        self.broll._pexels_key = ""
        self.broll._t2v_enabled = False
        result = await self.broll.get_for_keyword("ocean", duration=3.0)
        assert result is not None
        assert result.source == "local"

    @pytest.mark.asyncio
    async def test_get_for_keyword_nothing_found(self, tmp_path):
        self.broll._bank = tmp_path / "nonexistent"
        self.broll._pexels_key = ""
        self.broll._t2v_enabled = False
        result = await self.broll.get_for_keyword("zebra", duration=3.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_for_timeline_filters_hook_impact(self, tmp_path):
        from src.services.multimodal_detector import TimelineEvent
        timeline = [
            TimelineEvent(t=1.0, type="keyword", strength=0.9, duration=0.4,
                          payload={"word": "ocean", "category": "hook"}),
            TimelineEvent(t=2.0, type="audio_peak", strength=0.8, duration=0.2,
                          payload={}),  # not keyword — should be ignored
        ]
        self.broll._bank = tmp_path / "nonexistent"
        self.broll._pexels_key = ""
        self.broll._t2v_enabled = False
        pairs = await self.broll.get_for_timeline(timeline)
        # No assets found → empty list (graceful)
        assert pairs == []
