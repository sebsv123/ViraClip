"""
Voice Cloning Service — ElevenLabs API para clonación de voz y voiceover.

Flujo:
1. Transcripción con Whisper (existente)
2. Clonar voz del creador con ElevenLabs Voice Cloning
3. Regenerar audio con voz clonada mejorada
"""

import logging
import os
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class VoiceCloningService:
    """ElevenLabs voice cloning and voiceover generation."""

    def __init__(self):
        self.api_key = os.getenv("ELEVENLABS_API_KEY", "")
        self.is_available = bool(self.api_key)
        if not self.is_available:
            logger.warning("[VoiceClone] ELEVENLABS_API_KEY not set — voice cloning unavailable")

    async def clone_voice(
        self,
        audio_samples: List[str],
        voice_name: str = "Cloned Voice",
    ) -> Optional[str]:
        """Clone a voice from audio samples using ElevenLabs API."""
        if not self.is_available:
            return None
        try:
            from elevenlabs import Voice, VoiceSettings, clone
            voice = clone(
                name=voice_name,
                files=audio_samples,
            )
            logger.info(f"[VoiceClone] Voice cloned: {voice_name} ({voice.voice_id})")
            return voice.voice_id
        except Exception as e:
            logger.error(f"[VoiceClone] Clone failed: {e}")
            return None

    async def generate_voiceover(
        self,
        text: str,
        voice_id: str = "21m00Tcm4TlvDq8ikWAM",
        output_path: str = "/tmp/voiceover.wav",
        stability: float = 0.7,
        similarity: float = 0.8,
    ) -> Optional[str]:
        """Generate voiceover audio from text using ElevenLabs."""
        if not self.is_available:
            return None
        try:
            from elevenlabs import generate, save, Voice
            audio = generate(
                text=text,
                voice=Voice(voice_id=voice_id),
                model="eleven_multilingual_v2",
                stability=stability,
                similarity_boost=similarity,
            )
            save(audio, output_path)
            logger.info(f"[VoiceClone] Voiceover generated: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"[VoiceClone] Voiceover failed: {e}")
            return None

    async def replace_audio(
        self,
        video_path: str,
        new_audio_path: str,
        output_path: str,
    ) -> bool:
        """Replace audio track in video with new voiceover."""
        import subprocess
        try:
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", new_audio_path,
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-shortest:v",
                output_path,
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=120)
            if result.returncode == 0:
                logger.info(f"[VoiceClone] Audio replaced: {output_path}")
                return True
            logger.error(f"[VoiceClone] Audio replace failed: {result.stderr.decode()[-200:]}")
            return False
        except Exception as e:
            logger.error(f"[VoiceClone] Audio replace error: {e}")
            return False
