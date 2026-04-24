"""
Learning Loop — Phase 9 Creative Engine

Post-render QA verification + render manifest persistence.
Every render saves a JSON record to /app/datasets/render_feedback/
for future virality model training.
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_MANIFEST_DIR = Path(os.environ.get("DATASET_DIR", "/app/datasets")) / "render_feedback"
_MIN_DURATION_S = 3.0
_MAX_DURATION_S = 180.0


@dataclass
class RenderManifest:
    task_id: str
    clip_index: int
    viral_score: float
    hook_score: float
    pacing_score: float
    emotion_score: float
    timeline_events: int
    preset_used: str
    sfx_injected: int
    broll_overlays: int
    loudnorm_applied: bool
    output_duration_s: float
    output_size_bytes: int
    has_audio: bool
    qa_passed: bool
    qa_issues: "list[str]" = field(default_factory=list)
    improvements: "list[str]" = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


class LearningLoop:
    """
    Runs QA assertions on a rendered clip and saves a structured manifest.
    """

    async def post_render_analysis(
        self,
        clip_path: Path,
        source_path: Path,
        task_id: str,
        clip_index: int,
        virality_prediction,
        timeline_events: list,
        preset_name: str,
        sfx_count: int,
        broll_count: int,
        loudnorm_applied: bool,
    ) -> RenderManifest:
        duration, size, has_audio = await self._probe(clip_path)
        qa_issues = await self._qa(clip_path, source_path, duration, size, has_audio)
        qa_passed = len(qa_issues) == 0

        manifest = RenderManifest(
            task_id=task_id,
            clip_index=clip_index,
            viral_score=float(getattr(virality_prediction, "score", 0.0)),
            hook_score=float(getattr(virality_prediction, "hook_score", 0.0)),
            pacing_score=float(getattr(virality_prediction, "pacing_score", 0.0)),
            emotion_score=float(getattr(virality_prediction, "emotion_score", 0.0)),
            timeline_events=len(timeline_events),
            preset_used=preset_name,
            sfx_injected=sfx_count,
            broll_overlays=broll_count,
            loudnorm_applied=loudnorm_applied,
            output_duration_s=round(duration, 2),
            output_size_bytes=size,
            has_audio=has_audio,
            qa_passed=qa_passed,
            qa_issues=qa_issues,
            improvements=list(getattr(virality_prediction, "improvements", [])),
        )

        await self._save(manifest)

        level = logger.info if qa_passed else logger.warning
        level(
            "QA %s for %s/clip%d — score=%.1f events=%d sfx=%d broll=%d%s",
            "PASSED" if qa_passed else "FAILED",
            task_id, clip_index,
            manifest.viral_score, manifest.timeline_events,
            sfx_count, broll_count,
            f" issues={qa_issues}" if qa_issues else "",
        )
        return manifest

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _probe(self, path: Path) -> "tuple[float, int, bool]":
        if not path.exists():
            return 0.0, 0, False
        size = path.stat().st_size
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams", "-show_format",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            data = json.loads(stdout.decode(errors="ignore"))
            duration = float(data.get("format", {}).get("duration", 0))
            has_audio = any(
                s.get("codec_type") == "audio" for s in data.get("streams", [])
            )
            return duration, size, has_audio
        except Exception as exc:
            logger.debug("ffprobe failed for %s: %s", path, exc)
            return 0.0, size, False

    async def _qa(
        self,
        output: Path,
        source: Path,
        duration: float,
        size: int,
        has_audio: bool,
    ) -> "list[str]":
        issues: list[str] = []
        if not output.exists():
            return ["Output file does not exist"]
        if size == 0:
            issues.append("Output file is empty (0 bytes)")
        if duration < _MIN_DURATION_S:
            issues.append(f"Duration too short: {duration:.1f}s < {_MIN_DURATION_S}s")
        if duration > _MAX_DURATION_S:
            issues.append(f"Duration too long: {duration:.1f}s > {_MAX_DURATION_S}s")
        if not has_audio:
            issues.append("No audio stream in output")
        if source.exists() and size > 0:
            src_size = source.stat().st_size
            if abs(size - src_size) < 512:
                issues.append("Output size matches source — effects may not have applied")
        
        # Enhanced validation using ClipValidator
        try:
            from ..domains.validation.clip_validator import get_clip_validator
            validator = get_clip_validator()
            validation_result = await validator.validate_output(
                output_path=output,
                expected_duration=duration,
                source_path=source,
            )
            
            # Add validation-specific issues
            if not validation_result.passed:
                issues.extend(validation_result.issues)
            
            # Add warnings as issues if they're critical
            for warning in validation_result.warnings:
                if "bitrate" in warning.lower() or "corrupt" in warning.lower():
                    issues.append(f"Warning: {warning}")
        except Exception as exc:
            logger.debug("ClipValidator integration failed: %s", exc)
        
        return issues

    async def _save(self, manifest: RenderManifest) -> None:
        try:
            _MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
            fname = (
                f"{manifest.task_id}_clip{manifest.clip_index}"
                f"_{int(manifest.timestamp)}.json"
            )
            (_MANIFEST_DIR / fname).write_text(
                json.dumps(asdict(manifest), indent=2)
            )
        except Exception as exc:
            logger.debug("Failed to save render manifest: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────

_loop: "LearningLoop | None" = None


def get_learning_loop() -> LearningLoop:
    global _loop
    if _loop is None:
        _loop = LearningLoop()
    return _loop
