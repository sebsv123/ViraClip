"""
Tests for Phase 11 new features:
  1. Creator Profile Service
  2. Analytics Importer (A/B Feedback)
  3. Trending Audio Service
  4. Thumbnail Text Service
  5. Subtitle QA
  6. Smart Reframe
  7. Language Detector
  8. Narrative Arc Service
  9. Brand Overlay Service
 10. Clip Health Service
 11. TikTok Templates Service
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open


def run(coro):
    return asyncio.run(coro)


# ===========================================================================
# 1. Creator Profile Service
# ===========================================================================

class TestCreatorProfileService(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _patch_dir(self):
        return patch(
            "src.services.creator_profile_service._PROFILE_DIR",
            Path(self.tmpdir),
        )

    def test_get_profile_creates_defaults(self):
        with self._patch_dir():
            from src.services.creator_profile_service import get_profile
            p = get_profile("user_abc")
        self.assertEqual(p.user_id, "user_abc")
        self.assertEqual(p.niche, "lifestyle")

    def test_save_and_reload(self):
        with self._patch_dir():
            from src.services.creator_profile_service import (
                get_profile, save_profile,
            )
            p = get_profile("user_save")
            p.niche = "fitness"
            save_profile(p)
            reloaded = get_profile("user_save")
        self.assertEqual(reloaded.niche, "fitness")

    def test_update_profile_partial(self):
        with self._patch_dir():
            from src.services.creator_profile_service import update_profile
            p = update_profile("user_upd", {"niche": "gaming", "tone": "entertainment"})
        self.assertEqual(p.niche, "gaming")
        self.assertEqual(p.tone, "entertainment")

    def test_update_profile_ignores_user_id(self):
        with self._patch_dir():
            from src.services.creator_profile_service import update_profile
            p = update_profile("user_x", {"user_id": "hacked"})
        self.assertEqual(p.user_id, "user_x")

    def test_delete_profile(self):
        with self._patch_dir():
            from src.services.creator_profile_service import (
                get_profile, delete_profile,
            )
            get_profile("user_del")
            deleted = delete_profile("user_del")
        self.assertTrue(deleted)

    def test_delete_nonexistent_returns_false(self):
        with self._patch_dir():
            from src.services.creator_profile_service import delete_profile
            result = delete_profile("ghost_user_xyz")
        self.assertFalse(result)

    def test_music_genres_auto_fitness(self):
        with self._patch_dir():
            from src.services.creator_profile_service import get_profile
            p = get_profile("usr_music")
            p.niche = "fitness"
            p.preferred_music_genre = "auto"
        genres = p.music_genres()
        self.assertIn("hype", genres)

    def test_music_genres_explicit(self):
        with self._patch_dir():
            from src.services.creator_profile_service import get_profile
            p = get_profile("usr_exp")
            p.preferred_music_genre = "lofi"
        self.assertEqual(p.music_genres(), ["lofi"])

    def test_cta_for_platform(self):
        with self._patch_dir():
            from src.services.creator_profile_service import get_profile
            p = get_profile("usr_cta")
            p.niche = "finance"
        cta = p.cta_for_platform("tiktok")
        self.assertIn("finance", cta)

    def test_cta_custom_text_overrides(self):
        with self._patch_dir():
            from src.services.creator_profile_service import get_profile
            p = get_profile("usr_custom_cta")
            p.cta_text = "Buy my course!"
        cta = p.cta_for_platform("tiktok")
        self.assertEqual(cta, "Buy my course!")

    def test_locale_prompt_hints(self):
        with self._patch_dir():
            from src.services.creator_profile_service import get_profile
            p = get_profile("usr_locale")
            p.language = "es"
            p.niche = "comedy"
        hints = p.locale_prompt_hints()
        self.assertEqual(hints["language"], "es")
        self.assertEqual(hints["niche"], "comedy")

    def test_list_profiles(self):
        with self._patch_dir():
            from src.services.creator_profile_service import (
                get_profile, list_profiles,
            )
            get_profile("a_user")
            get_profile("b_user")
            profiles = list_profiles()
        user_ids = [p.user_id for p in profiles]
        self.assertIn("a_user", user_ids)
        self.assertIn("b_user", user_ids)

    def test_to_dict_roundtrip(self):
        with self._patch_dir():
            from src.services.creator_profile_service import (
                CreatorProfile, get_profile,
            )
            p = get_profile("rt_user")
            d = p.to_dict()
            p2 = CreatorProfile.from_dict(d)
        self.assertEqual(p.user_id, p2.user_id)
        self.assertEqual(p.niche, p2.niche)


# ===========================================================================
# 2. Analytics Importer (A/B Feedback)
# ===========================================================================

class TestAnalyticsImporter(unittest.TestCase):

    def test_compute_score_zero_views(self):
        from src.services.analytics_importer import ClipMetrics, compute_actual_virality_score
        m = ClipMetrics(clip_id="c1", platform="tiktok", views=0)
        score = compute_actual_virality_score(m)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_compute_score_viral_clip(self):
        from src.services.analytics_importer import ClipMetrics, compute_actual_virality_score
        m = ClipMetrics(
            clip_id="c2", platform="youtube",
            views=1_000_000, likes=50_000, comments=2_000,
            engagement_rate=0.052, completion_rate=0.65,
        )
        score = compute_actual_virality_score(m)
        self.assertGreater(score, 50)

    def test_compute_score_range(self):
        from src.services.analytics_importer import ClipMetrics, compute_actual_virality_score
        for views in [1, 1000, 100_000, 10_000_000]:
            m = ClipMetrics("c", "tiktok", views=views)
            s = compute_actual_virality_score(m)
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(s, 100)

    def test_build_training_sample(self):
        from src.services.analytics_importer import build_training_sample
        sample = build_training_sample("c1", 65.0, 72.3, {"hook": 8})
        self.assertEqual(sample["clip_id"], "c1")
        self.assertAlmostEqual(sample["delta"], 7.3, places=1)
        self.assertEqual(sample["label"], 72.3)

    def test_youtube_metrics_no_key(self):
        result = run(__import__(
            "src.services.analytics_importer", fromlist=["fetch_youtube_metrics"]
        ).fetch_youtube_metrics("vid123"))
        self.assertIsNone(result)

    def test_tiktok_metrics_no_token(self):
        result = run(__import__(
            "src.services.analytics_importer", fromlist=["fetch_tiktok_metrics"]
        ).fetch_tiktok_metrics("vid456"))
        self.assertIsNone(result)

    def test_run_feedback_import_no_ids(self):
        from src.services.analytics_importer import run_feedback_import
        clips = [{"clip_id": "x", "youtube_video_id": None, "tiktok_video_id": None}]
        result = run(run_feedback_import(clips))
        self.assertEqual(result["updates"], [])
        self.assertEqual(result["training_samples"], [])

    def test_import_metrics_returns_empty_without_credentials(self):
        from src.services.analytics_importer import import_metrics_for_clip
        result = run(import_metrics_for_clip("c1", "yt_id", "tt_id"))
        self.assertIsInstance(result, list)


# ===========================================================================
# 3. Trending Audio Service
# ===========================================================================

class TestTrendingAudioService(unittest.TestCase):

    def test_local_sounds_always_available(self):
        from src.services.trending_audio_service import _LOCAL_SOUNDS
        self.assertGreater(len(_LOCAL_SOUNDS), 0)

    def test_trending_sound_matches_genre(self):
        from src.services.trending_audio_service import TrendingSound
        s = TrendingSound("Track", "Artist", "local", genre="hype", tags=["fitness"])
        self.assertTrue(s.matches_genre("auto"))
        self.assertTrue(s.matches_genre("hype"))
        self.assertTrue(s.matches_genre("fitness"))
        self.assertFalse(s.matches_genre("lofi"))

    def test_recommend_picks_genre_match(self):
        from src.services.trending_audio_service import (
            TrendingSound, recommend_sound_for_clip,
        )
        sounds = [
            TrendingSound("A", "Art", "local", genre="lofi", rank=1),
            TrendingSound("B", "Art", "local", genre="hype", tags=["fitness"], rank=2),
        ]
        rec = recommend_sound_for_clip({"niche": "fitness", "bpm_hint": 140}, sounds)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.genre, "hype")

    def test_recommend_returns_first_on_no_match(self):
        from src.services.trending_audio_service import (
            TrendingSound, recommend_sound_for_clip,
        )
        sounds = [TrendingSound("X", "A", "local", genre="pop", rank=1)]
        rec = recommend_sound_for_clip({"niche": "unknown_niche"}, sounds)
        self.assertIsNotNone(rec)

    def test_recommend_empty_list_returns_none(self):
        from src.services.trending_audio_service import recommend_sound_for_clip
        result = recommend_sound_for_clip({}, [])
        self.assertIsNone(result)

    def test_get_trending_sounds_fallback_to_local(self):
        with patch("src.services.trending_audio_service.fetch_tiktok_trending",
                   return_value=[]):
            with patch("src.services.trending_audio_service.fetch_spotify_trending",
                       return_value=[]):
                from src.services.trending_audio_service import get_trending_sounds
                sounds = run(get_trending_sounds(genre="auto", limit=5))
        self.assertGreater(len(sounds), 0)

    def test_to_dict_structure(self):
        from src.services.trending_audio_service import TrendingSound
        s = TrendingSound("T", "A", "local", genre="pop", bpm=120.0)
        d = s.to_dict()
        self.assertIn("title", d)
        self.assertIn("genre", d)
        self.assertIn("bpm", d)


# ===========================================================================
# 4. Thumbnail Text Service
# ===========================================================================

class TestThumbnailTextService(unittest.TestCase):

    def test_hex_to_rgb(self):
        from src.services.thumbnail_text_service import _hex_to_rgb
        self.assertEqual(_hex_to_rgb("#FFFFFF"), (255, 255, 255))
        self.assertEqual(_hex_to_rgb("#000000"), (0, 0, 0))
        self.assertEqual(_hex_to_rgb("#FFF"), (255, 255, 255))

    def test_add_hook_text_missing_file(self):
        from src.services.thumbnail_text_service import (
            ThumbnailTextConfig, add_hook_text,
        )
        cfg = ThumbnailTextConfig(hook_text="Test")
        result = add_hook_text("/nonexistent/img.jpg", cfg)
        self.assertEqual(result, "/nonexistent/img.jpg")

    def test_add_hook_text_no_pillow_graceful(self):
        import sys
        with patch.dict(sys.modules, {"PIL": None, "PIL.Image": None}):
            from src.services.thumbnail_text_service import (
                ThumbnailTextConfig, add_hook_text,
            )
            cfg = ThumbnailTextConfig(hook_text="Test")
            result = add_hook_text("/fake.jpg", cfg)
        self.assertEqual(result, "/fake.jpg")

    def test_generate_hook_thumbnail_missing_file(self):
        from src.services.thumbnail_text_service import generate_hook_thumbnail
        result = run(generate_hook_thumbnail(
            "/nonexistent.jpg", "Hook Text!", platform="tiktok"
        ))
        self.assertEqual(result, "/nonexistent.jpg")

    def test_thumbnail_text_config_defaults(self):
        from src.services.thumbnail_text_service import ThumbnailTextConfig
        cfg = ThumbnailTextConfig(hook_text="Fire content!")
        self.assertTrue(cfg.arrow_enabled)
        self.assertEqual(cfg.text_position, "top")
        self.assertEqual(cfg.background_opacity, 0.45)


# ===========================================================================
# 5. Subtitle QA
# ===========================================================================

_SAMPLE_ASS = """\
[Script Info]
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize
Style: Default,Arial,24
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Hello world this is a test subtitle
Dialogue: 0,0:00:03.00,0:00:03.50,Default,,0,0,0,,The fuck is this amazing incredible fire content
Dialogue: 0,0:00:05.00,0:00:06.00,Default,,0,0,0,,Win champion amazing fire money rich
"""


class TestSubtitleQA(unittest.TestCase):

    def test_reading_speed_pass(self):
        from src.video_processing.subtitle_qa import check_reading_speed
        issue = check_reading_speed("Hello world", 0.0, 2.0, 0)
        self.assertIsNone(issue)

    def test_reading_speed_fail(self):
        from src.video_processing.subtitle_qa import check_reading_speed
        issue = check_reading_speed("one two three four five six", 0.0, 1.0, 0)
        self.assertIsNotNone(issue)
        self.assertEqual(issue.kind, "reading_speed")

    def test_profanity_filter_detects(self):
        from src.video_processing.subtitle_qa import apply_profanity_filter
        text, count = apply_profanity_filter("What the fuck is this")
        self.assertGreater(count, 0)
        self.assertNotIn("fuck", text.lower())

    def test_profanity_filter_clean(self):
        from src.video_processing.subtitle_qa import apply_profanity_filter
        text, count = apply_profanity_filter("This is great content")
        self.assertEqual(count, 0)
        self.assertEqual(text, "This is great content")

    def test_inject_emojis(self):
        from src.video_processing.subtitle_qa import inject_emojis
        text, count = inject_emojis("This fire content is amazing")
        self.assertGreater(count, 0)
        self.assertIn("🔥", text)

    def test_inject_emojis_no_match(self):
        from src.video_processing.subtitle_qa import inject_emojis
        text, count = inject_emojis("The cat sat on the mat")
        self.assertEqual(count, 0)

    def test_fix_line_breaks_short_text(self):
        from src.video_processing.subtitle_qa import fix_line_breaks
        result = fix_line_breaks("Hello world")
        self.assertNotIn("\\N", result)

    def test_run_subtitle_qa_counts_segments(self):
        from src.video_processing.subtitle_qa import run_subtitle_qa
        report = run_subtitle_qa(_SAMPLE_ASS, apply_fixes=True)
        self.assertGreater(report.total_segments, 0)

    def test_run_subtitle_qa_detects_profanity(self):
        from src.video_processing.subtitle_qa import run_subtitle_qa
        report = run_subtitle_qa(_SAMPLE_ASS, apply_fixes=True, censor_profanity=True)
        self.assertGreater(report.profanity_found, 0)

    def test_run_subtitle_qa_injects_emojis(self):
        from src.video_processing.subtitle_qa import run_subtitle_qa
        report = run_subtitle_qa(_SAMPLE_ASS, apply_fixes=True, add_emojis=True)
        self.assertGreater(report.emojis_injected, 0)

    def test_run_subtitle_qa_fixed_content_not_empty(self):
        from src.video_processing.subtitle_qa import run_subtitle_qa
        report = run_subtitle_qa(_SAMPLE_ASS, apply_fixes=True)
        self.assertGreater(len(report.fixed_content), 0)

    def test_report_passed_flag(self):
        from src.video_processing.subtitle_qa import run_subtitle_qa
        clean_ass = _SAMPLE_ASS.replace("fuck", "fudge")
        report = run_subtitle_qa(clean_ass, apply_fixes=False)
        # No errors expected (only possible warnings for speed)
        errors = [i for i in report.issues if i.severity == "error"]
        self.assertEqual(len(errors), 0)


# ===========================================================================
# 6. Smart Reframe
# ===========================================================================

class TestSmartReframe(unittest.TestCase):

    def _mock_proc(self, stdout=b"1080,1920", returncode=0):
        proc = AsyncMock()
        proc.communicate.return_value = (stdout, b"")
        proc.returncode = returncode
        return proc

    def test_probe_dimensions_parses(self):
        from src.video_processing.smart_reframe import _probe_dimensions
        with patch("asyncio.create_subprocess_exec",
                   return_value=self._mock_proc(b"1080,1920")):
            w, h = run(_probe_dimensions("/fake.mp4"))
        self.assertEqual(w, 1080)
        self.assertEqual(h, 1920)

    def test_probe_dimensions_fallback_on_bad_output(self):
        from src.video_processing.smart_reframe import _probe_dimensions
        with patch("asyncio.create_subprocess_exec",
                   return_value=self._mock_proc(b"bad_data")):
            w, h = run(_probe_dimensions("/fake.mp4"))
        self.assertEqual(w, 1080)
        self.assertEqual(h, 1920)

    def test_detect_face_x_fallback(self):
        from src.video_processing.smart_reframe import _detect_face_x_ratio
        with patch("asyncio.create_subprocess_exec",
                   return_value=self._mock_proc(b"")):
            ratio = run(_detect_face_x_ratio("/fake.mp4"))
        self.assertEqual(ratio, 0.5)

    def test_reframe_square_failed_returns_original(self):
        from src.video_processing.smart_reframe import reframe_to_square
        proc = self._mock_proc(b"", returncode=1)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = run(reframe_to_square("/in.mp4", "/out.mp4", 0.5, 1080, 1920))
        self.assertEqual(result.method, "failed")
        self.assertEqual(result.output_path, "/in.mp4")

    def test_reframe_square_success(self):
        from src.video_processing.smart_reframe import reframe_to_square
        proc = self._mock_proc(b"", returncode=0)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = run(reframe_to_square("/in.mp4", "/out.mp4", 0.5, 1080, 1920))
        self.assertEqual(result.ratio, "1:1")
        self.assertEqual(result.width, 1080)
        self.assertEqual(result.method, "face_crop")

    def test_reframe_landscape_success(self):
        from src.video_processing.smart_reframe import reframe_to_landscape
        proc = self._mock_proc(b"", returncode=0)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = run(reframe_to_landscape("/in.mp4", "/out.mp4", 1080, 1920))
        self.assertEqual(result.ratio, "16:9")
        self.assertEqual(result.width, 1920)
        self.assertEqual(result.height, 1080)
        self.assertEqual(result.method, "letterbox")

    def test_generate_all_reframes_both_ratios(self):
        from src.video_processing.smart_reframe import generate_all_reframes

        async def _fake_exec(*args, **kwargs):
            p = AsyncMock()
            p.communicate.return_value = (b"1080,1920", b"")
            p.returncode = 0
            return p

        with patch("asyncio.create_subprocess_exec", side_effect=_fake_exec):
            with tempfile.TemporaryDirectory() as d:
                results = run(generate_all_reframes("/in.mp4", d, ["1:1", "16:9"]))
        self.assertEqual(len(results), 2)
        ratios = {r.ratio for r in results}
        self.assertIn("1:1", ratios)
        self.assertIn("16:9", ratios)


# ===========================================================================
# 7. Language Detector
# ===========================================================================

class TestLanguageDetector(unittest.TestCase):

    def test_detect_english_text(self):
        from src.services.language_detector import detect_language
        result = detect_language("This is a test sentence in English language")
        self.assertIn(result.language, ["en", "es", "pt", "fr", "de"])

    def test_detect_fallback_short_text(self):
        from src.services.language_detector import detect_language
        result = detect_language("hi", fallback="en")
        self.assertEqual(result.language, "en")
        self.assertEqual(result.confidence, 0.5)

    def test_detect_fallback_empty(self):
        from src.services.language_detector import detect_language
        result = detect_language("", fallback="es")
        self.assertEqual(result.language, "es")

    def test_get_locale_english(self):
        from src.services.language_detector import get_locale
        loc = get_locale("en")
        self.assertEqual(loc["name"], "English")
        self.assertEqual(loc["caption_dir"], "ltr")

    def test_get_locale_arabic_rtl(self):
        from src.services.language_detector import get_locale
        loc = get_locale("ar")
        self.assertEqual(loc["caption_dir"], "rtl")

    def test_get_locale_unknown_falls_back_to_en(self):
        from src.services.language_detector import get_locale
        loc = get_locale("zz")
        self.assertEqual(loc["name"], "English")

    def test_supported_languages_count(self):
        from src.services.language_detector import supported_languages
        langs = supported_languages()
        self.assertGreaterEqual(len(langs), 15)

    def test_supported_languages_has_required_fields(self):
        from src.services.language_detector import supported_languages
        for lang in supported_languages():
            self.assertIn("code", lang)
            self.assertIn("name", lang)
            self.assertIn("territory", lang)

    def test_build_locale_prompt_virality(self):
        from src.services.language_detector import build_locale_prompt
        prompt = build_locale_prompt("test text", "virality", language="es")
        self.assertIn("Spanish", prompt)
        self.assertIn("viral", prompt.lower())

    def test_build_locale_prompt_hashtags(self):
        from src.services.language_detector import build_locale_prompt
        prompt = build_locale_prompt("test text", "hashtags", language="pt")
        self.assertIn("hashtag", prompt.lower())
        self.assertIn("Portuguese", prompt)

    def test_build_locale_prompt_cta(self):
        from src.services.language_detector import build_locale_prompt
        prompt = build_locale_prompt("x", "cta", language="en")
        self.assertIn("CTA", prompt)

    def test_detect_returns_is_supported(self):
        from src.services.language_detector import detect_language
        result = detect_language("hello world test sentence ok")
        self.assertIsInstance(result.is_supported, bool)


# ===========================================================================
# 8. Narrative Arc Service
# ===========================================================================

class TestNarrativeArcService(unittest.TestCase):

    def _clips(self, n=5):
        from src.services.narrative_arc_service import ClipMeta
        return [
            ClipMeta(
                clip_id=f"c{i}", file_path=f"/clip{i}.mp4",
                duration=15.0, virality_score=float(i * 10 + 20),
                order=i,
            )
            for i in range(n)
        ]

    def test_assign_parts_basic(self):
        from src.services.narrative_arc_service import _assign_parts
        clips = self._clips(6)
        parts = _assign_parts(clips, max_part_duration=60.0)
        total_clips = sum(len(p.clips) for p in parts)
        self.assertEqual(total_clips, 6)
        for p in parts:
            self.assertLessEqual(p.total_duration, 60.0 + 15.0)

    def test_assign_parts_order_preserved(self):
        from src.services.narrative_arc_service import _assign_parts
        clips = self._clips(3)
        parts = _assign_parts(clips, max_part_duration=60.0)
        first_clip = parts[0].clips[0]
        self.assertEqual(first_clip.order, 0)

    def test_assign_parts_max_parts_cap(self):
        from src.services.narrative_arc_service import _assign_parts
        clips = self._clips(20)
        parts = _assign_parts(clips, max_part_duration=15.0, max_parts=3)
        self.assertLessEqual(len(parts), 3)

    def test_select_best_of_by_virality(self):
        from src.services.narrative_arc_service import _select_best_of
        clips = self._clips(5)
        selected = _select_best_of(clips, n=3, max_total_duration=90.0)
        scores = [c.virality_score for c in selected]
        self.assertEqual(len(selected), 3)
        # verify sorted by order (not virality) after selection
        orders = [c.order for c in selected]
        self.assertEqual(orders, sorted(orders))

    def test_select_best_of_duration_cap(self):
        from src.services.narrative_arc_service import _select_best_of
        clips = self._clips(10)
        selected = _select_best_of(clips, n=10, max_total_duration=30.0)
        total = sum(c.duration for c in selected)
        self.assertLessEqual(total, 30.0 + 15.0)

    def test_find_teaser_returns_highest_virality(self):
        from src.services.narrative_arc_service import _find_teaser_clip
        clips = self._clips(5)
        best = _find_teaser_clip(clips)
        self.assertIsNotNone(best)
        self.assertEqual(best.virality_score, max(c.virality_score for c in clips))

    def test_find_teaser_empty(self):
        from src.services.narrative_arc_service import _find_teaser_clip
        self.assertIsNone(_find_teaser_clip([]))

    def test_build_series_no_valid_files(self):
        from src.services.narrative_arc_service import build_series, ClipMeta
        clips = [ClipMeta("c1", "/nonexistent.mp4", 15.0, 80.0, order=0)]
        with tempfile.TemporaryDirectory() as d:
            result = run(build_series(clips, d))
        self.assertEqual(result.strategy, "series")
        # No valid files → no output paths
        self.assertEqual(result.output_paths, [])

    def test_build_best_of_empty(self):
        from src.services.narrative_arc_service import build_best_of
        with tempfile.TemporaryDirectory() as d:
            result = run(build_best_of([], d))
        self.assertEqual(result.strategy, "best_of")
        self.assertIn("No clips", result.description)

    def test_build_teaser_empty(self):
        from src.services.narrative_arc_service import build_teaser
        with tempfile.TemporaryDirectory() as d:
            result = run(build_teaser([], d))
        self.assertEqual(result.strategy, "teaser")


# ===========================================================================
# 9. Brand Overlay Service
# ===========================================================================

class TestBrandOverlayService(unittest.TestCase):

    def _mock_proc(self, returncode=0):
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"")
        proc.returncode = returncode
        return proc

    def test_position_xy_bottom_right(self):
        from src.services.brand_overlay_service import _position_xy
        x, y = _position_xy("bottom_right", 20, 20)
        self.assertIn("W-w", x)
        self.assertIn("H-h", y)

    def test_position_xy_top_left(self):
        from src.services.brand_overlay_service import _position_xy
        x, y = _position_xy("top_left", 10, 10)
        self.assertEqual(x, "10")
        self.assertEqual(y, "10")

    def test_text_drawtext_filter_contains_text(self):
        from src.services.brand_overlay_service import BrandConfig, _text_drawtext_filter
        cfg = BrandConfig(text="@myhandle")
        vf = _text_drawtext_filter(cfg)
        self.assertIn("@myhandle", vf)
        self.assertIn("drawtext", vf)

    def test_apply_text_watermark_success(self):
        from src.services.brand_overlay_service import BrandConfig, apply_text_watermark
        cfg = BrandConfig(text="@test")
        with patch("asyncio.create_subprocess_exec",
                   return_value=self._mock_proc(0)):
            result = run(apply_text_watermark("/in.mp4", "/out.mp4", cfg))
        self.assertTrue(result)

    def test_apply_text_watermark_failure(self):
        from src.services.brand_overlay_service import BrandConfig, apply_text_watermark
        cfg = BrandConfig(text="@test")
        with patch("asyncio.create_subprocess_exec",
                   return_value=self._mock_proc(1)):
            result = run(apply_text_watermark("/in.mp4", "/out.mp4", cfg))
        self.assertFalse(result)

    def test_apply_image_watermark_missing_image(self):
        from src.services.brand_overlay_service import BrandConfig, apply_image_watermark
        cfg = BrandConfig(image_path="/nonexistent_logo.png")
        result = run(apply_image_watermark("/in.mp4", "/out.mp4", cfg))
        self.assertFalse(result)

    def test_apply_brand_overlay_no_text_or_image(self):
        from src.services.brand_overlay_service import BrandConfig, apply_brand_overlay
        cfg = BrandConfig()
        result = run(apply_brand_overlay("/in.mp4", "/out.mp4", cfg))
        self.assertEqual(result, "/in.mp4")

    def test_apply_brand_overlay_uses_text(self):
        from src.services.brand_overlay_service import BrandConfig, apply_brand_overlay
        cfg = BrandConfig(text="@brand")
        with patch("asyncio.create_subprocess_exec",
                   return_value=self._mock_proc(0)):
            with patch("os.path.exists", return_value=True):
                result = run(apply_brand_overlay("/in.mp4", "/out.mp4", cfg))
        self.assertEqual(result, "/out.mp4")


# ===========================================================================
# 10. Clip Health Service
# ===========================================================================

class TestClipHealthService(unittest.TestCase):

    def test_check_hook_presence_missing(self):
        from src.services.clip_health_service import check_hook_presence
        c = check_hook_presence(None, None, None)
        self.assertEqual(c.status, "fail")
        self.assertIn("No hook", c.message)

    def test_check_hook_presence_late(self):
        from src.services.clip_health_service import check_hook_presence
        c = check_hook_presence(7.0, 5.0, "question")
        self.assertEqual(c.status, "warn")
        self.assertIn("too late", c.message)

    def test_check_hook_presence_pass(self):
        from src.services.clip_health_service import check_hook_presence
        c = check_hook_presence(8.0, 1.5, "question")
        self.assertEqual(c.status, "pass")

    def test_check_duration_too_short(self):
        from src.services.clip_health_service import check_duration
        c = check_duration(3.0, "tiktok")
        self.assertEqual(c.status, "fail")

    def test_check_duration_too_long(self):
        from src.services.clip_health_service import check_duration
        c = check_duration(90.0, "tiktok")
        self.assertEqual(c.status, "warn")

    def test_check_duration_pass(self):
        from src.services.clip_health_service import check_duration
        c = check_duration(30.0, "tiktok")
        self.assertEqual(c.status, "pass")

    def test_check_virality_fail(self):
        from src.services.clip_health_service import check_virality_score
        c = check_virality_score(3.0)
        self.assertEqual(c.status, "fail")

    def test_check_virality_warn(self):
        from src.services.clip_health_service import check_virality_score
        c = check_virality_score(6.0)
        self.assertEqual(c.status, "warn")

    def test_check_virality_pass(self):
        from src.services.clip_health_service import check_virality_score
        c = check_virality_score(8.5)
        self.assertEqual(c.status, "pass")

    def test_check_audio_quality_no_loudnorm(self):
        from src.services.clip_health_service import check_audio_quality
        c = check_audio_quality(False, False)
        self.assertEqual(c.status, "warn")

    def test_check_audio_quality_pass(self):
        from src.services.clip_health_service import check_audio_quality
        c = check_audio_quality(True, True)
        self.assertEqual(c.status, "pass")

    def test_check_broll_zero(self):
        from src.services.clip_health_service import check_broll_coverage
        c = check_broll_coverage(0, 30.0)
        self.assertEqual(c.status, "warn")

    def test_check_captions_missing(self):
        from src.services.clip_health_service import check_captions
        c = check_captions(False)
        self.assertEqual(c.status, "fail")
        self.assertIn("85%", c.message)

    def test_check_captions_present(self):
        from src.services.clip_health_service import check_captions
        c = check_captions(True)
        self.assertEqual(c.status, "pass")

    def test_check_hashtags_empty(self):
        from src.services.clip_health_service import check_hashtags
        c = check_hashtags(0)
        self.assertEqual(c.status, "warn")

    def test_check_thumbnail_missing(self):
        from src.services.clip_health_service import check_thumbnail
        c = check_thumbnail(None)
        self.assertEqual(c.status, "warn")

    def test_generate_health_report_perfect_clip(self):
        from src.services.clip_health_service import generate_health_report
        report = generate_health_report(
            clip_id="c1",
            virality_score=9.0,
            hook_score=9.0,
            hook_start=1.0,
            hook_type="question",
            duration=45.0,
            platform="tiktok",
            loudnorm_applied=True,
            sfx_injected=True,
            broll_count=5,
            has_subtitles=True,
            hashtag_count=10,
            thumbnail_path="/thumb.jpg",
            zoom_punch_applied=True,
        )
        self.assertGreater(report.overall_score, 70)
        self.assertIn(report.grade, ["A", "B"])

    def test_generate_health_report_bad_clip(self):
        from src.services.clip_health_service import generate_health_report
        report = generate_health_report(
            clip_id="bad",
            virality_score=1.0,
            duration=3.0,
            has_subtitles=False,
        )
        self.assertLess(report.overall_score, 60)
        self.assertIn(report.grade, ["D", "F"])
        self.assertNotEqual(report.top_fix, "")

    def test_report_to_dict(self):
        from src.services.clip_health_service import generate_health_report
        report = generate_health_report("c", virality_score=5.0, duration=30.0)
        d = report.to_dict()
        self.assertIn("clip_id", d)
        self.assertIn("overall_score", d)
        self.assertIn("grade", d)
        self.assertIn("checks", d)
        self.assertIsInstance(d["checks"], list)

    def test_score_from_checks_logic(self):
        from src.services.clip_health_service import _score_from_checks, HealthCheck
        checks = [
            HealthCheck("A", "pass", "✅", "ok"),
            HealthCheck("B", "fail", "❌", "bad"),
            HealthCheck("C", "warn", "⚠️", "meh"),
        ]
        from src.services.clip_health_service import _score_from_checks
        score = _score_from_checks(checks)
        self.assertEqual(score, 80.0)   # 100 - 15 (fail) - 5 (warn)


# ===========================================================================
# 11. TikTok Templates Service
# ===========================================================================

class TestTikTokTemplatesService(unittest.TestCase):

    def _mock_proc(self, returncode=0, stdout=b"30.0"):
        proc = AsyncMock()
        proc.communicate.return_value = (stdout, b"")
        proc.returncode = returncode
        return proc

    def test_render_duet_success(self):
        from src.services.tiktok_templates_service import render_duet
        with patch("asyncio.create_subprocess_exec",
                   return_value=self._mock_proc(0)):
            result = run(render_duet("/a.mp4", "/b.mp4", "/out.mp4"))
        self.assertTrue(result.success)
        self.assertEqual(result.template, "duet")

    def test_render_duet_failure(self):
        from src.services.tiktok_templates_service import render_duet
        with patch("asyncio.create_subprocess_exec",
                   return_value=self._mock_proc(1)):
            result = run(render_duet("/a.mp4", "/b.mp4", "/out.mp4"))
        self.assertFalse(result.success)

    def test_render_stitch_success(self):
        from src.services.tiktok_templates_service import render_stitch
        call_count = 0

        async def _fake(*args, **kw):
            nonlocal call_count
            call_count += 1
            p = AsyncMock()
            p.communicate.return_value = (b"", b"")
            p.returncode = 0
            return p

        with patch("asyncio.create_subprocess_exec", side_effect=_fake):
            with tempfile.TemporaryDirectory() as d:
                out = f"{d}/stitch.mp4"
                result = run(render_stitch("/a.mp4", "/b.mp4", out, stitch_seconds=5.0))
        self.assertTrue(result.success)
        self.assertEqual(result.template, "stitch")

    def test_render_stitch_preprocess_failure(self):
        from src.services.tiktok_templates_service import render_stitch
        with patch("asyncio.create_subprocess_exec",
                   return_value=self._mock_proc(1)):
            result = run(render_stitch("/a.mp4", "/b.mp4", "/out.mp4"))
        self.assertFalse(result.success)

    def test_render_green_screen_success(self):
        from src.services.tiktok_templates_service import render_green_screen
        with patch("asyncio.create_subprocess_exec",
                   return_value=self._mock_proc(0)):
            result = run(render_green_screen(
                "/subject.mp4", "/bg.mp4", "/out.mp4"
            ))
        self.assertTrue(result.success)
        self.assertEqual(result.template, "green_screen")

    def test_render_green_screen_failure(self):
        from src.services.tiktok_templates_service import render_green_screen
        with patch("asyncio.create_subprocess_exec",
                   return_value=self._mock_proc(1)):
            result = run(render_green_screen("/s.mp4", "/bg.mp4", "/out.mp4"))
        self.assertFalse(result.success)

    def test_render_subject_over_broll_success(self):
        from src.services.tiktok_templates_service import render_subject_over_broll
        with patch("asyncio.create_subprocess_exec",
                   return_value=self._mock_proc(0)):
            result = run(render_subject_over_broll("/s.mp4", "/bg.mp4", "/out.mp4"))
        self.assertTrue(result.success)
        self.assertEqual(result.template, "subject_over_broll")

    def test_template_result_fields(self):
        from src.services.tiktok_templates_service import render_duet
        with patch("asyncio.create_subprocess_exec",
                   return_value=self._mock_proc(0)):
            result = run(render_duet("/a.mp4", "/b.mp4", "/out.mp4",
                                     target_w=1080, target_h=1920))
        self.assertEqual(result.width, 1080)
        self.assertEqual(result.height, 1920)


if __name__ == "__main__":
    unittest.main()
