"""
Word-Level Confidence Subtitling
Uses faster-whisper probability scores for semantic color coding
MIT License - Unique visual effect impossible to replicate with other tools
"""
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Confidence-based color mapping
# Counter-intuitive: LOW confidence = interesting/rare words = highlight
CONFIDENCE_COLOR_MAP = {
    "high": "#FFFFFF",      # > 0.95: Common words - bright white
    "medium": "#FFD700",    # 0.80-0.95: Standard terms - gold
    "low": "#FF6B35",       # < 0.80: Rare/technical terms - orange impact
    "very_low": "#FF1744"   # < 0.60: Unclear/unique - red attention
}


@dataclass
class WordConfidence:
    """Word with confidence metadata"""
    text: str
    start: float
    end: float
    probability: float
    color: str
    is_emphasis: bool  # True if low confidence (rare word)


@dataclass  
class ColoredSubtitleSegment:
    """Subtitle segment with word-level colors"""
    text: str
    start: float
    end: float
    words: List[WordConfidence]
    dominant_color: str
    has_rare_words: bool


class ConfidenceSubtitleGenerator:
    """
    Generates confidence-colored subtitles using faster-whisper
    Inverted logic: low confidence = visually highlighted
    """
    
    def __init__(self, model_size: str = "large-v3", device: str = "auto"):
        self.model_size = model_size
        # Resolve device: "auto" → detect; "cuda" → validate CUDA available first
        if device in ("auto", "cuda"):
            import os as _os
            _env_dev = _os.environ.get("WHISPER_DEVICE", "cpu").lower()
            if _env_dev == "cuda":
                try:
                    import torch as _torch
                    device = "cuda" if _torch.cuda.is_available() else "cpu"
                except ImportError:
                    device = "cpu"
            else:
                device = _env_dev if _env_dev in ("cpu", "cuda") else "cpu"
        self.device = device
        self.model = None
        
        # Confidence thresholds
        self.high_threshold = 0.95
        self.medium_threshold = 0.80
        self.low_threshold = 0.60
    
    def _load_model(self):
        """Lazy load faster-whisper model"""
        if self.model is None:
            try:
                from faster_whisper import WhisperModel
                
                compute_type = "float16" if self.device == "cuda" else "int8"
                self.model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=compute_type
                )
                logger.info(f"Loaded faster-whisper {self.model_size} on {self.device}")
            except ImportError:
                logger.error("faster-whisper not installed. Run: pip install faster-whisper")
                raise
    
    def transcribe_with_confidence(
        self, 
        audio_path: str,
        language: Optional[str] = None
    ) -> List[ColoredSubtitleSegment]:
        """
        Transcribe audio with word-level confidence scoring
        
        Args:
            audio_path: Path to audio file
            language: Optional language code (auto-detect if None)
            
        Returns:
            List of colored subtitle segments
        """
        self._load_model()
        
        logger.info(f"Transcribing with confidence: {audio_path}")
        
        # Transcribe with word timestamps
        segments, info = self.model.transcribe(
            audio_path,
            language=language,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        
        logger.info(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")
        
        colored_segments = []
        
        for segment in segments:
            words = []
            
            if segment.words:
                for word in segment.words:
                    # Determine color based on confidence
                    prob = word.probability
                    
                    if prob > self.high_threshold:
                        color = CONFIDENCE_COLOR_MAP["high"]
                        is_emphasis = False
                    elif prob > self.medium_threshold:
                        color = CONFIDENCE_COLOR_MAP["medium"]
                        is_emphasis = False
                    elif prob > self.low_threshold:
                        color = CONFIDENCE_COLOR_MAP["low"]
                        is_emphasis = True  # Rare word!
                    else:
                        color = CONFIDENCE_COLOR_MAP["very_low"]
                        is_emphasis = True
                    
                    words.append(WordConfidence(
                        text=word.word.strip(),
                        start=word.start,
                        end=word.end,
                        probability=prob,
                        color=color,
                        is_emphasis=is_emphasis
                    ))
                
                # Calculate segment metadata
                has_rare = any(w.is_emphasis for w in words)
                dominant_color = self._calculate_dominant_color(words)
                
                colored_segments.append(ColoredSubtitleSegment(
                    text=segment.text.strip(),
                    start=segment.start,
                    end=segment.end,
                    words=words,
                    dominant_color=dominant_color,
                    has_rare_words=has_rare
                ))
        
        # Log statistics
        total_words = sum(len(s.words) for s in colored_segments)
        rare_words = sum(1 for s in colored_segments for w in s.words if w.is_emphasis)
        
        logger.info(f"Transcription complete: {len(colored_segments)} segments, "
                   f"{total_words} words, {rare_words} rare/technical terms highlighted")
        
        return colored_segments
    
    def _calculate_dominant_color(self, words: List[WordConfidence]) -> str:
        """Calculate the dominant color for a segment"""
        if not words:
            return CONFIDENCE_COLOR_MAP["high"]
        
        # Weight by confidence (but inverted - low confidence = more visual weight)
        color_weights = {}
        for word in words:
            color_weights[word.color] = color_weights.get(word.color, 0) + 1
        
        # Return most common
        return max(color_weights.items(), key=lambda x: x[1])[0]
    
    def generate_colored_srt(
        self,
        segments: List[ColoredSubtitleSegment],
        output_path: str
    ):
        """Generate SRT with color tags for word-level coloring"""
        def format_time(seconds: float) -> str:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            millis = int((seconds % 1) * 1000)
            return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
        
        with open(output_path, 'w', encoding='utf-8') as f:
            for i, segment in enumerate(segments, 1):
                # SRT entry header
                f.write(f"{i}\n")
                f.write(f"{format_time(segment.start)} --> {format_time(segment.end)}\n")
                
                # Colored text with HTML-style tags
                colored_text_parts = []
                for word in segment.words:
                    # Use font color tags
                    colored_text_parts.append(
                        f'<font color="{word.color}">{word.text}</font>'
                    )
                
                colored_text = " ".join(colored_text_parts)
                f.write(f"{colored_text}\n\n")
        
        logger.info(f"Generated colored SRT: {output_path}")
    
    def get_high_impact_moments(
        self,
        segments: List[ColoredSubtitleSegment],
        min_rare_words: int = 2
    ) -> List[Tuple[float, float, str]]:
        """
        Identify high-impact moments based on rare word density
        
        Returns:
            List of (start, end, reason) tuples for viral moments
        """
        moments = []
        
        for segment in segments:
            rare_count = sum(1 for w in segment.words if w.is_emphasis)
            
            if rare_count >= min_rare_words:
                moments.append((
                    segment.start,
                    segment.end,
                    f"technical_terms_{rare_count}"
                ))
        
        logger.info(f"Found {len(moments)} high-impact moments with rare words")
        return moments
    
    def realign_on_segment(
        self,
        segment_video_path: str,
        original_words: Optional[List[Dict]] = None,
        language: Optional[str] = None,
        anticipation_offset_ms: float = -50.0
    ) -> List[Dict[str, Any]]:
        """
        Re-transcribe un clip ya cortado para obtener timestamps exactos.

        El video original puede tener drift de 200-500ms en transcripciones largas.
        Al re-transcribir solo el segmento (15-60s), faster-whisper da timestamps
        con precision de +-30ms.

        Args:
            segment_video_path: Ruta al clip ya cortado (el .mp4 que sale de create_optimized_clip)
            original_words: Palabras remapeadas del video original (para validacion)
            language: Codigo de idioma ('es', 'en', etc.)
            anticipation_offset_ms: Offset en ms para que subtitulos aparezcan
                                    ligeramente ANTES de la palabra (-50ms = aparece 50ms antes)

        Returns:
            Lista de dicts compatibles con words_with_confidence:
            [{"word": str, "start": float_seconds, "end": float_seconds,
              "confidence": float, "is_emphasis": bool}]
        """
        import subprocess
        import tempfile

        logger.info(f"[RE-ALIGN] Transcribiendo segmento: {segment_video_path}")

        # Normalizar codigo ISO 639-3 → ISO 639-1 (faster-whisper solo acepta 2 letras)
        _ISO3_TO_ISO1 = {
            "eng": "en", "spa": "es", "fra": "fr", "deu": "de", "ita": "it",
            "por": "pt", "rus": "ru", "zho": "zh", "jpn": "ja", "kor": "ko",
            "ara": "ar", "hin": "hi", "nld": "nl", "pol": "pl", "tur": "tr",
            "vie": "vi", "tha": "th", "swe": "sv", "nor": "no", "dan": "da",
        }
        if language and len(language) == 3:
            language = _ISO3_TO_ISO1.get(language.lower(), None)

        # Paso 1: Extraer audio WAV del segmento (16kHz mono, optimo para Whisper)
        tmp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_audio_path = tmp_audio.name
        tmp_audio.close()

        try:
            extract_cmd = [
                'ffmpeg', '-y', '-i', segment_video_path,
                '-vn',                    # Sin video
                '-acodec', 'pcm_s16le',   # WAV sin compresion
                '-ar', '16000',           # 16kHz (optimo Whisper)
                '-ac', '1',               # Mono
                tmp_audio_path
            ]
            result = subprocess.run(extract_cmd, capture_output=True, timeout=30)
            if result.returncode != 0:
                logger.error(f"[RE-ALIGN] FFmpeg fallo: {result.stderr.decode()}")
                return original_words or []

            # Paso 2: Transcribir con faster-whisper (self.model ya esta cargado)
            self._load_model()
            segments_iter, info = self.model.transcribe(
                tmp_audio_path,
                language=language,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=300),
                beam_size=5
            )

            # Paso 3: Construir lista de palabras con offset de anticipacion
            offset_s = anticipation_offset_ms / 1000.0  # Convertir a segundos
            realigned_words = []

            for segment in segments_iter:
                if not segment.words:
                    continue
                for word in segment.words:
                    word_text = word.word.strip()
                    if not word_text:
                        continue
                    realigned_words.append({
                        'word': word_text,
                        'text': word_text,  # Ambos campos por compatibilidad
                        'start': max(0.0, round(word.start + offset_s, 3)),
                        'end': round(word.end + offset_s, 3),
                        'confidence': round(word.probability, 3),
                        'is_emphasis': word.probability < 0.80
                    })

            logger.info(f"[RE-ALIGN] {len(realigned_words)} palabras re-alineadas")

            # Paso 4: Validacion contra palabras originales (si las hay)
            if original_words and realigned_words:
                orig_text = ' '.join(
                    w.get('word', w.get('text', '')) for w in original_words
                ).lower().strip()
                new_text = ' '.join(w['word'] for w in realigned_words).lower().strip()

                from difflib import SequenceMatcher
                similarity = SequenceMatcher(None, orig_text, new_text).ratio()
                logger.info(f"[RE-ALIGN] Similitud texto: {similarity:.1%}")

                if similarity < 0.70:
                    logger.warning(
                        f"[RE-ALIGN] Similitud muy baja ({similarity:.1%}). "
                        "Usando palabras originales como fallback."
                    )
                    return original_words

            # Paso 5: Transferir flags de emphasis del original si los tiene
            if original_words:
                _transfer_emphasis_flags(realigned_words, original_words)

            return realigned_words

        except Exception as e:
            logger.error(f"[RE-ALIGN] Error: {e}")
            return original_words or []
        finally:
            Path(tmp_audio_path).unlink(missing_ok=True)


def _transfer_emphasis_flags(realigned: List[Dict], original: List[Dict]):
    """
    Copia is_emphasis del original al realineado cuando las palabras coinciden.
    Usa matching por texto, no por posicion (pueden diferir en cantidad).
    """
    orig_emphasis = set()
    for w in original:
        if w.get('is_emphasis', False):
            orig_emphasis.add(w.get('word', w.get('text', '')).lower().strip())

    for w in realigned:
        if w['word'].lower().strip() in orig_emphasis:
            w['is_emphasis'] = True


def create_confidence_colored_subtitles(
    video_path: str,
    output_srt_path: str,
    model_size: str = "large-v3"
) -> bool:
    """
    Convenience function: extract audio and create colored subtitles
    
    Args:
        video_path: Path to video file
        output_srt_path: Output SRT file path
        model_size: faster-whisper model size
        
    Returns:
        True if successful
    """
    from moviepy import VideoFileClip
    import tempfile
    
    try:
        # Extract audio
        video = VideoFileClip(video_path)
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            audio_path = tmp.name
        
        video.audio.write_audiofile(
            audio_path,
            fps=16000,
            nbytes=2,
            codec='pcm_s16le',
            verbose=False,
            logger=None
        )
        video.close()
        
        # Generate colored subtitles
        generator = ConfidenceSubtitleGenerator(model_size=model_size, device="cpu")
        segments = generator.transcribe_with_confidence(audio_path)
        generator.generate_colored_srt(segments, output_srt_path)
        
        # Cleanup
        Path(audio_path).unlink(missing_ok=True)
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to create colored subtitles: {e}")
        return False


# Example usage
if __name__ == "__main__":
    # Test transcription
    test_audio = "test_audio.mp3"
    if Path(test_audio).exists():
        gen = ConfidenceSubtitleGenerator(model_size="base", device="cpu")
        segments = gen.transcribe_with_confidence(test_audio)
        
        print(f"\nSegments: {len(segments)}")
        for seg in segments[:3]:
            rare = [w.text for w in seg.words if w.is_emphasis]
            print(f"[{seg.start:.1f}s] {seg.text[:50]}...")
            if rare:
                print(f"  Rare words highlighted: {rare}")
