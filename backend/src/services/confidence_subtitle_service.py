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
    
    def __init__(self, model_size: str = "large-v3", device: str = "cuda"):
        self.model_size = model_size
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
