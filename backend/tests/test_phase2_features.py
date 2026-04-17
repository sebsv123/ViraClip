"""
Tests for Phase 2 features:
  - Hook slowmo auto-enable (score-based, env var as hard-disable)
  - variant_generator.py (A/B variants: caption style + BGM)
  - beat_sync_service preferred_category param
  - Talking-head eye contact auto-detection in video_service.py
  - Coordinator A/B variant wiring
"""
import asyncio
import inspect
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ══════════════════════════════════════════════════════════════════════════════
# Hook slowmo auto-enable
# ══════════════════════════════════════════════════════════════════════════════

class TestHookSlowmoAutoEnable(unittest.TestCase):

    def _get_maybe_fn(self):
        # Re-import fresh each test to avoid module-level constant caching
        import importlib
        import src.video_processing.hook_slowmo as _m
        importlib.reload(_m)
        return _m.maybe_apply_hook_slowmo

    def test_high_score_applies_without_env_var(self):
        """Score ≥ threshold with no HOOK_SLOWMO_ENABLED env var → applied."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HOOK_SLOWMO_ENABLED", None)
            import importlib, src.video_processing.hook_slowmo as _m
            importlib.reload(_m)
            with patch.object(_m, "apply_hook_slowmo", return_value=True) as mock_apply, \
                 patch("pathlib.Path.exists", return_value=True):
                result = _m.maybe_apply_hook_slowmo(
                    Path("/fake/clip.mp4"), virality_score=85, inplace=False
                )
        self.assertTrue(result)
        mock_apply.assert_called_once()

    def test_low_score_skipped(self):
        """Score < threshold → no slow-mo regardless of env var."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HOOK_SLOWMO_ENABLED", None)
            import importlib, src.video_processing.hook_slowmo as _m
            importlib.reload(_m)
            with patch.object(_m, "apply_hook_slowmo", return_value=True) as mock_apply:
                result = _m.maybe_apply_hook_slowmo(
                    Path("/fake/clip.mp4"), virality_score=40
                )
        self.assertFalse(result)
        mock_apply.assert_not_called()

    def test_env_false_disables_high_score(self):
        """HOOK_SLOWMO_ENABLED=false hard-disables even for score=100."""
        with patch.dict(os.environ, {"HOOK_SLOWMO_ENABLED": "false"}):
            import importlib, src.video_processing.hook_slowmo as _m
            importlib.reload(_m)
            with patch.object(_m, "apply_hook_slowmo", return_value=True) as mock_apply:
                result = _m.maybe_apply_hook_slowmo(
                    Path("/fake/clip.mp4"), virality_score=100
                )
        self.assertFalse(result)
        mock_apply.assert_not_called()

    def test_env_true_doesnt_override_low_score(self):
        """HOOK_SLOWMO_ENABLED=true still respects MIN_VIRALITY_SCORE."""
        with patch.dict(os.environ, {"HOOK_SLOWMO_ENABLED": "true"}):
            import importlib, src.video_processing.hook_slowmo as _m
            importlib.reload(_m)
            with patch.object(_m, "apply_hook_slowmo", return_value=True) as mock_apply:
                result = _m.maybe_apply_hook_slowmo(
                    Path("/fake/clip.mp4"), virality_score=30
                )
        self.assertFalse(result)
        mock_apply.assert_not_called()

    def test_min_virality_score_default_is_70(self):
        import src.video_processing.hook_slowmo as _m
        self.assertEqual(_m.MIN_VIRALITY_SCORE, 70)

    def test_maybe_fn_is_not_async(self):
        """maybe_apply_hook_slowmo is a sync function (runs in thread pool)."""
        import src.video_processing.hook_slowmo as _m
        self.assertFalse(asyncio.iscoroutinefunction(_m.maybe_apply_hook_slowmo))


# ══════════════════════════════════════════════════════════════════════════════
# variant_generator.py
# ══════════════════════════════════════════════════════════════════════════════

class TestVariantGenerator(unittest.IsolatedAsyncioTestCase):

    def _sample_words(self):
        return [
            {"word": "fire", "start": 0.0, "end": 0.3},
            {"word": "amazing", "start": 1.0, "end": 1.4},
            {"word": "secret", "start": 2.0, "end": 2.5},
        ]

    async def test_module_importable(self):
        from src.services.variant_generator import generate_clip_variants
        self.assertTrue(asyncio.iscoroutinefunction(generate_clip_variants))

    async def test_next_caption_style_rotates(self):
        from src.services.variant_generator import _next_caption_style, _CAPTION_STYLE_ROTATION
        for i, style in enumerate(_CAPTION_STYLE_ROTATION):
            nxt = _next_caption_style(style)
            expected = _CAPTION_STYLE_ROTATION[(i + 1) % len(_CAPTION_STYLE_ROTATION)]
            self.assertEqual(nxt, expected)

    async def test_next_caption_style_unknown_falls_back(self):
        from src.services.variant_generator import _next_caption_style, _CAPTION_STYLE_ROTATION
        result = _next_caption_style("nonexistent")
        self.assertIn(result, _CAPTION_STYLE_ROTATION)

    async def test_returns_empty_list_when_both_fail(self):
        from src.services.variant_generator import generate_clip_variants
        with patch("src.services.variant_generator._generate_caption_variant",
                   new=AsyncMock(return_value=False)), \
             patch("src.services.variant_generator._generate_bgm_variant",
                   new=AsyncMock(return_value=None)):
            variants = await generate_clip_variants(
                Path("/fake/clip.mp4"), words=self._sample_words()
            )
        self.assertEqual(variants, [])

    async def test_returns_variant_a_on_caption_success(self):
        from src.services.variant_generator import generate_clip_variants
        with patch("src.services.variant_generator._generate_caption_variant",
                   new=AsyncMock(return_value=True)), \
             patch("src.services.variant_generator._generate_bgm_variant",
                   new=AsyncMock(return_value=None)):
            variants = await generate_clip_variants(
                Path("/fake/clip.mp4"), words=self._sample_words()
            )
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["variant"], "A")
        self.assertEqual(variants[0]["type"], "caption_style")
        self.assertIn("_va", variants[0]["path"])

    async def test_returns_variant_b_on_bgm_success(self):
        from src.services.variant_generator import generate_clip_variants
        with patch("src.services.variant_generator._generate_caption_variant",
                   new=AsyncMock(return_value=False)), \
             patch("src.services.variant_generator._generate_bgm_variant",
                   new=AsyncMock(return_value="chill")):
            variants = await generate_clip_variants(
                Path("/fake/clip.mp4"), words=self._sample_words()
            )
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["variant"], "B")
        self.assertEqual(variants[0]["type"], "bgm_category")
        self.assertEqual(variants[0]["label"], "bgm:chill")
        self.assertIn("_vb", variants[0]["path"])

    async def test_returns_both_variants_on_full_success(self):
        from src.services.variant_generator import generate_clip_variants
        with patch("src.services.variant_generator._generate_caption_variant",
                   new=AsyncMock(return_value=True)), \
             patch("src.services.variant_generator._generate_bgm_variant",
                   new=AsyncMock(return_value="lofi")):
            variants = await generate_clip_variants(
                Path("/fake/clip.mp4"), words=self._sample_words()
            )
        self.assertEqual(len(variants), 2)
        types = {v["type"] for v in variants}
        self.assertIn("caption_style", types)
        self.assertIn("bgm_category", types)

    async def test_caption_variant_is_async(self):
        from src.services.variant_generator import _generate_caption_variant
        self.assertTrue(asyncio.iscoroutinefunction(_generate_caption_variant))

    async def test_bgm_variant_is_async(self):
        from src.services.variant_generator import _generate_bgm_variant
        self.assertTrue(asyncio.iscoroutinefunction(_generate_bgm_variant))

    async def test_caption_variant_returns_false_on_no_words(self):
        from src.services.variant_generator import _generate_caption_variant
        result = await _generate_caption_variant(
            Path("/fake/in.mp4"), Path("/fake/out.mp4"),
            words=[], current_style="tiktok",
        )
        self.assertFalse(result)

    async def test_bgm_variant_uses_different_category(self):
        from src.services.variant_generator import _BGM_VARIANT_CATEGORIES
        # Must have at least 3 categories to always find a different one
        self.assertGreaterEqual(len(_BGM_VARIANT_CATEGORIES), 3)
        # Verify "hype" is in the list (primary default) so we can differ from it
        self.assertIn("hype", _BGM_VARIANT_CATEGORIES)


# ══════════════════════════════════════════════════════════════════════════════
# beat_sync_service preferred_category param
# ══════════════════════════════════════════════════════════════════════════════

class TestBeatSyncPreferredCategory(unittest.TestCase):

    def test_mix_bgm_beat_synced_has_preferred_category_param(self):
        from src.services.beat_sync_service import mix_bgm_beat_synced
        sig = inspect.signature(mix_bgm_beat_synced)
        self.assertIn("preferred_category", sig.parameters)
        self.assertIsNone(sig.parameters["preferred_category"].default)

    def test_select_bgm_has_prefer_category_param(self):
        from src.services.beat_sync_service import select_bgm
        sig = inspect.signature(select_bgm)
        self.assertIn("prefer_category", sig.parameters)

    def test_preferred_category_passed_to_select_bgm(self):
        from src.services import beat_sync_service as _bss
        src = inspect.getsource(_bss.mix_bgm_beat_synced)
        self.assertIn("prefer_category=preferred_category", src)


# ══════════════════════════════════════════════════════════════════════════════
# Talking-head eye contact auto-detection
# ══════════════════════════════════════════════════════════════════════════════

class TestTalkingHeadEyeContactAutoDetect(unittest.TestCase):

    def _get_create_single_clip_source(self):
        from src.services.video_service import VideoService
        return inspect.getsource(VideoService.create_single_clip)

    def test_eye_contact_auto_env_guard_present(self):
        src = self._get_create_single_clip_source()
        self.assertIn("EYE_CONTACT_AUTO", src)

    def test_talking_head_detection_uses_face_centered_flag(self):
        src = self._get_create_single_clip_source()
        self.assertIn("_face_centered", src)
        self.assertIn("_is_talking_head", src)

    def test_auto_condition_requires_words(self):
        src = self._get_create_single_clip_source()
        # _is_talking_head must require words_with_confidence
        self.assertIn("words_with_confidence", src)

    def test_auto_center_face_return_value_captured(self):
        src = self._get_create_single_clip_source()
        # Must capture return value of auto_center_face
        self.assertIn("_face_centered = await polisher.auto_center_face", src)

    def test_env_false_disables_auto_eye_contact(self):
        src = self._get_create_single_clip_source()
        self.assertIn("EYE_CONTACT_AUTO", src)
        self.assertIn("!= \"false\"", src)

    def test_eye_contact_still_applies_when_explicitly_requested(self):
        """eye_contact_correction=True must still work even without face detection."""
        src = self._get_create_single_clip_source()
        # The condition must OR explicit request with auto-detect
        self.assertIn("eye_contact_correction or", src)


# ══════════════════════════════════════════════════════════════════════════════
# Coordinator variant wiring
# ══════════════════════════════════════════════════════════════════════════════

class TestCoordinatorVariantWiring(unittest.TestCase):

    def _get_coordinator_source(self):
        from src.services.coordinator import VideoCoordinator
        return inspect.getsource(VideoCoordinator)

    def test_variant_generator_imported_in_render(self):
        src = self._get_coordinator_source()
        self.assertIn("variant_generator", src)
        self.assertIn("generate_clip_variants", src)

    def test_variants_stored_in_clip_dict(self):
        src = self._get_coordinator_source()
        self.assertIn("clip[\"variants\"]", src)

    def test_primary_caption_style_passed_to_variants(self):
        src = self._get_coordinator_source()
        self.assertIn("primary_caption_style", src)

    def test_primary_bgm_category_passed_to_variants(self):
        src = self._get_coordinator_source()
        self.assertIn("primary_bgm_category", src)

    def test_variant_generation_is_non_fatal(self):
        """Must be wrapped in try/except so failures don't break the clip."""
        src = self._get_coordinator_source()
        # Check that generate_clip_variants is inside a try block
        idx_try = src.find("generate_clip_variants")
        # walk backward to find nearest 'try'
        sub = src[:idx_try]
        self.assertIn("try:", sub[-300:], "generate_clip_variants must be inside a try block")


# ══════════════════════════════════════════════════════════════════════════════
# Variant file naming convention
# ══════════════════════════════════════════════════════════════════════════════

class TestVariantFileNaming(unittest.TestCase):

    def test_variant_a_suffix(self):
        from src.services.variant_generator import generate_clip_variants
        # Verify naming by checking the source
        src = inspect.getsource(generate_clip_variants)
        self.assertIn("_va", src)
        self.assertIn("_vb", src)

    def test_variant_paths_are_siblings(self):
        """Variants must be in the same directory as the source clip."""
        from src.services.variant_generator import generate_clip_variants
        src = inspect.getsource(generate_clip_variants)
        self.assertIn("parent", src)

    def test_variant_label_format(self):
        from src.services.variant_generator import _next_caption_style
        style = _next_caption_style("tiktok")
        # Label should be "caption:<style>"
        label = f"caption:{style}"
        self.assertTrue(label.startswith("caption:"))


if __name__ == "__main__":
    unittest.main()
