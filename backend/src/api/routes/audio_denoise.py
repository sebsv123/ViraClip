"""Audio Denoiser API routes."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/audio-denoise", tags=["audio-denoise"])


class DenoiseRequest(BaseModel):
    video_path: str
    noise_reduction: bool = True
    voice_isolation: bool = True
    apply_loudnorm: bool = True
    loudnorm_target_lufs: float = -14.0


class DenoiseResponse(BaseModel):
    output_path: str
    noise_reduction_applied: bool
    voice_isolation_applied: bool
    loudnorm_applied: bool
    original_lufs: Optional[float]
    output_lufs: Optional[float]
    error: Optional[str]


@router.post("/clean", response_model=DenoiseResponse)
async def clean_audio(body: DenoiseRequest):
    """
    Denoise video audio: removes broadband noise, isolates voice,
    and optionally normalises loudness to EBU R128.
    """
    if not Path(body.video_path).exists():
        raise HTTPException(status_code=404, detail=f"File not found: {body.video_path}")

    from ...services.audio_denoiser import denoise_audio

    src = Path(body.video_path)
    output_path = str(src.parent / f"{src.stem}_denoised{src.suffix}")

    result = await denoise_audio(
        input_path=body.video_path,
        output_path=output_path,
        noise_reduction=body.noise_reduction,
        voice_isolation=body.voice_isolation,
        apply_loudnorm=body.apply_loudnorm,
        loudnorm_target_lufs=body.loudnorm_target_lufs,
    )

    if result.error:
        raise HTTPException(status_code=500, detail=result.error)

    return DenoiseResponse(
        output_path=result.output_path,
        noise_reduction_applied=result.noise_reduction_applied,
        voice_isolation_applied=result.voice_isolation_applied,
        loudnorm_applied=result.loudnorm_applied,
        original_lufs=result.original_lufs,
        output_lufs=result.output_lufs,
        error=result.error,
    )


@router.post("/measure-lufs")
async def measure_lufs(video_path: str):
    """Measure integrated loudness (LUFS) of a video's audio track."""
    if not Path(video_path).exists():
        raise HTTPException(status_code=404, detail=f"File not found: {video_path}")

    from ...services.audio_denoiser import _measure_lufs
    lufs = await _measure_lufs(video_path)
    return {"video_path": video_path, "lufs": lufs, "target_lufs": -14.0}
