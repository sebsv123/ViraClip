"""
Unit Tests — Phase 4.1: Multi-platform Export
==============================================
Tests for export profiles, bitrate variants, and SRT export.
"""

import pytest
from pathlib import Path
from video_processing.export_profiles import (
    ExportService, Platform, BitrateVariant, ExportProfile
)


class TestExportProfiles:
    """Test export profile configuration."""
    
    def test_tiktok_profile_has_variants(self):
        """TikTok profile should have 3 bitrate variants."""
        service = ExportService()
        profile = service.get_profile(Platform.TIKTOK)
        
        assert profile.bitrate_variants is not None
        assert len(profile.bitrate_variants) == 3
        
        # Check variant names
        variant_names = [v.suffix for v in profile.bitrate_variants]
        assert "hq" in variant_names
        assert "mq" in variant_names
        assert "lq" in variant_names
    
    def test_reels_profile_has_variants(self):
        """Instagram Reels profile should have bitrate variants."""
        service = ExportService()
        profile = service.get_profile(Platform.REELS)
        
        assert profile.bitrate_variants is not None
        assert len(profile.bitrate_variants) == 3
    
    def test_shorts_profile_has_variants(self):
        """YouTube Shorts profile should have bitrate variants."""
        service = ExportService()
        profile = service.get_profile(Platform.SHORTS)
        
        assert profile.bitrate_variants is not None
        assert len(profile.bitrate_variants) == 3
    
    def test_variant_bitrate_ordering(self):
        """Variants should be ordered: high > medium > low."""
        service = ExportService()
        profile = service.get_profile(Platform.TIKTOK)
        
        variants = sorted(profile.bitrate_variants, key=lambda v: v.suffix)
        
        hq = next(v for v in variants if v.suffix == "hq")
        mq = next(v for v in variants if v.suffix == "mq")
        lq = next(v for v in variants if v.suffix == "lq")
        
        assert hq.video_bitrate > mq.video_bitrate
        assert mq.video_bitrate > lq.video_bitrate
    
    def test_all_platforms_have_profiles(self):
        """All platforms should have valid profiles."""
        service = ExportService()
        
        for platform in [Platform.TIKTOK, Platform.REELS, Platform.SHORTS, Platform.UNIVERSAL]:
            profile = service.get_profile(platform)
            assert profile is not None
            assert profile.width > 0
            assert profile.height > 0
            assert profile.fps > 0


class TestExportService:
    """Test ExportService functionality."""
    
    def test_service_initialization(self):
        """Service should initialize without errors."""
        service = ExportService()
        assert service is not None
    
    def test_get_export_specs(self):
        """Should return complete export specs."""
        service = ExportService()
        specs = service.get_export_specs(Platform.TIKTOK)
        
        assert "platform" in specs
        assert "has_variants" in specs
        assert "variants" in specs
        assert specs["platform"] == "tiktok"
        assert specs["has_variants"] is True
        assert len(specs["variants"]) == 3
    
    def test_get_recommended_platform(self):
        """Should recommend platform based on aspect ratio."""
        service = ExportService()
        
        # Vertical video (9:16) -> TikTok
        platform = service.get_recommended_platform(aspect_ratio=9/16)
        assert platform == Platform.TIKTOK
        
        # Square video (1:1) -> Instagram Reels
        platform = service.get_recommended_platform(aspect_ratio=1.0)
        assert platform == Platform.REELS
        
        # Horizontal video (16:9) -> Universal
        platform = service.get_recommended_platform(aspect_ratio=16/9)
        assert platform == Platform.UNIVERSAL
    
    def test_srt_export_method_exists(self):
        """SRT export method should exist."""
        service = ExportService()
        assert hasattr(service, 'export_srt_captions')
    
    def test_export_with_variants_method_exists(self):
        """Export with variants method should exist."""
        service = ExportService()
        assert hasattr(service, 'export_with_variants')


class TestBitrateVariant:
    """Test BitrateVariant dataclass."""
    
    def test_variant_creation(self):
        """Should create variant with correct attributes."""
        variant = BitrateVariant(
            suffix="hq",
            video_bitrate="5000k",
            audio_bitrate="192k",
            crf=18
        )
        
        assert variant.suffix == "hq"
        assert variant.video_bitrate == "5000k"
        assert variant.audio_bitrate == "192k"
        assert variant.crf == 18
    
    def test_variant_defaults(self):
        """CRF should have default value."""
        variant = BitrateVariant(
            suffix="mq",
            video_bitrate="3000k",
            audio_bitrate="128k"
        )
        
        assert variant.crf is not None


class TestFFmpegCommands:
    """Test FFmpeg command building."""
    
    def test_build_ffmpeg_command(self):
        """Should build valid FFmpeg command."""
        service = ExportService()
        
        cmd = service.build_ffmpeg_command(
            input_file="test.mp4",
            output_file="output.mp4",
            profile=service.get_profile(Platform.TIKTOK)
        )
        
        assert "ffmpeg" in cmd
        assert "-i" in cmd
        assert "test.mp4" in cmd
        assert "output.mp4" in cmd
        assert "-c:v" in cmd  # Video codec
        assert "-c:a" in cmd  # Audio codec
    
    def test_enforce_clip_duration(self):
        """Should enforce platform duration limits."""
        service = ExportService()
        profile = service.get_profile(Platform.TIKTOK)
        
        # Test video within limits
        duration = 30.0
        enforced = service.enforce_clip_duration(duration, profile)
        assert enforced == duration
        
        # Test video too long
        duration = 200.0
        enforced = service.enforce_clip_duration(duration, profile)
        assert enforced <= profile.max_duration


@pytest.mark.integration
class TestExportIntegration:
    """Integration tests for export pipeline."""
    
    @pytest.mark.skip(reason="Requires actual video file")
    def test_export_all_variants(self):
        """Should export video in all variants."""
        service = ExportService()
        
        input_file = Path("test_data/sample_video.mp4")
        output_dir = Path("test_output")
        
        if not input_file.exists():
            pytest.skip("Test video not available")
        
        variants = service.export_with_variants(
            input_file=str(input_file),
            output_dir=str(output_dir),
            platform=Platform.TIKTOK
        )
        
        assert len(variants) == 3
        for variant_path in variants:
            assert Path(variant_path).exists()
    
    @pytest.mark.skip(reason="Requires actual subtitle file")
    def test_srt_export(self):
        """Should export SRT captions."""
        service = ExportService()
        
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Hello world"},
            {"start": 2.0, "end": 4.0, "text": "This is a test"}
        ]
        
        output_path = service.export_srt_captions(
            segments=segments,
            output_file="test_output/captions.srt"
        )
        
        assert Path(output_path).exists()
        
        # Verify SRT format
        with open(output_path, 'r') as f:
            content = f.read()
            assert "00:00:00,000 --> 00:00:02,000" in content
            assert "Hello world" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
