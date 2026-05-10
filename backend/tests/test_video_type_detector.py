"""Tests for video type auto-detection."""
from src.core.video_type_detector import (
    VideoType, CropProfile,
    _classify_type, CROP_PROFILE_FOR_TYPE, CROP_FILTERS,
)


def test_screen_content_detected_no_skin_low_motion():
    """No skin, low motion → screen content."""
    vtype = _classify_type(motion=0.10, skin_zones=0, speech=0.6)
    assert vtype == VideoType.SCREEN_CONTENT


def test_single_speaker_detected():
    """1 skin zone, speech → single speaker."""
    vtype = _classify_type(motion=0.20, skin_zones=1, speech=0.8)
    assert vtype == VideoType.SINGLE_SPEAKER


def test_multi_speaker_detected():
    """2+ skin zones, speech → multi speaker."""
    vtype = _classify_type(motion=0.25, skin_zones=2, speech=0.7)
    assert vtype == VideoType.MULTI_SPEAKER


def test_live_event_high_motion():
    """High motion → live event."""
    vtype = _classify_type(motion=0.80, skin_zones=1, speech=0.5)
    assert vtype == VideoType.LIVE_EVENT


def test_crop_filter_for_each_type():
    """Each type has a non-empty crop filter."""
    for vtype, crop_profile in CROP_PROFILE_FOR_TYPE.items():
        crop_filter = CROP_FILTERS[crop_profile]
        assert isinstance(crop_filter, str)
        assert len(crop_filter) > 0


def test_detect_video_type_never_raises():
    """Detection never raises — returns UNKNOWN + SAFE_WIDE."""
    from src.core.video_type_detector import detect_video_type
    import asyncio
    result = asyncio.run(detect_video_type("/nonexistent.mp4", 60.0))
    assert result["video_type"] == VideoType.UNKNOWN
    assert result["crop_profile"] == CropProfile.SAFE_WIDE
