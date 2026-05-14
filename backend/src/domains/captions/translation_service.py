"""
Translation service — multilingual subtitle burn.

Strategy (P5 fix):
  1. Use the existing word-level transcript (AssemblyAI / faster-whisper cache)
  2. Translate full text via Google Translate (free, no API key) or LibreTranslate (local)
  3. Build a translated SRT file
  4. Burn it into the clip with ffmpeg -vf subtitles=...

This replaces the broken SeamlessM4T approach (10GB model, never boots in practice).
The result is a video with burned-in translated subtitles — reliable on any machine with ffmpeg.
"""
import logging
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List, Dict
from src import gpu_utils

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Language code helpers
# ─────────────────────────────────────────────────────────────────────────────

# Map common short codes to Google Translate 2-letter codes
LANG_CODE_MAP: Dict[str, str] = {
    "eng": "en", "en": "en",
    "spa": "es", "es": "es",
    "fra": "fr", "fr": "fr",
    "deu": "de", "de": "de",
    "ita": "it", "it": "it",
    "por": "pt", "pt": "pt",
    "zho": "zh-CN", "zh": "zh-CN",
    "jpn": "ja", "ja": "ja",
    "kor": "ko", "ko": "ko",
    "rus": "ru", "ru": "ru",
    "ara": "ar", "ar": "ar",
    "hin": "hi", "hi": "hi",
    "nld": "nl", "nl": "nl",
    "pol": "pl", "pl": "pl",
    "tur": "tr", "tr": "tr",
    "swe": "sv", "sv": "sv",
    "nor": "no", "no": "no",
    "dan": "da", "da": "da",
}


def _normalize_lang(code: str) -> str:
    return LANG_CODE_MAP.get(code.lower(), code[:2].lower())


# ─────────────────────────────────────────────────────────────────────────────
# Free translation backend — tries Google Translate (unofficial), falls back
# to returning the original text (graceful degradation).
# ─────────────────────────────────────────────────────────────────────────────

def _translate_text(text: str, target_lang: str) -> str:
    """
    Translate `text` to `target_lang` using the unofficial Google Translate
    endpoint (no API key required, rate-limited to ~100 req/min).

    Falls back to the original text if the request fails so the clip is
    still generated (just without translation).
    """
    import urllib.request
    import urllib.parse

    tl = _normalize_lang(target_lang)
    if tl == "en" and len(text) < 50:
        # Probably already English — skip round-trip
        return text

    url = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl=auto&tl={tl}&dt=t&q={urllib.parse.quote(text)}"
    )
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # Response: [[[translated, original, ...], ...], ...]
        parts = [item[0] for item in data[0] if item[0]]
        return " ".join(parts).strip() or text
    except Exception as e:
        logger.warning(f"Translation request failed ({e}), using original text")
        return text


# ─────────────────────────────────────────────────────────────────────────────
# SRT generation from word-level transcript
# ─────────────────────────────────────────────────────────────────────────────

def _ms_to_srt_time(ms: int) -> str:
    h = ms // 3_600_000
    ms %= 3_600_000
    m = ms // 60_000
    ms %= 60_000
    s = ms // 1_000
    ms %= 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _build_translated_srt(
    words: List[Dict],
    clip_start_ms: int,
    clip_end_ms: int,
    target_lang: str,
    words_per_line: int = 5,
) -> str:
    """
    Build a translated SRT file from a word list filtered to the clip range.

    Words timestamps are absolute (from start of source video).
    clip_start_ms / clip_end_ms define the clip window.
    Output timestamps are relative to clip start (so t=0 = clip start).
    """
    # Filter words to clip range
    clip_words = [
        w for w in words
        if w.get("start", 0) >= clip_start_ms
        and w.get("end", 0) <= clip_end_ms + 500  # small tolerance
    ]
    if not clip_words:
        return ""

    # Group into lines of N words
    lines = []
    for i in range(0, len(clip_words), words_per_line):
        group = clip_words[i: i + words_per_line]
        group_text = " ".join(w.get("text", "") for w in group).strip()
        if not group_text:
            continue
        start_ms = group[0]["start"] - clip_start_ms
        end_ms = group[-1]["end"] - clip_start_ms
        if end_ms <= start_ms:
            end_ms = start_ms + 2000
        lines.append((start_ms, end_ms, group_text))

    if not lines:
        return ""

    # Translate all line texts in one batch (join → translate → split)
    separator = " ||| "
    combined = separator.join(t for _, _, t in lines)
    translated = _translate_text(combined, target_lang)
    translated_parts = translated.split(separator.strip())

    # Pad/truncate in case split count differs
    while len(translated_parts) < len(lines):
        translated_parts.append(lines[len(translated_parts)][2])
    translated_parts = translated_parts[: len(lines)]

    # Build SRT content
    srt_blocks = []
    for idx, ((start_ms, end_ms, _orig), trans_text) in enumerate(
        zip(lines, translated_parts), start=1
    ):
        srt_blocks.append(
            f"{idx}\n"
            f"{_ms_to_srt_time(max(0, start_ms))} --> {_ms_to_srt_time(max(0, end_ms))}\n"
            f"{trans_text.strip()}\n"
        )
    return "\n".join(srt_blocks)


# ─────────────────────────────────────────────────────────────────────────────
# Main service class
# ─────────────────────────────────────────────────────────────────────────────

class TranslationService:
    """
    Translate clip captions by:
      1. Loading the word-level transcript cache for the source video
      2. Translating the segment text via free Google Translate
      3. Burning translated subtitles into the output clip with ffmpeg

    No large model download required — works on any machine with ffmpeg.
    """

    async def dub_clip(
        self,
        video_path: Path,
        output_path: Path,
        target_lang: str = "en",
    ) -> None:
        """
        Create a translated version of `video_path` at `output_path`.

        Falls back to copying the original file if translation fails,
        so the pipeline never crashes due to a missing API key or network.
        """
        import shutil

        try:
            await self._burn_translated_subtitles(video_path, output_path, target_lang)
        except Exception as e:
            logger.error(f"Translation failed ({e}), falling back to original clip")
            shutil.copy2(str(video_path), str(output_path))

    async def _burn_translated_subtitles(
        self,
        video_path: Path,
        output_path: Path,
        target_lang: str,
    ) -> None:
        from ...video_processing import load_cached_transcript_data
        from ...video_processing.utils import parse_timestamp_to_seconds

        # Load transcript cache
        transcript = load_cached_transcript_data(video_path)
        words = transcript.get("words", []) if transcript else []

        if not words:
            logger.warning("No word-level transcript for translation, copying original")
            import shutil
            shutil.copy2(str(video_path), str(output_path))
            return

        # Determine clip timing from the video itself
        probe_cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", str(video_path),
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, timeout=15)
        clip_duration_s = 30.0  # fallback
        try:
            probe_data = json.loads(probe_result.stdout)
            for stream in probe_data.get("streams", []):
                dur = float(stream.get("duration", 0))
                if dur > 0:
                    clip_duration_s = dur
                    break
        except Exception:
            pass

        # Words are in milliseconds (AssemblyAI) or converted to ms by cache_transcript_data
        # We don't know the absolute offset of this clip — use relative timestamps (start at 0)
        clip_start_ms = 0
        clip_end_ms = int(clip_duration_s * 1000)

        # Normalise words to ms if they appear to be in seconds (faster-whisper)
        if words and words[0].get("start", 0) < 1000:
            words = [
                {**w, "start": int(w["start"] * 1000), "end": int(w["end"] * 1000)}
                for w in words
            ]

        srt_content = _build_translated_srt(
            words, clip_start_ms, clip_end_ms, target_lang
        )
        if not srt_content.strip():
            logger.warning("Empty SRT after translation — copying original")
            import shutil
            shutil.copy2(str(video_path), str(output_path))
            return

        # Write SRT to a temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".srt", delete=False, encoding="utf-8"
        ) as f:
            f.write(srt_content)
            srt_path = f.name

        try:
            # Burn subtitles with ffmpeg
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-vf", (
                    f"subtitles={srt_path}:force_style="
                    "'FontName=Arial,FontSize=18,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,"
                    "BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=40'"
                ),
                "-c:a", "copy",
                *gpu_utils.ffmpeg_codec_flags("high"),
                "-preset", "fast",
                "-crf", "23",
                str(output_path),
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode != 0:
                logger.error(
                    f"ffmpeg subtitle burn failed (rc={result.returncode}): "
                    f"{result.stderr[-500:].decode('utf-8', errors='replace')}"
                )
                raise RuntimeError("ffmpeg subtitle burn failed")
            logger.info(f"✅ Translated subtitles burned: {output_path.name} (lang={target_lang})")
        finally:
            try:
                Path(srt_path).unlink()
            except Exception:
                pass

    async def translate_speech_to_text(
        self, audio_path: Path, target_lang: str = "en"
    ) -> str:
        """Translate transcript text to target language (text-only, no audio)."""
        from ...video_processing import load_cached_transcript_data
        transcript = load_cached_transcript_data(audio_path.with_suffix(".mp4"))
        text = (transcript or {}).get("text", "")
        return _translate_text(text, target_lang) if text else ""
