import asyncio
_ELEVENLABS_SEMAPHORE = asyncio.Semaphore(int(os.getenv("ELEVENLABS_CONCURRENCY", "2")))
"""
Narrator TTS — generates voice narration via ElevenLabs (primary) or gTTS (fallback).
"""
import asyncio
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import httpx

from .script_writer import ScriptSection

logger = logging.getLogger(__name__)


@dataclass
class NarrationAudio:
    section_index: int
    audio_path: Path
    actual_duration: float
    provider: str  # "elevenlabs" or "gtts"


async def generate_narration(
    sections: List[ScriptSection],
    voice_id: Optional[str] = None,
    output_dir: Path = Path("/tmp/narration"),
) -> List[NarrationAudio]:
    """Generate narration audio for all sections in parallel."""
    output_dir.mkdir(parents=True, exist_ok=True)
    voice_id = voice_id or os.getenv("ELEVENLABS_NARRATOR_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

    async def _generate_one(section: ScriptSection) -> NarrationAudio:
        path = output_dir / f"narration_{section.index}.mp3"
        provider = "gtts"

        # Try ElevenLabs first
        api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
        if api_key:
            try:
                async with _ELEVENLABS_SEMAPHORE:
                await asyncio.sleep(0.4)
                async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
                    resp = await client.post(
                        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                        json={
                            "text": section.narration_text,
                            "model_id": "eleven_multilingual_v2",
                        },
                    )
                    resp.raise_for_status()
                    path.write_bytes(resp.content)
                    provider = "elevenlabs"
                    logger.info(f"[Narrator] ElevenLabs section {section.index}: {len(resp.content)} bytes")
            except Exception as e:
                logger.warning(f"[Narrator] ElevenLabs failed for section {section.index}: {e}, falling back to gTTS")

        # Fallback to gTTS
        if provider == "gtts":
            try:
                from gtts import gTTS
                tts = gTTS(text=section.narration_text, lang=section.narration_text[:2] if len(section.narration_text) > 1 else "es", slow=False)
                tts.save(str(path))
                logger.info(f"[Narrator] gTTS section {section.index}: {path}")
            except Exception as e:
                logger.error(f"[Narrator] gTTS also failed for section {section.index}: {e}")
                # Create silent audio as last resort
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                     "-t", str(section.estimated_duration), str(path)],
                    capture_output=True, timeout=30,
                )

        # Measure actual duration with FFprobe
        actual_dur = section.estimated_duration
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                streams = data.get("streams", [])
                if streams:
                    actual_dur = float(streams[0].get("duration", section.estimated_duration))
        except Exception:
            pass

        return NarrationAudio(
            section_index=section.index,
            audio_path=path,
            actual_duration=actual_dur,
            provider=provider,
        )

    tasks = [_generate_one(s) for s in sections]
    return await asyncio.gather(*tasks)
