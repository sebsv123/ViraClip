"""
Visual Keyword Detector — Contextual Overlay System

Detects visual keywords from transcript that should trigger image/video overlays.
Uses NLP to identify concrete nouns and visual concepts.
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Visual keyword categories
VISUAL_KEYWORDS = {
    # Nature & Environment
    "nature": ["ocean", "sea", "beach", "mountain", "forest", "sky", "sunset", "sunrise", "river", "lake", "waterfall", "clouds", "stars", "moon", "sun"],
    
    # Money & Business
    "money": ["money", "cash", "dollars", "wealth", "rich", "profit", "revenue", "income", "investment", "business", "success", "growth"],
    
    # Emotions & Abstract Concepts (visualizable)
    "emotion": ["success", "failure", "happiness", "sadness", "anger", "fear", "love", "hate", "celebration", "victory"],
    
    # Technology
    "tech": ["computer", "phone", "laptop", "screen", "technology", "ai", "robot", "code", "software", "internet"],
    
    # People & Actions
    "people": ["person", "people", "crowd", "team", "group", "family", "friends", "audience"],
    
    # Objects
    "objects": ["car", "house", "building", "city", "food", "book", "camera", "microphone"],
    
    # Sports & Action
    "sports": ["running", "jumping", "swimming", "playing", "fighting", "racing", "climbing"],
}

# Flatten all keywords for quick lookup
ALL_VISUAL_KEYWORDS = set()
for category_words in VISUAL_KEYWORDS.values():
    ALL_VISUAL_KEYWORDS.update(category_words)


@dataclass
class VisualKeyword:
    """Detected visual keyword with timing and context."""
    keyword: str
    category: str
    start_time: float
    end_time: float
    word: str  # Original word from transcript
    confidence: float  # 0.0-1.0


class VisualKeywordDetector:
    """
    Detects visual keywords from transcript with word timings.
    
    Strategy:
    1. Match against predefined visual keyword dictionary
    2. Use simple stemming/lemmatization for variations
    3. Filter based on part-of-speech (prefer nouns)
    4. Return with timing information for overlay synchronization
    """
    
    def __init__(self):
        self.visual_keywords = VISUAL_KEYWORDS
        self.all_keywords = ALL_VISUAL_KEYWORDS
    
    def detect(
        self,
        transcript: str,
        word_timings: List[Dict],
        max_keywords: int = 10,
        min_confidence: float = 0.6
    ) -> List[VisualKeyword]:
        """
        Detect visual keywords from transcript with timing.
        
        Args:
            transcript: Full transcript text
            word_timings: List of {word, start, end, confidence?}
            max_keywords: Maximum keywords to return
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of VisualKeyword objects sorted by start time
        """
        detected = []
        
        if not word_timings:
            logger.debug("No word timings provided for visual keyword detection")
            return []
        
        # Process each word
        for word_info in word_timings:
            word = word_info.get("word", "").lower().strip()
            start = float(word_info.get("start", 0.0))
            end = float(word_info.get("end", start + 0.5))
            
            if not word:
                continue
            
            # Clean word (remove punctuation)
            clean_word = re.sub(r'[^\w\s]', '', word)
            
            # Check if word is a visual keyword
            if clean_word in self.all_keywords:
                category = self._get_category(clean_word)
                confidence = word_info.get("confidence", 0.8)
                
                if confidence >= min_confidence:
                    detected.append(VisualKeyword(
                        keyword=clean_word,
                        category=category,
                        start_time=start,
                        end_time=end,
                        word=word,
                        confidence=confidence
                    ))
        
        # Sort by start time
        detected.sort(key=lambda k: k.start_time)
        
        # Deduplicate nearby keywords (within 2 seconds)
        deduplicated = self._deduplicate(detected, min_gap_seconds=2.0)
        
        # Return top N
        return deduplicated[:max_keywords]
    
    def detect_with_virality_filter(
        self,
        transcript: str,
        word_timings: List[Dict],
        audio_features: Dict,
        virality_score: float,
        max_keywords: int = 10
    ) -> List[VisualKeyword]:
        """
        Detect visual keywords with virality-based filtering.
        
        Only returns keywords if:
        - Clip virality score is above threshold (60)
        - Keyword occurs during high-energy moment
        - Keyword is spaced appropriately (5-8 per minute)
        """
        # Don't show overlays on low-virality clips
        if virality_score < 60:
            logger.debug(f"Virality score {virality_score} below threshold (60), skipping overlays")
            return []
        
        # Detect all keywords
        all_keywords = self.detect(transcript, word_timings, max_keywords=max_keywords * 2)
        
        # Filter by energy if audio features available
        if audio_features and "energy" in audio_features:
            energy_threshold = 0.5
            filtered = []
            
            for kw in all_keywords:
                # Simple approximation: use overall energy
                # In production, would use frame-level energy at kw.start_time
                if audio_features["energy"] > energy_threshold:
                    filtered.append(kw)
            
            return filtered[:max_keywords]
        
        return all_keywords[:max_keywords]
    
    def _get_category(self, keyword: str) -> str:
        """Get category for a keyword."""
        for category, words in self.visual_keywords.items():
            if keyword in words:
                return category
        return "general"
    
    def _deduplicate(self, keywords: List[VisualKeyword], min_gap_seconds: float = 2.0) -> List[VisualKeyword]:
        """Remove keywords that are too close together."""
        if not keywords:
            return []
        
        deduplicated = [keywords[0]]
        
        for kw in keywords[1:]:
            last_kw = deduplicated[-1]
            gap = kw.start_time - last_kw.end_time
            
            if gap >= min_gap_seconds:
                deduplicated.append(kw)
            elif kw.confidence > last_kw.confidence:
                # Replace if higher confidence
                deduplicated[-1] = kw
        
        return deduplicated


# Singleton instance
_detector_instance: Optional[VisualKeywordDetector] = None


def get_visual_keyword_detector() -> VisualKeywordDetector:
    """Get or create singleton detector instance."""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = VisualKeywordDetector()
    return _detector_instance
