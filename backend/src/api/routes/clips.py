"""
Clip management routes — including user rating endpoint (B.6).
"""
import logging
import asyncio
import subprocess
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from ...database import get_db
from ...repositories.clip_repository import ClipRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/clips", tags=["clips"])

BGM_DIR = Path("/app/assets/sounds/bgm")

TRACK_LABELS: dict[str, str] = {
    "upbeat_energy":       "Upbeat Energy",
    "lofi_chill":          "Lo-Fi Chill",
    "cinematic_build":     "Cinematic Build",
    "corporate_clean":     "Corporate Clean",
    "minimal_ambient":     "Minimal Ambient",
    "bgm_upbeat_positive": "Upbeat Positive",
    "bgm_lofi_chill":      "Lo-Fi Chill (short)",
    "bgm_energetic_hype":  "Energetic Hype",
    "bgm_cinematic_ambient": "Cinematic Ambient",
    "bgm_dramatic_tension":  "Dramatic Tension",
}


class ApplyMusicRequest(BaseModel):
    track: str = Field(..., description="Track filename stem, e.g. 'upbeat_energy'")


class RatingRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="User rating from 1 to 5")
    task_id: Optional[str] = Field(None, description="Parent task ID for dataset collection")


class ThumbsRequest(BaseModel):
    rating: str = Field(..., pattern="^(thumbs_up|thumbs_down|neutral)$")
    task_id: Optional[str] = Field(None, description="Parent task ID for dataset collection")
    feedback_text: Optional[str] = Field(None, max_length=500)


@router.post("/{clip_id}/rating", summary="Rate a generated clip (1–5 stars)")
async def rate_clip(
    clip_id: str,
    body: RatingRequest,
    db: AsyncSession = Depends(get_db),
):
    updated = await ClipRepository.update_clip_rating(db, clip_id, body.rating)
    if not updated:
        raise HTTPException(status_code=404, detail="Clip not found")

    # Feed into dataset collector for LLM training (non-blocking)
    if body.task_id:
        try:
            from ...services.dataset_collector import get_dataset_collector
            from ...config import get_config
            collector = get_dataset_collector(get_config().dataset_dir)
            thumbs = "thumbs_up" if body.rating >= 4 else ("thumbs_down" if body.rating <= 2 else "neutral")
            await collector.add_user_feedback(
                task_id=body.task_id,
                clip_id=clip_id,
                rating=thumbs,
            )
        except Exception as e:
            logger.warning(f"Dataset collection failed (non-fatal): {e}")

    return {"clip_id": clip_id, "rating": body.rating}


@router.post("/{clip_id}/thumbs", summary="Thumbs up/down on a clip (feeds LLM training dataset)")
async def thumbs_clip(
    clip_id: str,
    body: ThumbsRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Quick thumbs rating — also records feedback in the LLM training dataset.
    Used to progressively improve local model quality via DSPy / fine-tuning.
    """
    # Map to numeric for DB storage
    numeric = {"thumbs_up": 5, "neutral": 3, "thumbs_down": 1}[body.rating]
    updated = await ClipRepository.update_clip_rating(db, clip_id, numeric)
    if not updated:
        raise HTTPException(status_code=404, detail="Clip not found")

    # Feed into dataset collector
    if body.task_id:
        try:
            from ...services.dataset_collector import get_dataset_collector
            from ...config import get_config
            collector = get_dataset_collector(get_config().dataset_dir)
            await collector.add_user_feedback(
                task_id=body.task_id,
                clip_id=clip_id,
                rating=body.rating,
                feedback_text=body.feedback_text,
            )
            stats = await collector.get_stats()
            logger.info(
                f"Dataset: {stats['total_examples']} examples "
                f"(DSPy ready: {stats['ready_for_dspy']}, "
                f"FT ready: {stats['ready_for_finetuning']})"
            )
        except Exception as e:
            logger.warning(f"Dataset collection failed (non-fatal): {e}")

    return {"clip_id": clip_id, "rating": body.rating, "recorded_for_training": bool(body.task_id)}


@router.get("/music/tracks", summary="List available background music tracks")
async def list_music_tracks():
    """Return the tracks available in the BGM library."""
    tracks = []
    if BGM_DIR.exists():
        for f in sorted(BGM_DIR.iterdir()):
            if f.suffix in {".mp3", ".wav", ".ogg", ".m4a"} and f.is_file():
                stem = f.stem
                tracks.append({
                    "id":    stem,
                    "label": TRACK_LABELS.get(stem, stem.replace("_", " ").title()),
                    "file":  f.name,
                })
    return {"tracks": tracks}


@router.post("/{clip_id}/apply-music", summary="Apply a music track to a clip")
async def apply_music_to_clip(
    clip_id: str,
    body: ApplyMusicRequest,
    db: AsyncSession = Depends(get_db),
):
    clip = await ClipRepository.get_clip_by_id(db, clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_dict = clip if isinstance(clip, dict) else clip.__dict__
    file_path = clip_dict.get("file_path") or ""
    if not file_path or not Path(file_path).exists():
        raise HTTPException(status_code=404, detail="Clip file not found on disk")

    # Locate the chosen track
    track_path: Optional[Path] = None
    for ext in (".mp3", ".wav", ".ogg", ".m4a"):
        candidate = BGM_DIR / f"{body.track}{ext}"
        if candidate.exists():
            track_path = candidate
            break
    if not track_path:
        raise HTTPException(status_code=404, detail=f"Track '{body.track}' not found")

    video_path = Path(file_path)
    out_path = video_path.with_name(f"music_{video_path.name}")

    filter_complex = (
        f"[1:a]volume=0.22,aloop=loop=-1:size=2000000000[bgm];"
        "[0:a][bgm]sidechaincompress=threshold=0.015:ratio=6:attack=50:release=800[bgmduck];"
        "[0:a][bgmduck]amix=inputs=2:duration=first:normalize=0[aout]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(track_path),
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_path),
    ]
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, timeout=120),
        )
        if result.returncode != 0:
            logger.error("[apply-music] FFmpeg failed: %s", result.stderr.decode()[-300:])
            raise HTTPException(status_code=500, detail="FFmpeg failed to mix music")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Music mixing timed out")

    if not out_path.exists():
        raise HTTPException(status_code=500, detail="Output file not created")

    # Replace original with music version
    out_path.replace(video_path)
    logger.info("[apply-music] Clip %s → track=%s", clip_id, body.track)

    label = TRACK_LABELS.get(body.track, body.track.replace("_", " ").title())
    return {"success": True, "track_applied": label}


class AutoMusicRequest(BaseModel):
    mood: str = Field(..., description="Target mood: energetic, calm, sad, dramatic, funny, mysterious, romantic, inspirational")
    duration: float = Field(default=0.0, description="Target duration in seconds (0 = auto from clip)")
    allow_sfx: bool = Field(default=True, description="Also fetch matching SFX if available")


@router.post("/{clip_id}/apply-music-auto", summary="Auto-match Freesound music to clip mood")
async def apply_music_auto(
    clip_id: str,
    body: AutoMusicRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Automatically fetch and apply background music from Freesound based on mood.
    
    Searches Freesound with tags like mood:happy, loop, duration filter.
    Downloads, normalizes to -14 LUFS, and mixes with sidechain ducking.
    Returns attribution info if the sound requires it (CC-BY licenses).
    """
    from ...services.freesound_service import get_freesound_service

    clip = await ClipRepository.get_clip_by_id(db, clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_dict = clip if isinstance(clip, dict) else clip.__dict__
    file_path = clip_dict.get("file_path") or ""
    if not file_path or not Path(file_path).exists():
        raise HTTPException(status_code=404, detail="Clip file not found on disk")

    # Get clip duration if not provided
    target_duration = body.duration
    if target_duration <= 0:
        try:
            import asyncio
            probe_cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)
            ]
            proc = await asyncio.create_subprocess_exec(
                *probe_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
            )
            stdout, _ = await proc.communicate()
            target_duration = float(stdout.decode().strip())
        except Exception:
            target_duration = 30.0  # fallback

    # Fetch from Freesound
    service = get_freesound_service()
    audio_meta = await service.fetch_for_broll(
        mood=body.mood,
        duration=target_duration,
        output_dir=str(Path(file_path).parent / "freesound"),
    )

    if not audio_meta:
        raise HTTPException(status_code=404, detail=f"No Freesound match for mood '{body.mood}'")

    # Apply music using existing sidechain mixing
    video_path = Path(file_path)
    track_path = Path(audio_meta["path"])
    out_path = video_path.with_name(f"music_auto_{video_path.name}")

    filter_complex = (
        f"[1:a]volume=0.22,aloop=loop=-1:size=2000000000[bgm];"
        "[0:a][bgm]sidechaincompress=threshold=0.015:ratio=6:attack=50:release=800[bgmduck];"
        "[0:a][bgmduck]amix=inputs=2:duration=first:normalize=0[aout]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(track_path),
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_path),
    ]
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, timeout=120),
        )
        if result.returncode != 0:
            logger.error("[apply-music-auto] FFmpeg failed: %s", result.stderr.decode()[-300:])
            raise HTTPException(status_code=500, detail="FFmpeg failed to mix music")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Music mixing timed out")

    if not out_path.exists():
        raise HTTPException(status_code=500, detail="Output file not created")

    # Replace original with music version
    out_path.replace(video_path)
    logger.info("[apply-music-auto] Clip %s → mood=%s, sound=%s", clip_id, body.mood, audio_meta["name"])

    return {
        "success": True,
        "mood": body.mood,
        "track_applied": audio_meta["name"],
        "license": audio_meta["license"],
        "attribution": audio_meta.get("attribution"),
        "preview_url": audio_meta.get("preview_url"),
        "source": "freesound",
        "sound_id": audio_meta.get("sound_id"),
    }


@router.get("/{clip_id}", summary="Get a single clip by ID")
async def get_clip(clip_id: str, db: AsyncSession = Depends(get_db)):
    clip = await ClipRepository.get_clip_by_id(db, clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    return clip
