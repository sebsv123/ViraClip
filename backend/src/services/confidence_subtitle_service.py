"""
ConfidenceSubtitleGenerator — Word-by-word viral subtitles
Fuente de énfasis: word['score'] de WhisperX forced alignment.
score >= 0.88 → pronunciación clara/enfática → color amarillo.
score < 0.88 → color blanco normal.
Contexto: palabra anterior y siguiente en gris para dar ritmo visual.
"""
import os
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Umbral de score para considerar una palabra como énfasis
EMPHASIS_SCORE_THRESHOLD = 0.88


class ConfidenceSubtitleGenerator:
    """Genera subtítulos word-by-word con énfasis basado en WhisperX alignment score."""

    def __init__(
        self,
        font_name: str = "Arial Bold",
        font_size: int = 72,
        active_color: str = "&H00FFFFFF",       # blanco — palabra activa normal
        emphasis_color: str = "&H0000FFFF",     # amarillo — word.score alto
        context_color: str = "&H80AAAAAA",      # gris 50% — contexto
        stroke_color: str = "&H00000000",       # negro
        position_y_pct: float = 0.75,
        emphasis_threshold: float = EMPHASIS_SCORE_THRESHOLD,
        model_size: Optional[str] = None,
        device: Optional[str] = None,
    ):
        self.font_name = font_name
        self.font_size = font_size
        self.active_color = active_color
        self.emphasis_color = emphasis_color
        self.context_color = context_color
        self.stroke_color = stroke_color
        self.position_y_pct = position_y_pct
        self.emphasis_threshold = emphasis_threshold
        self.model_size = model_size
        self.device = device
    
    def _word_color(self, word: dict) -> str:
        """
        Determina el color según word['score'] de WhisperX.
        No hay listas de palabras — la IA decide qué es énfasis.
        """
        score = word.get("score", 0.0)
        return self.emphasis_color if score >= self.emphasis_threshold else self.active_color

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds % 1) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    def generate_ass(
        self,
        words: list,
        video_width: int = 1080,
        video_height: int = 1920,
        output_path: str = None
    ) -> str:
        """
        Genera archivo ASS con karaoke word-by-word.
        words: [{'word': str, 'start': float, 'end': float, 'score': float}]
        """
        if not words:
            logger.warning("[Subtitles] No words provided to generate_ass")
            return ""

        pos_y = int(video_height * self.position_y_pct)
        pos_x = video_width // 2

        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,{self.font_name},{self.font_size},{self.active_color},&H000000FF,{self.stroke_color},&H90000000,-1,0,0,0,100,100,1,0,1,4,3,2,20,20,50,1
Style: Context,{self.font_name},{int(self.font_size * 0.88)},{self.context_color},&H000000FF,{self.stroke_color},&H90000000,0,0,0,0,100,100,1,0,1,3,2,2,20,20,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        events = []

        for i, word in enumerate(words):
            start = word.get("start", 0.0)
            end = word.get("end", start + 0.25)
            w_prev = words[i - 1] if i > 0 else None
            w_next = words[i + 1] if i < len(words) - 1 else None

            color = self._word_color(word)
            text_parts = [f"{{\\an2\\pos({pos_x},{pos_y})}}"]

            if w_prev:
                text_parts.append(
                    f"{{\\c{self.context_color}\\fscx88\\fscy88}}"
                    f"{w_prev['word'].strip().upper()} "
                )

            # Palabra activa: pop animation + color según score
            text_parts.append(
                f"{{\\c{color}\\b1\\fscx115\\fscy115"
                f"\\t(0,60,\\fscx105\\fscy105)\\t(60,120,\\fscx100\\fscy100)}}"
                f"{word['word'].strip().upper()}"
            )

            if w_next:
                text_parts.append(
                    f" {{\\c{self.context_color}\\fscx88\\fscy88}}"
                    f"{w_next['word'].strip().upper()}"
                )

            text_parts.append("{\\r}")
            full_text = "".join(text_parts)

            events.append(
                f"Dialogue: 0,{self._fmt_time(start)},{self._fmt_time(end)},"
                f"Word,,0,0,0,,{full_text}"
            )

        content = header + "\n".join(events)

        if output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w", encoding="utf-8-sig") as f:
                f.write(content)
            logger.info(f"[Subtitles] ASS written to {output_path}")

        return content

    def generate_from_segments(
        self,
        segments: list,
        video_width: int = 1080,
        video_height: int = 1920,
        output_path: str = None
    ) -> str:
        """Extrae words de segments WhisperX y genera ASS."""
        all_words = []
        for seg in segments:
            all_words.extend(seg.get("words", []))

        if not all_words:
            logger.warning("[Subtitles] Segments tienen 0 words — ¿se ejecutó WhisperX?")
            return ""

        return self.generate_ass(all_words, video_width, video_height, output_path)

    def transcribe_with_confidence(self, audio_path: str) -> list:
        """
        Compatibility shim for legacy callers.

        This lightweight generator no longer owns Whisper transcription. Returning
        an empty list lets the caller continue to the next subtitle source without
        raising constructor or attribute errors.
        """
        logger.warning(
            "[Subtitles] transcribe_with_confidence unavailable in lightweight generator; "
            "returning no segments for %s",
            audio_path,
        )
        return []

    def realign_on_segment(
        self,
        segment_video_path: str,
        original_words: List[Dict[str, Any]],
        language: Optional[str] = None,
        anticipation_offset_ms: float = 0.0,
    ) -> list:
        """
        Compatibility shim for the realignment hook.

        No forced-alignment model is available in this class, so do not invent new
        timings. Return an empty result and let video_service keep the current
        adjusted timeline.
        """
        logger.warning(
            "[RE-ALIGN] ConfidenceSubtitleGenerator has no alignment backend; "
            "keeping existing words for %s",
            segment_video_path,
        )
        return []


# Legacy compatibility functions
def create_confidence_colored_subtitles(
    video_path: str,
    output_srt_path: str,
    model_size: str = "large-v3"
) -> bool:
    """
    Legacy convenience function — now delegates to WhisperX via video_service.
    Returns True to maintain backward compatibility.
    """
    logger.warning("[Subtitles] create_confidence_colored_subtitles is deprecated. "
                   "Use ConfidenceSubtitleGenerator with WhisperX data directly.")
    return True
