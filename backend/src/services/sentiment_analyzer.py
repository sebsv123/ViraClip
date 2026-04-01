"""
Real-time Sentiment Analysis Service
Analyzes emotional tone and sentiment of video content in real-time.
"""

import logging
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class SentimentCategory(Enum):
    """Sentiment categories."""
    VERY_POSITIVE = "very_positive"
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    VERY_NEGATIVE = "very_negative"


class EmotionType(Enum):
    """Detected emotion types."""
    JOY = "joy"
    EXCITEMENT = "excitement"
    ANGER = "anger"
    SADNESS = "sadness"
    FEAR = "fear"
    SURPRISE = "surprise"
    NEUTRAL = "neutral"


@dataclass
class SentimentSegment:
    """Sentiment analysis for a transcript segment."""
    start_time: float
    end_time: float
    text: str
    sentiment_score: float  # -1 to 1
    confidence: float
    dominant_emotion: EmotionType
    keywords: List[str]


@dataclass
class SentimentAnalysisResult:
    """Complete sentiment analysis result."""
    overall_sentiment: float
    overall_category: SentimentCategory
    confidence: float
    segments: List[SentimentSegment]
    dominant_emotions: List[Tuple[EmotionType, float]]
    sentiment_trend: str  # improving, declining, stable
    viral_correlation: float  # Correlation with virality


class SentimentAnalyzer:
    """
    Real-time sentiment analysis for video transcripts.
    """
    
    # Sentiment lexicons
    POSITIVE_WORDS = [
        "amazing", "awesome", "excellent", "fantastic", "great", "good", "love",
        "best", "perfect", "wonderful", "brilliant", "incredible", "outstanding",
        "superb", "magnificent", "terrific", "fabulous", "remarkable", "exceptional",
        "happy", "excited", "thrilled", "delighted", "pleased", "satisfied",
        "win", "success", "victory", "achieve", "accomplish", "triumph"
    ]
    
    NEGATIVE_WORDS = [
        "terrible", "awful", "horrible", "bad", "worst", "hate", "dislike",
        "angry", "frustrated", "annoyed", "disappointed", "sad", "depressed",
        "fail", "failure", "lose", "loss", "wrong", "error", "mistake",
        "problem", "issue", "difficulty", "trouble", "concern", "worry",
        "fear", "scared", "afraid", "anxious", "nervous", "panic",
        "boring", "dull", "tedious", "monotonous", "lifeless"
    ]
    
    INTENSIFIERS = [
        "very", "extremely", "incredibly", "absolutely", "completely",
        "totally", "utterly", "quite", "really", "so", "too"
    ]
    
    NEGATORS = [
        "not", "no", "never", "neither", "nor", "barely", "hardly",
        "scarcely", "seldom", "rarely", "don't", "doesn't", "didn't",
        "wasn't", "weren't", "isn't", "aren't", "won't", "wouldn't",
        "can't", "cannot", "couldn't", "shouldn't"
    ]
    
    EMOTION_PATTERNS = {
        EmotionType.JOY: ["happy", "joy", "delighted", "cheerful", "elated"],
        EmotionType.EXCITEMENT: ["excited", "thrilled", "enthusiastic", "pumped", "hyped"],
        EmotionType.ANGER: ["angry", "furious", "mad", "irritated", "annoyed", "frustrated"],
        EmotionType.SADNESS: ["sad", "depressed", "disappointed", "melancholy", "gloomy"],
        EmotionType.FEAR: ["scared", "afraid", "terrified", "anxious", "worried", "nervous"],
        EmotionType.SURPRISE: ["surprised", "shocked", "amazed", "astonished", "wow", "unexpected"]
    }
    
    def __init__(self):
        self._analysis_history: List[Dict[str, Any]] = []
    
    async def analyze_transcript(
        self,
        transcript: str,
        segments: Optional[List[Tuple[float, float, str]]] = None
    ) -> SentimentAnalysisResult:
        """
        Analyze sentiment of video transcript.
        
        Args:
            transcript: Full transcript text
            segments: Optional list of (start_time, end_time, text) tuples
        """
        # If no segments provided, create basic segments
        if not segments:
            segments = self._create_segments(transcript)
        
        # Analyze each segment
        analyzed_segments = []
        for start, end, text in segments:
            segment_analysis = self._analyze_segment(start, end, text)
            analyzed_segments.append(segment_analysis)
        
        # Calculate overall sentiment
        overall_sentiment = self._calculate_overall_sentiment(analyzed_segments)
        
        # Determine category
        category = self._categorize_sentiment(overall_sentiment)
        
        # Find dominant emotions
        dominant_emotions = self._find_dominant_emotions(analyzed_segments)
        
        # Calculate trend
        trend = self._calculate_trend(analyzed_segments)
        
        # Estimate viral correlation
        viral_corr = self._estimate_viral_correlation(
            overall_sentiment, dominant_emotions, trend
        )
        
        result = SentimentAnalysisResult(
            overall_sentiment=overall_sentiment,
            overall_category=category,
            confidence=self._calculate_confidence(analyzed_segments),
            segments=analyzed_segments,
            dominant_emotions=dominant_emotions,
            sentiment_trend=trend,
            viral_correlation=viral_corr
        )
        
        # Store in history
        self._analysis_history.append({
            "timestamp": datetime.now().isoformat(),
            "overall_sentiment": overall_sentiment,
            "category": category.value,
            "viral_correlation": viral_corr
        })
        
        return result
    
    def _create_segments(
        self,
        transcript: str,
        segment_duration: float = 10.0
    ) -> List[Tuple[float, float, str]]:
        """Create time-based segments from transcript."""
        # Split by sentences
        sentences = re.split(r'(?<=[.!?])\s+', transcript)
        
        segments = []
        current_time = 0.0
        
        for sentence in sentences:
            if not sentence.strip():
                continue
            
            # Estimate duration based on word count (avg 150 words per minute)
            word_count = len(sentence.split())
            duration = (word_count / 150) * 60  # seconds
            
            segments.append((
                current_time,
                current_time + duration,
                sentence.strip()
            ))
            
            current_time += duration
        
        return segments
    
    def _analyze_segment(
        self,
        start: float,
        end: float,
        text: str
    ) -> SentimentSegment:
        """Analyze sentiment of a single segment."""
        text_lower = text.lower()
        words = text_lower.split()
        
        # Calculate base sentiment
        sentiment_score = 0.0
        pos_count = 0
        neg_count = 0
        
        i = 0
        while i < len(words):
            word = words[i]
            multiplier = 1.0
            
            # Check for negators
            if i > 0 and words[i-1] in self.NEGATORS:
                multiplier = -1.0
            
            # Check for intensifiers
            if i > 0 and words[i-1] in self.INTENSIFIERS:
                multiplier *= 1.5
            
            if word in self.POSITIVE_WORDS:
                sentiment_score += (0.5 * multiplier)
                pos_count += 1
            elif word in self.NEGATIVE_WORDS:
                sentiment_score -= (0.5 * multiplier)
                neg_count += 1
            
            i += 1
        
        # Normalize score
        total_words = len(words)
        if total_words > 0:
            sentiment_score = max(-1, min(1, sentiment_score / max(pos_count + neg_count, 1)))
        
        # Detect dominant emotion
        emotion_scores = {}
        for emotion, patterns in self.EMOTION_PATTERNS.items():
            score = sum(1 for pattern in patterns if pattern in text_lower)
            emotion_scores[emotion] = score
        
        dominant_emotion = max(emotion_scores, key=emotion_scores.get)
        if emotion_scores[dominant_emotion] == 0:
            dominant_emotion = EmotionType.NEUTRAL
        
        # Extract keywords
        keywords = [
            word for word in words
            if word in self.POSITIVE_WORDS or word in self.NEGATIVE_WORDS
        ][:5]
        
        # Calculate confidence
        confidence = min(1.0, (pos_count + neg_count) / max(len(words) * 0.1, 1))
        
        return SentimentSegment(
            start_time=start,
            end_time=end,
            text=text,
            sentiment_score=sentiment_score,
            confidence=confidence,
            dominant_emotion=dominant_emotion,
            keywords=keywords
        )
    
    def _calculate_overall_sentiment(
        self,
        segments: List[SentimentSegment]
    ) -> float:
        """Calculate overall sentiment score."""
        if not segments:
            return 0.0
        
        # Weight by confidence
        weighted_sum = sum(
            s.sentiment_score * s.confidence
            for s in segments
        )
        total_confidence = sum(s.confidence for s in segments)
        
        if total_confidence == 0:
            return 0.0
        
        return max(-1, min(1, weighted_sum / total_confidence))
    
    def _categorize_sentiment(self, score: float) -> SentimentCategory:
        """Categorize sentiment score."""
        if score >= 0.6:
            return SentimentCategory.VERY_POSITIVE
        elif score >= 0.2:
            return SentimentCategory.POSITIVE
        elif score <= -0.6:
            return SentimentCategory.VERY_NEGATIVE
        elif score <= -0.2:
            return SentimentCategory.NEGATIVE
        else:
            return SentimentCategory.NEUTRAL
    
    def _find_dominant_emotions(
        self,
        segments: List[SentimentSegment]
    ) -> List[Tuple[EmotionType, float]]:
        """Find dominant emotions across segments."""
        emotion_counts = {}
        
        for segment in segments:
            emotion = segment.dominant_emotion
            emotion_counts[emotion] = emotion_counts.get(emotion, 0) + segment.confidence
        
        # Sort by frequency
        sorted_emotions = sorted(
            emotion_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        # Normalize to percentages
        total = sum(count for _, count in sorted_emotions)
        if total > 0:
            return [
                (emotion, count / total)
                for emotion, count in sorted_emotions[:3]
            ]
        
        return [(EmotionType.NEUTRAL, 1.0)]
    
    def _calculate_trend(self, segments: List[SentimentSegment]) -> str:
        """Calculate sentiment trend."""
        if len(segments) < 3:
            return "stable"
        
        # Compare first half vs second half
        mid = len(segments) // 2
        first_half = segments[:mid]
        second_half = segments[mid:]
        
        first_avg = sum(s.sentiment_score for s in first_half) / len(first_half)
        second_avg = sum(s.sentiment_score for s in second_half) / len(second_half)
        
        diff = second_avg - first_avg
        
        if diff > 0.2:
            return "improving"
        elif diff < -0.2:
            return "declining"
        else:
            return "stable"
    
    def _estimate_viral_correlation(
        self,
        sentiment: float,
        emotions: List[Tuple[EmotionType, float]],
        trend: str
    ) -> float:
        """Estimate correlation with virality based on sentiment."""
        # Viral content often has:
        # - High excitement or surprise
        # - Positive sentiment
        # - Improving trend
        
        score = 0.5  # Base score
        
        # Positive sentiment boost
        if sentiment > 0.3:
            score += 0.2
        elif sentiment < -0.3:
            score -= 0.1
        
        # Emotion analysis
        for emotion, weight in emotions:
            if emotion in [EmotionType.EXCITEMENT, EmotionType.SURPRISE]:
                score += 0.15 * weight
            elif emotion == EmotionType.JOY:
                score += 0.1 * weight
            elif emotion in [EmotionType.ANGER, EmotionType.SADNESS]:
                score -= 0.05 * weight
        
        # Trend bonus
        if trend == "improving":
            score += 0.1
        
        return max(0, min(1, score))
    
    def _calculate_confidence(self, segments: List[SentimentSegment]) -> float:
        """Calculate overall confidence."""
        if not segments:
            return 0.0
        
        avg_confidence = sum(s.confidence for s in segments) / len(segments)
        return avg_confidence
    
    def get_historical_trends(self, days: int = 7) -> Dict[str, Any]:
        """Get sentiment trends from analysis history."""
        from datetime import timedelta
        
        cutoff = datetime.now() - timedelta(days=days)
        recent = [
            h for h in self._analysis_history
            if datetime.fromisoformat(h["timestamp"]) > cutoff
        ]
        
        if not recent:
            return {"error": "No data available"}
        
        avg_sentiment = sum(h["overall_sentiment"] for h in recent) / len(recent)
        avg_viral = sum(h["viral_correlation"] for h in recent) / len(recent)
        
        # Count categories
        categories = {}
        for h in recent:
            cat = h["category"]
            categories[cat] = categories.get(cat, 0) + 1
        
        return {
            "period_days": days,
            "analyses_count": len(recent),
            "average_sentiment": avg_sentiment,
            "average_viral_correlation": avg_viral,
            "category_distribution": categories,
            "trend_direction": "positive" if avg_sentiment > 0.2 else "negative" if avg_sentiment < -0.2 else "neutral"
        }


# Global instance
_sentiment_analyzer: Optional[SentimentAnalyzer] = None


def get_sentiment_analyzer() -> SentimentAnalyzer:
    """Get global sentiment analyzer instance."""
    global _sentiment_analyzer
    if _sentiment_analyzer is None:
        _sentiment_analyzer = SentimentAnalyzer()
    return _sentiment_analyzer


# Convenience functions
async def analyze_transcript_sentiment(
    transcript: str,
    segments: Optional[List[Tuple[float, float, str]]] = None
) -> SentimentAnalysisResult:
    """Analyze sentiment of a transcript."""
    return await get_sentiment_analyzer().analyze_transcript(transcript, segments)


def get_sentiment_for_virality(transcript: str) -> float:
    """Quick sentiment check for virality prediction."""
    import asyncio
    result = asyncio.run(get_sentiment_analyzer().analyze_transcript(transcript))
    return result.viral_correlation
