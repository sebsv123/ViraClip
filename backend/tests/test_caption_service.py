"""
Tests for the redesigned caption/subtitle style system.

Covers:
  - CaptionStyleConfig dataclass defaults
  - ASS colour helpers (_ass_colour, _hex_to_ass, _hex_to_ass_bg)
  - Platform-aware margin calculation (_margin_v, _dynamic_margin_v)
  - Adaptive font sizing (_adaptive_font_size)
  - ASS script generation (build_ass_script) with style presets
  - Drawtext filter generation (build_drawtext_filter)
  - Word segmentation (segment_words_into_lines)
  - CaptionService integration (style_for_template, build_config_from_style)
  - Legacy _subtitles.py preset values (alignment, margin_v, back colour)
"""

from __future__ import annotations

import pytest
from pathlib import Path
from typing import Any, Dict, List

from src.domains.captions.caption_service import (
    CaptionStyleConfig,
    _ass_colour,
    _hex_to_ass,
    _hex_to_ass_bg,
    _margin_v,
    _dynamic_margin_v,
    _adaptive_font_size,
    _STYLE_DEFS,
    _PLATFORM_MARGIN_V,
    _CTA_EXTRA_MARGIN,
    build_ass_script,
    build_drawtext_filter,
    segment_words_into_lines,
    CaptionService,
    CaptionLine,
    WordTimestamp,
)
from src.domains.video._subtitles import CAPTION_STYLES as LEGACY_STYLES


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_words() -> List[Dict[str, Any]]:
    return [
        {"text": "Hello", "start": 0.0, "end": 0.3},
        {"text": "world", "start": 0.35, "end": 0.65},
        {"text": "this", "start": 0.7, "end": 0.9},
        {"text": "is", "start": 0.95, "end": 1.1},
        {"text": "a", "start": 1.15, "end": 1.25},
        {"text": "test", "start": 1.3, "end": 1.6},
    ]


# ── CaptionStyleConfig tests ──────────────────────────────────────────────────

class TestCaptionStyleConfig:
    def test_default_values(self):
        """Default config should use TikTok-safe bottom-centre alignment and 180px margin."""
        cfg = CaptionStyleConfig()
        assert cfg.font_family == "TikTokSans-Bold"
        assert cfg.font_size == 72
        assert cfg.font_color == "#FFFFFF"
        assert cfg.outline_width == 3
        assert cfg.outline_color == "#000000"
        assert cfg.bg_color == "#000000"
        assert cfg.bg_opacity == 0.5
        assert cfg.alignment == 2  # bottom-centre
        assert cfg.margin_v == 180  # safe zone

    def test_custom_values(self):
        """Custom config should override defaults."""
        cfg = CaptionStyleConfig(
            font_family="Montserrat-Bold",
            font_size=80,
            font_color="#FFFF00",
            outline_width=5,
            outline_color="#FF0000",
            bg_color="#333333",
            bg_opacity=0.7,
            alignment=8,
            margin_v=200,
        )
        assert cfg.font_family == "Montserrat-Bold"
        assert cfg.font_size == 80
        assert cfg.font_color == "#FFFF00"
        assert cfg.outline_width == 5
        assert cfg.outline_color == "#FF0000"
        assert cfg.bg_color == "#333333"
        assert cfg.bg_opacity == 0.7
        assert cfg.alignment == 8
        assert cfg.margin_v == 200


# ── ASS colour helper tests ───────────────────────────────────────────────────

class TestAssColourHelpers:
    def test_ass_colour_white(self):
        """White should be &H00BBGGRR with B=G=R=255."""
        assert _ass_colour(255, 255, 255) == "&H00FFFFFF"

    def test_ass_colour_black(self):
        """Black should be &H00000000."""
        assert _ass_colour(0, 0, 0) == "&H00000000"

    def test_ass_colour_red(self):
        """Red should be &H000000FF (little-endian: B=0, G=0, R=255)."""
        assert _ass_colour(255, 0, 0) == "&H000000FF"

    def test_ass_colour_green(self):
        """Green should be &H0000FF00 (little-endian: B=0, G=255, R=0)."""
        assert _ass_colour(0, 255, 0) == "&H0000FF00"

    def test_ass_colour_blue(self):
        """Blue should be &H00FF0000 (little-endian: B=255, G=0, R=0)."""
        assert _ass_colour(0, 0, 255) == "&H00FF0000"

    def test_ass_colour_with_alpha(self):
        """Alpha should appear in the high byte: &HAABBGGRR."""
        assert _ass_colour(255, 255, 255, 128) == "&H80FFFFFF"

    def test_hex_to_ass_white(self):
        """Hex #FFFFFF should convert to &H00FFFFFF."""
        assert _hex_to_ass("#FFFFFF") == "&H00FFFFFF"

    def test_hex_to_ass_black(self):
        """Hex #000000 should convert to &H00000000."""
        assert _hex_to_ass("#000000") == "&H00000000"

    def test_hex_to_ass_short_hex(self):
        """Short hex #FFF should expand to #FFFFFF."""
        assert _hex_to_ass("#FFF") == "&H00FFFFFF"

    def test_hex_to_ass_bg_opaque(self):
        """Opacity 1.0 should give alpha 0x00 (fully opaque)."""
        result = _hex_to_ass_bg("#000000", 1.0)
        assert result == "&H00000000"

    def test_hex_to_ass_bg_transparent(self):
        """Opacity 0.0 should give alpha 0xFF (fully transparent)."""
        result = _hex_to_ass_bg("#000000", 0.0)
        assert result == "&HFF000000"

    def test_hex_to_ass_bg_half(self):
        """Opacity 0.5 should give alpha ~0x7F."""
        result = _hex_to_ass_bg("#000000", 0.5)
        assert result == "&H7F000000"


# ── Platform margin tests ─────────────────────────────────────────────────────

class TestPlatformMargins:
    def test_all_platforms_have_180_minimum(self):
        """All platforms should have margin_v >= 180."""
        for platform, margin in _PLATFORM_MARGIN_V.items():
            assert margin >= 180, f"{platform} has margin_v={margin}, expected >= 180"

    def test_margin_v_known_platform(self):
        """Known platform should return its configured margin."""
        assert _margin_v("tiktok") == 180

    def test_margin_v_unknown_platform(self):
        """Unknown platform should fall back to default (180)."""
        assert _margin_v("unknown_platform") == 180

    def test_dynamic_margin_v_no_cta(self):
        """Without CTA, margin should be the base value."""
        assert _dynamic_margin_v("tiktok", cta_present=False) == 180

    def test_dynamic_margin_v_with_cta(self):
        """With CTA, margin should be base + _CTA_EXTRA_MARGIN."""
        expected = 180 + _CTA_EXTRA_MARGIN
        assert _dynamic_margin_v("tiktok", cta_present=True) == expected

    def test_dynamic_margin_v_unknown_platform_with_cta(self):
        """Unknown platform with CTA should still add extra margin."""
        expected = 180 + _CTA_EXTRA_MARGIN
        assert _dynamic_margin_v("unknown", cta_present=True) == expected


# ── Adaptive font size tests ──────────────────────────────────────────────────

class TestAdaptiveFontSize:
    def test_short_phrase(self):
        """<=3 words should use base size."""
        assert _adaptive_font_size(72, 1) == 72
        assert _adaptive_font_size(72, 2) == 72
        assert _adaptive_font_size(72, 3) == 72

    def test_medium_phrase(self):
        """4-5 words should reduce by 10%."""
        assert _adaptive_font_size(72, 4) == 64  # 72 * 0.9 = 64.8 → int = 64
        assert _adaptive_font_size(72, 5) == 64

    def test_long_phrase(self):
        """6-7 words should reduce by 20%."""
        assert _adaptive_font_size(72, 6) == 57  # 72 * 0.8 = 57.6 → int = 57
        assert _adaptive_font_size(72, 7) == 57

    def test_very_long_phrase(self):
        """8+ words should reduce by 30%."""
        assert _adaptive_font_size(72, 8) == 50  # 72 * 0.7 = 50.4 → int = 50
        assert _adaptive_font_size(72, 10) == 50

    def test_minimum_floor(self):
        """Font size should never go below 32."""
        assert _adaptive_font_size(40, 10) == 32  # 40 * 0.7 = 28 → max(32, 28) = 32


# ── ASS script generation tests ───────────────────────────────────────────────

class TestBuildAssScript:
    def test_header_contains_playres(self):
        """ASS header should contain PlayResX and PlayResY."""
        lines = [CaptionLine(
            words=[WordTimestamp("HELLO", 0.0, 0.5)],
            line_start=0.0, line_end=0.5,
        )]
        script = build_ass_script(lines, style="default")
        assert "PlayResX: 1080" in script
        assert "PlayResY: 1920" in script

    def test_style_name_is_viraclip_captions(self):
        """All presets should use 'VIRACLIP-CAPTIONS' as the style name."""
        lines = [CaptionLine(
            words=[WordTimestamp("HELLO", 0.0, 0.5)],
            line_start=0.0, line_end=0.5,
        )]
        for style in ["default", "brand_primary", "high_contrast", "tiktok", "karaoke", "minimal", "neon"]:
            script = build_ass_script(lines, style=style)
            assert "VIRACLIP-CAPTIONS" in script, f"Style '{style}' missing VIRACLIP-CAPTIONS"

    def test_alignment_is_2(self):
        """All presets should use Alignment=2 (bottom-centre)."""
        lines = [CaptionLine(
            words=[WordTimestamp("HELLO", 0.0, 0.5)],
            line_start=0.0, line_end=0.5,
        )]
        for style in _STYLE_DEFS:
            script = build_ass_script(lines, style=style)
            # The style definition ends with ",2,10,10,MARGINV,1" → after substitution ",2,10,10,180,1"
            # Alignment is the 4th-from-last field in the style definition
            assert ",2,10,10," in script, f"Style '{style}' does not use Alignment=2"

    def test_margin_v_substituted(self):
        """MARGINV placeholder should be replaced with actual margin value."""
        lines = [CaptionLine(
            words=[WordTimestamp("HELLO", 0.0, 0.5)],
            line_start=0.0, line_end=0.5,
        )]
        script = build_ass_script(lines, style="default", platform="tiktok")
        assert "MARGINV" not in script, "MARGINV placeholder was not substituted"
        assert ",180,1" in script or "180,1" in script

    def test_cta_present_increases_margin(self):
        """When cta_present=True, margin should be higher."""
        lines = [CaptionLine(
            words=[WordTimestamp("HELLO", 0.0, 0.5)],
            line_start=0.0, line_end=0.5,
        )]
        script_no_cta = build_ass_script(lines, style="default", platform="tiktok", cta_present=False)
        script_cta = build_ass_script(lines, style="default", platform="tiktok", cta_present=True)
        # Extract margin values
        import re
        margin_no_cta = int(re.search(r",(\d+),1\n", script_no_cta).group(1))
        margin_cta = int(re.search(r",(\d+),1\n", script_cta).group(1))
        assert margin_cta > margin_no_cta
        assert margin_cta - margin_no_cta == _CTA_EXTRA_MARGIN

    def test_karaoke_tags_present(self):
        """Default/tiktok/karaoke styles should use \\k tags."""
        lines = [CaptionLine(
            words=[WordTimestamp("HELLO", 0.0, 0.3), WordTimestamp("WORLD", 0.35, 0.65)],
            line_start=0.0, line_end=0.65,
        )]
        script = build_ass_script(lines, style="default")
        assert "\\k" in script

    def test_uppercase(self):
        """Text should be uppercased by default."""
        lines = [CaptionLine(
            words=[WordTimestamp("Hello", 0.0, 0.5)],
            line_start=0.0, line_end=0.5,
        )]
        script = build_ass_script(lines, style="default")
        assert "HELLO" in script
        assert "Hello" not in script

    def test_dialogue_events_present(self):
        """Script should contain Dialogue events."""
        lines = [CaptionLine(
            words=[WordTimestamp("HELLO", 0.0, 0.5)],
            line_start=0.0, line_end=0.5,
        )]
        script = build_ass_script(lines, style="default")
        assert "Dialogue:" in script

    def test_highlight_style_per_word(self):
        """Highlight style should produce one event per word."""
        lines = [CaptionLine(
            words=[
                WordTimestamp("HELLO", 0.0, 0.3),
                WordTimestamp("WORLD", 0.35, 0.65),
            ],
            line_start=0.0, line_end=0.65,
        )]
        script = build_ass_script(lines, style="highlight")
        # Should have 2 dialogue events (one per word)
        assert script.count("Dialogue:") == 2


# ── Drawtext filter tests ─────────────────────────────────────────────────────

class TestBuildDrawtextFilter:
    def test_empty_lines_returns_empty(self):
        """Empty lines should return empty string."""
        assert build_drawtext_filter([]) == ""

    def test_contains_box_parameters(self):
        """Drawtext filter should include box=1 and boxcolor."""
        lines = [CaptionLine(
            words=[WordTimestamp("HELLO", 0.0, 0.5)],
            line_start=0.0, line_end=0.5,
        )]
        result = build_drawtext_filter(lines)
        assert "box=1" in result
        assert "boxcolor=black@0.5" in result

    def test_contains_positioning(self):
        """Drawtext filter should centre text horizontally and position from bottom."""
        lines = [CaptionLine(
            words=[WordTimestamp("HELLO", 0.0, 0.5)],
            line_start=0.0, line_end=0.5,
        )]
        result = build_drawtext_filter(lines)
        assert "x=(w-text_w)/2" in result
        assert "y=h-" in result

    def test_custom_margin(self):
        """Custom margin_v should be reflected in y position."""
        lines = [CaptionLine(
            words=[WordTimestamp("HELLO", 0.0, 0.5)],
            line_start=0.0, line_end=0.5,
        )]
        result = build_drawtext_filter(lines, margin_v=200)
        assert "y=h-200" in result

    def test_adaptive_font_size_applied(self):
        """Long phrases should get reduced font size in drawtext."""
        lines = [CaptionLine(
            words=[WordTimestamp(f"WORD{i}", 0.0, 0.3) for i in range(6)],
            line_start=0.0, line_end=1.8,
        )]
        result = build_drawtext_filter(lines, font_size=72)
        # 6 words → 20% reduction → 57
        assert "fontsize=57" in result


# ── Word segmentation tests ───────────────────────────────────────────────────

class TestSegmentWordsIntoLines:
    def test_empty_words(self):
        """Empty word list should return empty lines."""
        assert segment_words_into_lines([]) == []

    def test_single_word(self):
        """Single word should produce one line."""
        words = [{"text": "Hello", "start": 0.0, "end": 0.5}]
        lines = segment_words_into_lines(words)
        assert len(lines) == 1
        assert lines[0].full_text == "Hello"

    def test_multiple_words_single_line(self):
        """Multiple close words should group into one line."""
        words = [
            {"text": "Hello", "start": 0.0, "end": 0.3},
            {"text": "world", "start": 0.35, "end": 0.65},
        ]
        lines = segment_words_into_lines(words)
        assert len(lines) == 1
        assert lines[0].full_text == "Hello world"

    def test_gap_triggers_split(self):
        """Large gap between words should trigger a line break."""
        words = [
            {"text": "Hello", "start": 0.0, "end": 0.3},
            {"text": "world", "start": 1.5, "end": 1.8},  # gap > 0.8
        ]
        lines = segment_words_into_lines(words, gap_threshold=0.8)
        assert len(lines) == 2

    def test_max_words_per_line(self):
        """Exceeding max_words_per_line should trigger a split."""
        words = [
            {"text": "A", "start": 0.0, "end": 0.2},
            {"text": "B", "start": 0.25, "end": 0.45},
            {"text": "C", "start": 0.5, "end": 0.7},
            {"text": "D", "start": 0.75, "end": 0.95},
        ]
        lines = segment_words_into_lines(words, max_words_per_line=2)
        assert len(lines) == 2
        assert lines[0].full_text == "A B"
        assert lines[1].full_text == "C D"

    def test_special_chars_removed(self):
        """Non-alphanumeric characters (except apostrophes/hyphens) should be stripped."""
        words = [{"text": "Hello!!!", "start": 0.0, "end": 0.5}]
        lines = segment_words_into_lines(words)
        assert lines[0].full_text == "Hello"

    def test_empty_word_skipped(self):
        """Words with only whitespace should be skipped."""
        words = [
            {"text": "Hello", "start": 0.0, "end": 0.3},
            {"text": "   ", "start": 0.35, "end": 0.5},
            {"text": "world", "start": 0.55, "end": 0.85},
        ]
        lines = segment_words_into_lines(words)
        assert len(lines) == 1
        assert lines[0].full_text == "Hello world"


# ── CaptionService integration tests ──────────────────────────────────────────

class TestCaptionService:
    def test_style_for_template_maps_correctly(self):
        """Template names should map to appropriate caption styles."""
        assert CaptionService.style_for_template("tiktok_viral") == "tiktok"
        assert CaptionService.style_for_template("tutorial") == "default"
        assert CaptionService.style_for_template("interview") == "default"
        assert CaptionService.style_for_template("education") == "default"
        assert CaptionService.style_for_template("unknown") == "tiktok"

    def test_get_styles_includes_new_presets(self):
        """get_styles() should include the new presets."""
        styles = CaptionService.get_styles(CaptionService)
        assert "default" in styles
        assert "brand_primary" in styles
        assert "high_contrast" in styles

    def test_build_config_from_style_default(self):
        """build_config_from_style('default') should return TikTok-safe config."""
        cfg = CaptionService().build_config_from_style("default")
        assert isinstance(cfg, CaptionStyleConfig)
        assert cfg.font_color == "#FFFFFF"
        assert cfg.alignment == 2
        assert cfg.margin_v == 180
        assert cfg.bg_opacity == 0.5

    def test_build_config_from_style_brand_primary(self):
        """build_config_from_style('brand_primary') should return brand blue config."""
        cfg = CaptionService().build_config_from_style("brand_primary")
        assert cfg.font_color == "#0078FF"
        assert cfg.outline_color == "#003CB4"
        assert cfg.alignment == 2
        assert cfg.margin_v == 180

    def test_build_config_from_style_high_contrast(self):
        """build_config_from_style('high_contrast') should return yellow+thick outline."""
        cfg = CaptionService().build_config_from_style("high_contrast")
        assert cfg.font_color == "#FFFF00"
        assert cfg.outline_width == 5
        assert cfg.font_size == 80
        assert cfg.alignment == 2
        assert cfg.margin_v == 180

    def test_build_config_from_style_unknown_falls_back(self):
        """Unknown style should fall back to default config."""
        cfg = CaptionService().build_config_from_style("nonexistent")
        assert cfg.font_color == "#FFFFFF"
        assert cfg.alignment == 2
        assert cfg.margin_v == 180

    def test_segment_words_returns_serialisable(self):
        """segment_words() should return JSON-serialisable dicts."""
        words = [
            {"text": "Hello", "start": 0.0, "end": 0.3},
            {"text": "world", "start": 0.35, "end": 0.65},
        ]
        result = CaptionService().segment_words(words)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["text"] == "Hello world"
        assert "words" in result[0]
        assert "start" in result[0]
        assert "end" in result[0]
        # Verify JSON-serialisable
        import json
        json.dumps(result)  # should not raise

    def test_generate_ass_returns_string(self):
        """generate_ass() should return a valid ASS string."""
        words = [
            {"text": "Hello", "start": 0.0, "end": 0.3},
            {"text": "world", "start": 0.35, "end": 0.65},
        ]
        ass = CaptionService().generate_ass(words, style="default")
        assert isinstance(ass, str)
        assert ass.startswith("[Script Info]")
        assert "VIRACLIP-CAPTIONS" in ass
        assert "Dialogue:" in ass


# ── Legacy _subtitles.py compatibility tests ──────────────────────────────────

class TestLegacySubtitlesCompatibility:
    """Ensure the legacy _subtitles.py fallback also uses safe margins."""

    def test_hormozi_alignment_is_2(self):
        """Hormozi preset should use Alignment=2 (bottom-centre)."""
        assert LEGACY_STYLES["hormozi"]["alignment"] == 2

    def test_hormozi_margin_v_is_180(self):
        """Hormozi preset should use margin_v=180."""
        assert LEGACY_STYLES["hormozi"]["margin_v"] == 180

    def test_hormozi_has_back_box(self):
        """Hormozi preset should have a semi-transparent back box."""
        back = LEGACY_STYLES["hormozi"]["back"]
        assert back != "&H00000000"  # not fully transparent
        assert back.startswith("&H")  # valid ASS colour

    def test_mrbeast_alignment_is_2(self):
        """MrBeast preset should use Alignment=2 (bottom-centre)."""
        assert LEGACY_STYLES["mrbeast"]["alignment"] == 2

    def test_mrbeast_margin_v_is_180(self):
        """MrBeast preset should use margin_v=180."""
        assert LEGACY_STYLES["mrbeast"]["margin_v"] == 180

    def test_mrbeast_has_back_box(self):
        """MrBeast preset should now have a semi-transparent back box (was transparent)."""
        back = LEGACY_STYLES["mrbeast"]["back"]
        assert back != "&H00000000"  # not fully transparent
        assert back.startswith("&H")  # valid ASS colour


# ── Render context preservation test ──────────────────────────────────────────

class TestRenderContextCtaPreserved:
    """Ensure cta_present is preserved in render context."""

    def test_cta_present_in_preserved_keys(self):
        """cta_present should be in _PRESERVED_SEGMENT_KEYS."""
        from src.domains.autopilot.render_context import _PRESERVED_SEGMENT_KEYS
        assert "cta_present" in _PRESERVED_SEGMENT_KEYS

    def test_cta_present_survives_filter(self):
        """cta_present should survive the segment filter."""
        from src.domains.autopilot.render_context import _filter_segment
        segment = {"cta_present": True, "text": "hello", "_internal": "drop"}
        filtered = _filter_segment(segment)
        assert filtered.get("cta_present") is True
        assert "_internal" not in filtered
