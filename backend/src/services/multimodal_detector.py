"""
Multimodal Event Detector — Phase 9 Creative Engine

Generates a unified event timeline [{t, type, strength, duration, payload}]
by combining audio energy peaks and transcript keyword events.
This timeline is the single shared input to the creative render pipeline.
"""

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Keyword trigger tables ────────────────────────────────────────────────────

HOOK_KEYWORDS = {
    "increíble", "increible", "nunca", "secreto", "sorprendente", "descubre",
    "descubrir", "imposible", "incredible", "never", "secret", "discover",
    "surprising", "impossible", "unbelievable", "shocking",
}
IMPACT_KEYWORDS = {
    "top", "número", "numero", "primer", "primero", "mejor", "peor",
    "number", "first", "best", "worst", "most", "least", "biggest", "viral",
}
ENERGY_KEYWORDS = {
    "wow", "dios", "espera", "mira", "escucha", "wait", "look", "listen",
    "amazing", "seriously", "literally", "actually", "finally",
}


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class TimelineEvent:
    t: float          # timestamp in seconds, relative to clip start
    type: str         # "audio_peak" | "keyword" | "silence"
    strength: float   # 0.0–1.0
    duration: float   # seconds
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Detector ──────────────────────────────────────────────────────────────────

class MultimodalDetector:
    """
    Combines audio energy analysis + transcript keyword detection into
    a single sorted event timeline per clip segment.
    """

    def __init__(self) -> None:
        self._ffmpeg_ok = self._check_ffmpeg()

    # ── Public API ────────────────────────────────────────────────────────────

    async def generate_timeline(
        self,
        video_path: "str | Path",
        segment_start: float,
        segment_end: float,
        words: "list[dict] | None" = None,
    ) -> "list[TimelineEvent]":
        """
        Generate merged, time-sorted event timeline for a clip segment.

        Args:
            video_path:     Path to the source video.
            segment_start:  Clip start within the video (absolute seconds).
            segment_end:    Clip end within the video (absolute seconds).
            words:          Optional word dicts: [{start, end, word, confidence?}].

        Returns:
            Sorted list of TimelineEvent (t is relative to segment_start = 0).
        """
        tasks: list = [
            self._detect_audio_peaks(video_path, segment_start, segment_end),
        ]
        if words:
            # keyword detection is sync — wrap in a coroutine
            async def _keyword_coro():
                return self._detect_keyword_events(words, segment_start)
            tasks.append(_keyword_coro())

        results = await asyncio.gather(*tasks, return_exceptions=True)

        events: list[TimelineEvent] = []
        for r in results:
            if isinstance(r, list):
                events.extend(r)

        events.sort(key=lambda e: e.t)
        events = self._deduplicate(events)
        logger.debug(
            "Timeline: %d events for segment %.1f-%.1fs",
            len(events), segment_start, segment_end,
        )
        return events

    # ── Audio peak detection ──────────────────────────────────────────────────

    async def _detect_audio_peaks(
        self,
        video_path: "str | Path",
        start: float,
        end: float,
    ) -> "list[TimelineEvent]":
        """
        Extract audio energy peaks via FFmpeg astats filter.
        Returns events with t relative to segment start (t=0).
        """
        events: list[TimelineEvent] = []
        if not self._ffmpeg_ok:
            return events

        duration = max(0.1, end - start)
        try:
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "quiet",
                "-ss", str(start), "-t", str(duration),
                "-i", str(video_path),
                "-af",
                "astats=metadata=1:reset=1,"
                "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
                "-f", "null", "-",
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30.0)

            rms_values: list[tuple[float, float]] = []
            frame_idx = 0
            frame_step = 0.1  # astats reset=1 → ~0.1s frames

            for line in stdout.decode(errors="ignore").splitlines():
                if "lavfi.astats.Overall.RMS_level=" in line:
                    try:
                        val = float(line.split("=", 1)[1].strip())
                        rms_values.append((frame_idx * frame_step, val))
                        frame_idx += 1
                    except (ValueError, IndexError):
                        pass

            if not rms_values:
                return events

            valid_vals = [v for _, v in rms_values if v > -100]
            if not valid_vals:
                return events

            mean_rms = sum(valid_vals) / len(valid_vals)
            threshold = mean_rms + 6.0  # 6 dB above mean

            for t_rel, rms in rms_values:
                if rms > threshold and rms > -40:
                    strength = min(1.0, (rms - threshold) / 20.0 + 0.5)
                    events.append(TimelineEvent(
                        t=round(t_rel, 3),
                        type="audio_peak",
                        strength=round(strength, 3),
                        duration=0.2,
                        payload={"rms_db": round(rms, 2), "mean_db": round(mean_rms, 2)},
                    ))

        except asyncio.TimeoutError:
            logger.warning("Audio peak detection timed out for %s", video_path)
        except Exception as exc:
            logger.debug("Audio peak detection failed: %s", exc)

        return events

    # ── Keyword detection ─────────────────────────────────────────────────────

    def _detect_keyword_events(
        self,
        words: "list[dict]",
        segment_start: float,
    ) -> "list[TimelineEvent]":
        """
        Scan transcript words for hook/impact/energy triggers.
        Returns events with t relative to segment_start = 0.
        """
        events: list[TimelineEvent] = []
        for w in words:
            raw = w.get("word", "")
            word = raw.lower().strip(".,!?¡¿\"'")
            t_abs = float(w.get("start", 0.0))
            t_rel = max(0.0, t_abs - segment_start)
            w_dur = float(w.get("end", t_abs + 0.3)) - t_abs

            if word in HOOK_KEYWORDS:
                cat, strength = "hook", 0.9
            elif word in IMPACT_KEYWORDS:
                cat, strength = "impact", 0.7
            elif word in ENERGY_KEYWORDS or float(w.get("confidence", 0.0)) > 0.95:
                cat, strength = "energy", 0.5
            else:
                continue

            events.append(TimelineEvent(
                t=round(t_rel, 3),
                type="keyword",
                strength=strength,
                duration=round(max(0.1, w_dur), 3),
                payload={"word": word, "category": cat},
            ))

        return events

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _deduplicate(self, events: "list[TimelineEvent]") -> "list[TimelineEvent]":
        """Remove events of the same type within 0.1s — keep the stronger one."""
        if len(events) < 2:
            return events
        result: list[TimelineEvent] = []
        prev = events[0]
        for curr in events[1:]:
            if curr.type == prev.type and (curr.t - prev.t) < 0.1:
                prev = curr if curr.strength > prev.strength else prev
            else:
                result.append(prev)
                prev = curr
        result.append(prev)
        return result

    @staticmethod
    def _check_ffmpeg() -> bool:
        import subprocess
        try:
            subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True, check=True, timeout=5,
            )
            return True
        except Exception:
            return False


# ── Singleton ─────────────────────────────────────────────────────────────────

_detector: "MultimodalDetector | None" = None


def get_multimodal_detector() -> MultimodalDetector:
    global _detector
    if _detector is None:
        _detector = MultimodalDetector()
    return _detector
