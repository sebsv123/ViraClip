"""
Scene Assembler — syncs narration audio with B-roll for each section, then concatenates.
"""
import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List

from .narrator_tts import NarrationAudio
from .script_writer import ScriptSection

logger = logging.getLogger(__name__)


@dataclass
class AssembledVideo:
    output_path: Path
    total_duration: float
    sections_count: int
    resolution: str


async def assemble_video(
    sections: List[ScriptSection],
    narrations: List[NarrationAudio],
    output_path: Path,
    resolution: str = "1920x1080",
) -> AssembledVideo:
    """Assemble final video: sync B-roll with narration for each section, then concat."""
    scenes_dir = Path("/tmp/longform_scenes")
    scenes_dir.mkdir(parents=True, exist_ok=True)
    scene_files: List[Path] = []

    for section, nar in zip(sections, narrations):
        scene_path = scenes_dir / f"scene_{section.index}.mp4"
        scene_files.append(scene_path)

        # Get B-roll for this section
        broll_path = await _fetch_broll(section.broll_keywords, nar.actual_duration)

        # Build FFmpeg command: B-roll video + narration audio
        audio_duration = nar.actual_duration
        cmd = [
            "ffmpeg", "-y",
            "-i", str(broll_path),
            "-i", str(nar.audio_path),
            "-filter_complex",
            "[0:a]volume=0.15[bga];[1:a][bga]amix=inputs=2:duration=first[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-t", str(audio_duration),
            "-shortest",
            "-vf", f"scale={resolution.split('x')[0]}:{resolution.split('x')[1]}:force_original_aspect_ratio=decrease,pad={resolution}:{resolution.split('x')[0]}:{resolution.split('x')[1]}:(ow-iw)/2:(oh-ih)/2",
            str(scene_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode != 0 or not scene_path.exists():
                logger.warning(f"[Assembler] Scene {section.index} FFmpeg failed, creating fallback")
                _create_fallback_scene(scene_path, nar.audio_path, audio_duration, resolution)
        except Exception as e:
            logger.warning(f"[Assembler] Scene {section.index} error: {e}, creating fallback")
            _create_fallback_scene(scene_path, nar.audio_path, audio_duration, resolution)

    # Concatenate all scenes
    concat_file = scenes_dir / "concat_list.txt"
    with open(concat_file, "w") as f:
        for sp in scene_files:
            f.write(f"file '{sp}'\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd_concat = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(output_path),
    ]
    try:
        subprocess.run(cmd_concat, capture_output=True, timeout=600)
    except Exception as e:
        logger.error(f"[Assembler] Concat failed: {e}")

    # Measure total duration
    total_dur = 0.0
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(output_path)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            total_dur = float(data.get("format", {}).get("duration", 0))
    except Exception:
        pass

    # Cleanup temp scenes
    import shutil
    shutil.rmtree(scenes_dir, ignore_errors=True)

    return AssembledVideo(
        output_path=output_path,
        total_duration=total_dur,
        sections_count=len(sections),
        resolution=resolution,
    )


async def _fetch_broll(keywords: List[str], target_duration: float) -> Path:
    """Fetch B-roll for keywords, loop/trim to match duration."""
    from ...domains.broll.broll_service import BrollService
    svc = BrollService()
    keyword = keywords[0] if keywords else "nature"
    asset = await svc.fetch_broll_asset(keyword)
    if asset and asset.exists():
        return asset
    # Fallback: generate a color clip
    fallback = Path(f"/tmp/broll_fallback_{keyword}.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x1a1a2e:s=1920x1080:d={target_duration}",
         "-c:v", "libx264", "-preset", "ultrafast", str(fallback)],
        capture_output=True, timeout=30,
    )
    return fallback


def _create_fallback_scene(scene_path: Path, audio_path: Path, duration: float, resolution: str):
    """Create a fallback scene with a static color background + narration."""
    w, h = resolution.split("x")
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", f"color=c=0x1a1a2e:s={w}x{h}:d={duration}",
         "-i", str(audio_path),
         "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "aac", "-b:a", "128k",
         "-shortest",
         str(scene_path)],
        capture_output=True, timeout=60,
    )
