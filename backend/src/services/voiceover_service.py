"""
AI Voiceover / Narration — OpenAI TTS + ElevenLabs integration.

Generates spoken narration from text and optionally mixes it into a video
at a configurable volume. Falls back gracefully when API keys are absent.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)

# Supported TTS voices
OPENAI_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
ELEVENLABS_DEFAULT_VOICE = "Rachel"

_VOICE_MODELS = {
    "openai": "tts-1-hd",       # use tts-1 for faster/cheaper
    "elevenlabs": "eleven_multilingual_v2",
}

# edge-tts default voices per language prefix
EDGE_TTS_VOICES = {
    "en": "en-US-GuyNeural",
    "es": "es-ES-AlvaroNeural",
    "fr": "fr-FR-HenriNeural",
    "de": "de-DE-ConradNeural",
    "pt": "pt-BR-AntonioNeural",
    "it": "it-IT-DiegoNeural",
    "ja": "ja-JP-KeitaNeural",
    "ko": "ko-KR-InJoonNeural",
    "zh": "zh-CN-YunxiNeural",
}


@dataclass
class VoiceoverResult:
    audio_path: Optional[str]    # path to generated .mp3 file
    mixed_video_path: Optional[str]  # path to video with VO mixed in
    provider: str
    voice: str
    duration_seconds: float = 0.0
    error: Optional[str] = None
    characters_used: int = 0


async def _tts_edge(
    text: str,
    output_path: str,
    voice: str = "en-US-GuyNeural",
) -> Optional[str]:
    """Generate speech via Microsoft edge-tts (free, no API key required).
    Returns output_path on success, raises on failure.
    """
    try:
        import edge_tts
    except ImportError:
        raise RuntimeError("edge-tts not installed — run: pip install edge-tts")

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)
    if not Path(output_path).exists() or Path(output_path).stat().st_size < 500:
        raise RuntimeError("edge-tts produced no audio output")
    logger.debug("[voiceover] edge-tts saved: %s", output_path)
    return output_path


def _pick_edge_voice(voice: str) -> str:
    """Map a generic voice name or language code to an edge-tts voice name."""
    if voice in OPENAI_VOICES or not voice:
        return EDGE_TTS_VOICES.get("en", "en-US-GuyNeural")
    # If caller already passes a full edge-tts voice name (e.g. "es-ES-AlvaroNeural")
    if "-" in voice and len(voice) > 6:
        return voice
    return EDGE_TTS_VOICES.get(voice[:2].lower(), "en-US-GuyNeural")


async def _tts_openai(
    text: str,
    output_path: str,
    voice: str = "nova",
    model: str = "tts-1-hd",
    speed: float = 1.0,
) -> Optional[str]:
    """Generate speech via OpenAI TTS. Returns output_path on success."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    try:
        import aiohttp
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "input": text[:4096],
            "voice": voice if voice in OPENAI_VOICES else "nova",
            "speed": max(0.25, min(4.0, speed)),
            "response_format": "mp3",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.openai.com/v1/audio/speech",
                headers=headers,
                json=payload,
            ) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    raise RuntimeError(f"OpenAI TTS HTTP {resp.status}: {err[:200]}")
                audio_bytes = await resp.read()

        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        return output_path
    except Exception as exc:
        logger.debug("[voiceover] OpenAI TTS failed: %s", exc)
        raise


async def _tts_elevenlabs(
    text: str,
    output_path: str,
    voice_id: str = "21m00Tcm4TlvDq8ikWAM",  # Rachel
    model_id: str = "eleven_multilingual_v2",
    stability: float = 0.5,
    similarity_boost: float = 0.75,
) -> Optional[str]:
    """Generate speech via ElevenLabs API. Returns output_path on success."""
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not set")

    try:
        import aiohttp
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text[:5000],
            "model_id": model_id,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
            },
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers=headers,
                json=payload,
            ) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    raise RuntimeError(f"ElevenLabs HTTP {resp.status}: {err[:200]}")
                audio_bytes = await resp.read()

        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        return output_path
    except Exception as exc:
        logger.debug("[voiceover] ElevenLabs TTS failed: %s", exc)
        raise


async def _get_audio_duration(audio_path: str) -> float:
    """Get audio duration via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return float(stdout.decode().strip())
    except Exception:
        return 0.0


async def _mix_voiceover_into_video(
    video_path: str,
    audio_path: str,
    output_path: str,
    vo_volume: float = 1.0,
    bg_volume: float = 0.15,
    offset_seconds: float = 0.0,
) -> bool:
    """Mix VO audio into video, ducking the original audio track."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-filter_complex",
        (
            f"[0:a]volume={bg_volume}[bg];"
            f"[1:a]adelay={int(offset_seconds * 1000)}|{int(offset_seconds * 1000)},"
            f"volume={vo_volume}[vo];"
            "[bg][vo]amix=inputs=2:duration=first:dropout_transition=2[outa]"
        ),
        "-map", "0:v", "-map", "[outa]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error("[voiceover] mix failed: %s", stderr.decode()[-300:])
            return False
        return True
    except Exception as exc:
        logger.error("[voiceover] mix exception: %s", exc)
        return False


async def generate_voiceover(
    text: str,
    output_dir: str,
    provider: str = "auto",   # auto | openai | elevenlabs
    voice: str = "nova",
    voice_id: Optional[str] = None,
    speed: float = 1.0,
) -> VoiceoverResult:
    """
    Generate a voiceover audio file from text.

    provider='auto' tries OpenAI first, then ElevenLabs.
    Returns VoiceoverResult with audio_path set on success.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    audio_path = str(Path(output_dir) / "voiceover.mp3")

    providers_to_try: List[str] = []
    if provider == "auto":
        # edge-tts is always tried first (free, no key needed)
        providers_to_try.append("edge")
        if os.environ.get("OPENAI_API_KEY"):
            providers_to_try.append("openai")
        if os.environ.get("ELEVENLABS_API_KEY"):
            providers_to_try.append("elevenlabs")
    else:
        providers_to_try = [provider]

    if not providers_to_try:
        return VoiceoverResult(
            audio_path=None, mixed_video_path=None,
            provider="none", voice=voice,
            error="No TTS provider available (edge-tts, OPENAI_API_KEY, or ELEVENLABS_API_KEY)",
        )

    last_error = ""
    for prov in providers_to_try:
        try:
            if prov == "edge":
                edge_voice = _pick_edge_voice(voice)
                await _tts_edge(text, audio_path, voice=edge_voice)
            elif prov == "openai":
                await _tts_openai(text, audio_path, voice=voice, speed=speed)
            elif prov == "elevenlabs":
                vid = voice_id or "21m00Tcm4TlvDq8ikWAM"
                await _tts_elevenlabs(text, audio_path, voice_id=vid)
            else:
                continue

            dur = await _get_audio_duration(audio_path)
            logger.info("[voiceover] Generated %.1fs audio via %s", dur, prov)
            return VoiceoverResult(
                audio_path=audio_path,
                mixed_video_path=None,
                provider=prov,
                voice=voice,
                duration_seconds=dur,
                characters_used=len(text),
            )
        except Exception as exc:
            last_error = str(exc)
            logger.debug("[voiceover] %s failed: %s", prov, exc)

    return VoiceoverResult(
        audio_path=None, mixed_video_path=None,
        provider="none", voice=voice, error=last_error,
    )


async def add_voiceover_to_clip(
    video_path: str,
    text: str,
    output_path: str,
    provider: str = "auto",
    voice: str = "nova",
    voice_id: Optional[str] = None,
    vo_volume: float = 1.0,
    bg_volume: float = 0.15,
    offset_seconds: float = 0.0,
    speed: float = 1.0,
) -> VoiceoverResult:
    """
    Generate TTS from text and mix it into the video clip.
    Returns VoiceoverResult with mixed_video_path on full success.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        vo_result = await generate_voiceover(
            text, tmpdir, provider=provider, voice=voice,
            voice_id=voice_id, speed=speed,
        )
        if not vo_result.audio_path:
            return vo_result

        ok = await _mix_voiceover_into_video(
            video_path, vo_result.audio_path, output_path,
            vo_volume=vo_volume, bg_volume=bg_volume,
            offset_seconds=offset_seconds,
        )
        vo_result.mixed_video_path = output_path if ok else None
        if not ok:
            vo_result.error = "Failed to mix voiceover into video"
        return vo_result
