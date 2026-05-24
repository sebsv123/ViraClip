"""
Regression tests for the 5 transition effects in clip_editor.py.

Tests cover:
  1. match_cut_transition — basic execution
  2. glitch_transition — rgb style
  3. glitch_transition — scan style
  4. glitch_transition — freeze style
  5. sweep_mask_transition — circle shape
  6. sweep_mask_transition — diagonal shape
  7. sweep_mask_transition — wipe shape
  8. mask_reveal_transition — auto (no semantic category)
  9. mask_reveal_transition — with semantic category
  10. shape_morph_transition — fast quality (rembg fallback)
  11. transition_selector — dispatch logic
  12. graceful degradation — invalid parameters
  13. IconScout no-key — graceful handling

Marked with @pytest.mark.gpu where GPU / SAM / rembg is required.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from moviepy import ColorClip, concatenate_videoclips

from clip_editor import (
    match_cut_transition,
    glitch_transition,
    sweep_mask_transition,
    mask_reveal_transition,
    shape_morph_transition,
    fetch_iconscout_asset,
)
from transition_selector import (
    select_and_apply_transition,
    merge_with_transitions,
    TRANSITION_DISPATCH,
)

from conftest import make_test_clip


# ── Helpers ────────────────────────────────────────────────────────────────────


def _assert_valid_clip(clip, min_duration: float = 0.5) -> None:
    """Assert that *clip* is a valid MoviePy clip with expected properties."""
    assert clip is not None, "Expected a valid clip, got None"
    assert clip.duration >= min_duration, (
        f"Clip duration {clip.duration:.2f}s < {min_duration:.2f}s"
    )
    assert clip.w > 0 and clip.h > 0, "Clip dimensions must be positive"
    assert clip.fps > 0, "Clip fps must be positive"


# ── Test 1: match_cut_transition ───────────────────────────────────────────────


class TestMatchCut:
    """match_cut_transition regression tests."""

    def test_basic_execution(self):
        """match_cut should return a valid concatenated clip."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = match_cut_transition(a, b, duration=0.08)
        _assert_valid_clip(result)
        # Duration should be roughly a.duration + b.duration
        expected = a.duration + b.duration
        assert abs(result.duration - expected) < 0.2, (
            f"Expected ~{expected:.2f}s, got {result.duration:.2f}s"
        )

    def test_with_obj_centers(self):
        """match_cut should accept explicit object centers."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = match_cut_transition(
            a, b,
            obj_center_a=(320, 240),
            obj_center_b=(160, 120),
            duration=0.08,
        )
        _assert_valid_clip(result)

    def test_no_motion_blur(self):
        """match_cut should work with motion_blur=False."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = match_cut_transition(a, b, duration=0.08, motion_blur=False)
        _assert_valid_clip(result)

    def test_graceful_fallback_on_error(self):
        """match_cut should fall back to concatenation on error."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        with patch("clip_editor._source_fps", side_effect=ValueError("mock error")):
            result = match_cut_transition(a, b, duration=0.08)
        _assert_valid_clip(result)


# ── Test 2-4: glitch_transition ────────────────────────────────────────────────


class TestGlitch:
    """glitch_transition regression tests for all 3 styles."""

    def test_rgb_style(self):
        """glitch with style='rgb' should return a valid clip."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = glitch_transition(a, b, style="rgb", duration=0.1)
        _assert_valid_clip(result)

    def test_scan_style(self):
        """glitch with style='scan' should return a valid clip."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = glitch_transition(a, b, style="scan", duration=0.1)
        _assert_valid_clip(result)

    def test_freeze_style(self):
        """glitch with style='freeze' should return a valid clip."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = glitch_transition(a, b, style="freeze", duration=0.1)
        _assert_valid_clip(result)

    def test_invalid_style_fallback(self):
        """glitch with unknown style should fall back gracefully."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = glitch_transition(a, b, style="unknown_style", duration=0.1)
        _assert_valid_clip(result)


# ── Test 5-7: sweep_mask_transition ────────────────────────────────────────────


class TestSweepMask:
    """sweep_mask_transition regression tests for all 3 shapes."""

    def test_circle_shape(self):
        """sweep_mask with shape='circle' should return a valid clip."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = sweep_mask_transition(a, b, shape="circle", duration=0.4)
        _assert_valid_clip(result)

    def test_diagonal_shape(self):
        """sweep_mask with shape='diagonal' should return a valid clip."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = sweep_mask_transition(a, b, shape="diagonal", duration=0.4)
        _assert_valid_clip(result)

    def test_wipe_shape(self):
        """sweep_mask with shape='wipe' should return a valid clip."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = sweep_mask_transition(a, b, shape="wipe", duration=0.4)
        _assert_valid_clip(result)

    def test_custom_center(self):
        """sweep_mask should accept custom cx/cy."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = sweep_mask_transition(a, b, cx=200, cy=200, shape="circle", duration=0.4)
        _assert_valid_clip(result)


# ── Test 8-9: mask_reveal_transition ───────────────────────────────────────────


class TestMaskReveal:
    """mask_reveal_transition regression tests."""

    def test_auto_no_semantic(self):
        """mask_reveal with semantic_category=None should auto-detect."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = mask_reveal_transition(a, b, semantic_category=None, duration=0.5)
        _assert_valid_clip(result)

    def test_with_semantic_category(self):
        """mask_reveal with a known semantic category should use it."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = mask_reveal_transition(
            a, b, semantic_category="naturaleza", duration=0.5,
        )
        _assert_valid_clip(result)

    def test_unknown_semantic_category(self):
        """mask_reveal with unknown category should fall back to circle."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = mask_reveal_transition(
            a, b, semantic_category="unknown_category", duration=0.5,
        )
        _assert_valid_clip(result)


# ── Test 10: shape_morph_transition ────────────────────────────────────────────


class TestShapeMorph:
    """shape_morph_transition regression tests."""

    @pytest.mark.gpu
    def test_fast_quality(self):
        """shape_morph with quality='fast' should use rembg and return a valid clip."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = shape_morph_transition(a, b, quality="fast", duration=0.6)
        _assert_valid_clip(result)

    @pytest.mark.gpu
    def test_high_quality(self):
        """shape_morph with quality='high' should attempt SAM vit_b."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = shape_morph_transition(a, b, quality="high", duration=0.6)
        _assert_valid_clip(result)

    @pytest.mark.gpu
    def test_ultra_quality(self):
        """shape_morph with quality='ultra' should attempt SAM vit_h."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = shape_morph_transition(a, b, quality="ultra", duration=0.6)
        _assert_valid_clip(result)

    def test_graceful_degradation_on_segmentation_failure(self):
        """shape_morph should degrade to sweep_mask when segmentation fails."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        with patch("clip_editor._segment_frame", return_value=None):
            result = shape_morph_transition(a, b, quality="fast", duration=0.6)
        _assert_valid_clip(result)


# ── Test 11: transition_selector dispatch logic ────────────────────────────────


class TestTransitionSelector:
    """transition_selector dispatch and merge logic."""

    def test_dispatch_map_has_all_effects(self):
        """TRANSITION_DISPATCH should contain all 5 effects."""
        expected = {"match_cut", "glitch", "sweep_mask", "mask_reveal", "shape_morph"}
        assert expected.issubset(TRANSITION_DISPATCH.keys()), (
            f"Missing transitions: {expected - set(TRANSITION_DISPATCH.keys())}"
        )

    def test_select_and_apply_hard_cut_fallback(self, tmp_output_dir):
        """select_and_apply_transition should fall back to hard cut on error."""
        a = make_test_clip(color=(255, 0, 0), duration=1.0)
        b = make_test_clip(color=(0, 255, 0), duration=1.0)
        path_a = tmp_output_dir / "clip_a.mp4"
        path_b = tmp_output_dir / "clip_b.mp4"
        a.write_videofile(str(path_a), codec="libx264", fps=24, logger=None)
        b.write_videofile(str(path_b), codec="libx264", fps=24, logger=None)

        result = select_and_apply_transition(
            path_a, path_b, tmp_output_dir,
            strategy="auto", force_transition="match_cut",
        )
        assert result is not None, "Expected a valid output path"
        assert Path(result).exists(), "Output file should exist"

    def test_merge_with_transitions_single_clip(self, tmp_output_dir):
        """merge_with_transitions with a single clip should return it as-is."""
        a = make_test_clip(color=(255, 0, 0), duration=1.0)
        path_a = tmp_output_dir / "single.mp4"
        a.write_videofile(str(path_a), codec="libx264", fps=24, logger=None)

        result = merge_with_transitions([path_a], tmp_output_dir)
        assert result == path_a, "Single clip should be returned unchanged"

    def test_merge_with_transitions_empty_list(self, tmp_output_dir):
        """merge_with_transitions with empty list should return None."""
        result = merge_with_transitions([], tmp_output_dir)
        assert result is None, "Empty list should return None"


# ── Test 12: graceful degradation ──────────────────────────────────────────────


class TestGracefulDegradation:
    """Graceful degradation on invalid parameters."""

    def test_unknown_transition_type(self, tmp_output_dir):
        """select_and_apply_transition with unknown type should fall back to auto."""
        a = make_test_clip(color=(255, 0, 0), duration=1.0)
        b = make_test_clip(color=(0, 255, 0), duration=1.0)
        path_a = tmp_output_dir / "clip_a.mp4"
        path_b = tmp_output_dir / "clip_b.mp4"
        a.write_videofile(str(path_a), codec="libx264", fps=24, logger=None)
        b.write_videofile(str(path_b), codec="libx264", fps=24, logger=None)

        result = select_and_apply_transition(
            path_a, path_b, tmp_output_dir,
            strategy="nonexistent_strategy",
        )
        assert result is not None, "Should fall back to hard cut"

    def test_zero_duration_transition(self):
        """match_cut with duration=0 should not crash."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = match_cut_transition(a, b, duration=0.0)
        _assert_valid_clip(result)

    def test_negative_duration_transition(self):
        """match_cut with negative duration should not crash."""
        a = make_test_clip(color=(255, 0, 0))
        b = make_test_clip(color=(0, 255, 0))
        result = match_cut_transition(a, b, duration=-0.1)
        _assert_valid_clip(result)


# ── Test 13: IconScout no-key ──────────────────────────────────────────────────


class TestIconScoutNoKey:
    """IconScout helper graceful handling when API key is missing."""

    def test_fetch_no_api_key(self):
        """fetch_iconscout_asset should return None gracefully when no key is set."""
        with patch.dict("os.environ", {}, clear=True):
            result = fetch_iconscout_asset("test_keyword")
        assert result is None, "Should return None when ICONSCOUT_API_KEY is missing"
