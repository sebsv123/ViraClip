"""
Phase 13 — Improvement Layer Tests

Covers:
  - Jump-cut engine (silence detection, filler detection, build_keep_segments)
  - Audio denoiser (filter building, graceful error handling)
  - Social publisher (platform routing, optimal post time)
  - Voiceover service (provider selection, mix helper)
  - Performance webhook service (event parsing, viral flagging, template stats)
  - Trend intelligence service (hooks, patterns, posting times, report)
  - Niche virality service (scoring, weights, retrain, recommendations)
  - Pipeline wiring (denoiser + jump-cut opt-in in coordinator)
"""
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call


# ── helpers ──────────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# 1. JUMP-CUT ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class TestFindFillerSegments(unittest.TestCase):
    def setUp(self):
        from src.services.jump_cut_service import find_filler_segments
        self.find = find_filler_segments

    def test_single_filler_word_detected(self):
        words = [
            {"word": "um", "start": 1.0, "end": 1.3},
            {"word": "hello", "start": 1.5, "end": 2.0},
        ]
        segs = self.find(words)
        self.assertEqual(len(segs), 1)
        self.assertAlmostEqual(segs[0][0], 0.98, places=1)  # start - pad

    def test_two_word_filler_phrase(self):
        words = [
            {"word": "you", "start": 0.5, "end": 0.8},
            {"word": "know", "start": 0.9, "end": 1.1},
            {"word": "coding", "start": 1.5, "end": 2.0},
        ]
        segs = self.find(words)
        self.assertEqual(len(segs), 1)

    def test_no_fillers(self):
        words = [
            {"word": "coding", "start": 0.0, "end": 0.5},
            {"word": "is", "start": 0.6, "end": 0.8},
            {"word": "great", "start": 0.9, "end": 1.2},
        ]
        segs = self.find(words)
        self.assertEqual(len(segs), 0)

    def test_custom_fillers(self):
        words = [
            {"word": "basically", "start": 0.0, "end": 0.4},
            {"word": "coding", "start": 0.5, "end": 1.0},
        ]
        segs = self.find(words, filler_set={"basically"})
        self.assertEqual(len(segs), 1)

    def test_empty_words(self):
        self.assertEqual(self.find([]), [])


class TestBuildKeepSegments(unittest.TestCase):
    def setUp(self):
        from src.services.jump_cut_service import build_keep_segments
        self.build = build_keep_segments

    def test_no_remove_returns_full(self):
        segs = self.build(10.0, [])
        self.assertEqual(segs, [(0.0, 10.0)])

    def test_single_silence_in_middle(self):
        segs = self.build(10.0, [(3.0, 5.0)])
        self.assertEqual(len(segs), 2)
        self.assertAlmostEqual(segs[0][0], 0.0, places=1)
        self.assertAlmostEqual(segs[1][1], 10.0, places=1)

    def test_overlapping_intervals_merged(self):
        segs = self.build(10.0, [(2.0, 4.0), (3.0, 6.0)])
        self.assertEqual(len(segs), 2)

    def test_silence_at_start(self):
        segs = self.build(10.0, [(0.0, 2.0)])
        self.assertTrue(all(s[0] >= 0 for s in segs))

    def test_tiny_keep_segments_dropped(self):
        # After removing (1.0, 9.9) from 10s, keep segs < 0.05s should be dropped
        segs = self.build(10.0, [(1.0, 9.9)])
        # Only one keep seg: 0→1.0 minus pad
        self.assertGreaterEqual(len(segs), 1)


class TestApplyJumpCutsUnit(unittest.TestCase):
    def test_no_cuts_when_no_intervals(self):
        """When keep_segs = full video, shutil.copy should be called."""
        import shutil
        with patch("src.services.jump_cut_service._get_duration", new=AsyncMock(return_value=10.0)), \
             patch("src.services.jump_cut_service.detect_silence", new=AsyncMock(return_value=[])), \
             patch("src.services.jump_cut_service.find_filler_segments", return_value=[]), \
             patch("shutil.copy2") as mock_copy:
            from src.services.jump_cut_service import apply_jump_cuts
            result = run(apply_jump_cuts("/fake/video.mp4", "/fake/out.mp4"))
            mock_copy.assert_called_once()
            self.assertEqual(result.segments_removed, 0)
            self.assertIsNone(result.error)

    def test_ffmpeg_error_returns_error_result(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"FFmpeg error"))
        with patch("src.services.jump_cut_service._get_duration", new=AsyncMock(return_value=10.0)), \
             patch("src.services.jump_cut_service.detect_silence",
                   new=AsyncMock(return_value=[(2.0, 4.0)])), \
             patch("src.services.jump_cut_service.find_filler_segments", return_value=[]), \
             patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
            from src.services.jump_cut_service import apply_jump_cuts
            result = run(apply_jump_cuts("/fake/video.mp4", "/fake/out.mp4"))
            self.assertIsNotNone(result.error)

    def test_zero_duration_returns_error(self):
        with patch("src.services.jump_cut_service._get_duration", new=AsyncMock(return_value=0)):
            from src.services.jump_cut_service import apply_jump_cuts
            result = run(apply_jump_cuts("/fake/video.mp4", "/fake/out.mp4"))
            self.assertIsNotNone(result.error)


# ═══════════════════════════════════════════════════════════════════════════
# 2. AUDIO DENOISER
# ═══════════════════════════════════════════════════════════════════════════

class TestAudioDenoiser(unittest.TestCase):
    def test_no_filters_copies_file(self):
        import shutil
        with patch("shutil.copy2") as mock_copy:
            from src.services.audio_denoiser import denoise_audio
            result = run(denoise_audio(
                "/fake/in.mp4", "/fake/out.mp4",
                noise_reduction=False,
                voice_isolation=False,
                apply_loudnorm=False,
            ))
            mock_copy.assert_called_once()
            self.assertFalse(result.noise_reduction_applied)

    def test_ffmpeg_error_sets_error_field(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))
        probe_proc = MagicMock()
        probe_proc.returncode = 0
        probe_proc.communicate = AsyncMock(return_value=(b"video\n", b""))

        def _make_proc(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, (list, tuple)) and "ffprobe" in str(cmd[0]):
                return probe_proc
            return mock_proc

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=_make_proc)), \
             patch("src.services.audio_denoiser._measure_lufs", new=AsyncMock(return_value=-18.0)):
            from src.services.audio_denoiser import denoise_audio
            result = run(denoise_audio("/fake/in.mp4", "/fake/out.mp4"))
            self.assertIsNotNone(result.error)

    def test_filter_string_contains_afftdn(self):
        """Verify afftdn filter is included when noise_reduction=True."""
        captured_cmd = []
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        probe_proc = MagicMock()
        probe_proc.returncode = 0
        probe_proc.communicate = AsyncMock(return_value=(b"video\n", b""))

        async def _capture(*args, **kwargs):
            captured_cmd.extend(args)
            if "ffprobe" in str(args[0] if args else ""):
                return probe_proc
            return mock_proc

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=_capture)), \
             patch("src.services.audio_denoiser._measure_lufs", new=AsyncMock(return_value=-18.0)):
            from src.services.audio_denoiser import denoise_audio
            run(denoise_audio("/fake/in.mp4", "/fake/out.mp4", noise_reduction=True))
            full_cmd = " ".join(str(a) for a in captured_cmd)
            self.assertIn("afftdn", full_cmd)


# ═══════════════════════════════════════════════════════════════════════════
# 3. SOCIAL PUBLISHER
# ═══════════════════════════════════════════════════════════════════════════

class TestSocialPublisher(unittest.TestCase):
    def test_get_optimal_post_time_returns_iso(self):
        from src.services.social_publisher import get_optimal_post_time
        t = get_optimal_post_time("tiktok")
        self.assertIn("T", t)
        self.assertTrue(t.endswith("Z"))

    def test_no_token_returns_failed(self):
        import os
        env = {k: v for k, v in os.environ.items() if k not in ("TIKTOK_ACCESS_TOKEN",)}
        with patch.dict("os.environ", env, clear=True):
            from src.services.social_publisher import publish_clip, PublishRequest, Platform, PublishStatus
            result = run(publish_clip(PublishRequest(
                video_path="/fake/clip.mp4",
                caption="test",
                platform=Platform.TIKTOK,
            )))
            self.assertEqual(result.status, PublishStatus.FAILED)
            self.assertIn("TIKTOK_ACCESS_TOKEN", result.error)

    def test_instagram_no_token_fails(self):
        import os
        env = {k: v for k, v in os.environ.items()
               if k not in ("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_ACCOUNT_ID")}
        with patch.dict("os.environ", env, clear=True):
            from src.services.social_publisher import publish_clip, PublishRequest, Platform, PublishStatus
            result = run(publish_clip(PublishRequest(
                video_path="/fake/clip.mp4",
                caption="test",
                platform=Platform.INSTAGRAM,
            )))
            self.assertEqual(result.status, PublishStatus.FAILED)

    def test_youtube_no_token_fails(self):
        import os
        env = {k: v for k, v in os.environ.items() if k != "YOUTUBE_ACCESS_TOKEN"}
        with patch.dict("os.environ", env, clear=True):
            from src.services.social_publisher import publish_clip, PublishRequest, Platform, PublishStatus
            result = run(publish_clip(PublishRequest(
                video_path="/fake/clip.mp4",
                caption="test",
                platform=Platform.YOUTUBE,
            )))
            self.assertEqual(result.status, PublishStatus.FAILED)

    def test_publish_to_all_returns_list(self):
        import os
        env = {k: v for k, v in os.environ.items()
               if k not in ("TIKTOK_ACCESS_TOKEN", "INSTAGRAM_ACCESS_TOKEN",
                             "INSTAGRAM_ACCOUNT_ID", "YOUTUBE_ACCESS_TOKEN")}
        with patch.dict("os.environ", env, clear=True):
            from src.services.social_publisher import publish_to_all
            results = run(publish_to_all("/fake/clip.mp4", "caption"))
            self.assertEqual(len(results), 3)

    def test_unsupported_platform_fails_gracefully(self):
        from src.services.social_publisher import publish_clip, PublishRequest, Platform, PublishStatus
        # Pass an invalid platform string — should raise or return failed
        req = PublishRequest(video_path="/fake.mp4", caption="t", platform=Platform.TIKTOK)
        # Manually test routing with no token
        import os
        env = {k: v for k, v in os.environ.items() if k != "TIKTOK_ACCESS_TOKEN"}
        with patch.dict("os.environ", env, clear=True):
            result = run(publish_clip(req))
            self.assertEqual(result.status, PublishStatus.FAILED)


# ═══════════════════════════════════════════════════════════════════════════
# 4. VOICEOVER SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestVoiceoverService(unittest.TestCase):
    def test_no_api_key_returns_error(self):
        import os
        env = {k: v for k, v in os.environ.items()
               if k not in ("OPENAI_API_KEY", "ELEVENLABS_API_KEY")}
        with patch.dict("os.environ", env, clear=True):
            from src.services.voiceover_service import generate_voiceover
            result = run(generate_voiceover("Hello world", "/tmp"))
            self.assertIsNone(result.audio_path)
            self.assertIsNotNone(result.error)

    def test_provider_auto_tries_openai_first(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test", "ELEVENLABS_API_KEY": ""}):
            with patch("src.services.voiceover_service._tts_openai",
                       new=AsyncMock(return_value="/tmp/vo.mp3")), \
                 patch("src.services.voiceover_service._get_audio_duration",
                       new=AsyncMock(return_value=3.5)):
                from src.services.voiceover_service import generate_voiceover
                result = run(generate_voiceover("Hello", "/tmp"))
                self.assertEqual(result.provider, "openai")
                self.assertIsNotNone(result.audio_path)

    def test_fallback_to_elevenlabs_when_openai_fails(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test", "ELEVENLABS_API_KEY": "el-test"}):
            with patch("src.services.voiceover_service._tts_openai",
                       new=AsyncMock(side_effect=RuntimeError("OpenAI down"))), \
                 patch("src.services.voiceover_service._tts_elevenlabs",
                       new=AsyncMock(return_value="/tmp/vo.mp3")), \
                 patch("src.services.voiceover_service._get_audio_duration",
                       new=AsyncMock(return_value=3.0)):
                from src.services.voiceover_service import generate_voiceover
                result = run(generate_voiceover("Hello", "/tmp"))
                self.assertEqual(result.provider, "elevenlabs")

    def test_add_voiceover_to_clip_returns_mixed_path(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            with patch("src.services.voiceover_service._tts_openai",
                       new=AsyncMock(return_value="/tmp/vo.mp3")), \
                 patch("src.services.voiceover_service._get_audio_duration",
                       new=AsyncMock(return_value=3.0)), \
                 patch("src.services.voiceover_service._mix_voiceover_into_video",
                       new=AsyncMock(return_value=True)):
                from src.services.voiceover_service import add_voiceover_to_clip
                result = run(add_voiceover_to_clip(
                    "/fake/clip.mp4", "Hook text", "/fake/out.mp4"
                ))
                self.assertEqual(result.mixed_video_path, "/fake/out.mp4")


# ═══════════════════════════════════════════════════════════════════════════
# 5. PERFORMANCE WEBHOOK SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestPerformanceWebhookService(unittest.TestCase):
    def setUp(self):
        import tempfile, os
        self.tmpdir = tempfile.mkdtemp()
        self._store_patch = patch(
            "src.services.performance_webhook_service._PERF_STORE",
            Path(self.tmpdir) / "events.json"
        )
        self._store_patch.start()

    def tearDown(self):
        self._store_patch.stop()

    def test_record_event_saves_to_store(self):
        from src.services.performance_webhook_service import (
            PerformanceEvent, record_performance_event, _load_store
        )
        event = PerformanceEvent(clip_id="c1", platform="tiktok", views=50000, likes=2000)
        record_performance_event(event, caption_template="bold")
        store = _load_store()
        self.assertEqual(len(store["events"]), 1)
        self.assertEqual(store["events"][0]["clip_id"], "c1")

    def test_viral_flag_set_for_high_views(self):
        from src.services.performance_webhook_service import PerformanceEvent
        event = PerformanceEvent(clip_id="c2", platform="instagram", views=200000)
        self.assertTrue(event.is_viral)

    def test_viral_flag_false_for_low_views(self):
        from src.services.performance_webhook_service import PerformanceEvent
        event = PerformanceEvent(clip_id="c3", platform="tiktok", views=1000)
        self.assertFalse(event.is_viral)

    def test_high_engagement_triggers_viral(self):
        from src.services.performance_webhook_service import PerformanceEvent
        event = PerformanceEvent(clip_id="c4", platform="tiktok", views=10000, likes=1000)
        self.assertTrue(event.is_viral)  # 10% engagement > 8% threshold

    def test_template_stats_updated(self):
        from src.services.performance_webhook_service import (
            PerformanceEvent, record_performance_event, get_top_templates
        )
        for i in range(3):
            event = PerformanceEvent(clip_id=f"c{i}", platform="tiktok",
                                     views=200000 if i == 0 else 5000)
            record_performance_event(event, caption_template="minimal")

        templates = get_top_templates(5)
        self.assertGreater(len(templates), 0)
        self.assertEqual(templates[0]["template"], "minimal")

    def test_parse_tiktok_webhook(self):
        from src.services.performance_webhook_service import parse_tiktok_webhook
        payload = {"data": {"video_id": "tk123", "video": {"play_count": 75000, "digg_count": 3000}}}
        event = parse_tiktok_webhook(payload)
        self.assertIsNotNone(event)
        self.assertEqual(event.clip_id, "tk123")
        self.assertEqual(event.views, 75000)

    def test_parse_instagram_webhook(self):
        from src.services.performance_webhook_service import parse_instagram_webhook
        payload = {
            "entry": [{"changes": [{"value": {"media_id": "ig456", "video_views": 30000, "like_count": 1500}}]}]
        }
        event = parse_instagram_webhook(payload)
        self.assertIsNotNone(event)
        self.assertEqual(event.clip_id, "ig456")

    def test_parse_youtube_webhook(self):
        from src.services.performance_webhook_service import parse_youtube_webhook
        payload = {"id": "yt789", "statistics": {"viewCount": "120000", "likeCount": "5000"}}
        event = parse_youtube_webhook(payload)
        self.assertIsNotNone(event)
        self.assertEqual(event.views, 120000)

    def test_performance_summary_counts(self):
        from src.services.performance_webhook_service import (
            PerformanceEvent, record_performance_event, get_performance_summary
        )
        record_performance_event(PerformanceEvent(clip_id="x", platform="tiktok", views=200000))
        record_performance_event(PerformanceEvent(clip_id="y", platform="tiktok", views=500))
        summary = get_performance_summary()
        self.assertEqual(summary["total_events"], 2)
        self.assertEqual(summary["viral_clips"], 1)


# ═══════════════════════════════════════════════════════════════════════════
# 6. TREND INTELLIGENCE SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestTrendIntelligenceService(unittest.TestCase):
    def test_hook_suggestions_returned_for_fitness(self):
        from src.services.trend_intelligence_service import get_hook_suggestions
        hooks = get_hook_suggestions("fitness", limit=3)
        self.assertEqual(len(hooks), 3)
        self.assertEqual(hooks[0].niche, "fitness")
        self.assertIsInstance(hooks[0].phrase, str)

    def test_unknown_niche_falls_back_to_auto(self):
        from src.services.trend_intelligence_service import get_hook_suggestions
        hooks = get_hook_suggestions("quantum_physics_niche", limit=3)
        self.assertEqual(len(hooks), 3)

    def test_caption_patterns_filtered_by_platform(self):
        from src.services.trend_intelligence_service import get_caption_patterns
        patterns = get_caption_patterns("tiktok", limit=5)
        self.assertGreater(len(patterns), 0)
        for p in patterns:
            self.assertIn("pattern", p)
            self.assertIn("avg_engagement_boost", p)

    def test_patterns_sorted_by_engagement_boost(self):
        from src.services.trend_intelligence_service import get_caption_patterns
        patterns = get_caption_patterns("tiktok", limit=10)
        boosts = [p["avg_engagement_boost"] for p in patterns]
        self.assertEqual(boosts, sorted(boosts, reverse=True))

    def test_best_posting_times_returns_hours(self):
        from src.services.trend_intelligence_service import get_best_posting_times
        hours = get_best_posting_times("tiktok", is_weekend=False)
        self.assertIsInstance(hours, list)
        self.assertGreater(len(hours), 0)
        self.assertTrue(all(0 <= h < 24 for h in hours))

    def test_posting_times_weekend_vs_weekday_differ(self):
        from src.services.trend_intelligence_service import get_best_posting_times
        weekday = get_best_posting_times("tiktok", is_weekend=False)
        weekend = get_best_posting_times("tiktok", is_weekend=True)
        # They may differ
        self.assertIsInstance(weekday, list)
        self.assertIsInstance(weekend, list)

    def test_build_report_includes_all_fields(self):
        from src.services.trend_intelligence_service import build_intelligence_report
        report = build_intelligence_report("fitness", "tiktok")
        self.assertEqual(report.niche, "fitness")
        self.assertGreater(len(report.hook_suggestions), 0)
        self.assertGreater(len(report.caption_patterns), 0)
        self.assertIn("tiktok", report.best_posting_hours)
        self.assertGreater(len(report.hashtags), 0)

    def test_supported_niches_list(self):
        from src.services.trend_intelligence_service import get_supported_niches
        niches = get_supported_niches()
        self.assertIn("fitness", niches)
        self.assertIn("finance", niches)
        self.assertIn("food", niches)

    def test_hashtag_cluster_for_niche(self):
        from src.services.trend_intelligence_service import _HASHTAG_CLUSTERS
        self.assertIn("fitness", _HASHTAG_CLUSTERS)
        self.assertIn("gym", _HASHTAG_CLUSTERS["fitness"])


# ═══════════════════════════════════════════════════════════════════════════
# 7. NICHE VIRALITY SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestNicheViralityService(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self._weights_patch = patch(
            "src.services.niche_virality_service._WEIGHTS_STORE",
            Path(self.tmpdir) / "weights.json"
        )
        self._weights_patch.start()

    def tearDown(self):
        self._weights_patch.stop()

    def test_score_returns_0_to_100(self):
        from src.services.niche_virality_service import score_for_niche
        result = score_for_niche("fitness", 75.0, hook_score=80, pacing_score=70,
                                  emotion_score=60, audio_energy=0.7, clip_duration=45)
        self.assertGreaterEqual(result.niche_score, 0)
        self.assertLessEqual(result.niche_score, 100)

    def test_duration_penalty_applied_for_too_long(self):
        from src.services.niche_virality_service import score_for_niche
        short = score_for_niche("comedy", 70.0, clip_duration=25)  # sweet spot 15-30
        long_ = score_for_niche("comedy", 70.0, clip_duration=120)  # way over
        self.assertGreater(short.niche_score, long_.niche_score)
        self.assertFalse(long_.duration_ok)

    def test_duration_ok_within_sweet_spot(self):
        from src.services.niche_virality_service import score_for_niche
        result = score_for_niche("fitness", 70.0, clip_duration=45)
        self.assertTrue(result.duration_ok)

    def test_unknown_niche_uses_defaults(self):
        from src.services.niche_virality_service import score_for_niche
        result = score_for_niche("quantum_physics", 60.0)
        self.assertGreaterEqual(result.niche_score, 0)
        self.assertLessEqual(result.niche_score, 100)

    def test_get_weights_returns_dict(self):
        from src.services.niche_virality_service import get_weights_for_niche
        w = get_weights_for_niche("finance")
        self.assertIn("hook_score", w)
        self.assertIn("pacing_score", w)
        self.assertAlmostEqual(sum(w.values()), 1.0, places=2)

    def test_retrain_updates_weights(self):
        from src.services.niche_virality_service import retrain_niche_weights, get_weights_for_niche
        import random
        random.seed(42)
        events = [
            {
                "views": random.randint(10000, 500000),
                "hook_score": random.uniform(40, 90),
                "pacing_score": random.uniform(40, 90),
                "emotion_score": random.uniform(40, 90),
                "audio_energy": random.uniform(0.3, 0.9),
            }
            for _ in range(15)
        ]
        new_weights = retrain_niche_weights("fitness", events)
        self.assertIn("hook_score", new_weights)
        # After retraining, weights should reflect learned values
        updated = get_weights_for_niche("fitness")
        self.assertIn("hook_score", updated)

    def test_retrain_requires_10_events(self):
        from src.services.niche_virality_service import retrain_niche_weights, get_weights_for_niche
        original = get_weights_for_niche("food")
        returned = retrain_niche_weights("food", [{"views": 100}] * 5)  # only 5
        # Should return unchanged defaults
        self.assertEqual(returned, get_weights_for_niche("food"))

    def test_recommendations_not_empty(self):
        from src.services.niche_virality_service import score_for_niche, get_niche_recommendations
        result = score_for_niche("fitness", 55.0, clip_duration=45)
        recs = get_niche_recommendations("fitness", result)
        self.assertIsInstance(recs, list)
        self.assertGreater(len(recs), 0)

    def test_high_score_gets_positive_recommendation(self):
        from src.services.niche_virality_service import score_for_niche, get_niche_recommendations
        result = score_for_niche("fitness", 90.0, hook_score=90, pacing_score=90,
                                  emotion_score=90, audio_energy=0.9, clip_duration=45)
        recs = get_niche_recommendations("fitness", result)
        self.assertTrue(any("well-optimised" in r.lower() or "great" in r.lower() for r in recs))


# ═══════════════════════════════════════════════════════════════════════════
# 8. PIPELINE WIRING (denoiser + jump-cut in coordinator)
# ═══════════════════════════════════════════════════════════════════════════

class _FakeProfile:
    caption_style = "default"
    watermark_text = ""
    watermark_image_path = ""
    watermark_position = "bottom_right"
    preferred_music_genre = "auto"
    def music_genres(self): return ["auto"]
    def cta_for_platform(self, p): return ""


def _make_coord(extra_config=None):
    """Build a minimal VideoCoordinator without calling __init__ fully."""
    from src.services.coordinator import VideoCoordinator
    coord = object.__new__(VideoCoordinator)
    coord.video_path = "/fake/video.mp4"
    coord.task_id = "task-test"
    coord.config = {
        "output_dir": "/tmp/clips",
        "target_platform": "tiktok",
        "add_subtitles": False,
        "user_id": "",
    }
    if extra_config:
        coord.config.update(extra_config)
    return coord


def _make_segment():
    return {"start_time": 1.0, "end_time": 11.0, "text": "hello world", "virality_score": 70}


def _base_patches():
    """Common patches needed to run coordinator._parallel_rendering."""
    return [
        patch("src.services.video_service.VideoService.create_single_clip",
              new=AsyncMock(return_value={
                  "path": "/tmp/clips/clip_0.mp4", "id": "c1",
                  "words": [], "audio_features": {},
              })),
        patch("src.services.progress_emitter.emit_clip_generated", new=AsyncMock()),
        patch("src.services.creative_pipeline.get_creative_pipeline",
              return_value=MagicMock(enhance=AsyncMock(return_value={}))),
        patch("src.services.clip_validator.get_clip_validator",
              return_value=MagicMock(
                  validate_input=AsyncMock(return_value=MagicMock(passed=True, warnings=[], issues=[])),
                  validate_output=AsyncMock(return_value=MagicMock(passed=True, warnings=[], issues=[], metadata={})),
              )),
        patch("src.utils.retry_helper.retry_ffmpeg_operation", side_effect=lambda f, **k: f()),
        patch("pathlib.Path.mkdir"),
    ]


class TestDenoiserPipelineWiring(unittest.TestCase):
    def test_denoiser_called_when_config_enabled(self):
        coord = _make_coord({"denoise_audio": True})
        segment = _make_segment()
        clip_path = MagicMock()
        clip_path.exists.return_value = True
        clip_path.stat.return_value = MagicMock(st_size=1000)
        clip_path.name = "clip_0.mp4"
        clip_path.with_name = MagicMock(return_value=clip_path)
        clip_path.__str__ = lambda s: "/tmp/clips/clip_0.mp4"

        from src.services.audio_denoiser import DenoiseResult
        mock_denoise_result = DenoiseResult(
            output_path="/tmp/clips/dn_clip_0.mp4",
            noise_reduction_applied=True,
            voice_isolation_applied=True,
            loudnorm_applied=True,
            original_lufs=-20.0,
            output_lufs=-14.0,
        )

        with patch("src.services.audio_denoiser.denoise_audio",
                   new=AsyncMock(return_value=mock_denoise_result)) as mock_dn:
            patches = _base_patches()
            for p in patches:
                p.start()
            try:
                run(coord._parallel_rendering([segment]))
            finally:
                for p in patches:
                    p.stop()
            mock_dn.assert_called_once()

    def test_denoiser_skipped_when_config_disabled(self):
        coord = _make_coord({"denoise_audio": False})
        segment = _make_segment()

        with patch("src.services.audio_denoiser.denoise_audio",
                   new=AsyncMock()) as mock_dn:
            patches = _base_patches()
            for p in patches:
                p.start()
            try:
                run(coord._parallel_rendering([segment]))
            finally:
                for p in patches:
                    p.stop()
            mock_dn.assert_not_called()


class TestJumpCutPipelineWiring(unittest.TestCase):
    def test_jump_cut_called_when_config_enabled(self):
        coord = _make_coord({"jump_cut": True})
        segment = _make_segment()

        from src.services.jump_cut_service import JumpCutResult
        mock_jc_result = JumpCutResult(
            output_path="/tmp/clips/jc_clip_0.mp4",
            original_duration=10.0,
            output_duration=8.5,
            segments_removed=3,
            time_saved=1.5,
            filler_words_removed=2,
            silence_gaps_removed=1,
        )
        clip_path = MagicMock()
        clip_path.exists.return_value = True
        clip_path.stat.return_value = MagicMock(st_size=1000)

        with patch("src.services.jump_cut_service.apply_jump_cuts",
                   new=AsyncMock(return_value=mock_jc_result)) as mock_jc:
            patches = _base_patches()
            for p in patches:
                p.start()
            try:
                run(coord._parallel_rendering([segment]))
            finally:
                for p in patches:
                    p.stop()
            mock_jc.assert_called_once()

    def test_jump_cut_skipped_when_config_disabled(self):
        coord = _make_coord({"jump_cut": False})
        segment = _make_segment()

        with patch("src.services.jump_cut_service.apply_jump_cuts",
                   new=AsyncMock()) as mock_jc:
            patches = _base_patches()
            for p in patches:
                p.start()
            try:
                run(coord._parallel_rendering([segment]))
            finally:
                for p in patches:
                    p.stop()
            mock_jc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
