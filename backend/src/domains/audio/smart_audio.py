"""
Smart Audio — Phase 9 Creative Engine

FFmpeg-only audio mastering: EBU R128 loudnorm, BGM mixing, and
event-driven SFX injection triggered by the multimodal timeline.
No extra Python audio deps required — all through FFmpeg filters.
"""

import asyncio
import json
import logging
import os
import random
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# SFX filenames to look for (without extension) per event type/category
SFX_TRIGGER_MAP: dict[str, str] = {
    "hook":       "whoosh_fast",
    "impact":     "punch_impact",
    "energy":     "ding_chime",
    "audio_peak": "punch_impact",
    "keyword":    "whoosh_heavy",
    "transition":  "whoosh_fast",
    "emphasis":    "glitch_hit",
    "bass":        "bass_boom",
    "riser":       "tension_riser",
}

LOUDNESS_TARGET = -14.0  # LUFS — TikTok / Reels recommendation
BGM_VOLUME      = 0.10   # 10% of original volume for background music
SFX_BASE_VOL    = 0.35   # base SFX volume (scaled by event strength)


@dataclass
class _SfxEvent:
    t: float        # seconds relative to clip start
    sfx_path: str
    volume: float   # 0–1


class SmartAudio:
    """
    Audio mastering pipeline (all FFmpeg, no Python audio libs):

    1. Two-pass EBU R128 loudnorm for consistent perceived loudness.
    2. Event-driven SFX overlay via adelay + amix.
    3. Optional BGM mix at low volume (looped, no ducking complexity).
    """

    async def master(
        self,
        input_path: Path,
        output_path: Path,
        timeline_events: list,
        bgm_path: "Path | None" = None,
    ) -> Path:
        """
        Apply full mastering chain.

        Returns output_path on success, input_path as safe fallback.
        """
        try:
            current = input_path

            # Step 1: loudnorm
            normed = await self._loudnorm(current)
            if normed and normed.exists():
                current = normed

            # Step 2: SFX injection
            sfx_events = self._build_sfx_events(timeline_events)
            if sfx_events:
                with_sfx = await self._inject_sfx(current, sfx_events)
                if with_sfx and with_sfx.exists():
                    if current != input_path:
                        current.unlink(missing_ok=True)
                    current = with_sfx

            # Step 3: BGM mix
            if bgm_path and bgm_path.exists():
                with_bgm = await self._mix_bgm(current, bgm_path)
                if with_bgm and with_bgm.exists():
                    if current != input_path:
                        current.unlink(missing_ok=True)
                    current = with_bgm

            # Move final result to output_path
            if current != output_path:
                import shutil
                shutil.move(str(current), str(output_path))

            return output_path if output_path.exists() else input_path

        except Exception as exc:
            logger.warning("SmartAudio.master failed: %s", exc)
            return input_path

    # ── Loudnorm ──────────────────────────────────────────────────────────────

    async def _loudnorm(self, src: Path) -> "Path | None":
        """Two-pass EBU R128 loudnorm. Falls back to single-pass on parse errors."""
        tmp = Path(tempfile.mktemp(suffix=src.suffix, dir=src.parent))
        try:
            # Pass 1: measure
            p1 = await asyncio.create_subprocess_exec(
                "ffmpeg", "-hide_banner", "-loglevel", "info", "-y",
                "-i", str(src),
                "-af", f"loudnorm=I={LOUDNESS_TARGET}:TP=-2.0:LRA=11:print_format=json",
                "-f", "null", "-",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(p1.communicate(), timeout=60.0)
            stderr_text = stderr.decode(errors="ignore")

            match = re.search(r"\{[^}]+\}", stderr_text, re.DOTALL)
            if not match:
                raise ValueError("loudnorm JSON not found in stderr")

            stats = json.loads(match.group())

            # Pass 2: apply
            af2 = (
                f"loudnorm=I={LOUDNESS_TARGET}:TP=-2.0:LRA=11"
                f":measured_I={stats.get('input_i', -23)}"
                f":measured_LRA={stats.get('input_lra', 7)}"
                f":measured_TP={stats.get('input_tp', -2)}"
                f":measured_thresh={stats.get('input_thresh', -33)}"
                f":offset={stats.get('target_offset', 0)}"
                ":linear=true:print_format=none"
            )
            p2 = await asyncio.create_subprocess_exec(
                "ffmpeg", "-hide_banner", "-loglevel", "quiet", "-y",
                "-i", str(src),
                "-af", af2, "-c:v", "copy",
                str(tmp),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(p2.wait(), timeout=120.0)
            return tmp if tmp.exists() else None

        except (asyncio.TimeoutError, Exception) as exc:
            logger.debug("Loudnorm failed (%s), trying single-pass", exc)
            tmp.unlink(missing_ok=True)
            # Single-pass fallback
            try:
                tmp2 = Path(tempfile.mktemp(suffix=src.suffix, dir=src.parent))
                sp = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-hide_banner", "-loglevel", "quiet", "-y",
                    "-i", str(src),
                    "-af", f"loudnorm=I={LOUDNESS_TARGET}:TP=-2.0:LRA=11",
                    "-c:v", "copy", str(tmp2),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(sp.wait(), timeout=120.0)
                return tmp2 if tmp2.exists() else None
            except Exception:
                return None

    # ── SFX injection ─────────────────────────────────────────────────────────

    def _build_sfx_events(self, timeline_events: list) -> "list[_SfxEvent]":
        sfx_dir = Path(os.environ.get("SFX_LIBRARY_PATH", "/app/assets/sounds"))
        if not sfx_dir.exists():
            return []

        result: list[_SfxEvent] = []
        # Limit SFX to prevent audio drowning (max 20 per clip)
        MAX_SFX = 20
        for ev in timeline_events:
            if ev.strength < 0.6:
                continue
            if len(result) >= MAX_SFX:
                break
            sfx_name = (
                SFX_TRIGGER_MAP.get(ev.payload.get("category", ""))
                or SFX_TRIGGER_MAP.get(ev.type, "")
            )
            if not sfx_name:
                continue
            for ext in (".wav", ".mp3", ".ogg"):
                p = sfx_dir / f"{sfx_name}{ext}"
                if p.exists():
                    result.append(_SfxEvent(
                        t=ev.t,
                        sfx_path=str(p),
                        volume=round(min(1.0, SFX_BASE_VOL * ev.strength * 1.5), 3),
                    ))
                    break

        return result

    async def _inject_sfx(self, src: Path, sfx_events: "list[_SfxEvent]") -> "Path | None":
        """Overlay SFX at their timestamps via FFmpeg adelay + amix."""
        tmp = Path(tempfile.mktemp(suffix=src.suffix, dir=src.parent))
        try:
            inputs: list[str] = ["-i", str(src)]
            for ev in sfx_events:
                inputs += ["-i", ev.sfx_path]

            n = len(sfx_events)
            parts: list[str] = []
            for i, ev in enumerate(sfx_events):
                delay_ms = int(ev.t * 1000)
                parts.append(
                    f"[{i + 1}:a]adelay={delay_ms}|{delay_ms},"
                    f"volume={ev.volume}[sfx{i}]"
                )
            sfx_labels = "".join(f"[sfx{i}]" for i in range(n))
            parts.append(
                f"[0:a]{sfx_labels}amix=inputs={n + 1}:"
                "duration=first:normalize=1[aout]"
            )

            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-hide_banner", "-loglevel", "quiet", "-y",
                *inputs,
                "-filter_complex", ";".join(parts),
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac",
                str(tmp),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=120.0)
            return tmp if tmp.exists() else None

        except (asyncio.TimeoutError, Exception) as exc:
            logger.debug("SFX injection failed: %s", exc)
            tmp.unlink(missing_ok=True)
            return None

    # ── BGM mix ───────────────────────────────────────────────────────────────

    async def _mix_bgm(self, src: Path, bgm: Path) -> "Path | None":
        """Mix looped background music at BGM_VOLUME under speech."""
        tmp = Path(tempfile.mktemp(suffix=src.suffix, dir=src.parent))
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-hide_banner", "-loglevel", "quiet", "-y",
                "-i", str(src),
                "-stream_loop", "-1", "-i", str(bgm),
                "-filter_complex",
                f"[1:a]volume={BGM_VOLUME}[bgm];"
                "[0:a][bgm]amix=inputs=2:duration=first:normalize=1[aout]",
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac",
                str(tmp),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=120.0)
            return tmp if tmp.exists() else None

        except (asyncio.TimeoutError, Exception) as exc:
            logger.debug("BGM mix failed: %s", exc)
            tmp.unlink(missing_ok=True)
            return None


def find_bgm_track() -> "Path | None":
    """Return a random BGM track from known music directories (Docker mount: ./backend/music:/app/assets/sounds)."""
    search_dirs = [
        "/app/assets/sounds/bgm",    # dedicated BGM subfolder (preferred)
        "/app/assets/sounds/music",
        "/app/assets/sounds",         # top-level fallback (filters out SFX by name)
        "/app/music/bgm",
        "/app/music",
    ]
    bgm_exclude = {"whoosh", "punch", "ding", "bass", "tension", "glitch"}  # skip SFX
    for d in search_dirs:
        p = Path(d)
        if p.exists():
            candidates = [
                f for f in (list(p.glob("*.mp3")) + list(p.glob("*.wav")))
                if not any(ex in f.stem.lower() for ex in bgm_exclude)
            ]
            if candidates:
                return random.choice(candidates)
    return None


# ── Singleton ─────────────────────────────────────────────────────────────────

_smart_audio: "SmartAudio | None" = None


def get_smart_audio() -> SmartAudio:
    global _smart_audio
    if _smart_audio is None:
        _smart_audio = SmartAudio()
    return _smart_audio
