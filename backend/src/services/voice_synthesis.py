"""
Voice Cloning and Synthesis Service
AI-powered voice cloning and text-to-speech for video narration.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class VoiceStyle(Enum):
    """Voice style presets."""
    NATURAL = "natural"
    ENERGETIC = "energetic"
    CALM = "calm"
    PROFESSIONAL = "professional"
    DRAMATIC = "dramatic"
    FUNNY = "funny"
    WHISPER = "whisper"
    NEWS = "news"


class SynthesisProvider(Enum):
    """TTS providers."""
    ELEVENLABS = "elevenlabs"
    AZURE = "azure"
    GOOGLE = "google"
    AMAZON = "amazon"
    OPENAI = "openai"


@dataclass
class VoiceProfile:
    """Voice profile for cloning/synthesis."""
    voice_id: str
    name: str
    description: str
    sample_audio_path: Optional[Path]
    age: int
    gender: str
    accent: str
    language: str
    cloned: bool
    created_at: str
    usage_count: int


@dataclass
class SynthesisJob:
    """Voice synthesis job."""
    job_id: str
    voice_id: str
    text: str
    style: VoiceStyle
    speed: float
    pitch: float
    emotion: str
    status: str  # pending, processing, completed, failed
    output_path: Optional[Path]
    duration: Optional[float]
    created_at: str
    completed_at: Optional[str]


class VoiceSynthesisService:
    """
    Voice cloning and text-to-speech synthesis service.
    """
    
    def __init__(self, output_dir: Path = Path("/app/temp/voice")):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self._voice_profiles: Dict[str, VoiceProfile] = {}
        self._synthesis_jobs: Dict[str, SynthesisJob] = {}
        self._provider_apis: Dict[SynthesisProvider, str] = {}
        
        # Initialize default voices
        self._initialize_default_voices()
    
    def _initialize_default_voices(self):
        """Initialize default voice profiles."""
        import uuid
        
        default_voices = [
            {
                "name": "Sarah",
                "description": "Natural female voice, perfect for storytelling",
                "age": 28,
                "gender": "female",
                "accent": "american",
                "language": "en"
            },
            {
                "name": "James",
                "description": "Professional male voice, ideal for documentaries",
                "age": 35,
                "gender": "male",
                "accent": "british",
                "language": "en"
            },
            {
                "name": "Maria",
                "description": "Energetic Spanish voice, great for tutorials",
                "age": 25,
                "gender": "female",
                "accent": "spanish",
                "language": "es"
            },
            {
                "name": "Alex",
                "description": "Versatile neutral voice for any content",
                "age": 30,
                "gender": "neutral",
                "accent": "american",
                "language": "en"
            }
        ]
        
        for voice_data in default_voices:
            voice_id = f"default_{voice_data['name'].lower()}"
            self._voice_profiles[voice_id] = VoiceProfile(
                voice_id=voice_id,
                name=voice_data["name"],
                description=voice_data["description"],
                sample_audio_path=None,
                age=voice_data["age"],
                gender=voice_data["gender"],
                accent=voice_data["accent"],
                language=voice_data["language"],
                cloned=False,
                created_at=datetime.now().isoformat(),
                usage_count=0
            )
    
    async def clone_voice(
        self,
        name: str,
        description: str,
        sample_audio_paths: List[Path],
        provider: SynthesisProvider = SynthesisProvider.ELEVENLABS
    ) -> VoiceProfile:
        """
        Clone a voice from audio samples.
        
        Args:
            name: Voice name
            description: Voice description
            sample_audio_paths: List of sample audio files (min 1 minute total)
            provider: Voice cloning provider
        """
        import uuid
        
        voice_id = f"cloned_{uuid.uuid4().hex[:8]}"
        
        # Validate samples
        total_duration = 0
        for path in sample_audio_paths:
            if not path.exists():
                raise FileNotFoundError(f"Sample not found: {path}")
            # Get audio duration
            duration = await self._get_audio_duration(path)
            total_duration += duration
        
        if total_duration < 60:
            raise ValueError("Need at least 60 seconds of audio samples")
        
        # Send to provider for cloning (simulated)
        external_voice_id = await self._send_to_provider_for_cloning(
            provider, sample_audio_paths
        )
        
        profile = VoiceProfile(
            voice_id=voice_id,
            name=name,
            description=description,
            sample_audio_path=sample_audio_paths[0] if sample_audio_paths else None,
            age=0,  # Unknown
            gender="unknown",
            accent="cloned",
            language="en",
            cloned=True,
            created_at=datetime.now().isoformat(),
            usage_count=0
        )
        
        self._voice_profiles[voice_id] = profile
        
        logger.info(f"Cloned voice {voice_id} with {total_duration:.1f}s of samples")
        return profile
    
    async def _get_audio_duration(self, audio_path: Path) -> float:
        """Get audio file duration."""
        import subprocess
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
                capture_output=True, text=True, timeout=10
            )
            return float(result.stdout.strip())
        except:
            return 30.0  # Default assumption
    
    async def _send_to_provider_for_cloning(
        self,
        provider: SynthesisProvider,
        samples: List[Path]
    ) -> str:
        """Send samples to provider for voice cloning."""
        # In production, API call to ElevenLabs, Azure, etc.
        import uuid
        return f"voice_{uuid.uuid4().hex[:12]}"
    
    async def synthesize_speech(
        self,
        voice_id: str,
        text: str,
        style: VoiceStyle = VoiceStyle.NATURAL,
        speed: float = 1.0,
        pitch: float = 1.0,
        emotion: str = "neutral",
        provider: SynthesisProvider = SynthesisProvider.ELEVENLABS
    ) -> SynthesisJob:
        """
        Synthesize speech from text.
        
        Args:
            voice_id: Voice profile ID
            text: Text to synthesize
            style: Speaking style
            speed: Speed multiplier (0.5 - 2.0)
            pitch: Pitch multiplier (0.8 - 1.2)
            emotion: Emotion preset
            provider: TTS provider
        """
        import uuid
        
        if voice_id not in self._voice_profiles:
            raise ValueError(f"Voice {voice_id} not found")
        
        job_id = str(uuid.uuid4())
        
        job = SynthesisJob(
            job_id=job_id,
            voice_id=voice_id,
            text=text,
            style=style,
            speed=max(0.5, min(2.0, speed)),
            pitch=max(0.8, min(1.2, pitch)),
            emotion=emotion,
            status="pending",
            output_path=None,
            duration=None,
            created_at=datetime.now().isoformat(),
            completed_at=None
        )
        
        self._synthesis_jobs[job_id] = job
        
        # Update voice usage
        self._voice_profiles[voice_id].usage_count += 1
        
        # Process synthesis
        await self._process_synthesis(job, provider)
        
        return job
    
    async def _process_synthesis(
        self,
        job: SynthesisJob,
        provider: SynthesisProvider
    ) -> None:
        """Process synthesis job."""
        job.status = "processing"
        
        try:
            # Call provider API (simulated)
            output_file = await self._call_tts_provider(job, provider)
            
            job.output_path = output_file
            job.duration = await self._get_audio_duration(output_file)
            job.status = "completed"
            job.completed_at = datetime.now().isoformat()
            
            logger.info(f"Synthesized {job.duration:.1f}s audio for job {job.job_id}")
            
        except Exception as e:
            logger.error(f"Synthesis failed for job {job.job_id}: {e}")
            job.status = "failed"
    
    async def _call_tts_provider(
        self,
        job: SynthesisJob,
        provider: SynthesisProvider
    ) -> Path:
        """Call TTS provider API."""
        # Estimate output duration based on text
        word_count = len(job.text.split())
        estimated_duration = word_count / 150 * 60 / job.speed  # Assuming 150 WPM
        
        # Simulated synthesis delay
        import asyncio
        await asyncio.sleep(estimated_duration * 0.1)  # 10% of duration
        
        # Create output file
        output_path = self.output_dir / f"{job.job_id}.wav"
        
        # In production, this would be actual audio from provider
        # For now, just create a placeholder
        output_path.touch()
        
        return output_path
    
    async def generate_narration(
        self,
        video_script: str,
        voice_id: str,
        style: VoiceStyle = VoiceStyle.NATURAL,
        segments: Optional[List[Dict[str, float]]] = None
    ) -> List[SynthesisJob]:
        """
        Generate narration for video script with optional timing.
        
        Args:
            video_script: Full script text
            voice_id: Voice to use
            style: Speaking style
            segments: List of {text, start_time, end_time} for timed narration
        """
        jobs = []
        
        if segments:
            # Generate per segment
            for i, segment in enumerate(segments):
                job = await self.synthesize_speech(
                    voice_id=voice_id,
                    text=segment["text"],
                    style=style
                )
                jobs.append(job)
        else:
            # Generate entire script
            # Split into manageable chunks
            chunks = self._split_script(video_script)
            
            for chunk in chunks:
                job = await self.synthesize_speech(
                    voice_id=voice_id,
                    text=chunk,
                    style=style
                )
                jobs.append(job)
        
        return jobs
    
    def _split_script(self, script: str, max_chars: int = 500) -> List[str]:
        """Split long script into chunks."""
        chunks = []
        sentences = script.replace(". ", ".").split(".")
        
        current_chunk = ""
        for sentence in sentences:
            if len(current_chunk) + len(sentence) < max_chars:
                current_chunk += sentence + ". "
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence + ". "
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks if chunks else [script]
    
    async def mix_with_video(
        self,
        video_path: Path,
        narration_jobs: List[SynthesisJob],
        output_path: Path,
        ducking_level: float = 0.3
    ) -> Path:
        """
        Mix narration audio with video.
        
        Args:
            video_path: Source video
            narration_jobs: Completed synthesis jobs
            output_path: Output video path
            ducking_level: Background audio ducking (0-1)
        """
        # Collect audio files
        audio_files = [
            job.output_path for job in narration_jobs
            if job.status == "completed" and job.output_path
        ]
        
        if not audio_files:
            raise ValueError("No completed narration audio found")
        
        # Concatenate audio
        combined_audio = self.output_dir / f"narration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        await self._concatenate_audio(audio_files, combined_audio)
        
        # Mix with video
        await self._mix_audio_video(video_path, combined_audio, output_path, ducking_level)
        
        logger.info(f"Created narrated video: {output_path}")
        return output_path
    
    async def _concatenate_audio(
        self,
        audio_files: List[Path],
        output: Path
    ) -> None:
        """Concatenate multiple audio files."""
        # Use ffmpeg concat demuxer
        import subprocess
        
        # Create concat list file
        list_file = self.output_dir / "concat_list.txt"
        with open(list_file, "w") as f:
            for audio_file in audio_files:
                f.write(f"file '{audio_file}'\n")
        
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(list_file), "-c", "copy", str(output)],
            capture_output=True
        )
        
        list_file.unlink(missing_ok=True)
    
    async def _mix_audio_video(
        self,
        video: Path,
        audio: Path,
        output: Path,
        ducking: float
    ) -> None:
        """Mix audio with video."""
        import subprocess
        
        # Mix with background ducking
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video), "-i", str(audio),
             "-filter_complex", f"[0:a]volume={ducking}[bg];[bg][1:a]amix=inputs=2:duration=first",
             "-c:v", "copy", "-c:a", "aac", str(output)],
            capture_output=True
        )
    
    def get_voice_profiles(self, cloned_only: bool = False) -> List[VoiceProfile]:
        """Get available voice profiles."""
        profiles = list(self._voice_profiles.values())
        
        if cloned_only:
            profiles = [p for p in profiles if p.cloned]
        
        return sorted(profiles, key=lambda x: x.usage_count, reverse=True)
    
    def get_job_status(self, job_id: str) -> Optional[SynthesisJob]:
        """Get synthesis job status."""
        return self._synthesis_jobs.get(job_id)
    
    async def delete_voice(self, voice_id: str) -> bool:
        """Delete a cloned voice."""
        if voice_id not in self._voice_profiles:
            return False
        
        profile = self._voice_profiles[voice_id]
        if not profile.cloned:
            raise ValueError("Cannot delete default voices")
        
        del self._voice_profiles[voice_id]
        logger.info(f"Deleted voice {voice_id}")
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics."""
        total_voices = len(self._voice_profiles)
        cloned_voices = len([v for v in self._voice_profiles.values() if v.cloned])
        
        total_jobs = len(self._synthesis_jobs)
        completed_jobs = len([j for j in self._synthesis_jobs.values() if j.status == "completed"])
        failed_jobs = len([j for j in self._synthesis_jobs.values() if j.status == "failed"])
        
        total_duration = sum(
            j.duration for j in self._synthesis_jobs.values()
            if j.duration and j.status == "completed"
        )
        
        return {
            "total_voices": total_voices,
            "cloned_voices": cloned_voices,
            "default_voices": total_voices - cloned_voices,
            "total_synthesis_jobs": total_jobs,
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
            "success_rate": completed_jobs / total_jobs if total_jobs > 0 else 0,
            "total_generated_audio_seconds": round(total_duration, 2)
        }


# Global instance
_voice_service: Optional[VoiceSynthesisService] = None


def get_voice_synthesis_service() -> VoiceSynthesisService:
    """Get global voice synthesis service."""
    global _voice_service
    if _voice_service is None:
        _voice_service = VoiceSynthesisService()
    return _voice_service


# Convenience functions
async def generate_narration(
    script: str,
    voice_id: str = "default_alex",
    style: str = "natural"
) -> Path:
    """Quick narration generation."""
    service = get_voice_synthesis_service()
    
    style_enum = VoiceStyle(style)
    job = await service.synthesize_speech(voice_id, script, style_enum)
    
    if job.output_path:
        return job.output_path
    raise RuntimeError("Synthesis failed")


async def clone_voice_from_samples(
    name: str,
    samples: List[Path]
) -> str:
    """Clone a voice from audio samples."""
    service = get_voice_synthesis_service()
    profile = await service.clone_voice(name, f"Cloned voice of {name}", samples)
    return profile.voice_id
