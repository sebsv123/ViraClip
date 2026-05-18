"""
Shorts Highlight Engine — LLM-based highlight detection + OpenCV face-aware crop.

Extracted and adapted from two open-source YouTube Shorts generators:
  - samuraigpt/ai-youtube-shorts-generator (highlights.py — LLM scoring of transcript moments)
  - SaarD00/AI-Youtube-Shorts-Generator (local/clipper.py — OpenCV face-tracking vertical crop)

Design:
  - Pluggable LLM backend via `llm_fn` argument (defaults to Groq via LLMRouter).
  - Graceful degradation: any failure logs a warning and returns empty results.
  - Score fusion: overlapping segments from the existing pipeline get a +0.1 bonus;
    if fewer than N acceptable clips exist, new segments are created from highlights.
  - CropInfo dataclass for passing crop hints to FaceAutocropService.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)
from src.services.metrics_aggregator import record_event

# ── Types ──────────────────────────────────────────────────────────────────────

LLMFn = Callable[[str], str]

# Minimum acceptable overlap ratio for score fusion
OVERLAP_BONUS_RATIO = 0.3
OVERLAP_BONUS = 0.1
MIN_ACCEPTABLE_CLIPS = 3

# Default highlight duration range (seconds)
MIN_HIGHLIGHT_DURATION = 20
MAX_HIGHLIGHT_DURATION = 180
SWEET_SPOT_MIN = 45
SWEET_SPOT_MAX = 90


@dataclass
class CropInfo:
    """Crop hint produced by the Shorts Highlight Engine.

    Passed to FaceAutocropService.process() to guide the crop window.
    When present, the autocrop service can use these hints instead of
    running full-frame face detection.
    """
    x: int          # Left edge of the crop window (pixels)
    y: int          # Top edge of the crop window (pixels)
    width: int      # Width of the crop window (pixels)
    height: int     # Height of the crop window (pixels)
    source_width: int   # Original frame width
    source_height: int  # Original frame height
    confidence: float = 1.0  # How confident we are in this crop (0-1)


@dataclass
class Highlight:
    """A single highlight segment identified by the engine."""
    title: str
    start_time: float
    end_time: float
    score: float
    hook_sentence: str = ""
    virality_reason: str = ""
    crop_info: Optional[CropInfo] = None


# ── LLM Prompts (ported from samuraigpt/ai-youtube-shorts-generator) ────────────

CONTENT_TYPE_PROMPT = """Analyze this video transcript sample and classify the content type.
Choose one: podcast, interview, tutorial, lecture, commentary, debate, vlog, other.
Also estimate content density: low (mostly filler/chit-chat), medium, or high (dense info/stories).
Respond with JSON only: {"content_type": "...", "density": "..."}"""

VIRALITY_CRITERIA = """
Virality signals to prioritize (ranked by impact):
1. HOOK MOMENTS — statements that create immediate curiosity ("The secret is...", "Nobody talks about...", "I was completely wrong about...")
2. EMOTIONAL PEAKS — genuine surprise, laughter, anger, vulnerability, excitement; raw unscripted reactions
3. OPINION BOMBS — strong, polarizing or counter-intuitive statements that trigger agree/disagree
4. REVELATION MOMENTS — surprising facts, stats, or confessions that reframe how the viewer thinks
5. CONFLICT/TENSION — disagreement, pushback, or a problem being confronted head-on
6. QUOTABLE ONE-LINERS — a sentence that works as a standalone quote card
7. STORY PEAKS — the climax or twist of an anecdote; the payoff moment
8. PRACTICAL VALUE — a concrete tip, hack, or insight the viewer can immediately apply
"""

HIGHLIGHT_SYSTEM_PROMPT = """You are an elite short-form video editor who has studied thousands of viral clips on TikTok, Instagram Reels, and YouTube Shorts. You know exactly what makes viewers stop scrolling, watch to the end, and share.

{virality_criteria}

Content type: {content_type} | Density: {density}

Your task: identify the most viral-worthy highlights from the transcript.

Rules:
- Every highlight must open with a strong HOOK — a line that grabs attention within the first 3 seconds
- Duration sweet spot: 45-90 seconds. Go shorter (20-44s) only for a perfect standalone one-liner. Go longer (91-180s) only when a story arc needs full context to land
- Never cut mid-sentence or mid-thought — each clip must feel complete and self-contained
- Clips must not overlap significantly with each other
- Score 0-100 on viral potential (not general quality)
- {num_clips_instruction}
- For each highlight, identify the single best "hook_sentence" — the opening line that would make someone stop scrolling
- Explain in one sentence why this clip is viral ("virality_reason")

Respond ONLY with valid JSON (no markdown, no explanation):
{{"highlights":[{{"title":"string","start_time":float,"end_time":float,"score":int,"hook_sentence":"string","virality_reason":"string"}}]}}"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_json_loose(raw: str) -> Dict:
    """Parse JSON, stripping markdown fences if present."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start:end + 1])
        raise


def _build_transcript_text(transcript: Dict) -> str:
    """Build a timestamped text representation from transcript segments."""
    segments = transcript.get("segments", [])
    return "\n".join(f"[{s['start']:.1f}s] {s['text'].strip()}" for s in segments)


def _dedupe_highlights(highlights: List[Dict]) -> List[Dict]:
    """Drop a highlight if it overlaps >50% with a higher-scoring one already kept."""
    highlights = sorted(highlights, key=lambda x: float(x.get("score", 0)), reverse=True)
    kept: List[Dict] = []
    for h in highlights:
        h_start = float(h["start_time"])
        h_end = float(h["end_time"])
        h_dur = h_end - h_start
        overlapping = False
        for k in kept:
            latest_start = max(h_start, float(k["start_time"]))
            earliest_end = min(h_end, float(k["end_time"]))
            overlap = earliest_end - latest_start
            if overlap > 0 and overlap > 0.5 * h_dur:
                overlapping = True
                break
        if not overlapping:
            kept.append(h)
    return kept


def _ratio(aspect_ratio: str) -> float:
    """Parse '9:16' → 9/16, '1:1' → 1.0."""
    try:
        w, h = aspect_ratio.split(":")
        return float(w) / float(h)
    except (ValueError, ZeroDivisionError):
        return 9.0 / 16.0


# ── Score Fusion ───────────────────────────────────────────────────────────────

def fuse_scores(
    highlights: List[Highlight],
    existing_segments: List[Dict],
    min_clips: int = MIN_ACCEPTABLE_CLIPS,
) -> List[Highlight]:
    """Fuse highlight scores with existing pipeline segments.

    Strategy:
      1. For each existing segment, check if it overlaps with any highlight.
         If overlap > OVERLAP_BONUS_RATIO, add OVERLAP_BONUS to the highlight score.
      2. If total clips (highlights + existing) < min_clips, create new highlight
         entries from existing segments that don't overlap with any highlight.
      3. Return merged list sorted by score descending.

    Args:
        highlights: Highlights from the Shorts Highlight Engine.
        existing_segments: Existing clip segments from the pipeline.
        min_clips: Minimum number of acceptable clips to aim for.

    Returns:
        Merged and sorted list of highlights.
    """
    if not existing_segments:
        return sorted(highlights, key=lambda h: h.score, reverse=True)

    # Build a set of existing segment time ranges
    existing_ranges = []
    for seg in existing_segments:
        s = float(seg.get("start_time", seg.get("start", 0)))
        e = float(seg.get("end_time", seg.get("end", s + 60)))
        existing_ranges.append((s, e))

    # Apply overlap bonus to highlights
    fused = list(highlights)
    for h in fused:
        for s, e in existing_ranges:
            overlap_start = max(h.start_time, s)
            overlap_end = min(h.end_time, e)
            overlap_dur = overlap_end - overlap_start
            h_dur = h.end_time - h.start_time
            if h_dur > 0 and overlap_dur / h_dur > OVERLAP_BONUS_RATIO:
                h.score += OVERLAP_BONUS * 100  # scale to 0-100 range
                break

    # If we still have fewer than min_clips, create new highlights from
    # existing segments that don't overlap with any existing highlight.
    if len(fused) < min_clips:
        existing_highlight_ranges = [(h.start_time, h.end_time) for h in fused]
        for i, (s, e) in enumerate(existing_ranges):
            if len(fused) >= min_clips:
                break
            # Check if this segment overlaps with any existing highlight
            overlaps = False
            for hs, he in existing_highlight_ranges:
                overlap_start = max(s, hs)
                overlap_end = min(e, he)
                if overlap_end - overlap_start > 0:
                    overlaps = True
                    break
            if not overlaps:
                seg = existing_segments[i]
                title = seg.get("title", seg.get("text", f"Segment {i + 1}")[:60])
                fused.append(Highlight(
                    title=title,
                    start_time=s,
                    end_time=e,
                    score=50.0,  # neutral score for pipeline segments
                    hook_sentence=title[:80] if len(title) > 10 else "",
                    virality_reason="Pipeline segment (no LLM highlight available)",
                ))

    return sorted(fused, key=lambda h: h.score, reverse=True)


# ── OpenCV Face-Aware Crop (ported from SaarD00/AI-Youtube-Shorts-Generator) ───

def compute_short_crop(
    frame_width: int,
    frame_height: int,
    aspect_ratio: str = "9:16",
    face_center_x: Optional[int] = None,
    face_center_y: Optional[int] = None,
) -> CropInfo:
    """Compute the optimal crop window for a given frame size and face position.

    Ported from _reframe_vertical() in local/clipper.py.

    Args:
        frame_width: Width of the source frame.
        frame_height: Height of the source frame.
        aspect_ratio: Target aspect ratio (e.g. "9:16").
        face_center_x: X coordinate of the face center (optional).
        face_center_y: Y coordinate of the face center (optional).

    Returns:
        CropInfo with the crop window coordinates.
    """
    target_ratio = _ratio(aspect_ratio)

    # Compute the largest crop that fits inside the frame at the target ratio
    if target_ratio < frame_width / frame_height:
        crop_h = frame_height
        crop_w = int(crop_h * target_ratio)
    else:
        crop_w = frame_width
        crop_h = int(crop_w / target_ratio)

    crop_w = max(2, crop_w - (crop_w % 2))
    crop_h = max(2, crop_h - (crop_h % 2))

    # Default to center of frame
    cx = face_center_x if face_center_x is not None else frame_width // 2
    cy = face_center_y if face_center_y is not None else frame_height // 2

    x0 = max(0, min(frame_width - crop_w, cx - crop_w // 2))
    y0 = max(0, min(frame_height - crop_h, cy - crop_h // 2))

    return CropInfo(
        x=x0,
        y=y0,
        width=crop_w,
        height=crop_h,
        source_width=frame_width,
        source_height=frame_height,
        confidence=0.8 if (face_center_x is not None and face_center_y is not None) else 0.5,
    )


def detect_face_center_opencv(
    frame_bytes: bytes,
    frame_width: int,
    frame_height: int,
) -> Optional[Tuple[int, int]]:
    """Detect the largest face in a frame using OpenCV Haar cascade.

    Ported from _reframe_vertical() in local/clipper.py.

    Args:
        frame_bytes: Raw frame bytes (BGR, no padding).
        frame_width: Width of the frame.
        frame_height: Height of the frame.

    Returns:
        (cx, cy) of the largest face, or None if no face detected.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        logger.warning("[ShortsHighlightEngine] OpenCV not available for face detection")
        return None

    try:
        arr = np.frombuffer(frame_bytes, dtype=np.uint8).reshape((frame_height, frame_width, 3))
        gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        if len(faces) > 0:
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            return (x + w // 2, y + h // 2)
        return None
    except Exception as exc:
        logger.warning("[ShortsHighlightEngine] Face detection failed: %s", exc)
        return None


# ── Default LLM backend ────────────────────────────────────────────────────────

def _default_llm_fn(prompt: str) -> str:
    """Default LLM backend: uses Groq via the existing LLMRouter infrastructure.

    Falls back to a simple rule-based response if LLM is unavailable.
    """
    try:
        from src.domains.ai.llm_router import LLMRouter
        import asyncio

        router = LLMRouter()
        # Use a simple synchronous wrapper around the async call
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                router._score_with_groq(prompt, "en", 3)
            )
            return json.dumps(result)
        finally:
            loop.close()
    except Exception as exc:
        logger.warning("[ShortsHighlightEngine] LLM call failed: %s", exc)
        # Return a minimal valid response so the pipeline doesn't break
        return json.dumps({"highlights": []})


# ── Main Engine ────────────────────────────────────────────────────────────────

class ShortsHighlightEngine:
    """LLM-based highlight detection + OpenCV crop for Shorts format.

    Usage:
        engine = ShortsHighlightEngine()
        highlights = await engine.find_highlights(transcript, num_clips=5)
        for h in highlights:
            crop = engine.compute_crop_for_highlight(video_path, h)
            # use crop with FaceAutocropService
    """

    def __init__(self, llm_fn: Optional[LLMFn] = None):
        self._llm_fn = llm_fn or _default_llm_fn

    async def find_highlights(
        self,
        transcript: Dict[str, Any],
        num_clips: int = 3,
        existing_segments: Optional[List[Dict]] = None,
    ) -> List[Highlight]:
        """Identify the most viral-worthy highlights from a transcript.

        Args:
            transcript: Dict with "segments" (list of {start, end, text}) and
                        optionally "duration".
            num_clips: Target number of highlight clips.
            existing_segments: Existing pipeline segments for score fusion.

        Returns:
            List of Highlight objects sorted by score descending.
            Empty list on any failure (graceful degradation).
        """
        try:
            raw_highlights = await self._get_highlights_raw(transcript, num_clips)
            highlights = self._highlights_from_raw(raw_highlights)

            # Apply score fusion if existing segments are provided
            if existing_segments:
                highlights = fuse_scores(highlights, existing_segments, min_clips=num_clips)

            # [Metrics] engine_shorts_engine
            record_event("engine_shorts_engine", payload={
                "highlights": len(highlights),
                "num_clips_requested": num_clips,
            })

            return highlights
        except Exception as exc:
            logger.warning(
                "[ShortsHighlightEngine] find_highlights failed: %s",
                exc,
                exc_info=True,
            )
            # [Metrics] engine_error
            record_event("engine_error", payload={
                "engine": "shorts_highlight_engine",
                "error": str(exc)[:200],
            })
            return []

    async def _get_highlights_raw(
        self,
        transcript: Dict,
        num_clips: int = 3,
    ) -> List[Dict]:
        """Core highlight detection logic (ported from get_highlights())."""
        duration = transcript.get("duration", 0)
        segments = transcript.get("segments", [])

        # Detect content type
        content_info = self._detect_content_type(transcript)

        # For long videos, chunk and process
        LONG_VIDEO_THRESHOLD = 1800  # 30 min
        CHUNK_SIZE_SECONDS = 1200    # 20 min
        CHUNK_OVERLAP_SECONDS = 60

        if duration >= LONG_VIDEO_THRESHOLD:
            chunks = self._chunk_transcript(
                transcript, CHUNK_SIZE_SECONDS, CHUNK_OVERLAP_SECONDS
            )
            all_highlights: List[Dict] = []
            for i, chunk in enumerate(chunks):
                offset = chunk.get("_offset", 0)
                text = _build_transcript_text(chunk)
                result = self._call_highlight_api(
                    text, content_info, chunk["duration"],
                    num_clips=num_clips, is_chunk=True,
                )
                for h in result.get("highlights", []):
                    h["start_time"] = float(h["start_time"]) + offset
                    h["end_time"] = float(h["end_time"]) + offset
                    all_highlights.append(h)
            highlights = _dedupe_highlights(all_highlights)
        else:
            text = _build_transcript_text(transcript)
            result = self._call_highlight_api(
                text, content_info, duration, num_clips=num_clips,
            )
            highlights = _dedupe_highlights(result.get("highlights", []))

        return highlights

    def _detect_content_type(self, transcript: Dict) -> Dict[str, str]:
        """Detect content type and density from transcript sample."""
        segments = transcript.get("segments", [])
        sample = " ".join(s["text"] for s in segments[:25])[:3000]
        prompt = f"{CONTENT_TYPE_PROMPT}\n\nTranscript sample:\n{sample}"
        try:
            raw = self._llm_fn(prompt)
            return _parse_json_loose(raw)
        except Exception:
            return {"content_type": "other", "density": "medium"}

    def _chunk_transcript(
        self,
        transcript: Dict,
        chunk_size: int,
        overlap: int,
    ) -> List[Dict]:
        """Split a long transcript into overlapping chunks."""
        segments = transcript.get("segments", [])
        duration = transcript.get("duration", segments[-1]["end"] if segments else 0)
        chunks = []
        start = 0
        while start < duration:
            end = min(start + chunk_size, duration)
            chunk_segs = [
                s for s in segments
                if s["start"] >= start and s["end"] <= end + overlap
            ]
            if chunk_segs:
                chunk = dict(transcript)
                chunk["segments"] = chunk_segs
                chunk["duration"] = end - start
                chunk["_offset"] = start
                chunks.append(chunk)
            start += chunk_size - overlap
        return chunks

    def _call_highlight_api(
        self,
        transcript_text: str,
        content_info: Dict,
        duration: float,
        num_clips: int = 3,
        is_chunk: bool = False,
    ) -> Dict:
        """Call the LLM to identify highlights in a transcript chunk."""
        target = max(num_clips * 2, 5)
        natural_max = max(2 if is_chunk else 3, int(duration / 90))
        min_clips = min(target, natural_max, 8)
        system = HIGHLIGHT_SYSTEM_PROMPT.format(
            virality_criteria=VIRALITY_CRITERIA,
            content_type=content_info.get("content_type", "other"),
            density=content_info.get("density", "medium"),
            num_clips_instruction=f"Generate at least {min_clips} highlights",
        )
        full_prompt = f"{system}\n\nTranscript:\n{transcript_text}"
        raw = self._llm_fn(full_prompt)
        return _parse_json_loose(raw)

    def _highlights_from_raw(self, raw_highlights: List[Dict]) -> List[Highlight]:
        """Convert raw dict highlights to Highlight dataclass instances."""
        result = []
        for h in raw_highlights:
            try:
                result.append(Highlight(
                    title=str(h.get("title", "")),
                    start_time=float(h.get("start_time", 0)),
                    end_time=float(h.get("end_time", 0)),
                    score=float(h.get("score", 0)),
                    hook_sentence=str(h.get("hook_sentence", "")),
                    virality_reason=str(h.get("virality_reason", "")),
                ))
            except (ValueError, TypeError) as exc:
                logger.warning("[ShortsHighlightEngine] Skipping invalid highlight: %s", exc)
        return result

    def compute_crop_for_highlight(
        self,
        video_path: str,
        highlight: Highlight,
        aspect_ratio: str = "9:16",
    ) -> Optional[CropInfo]:
        """Compute the optimal crop for a highlight by sampling a frame.

        Uses OpenCV to detect face position and compute the crop window.

        Args:
            video_path: Path to the source video.
            highlight: The highlight to compute crop for.
            aspect_ratio: Target aspect ratio.

        Returns:
            CropInfo or None if computation fails.
        """
        try:
            import cv2
        except ImportError:
            logger.warning("[ShortsHighlightEngine] OpenCV not available for crop computation")
            return None

        try:
            # Sample a frame from the middle of the highlight
            mid_time = (highlight.start_time + highlight.end_time) / 2
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise RuntimeError(f"Could not open {video_path}")

            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            frame_idx = int(mid_time * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                # Fall back to first frame
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()
                if not ret:
                    cap.release()
                    return None

            frame_height, frame_width = frame.shape[:2]

            # Detect face center
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40)
            )

            face_center = None
            if len(faces) > 0:
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                face_center = (x + w // 2, y + h // 2)

            cap.release()

            return compute_short_crop(
                frame_width=frame_width,
                frame_height=frame_height,
                aspect_ratio=aspect_ratio,
                face_center_x=face_center[0] if face_center else None,
                face_center_y=face_center[1] if face_center else None,
            )
        except Exception as exc:
            logger.warning(
                "[ShortsHighlightEngine] compute_crop_for_highlight failed: %s", exc
            )
            return None


# ── Singleton ──────────────────────────────────────────────────────────────────

_engine: "ShortsHighlightEngine | None" = None


def get_shorts_highlight_engine() -> ShortsHighlightEngine:
    """Get or create the singleton ShortsHighlightEngine."""
    global _engine
    if _engine is None:
        _engine = ShortsHighlightEngine()
    return _engine
