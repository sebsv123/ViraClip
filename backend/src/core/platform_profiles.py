"""
Platform export profiles with optimal encoding parameters.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformProfile:
    name: str
    max_size_mb: float
    max_duration_s: int
    width: int
    height: int
    fps: int
    video_bitrate: str
    audio_bitrate: str
    audio_rate: int
    container: str
    notes: str


PLATFORM_PROFILES = {
    "tiktok": PlatformProfile(
        name="TikTok", max_size_mb=287.0, max_duration_s=600,
        width=1080, height=1920, fps=30,
        video_bitrate="8000k", audio_bitrate="128k", audio_rate=44100,
        container="mp4",
        notes="H.264 High Profile L4.0. AAC-LC. No B-frames recomendado.",
    ),
    "reels": PlatformProfile(
        name="Instagram Reels", max_size_mb=100.0, max_duration_s=90,
        width=1080, height=1920, fps=30,
        video_bitrate="5000k", audio_bitrate="128k", audio_rate=44100,
        container="mp4",
        notes="H.264. AAC. Reels < 90s. Stories < 15s.",
    ),
    "shorts": PlatformProfile(
        name="YouTube Shorts", max_size_mb=256.0, max_duration_s=60,
        width=1080, height=1920, fps=60,
        video_bitrate="10000k", audio_bitrate="192k", audio_rate=48000,
        container="mp4",
        notes="H.264 o VP9. AAC-LC. 48kHz recomendado.",
    ),
    "twitter": PlatformProfile(
        name="Twitter/X", max_size_mb=512.0, max_duration_s=140,
        width=1280, height=720, fps=40,
        video_bitrate="6000k", audio_bitrate="128k", audio_rate=44100,
        container="mp4",
        notes="H.264 Baseline/Main. AAC. Landscape recomendado.",
    ),
    "linkedin": PlatformProfile(
        name="LinkedIn", max_size_mb=200.0, max_duration_s=600,
        width=1080, height=1080, fps=30,
        video_bitrate="5000k", audio_bitrate="128k", audio_rate=44100,
        container="mp4",
        notes="H.264. AAC. 1:1 square funciona mejor.",
    ),
}


def get_profile(platform: str) -> PlatformProfile:
    return PLATFORM_PROFILES.get(platform.lower(), PLATFORM_PROFILES["tiktok"])
