"""
Content Moderation Advanced Service
Entity recognition and inappropriate content detection with AI.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
import re

logger = logging.getLogger(__name__)


class ContentCategory(Enum):
    """Content moderation categories."""
    SAFE = "safe"
    SUGGESTIVE = "suggestive"
    VIOLENCE = "violence"
    HATE_SPEECH = "hate_speech"
    HARASSMENT = "harassment"
    SPAM = "spam"
    MISINFORMATION = "misinformation"
    COPYRIGHT = "copyright"


class EntityType(Enum):
    """Types of entities to recognize."""
    PERSON = "person"
    ORGANIZATION = "organization"
    LOCATION = "location"
    PRODUCT = "product"
    EVENT = "event"
    BRAND = "brand"


@dataclass
class DetectedEntity:
    """Detected entity information."""
    entity_id: str
    text: str
    type: EntityType
    confidence: float
    start_pos: int
    end_pos: int
    normalized_value: Optional[str]


@dataclass
class ModerationResult:
    """Content moderation result."""
    content_id: str
    is_appropriate: bool
    categories: List[ContentCategory]
    confidence_scores: Dict[str, float]
    entities: List[DetectedEntity]
    flagged_segments: List[Dict[str, Any]]
    recommended_action: str
    reviewed_at: str


class ContentModerationAdvancedService:
    """
    Advanced content moderation with entity recognition and AI detection.
    """
    
    def __init__(self):
        self._blocked_patterns: List[re.Pattern] = []
        self._sensitive_entities: Dict[str, List[str]] = {}
        self._moderation_history: List[ModerationResult] = []
        self._initialize_patterns()
    
    def _initialize_patterns(self):
        """Initialize detection patterns."""
        # Blocked word patterns
        blocked_words = [
            r"\b(hate|kill|attack|violence)\b",
            r"\b(explicit|nsfw|adult content)\b",
            r"\b(spam|scam|fake|fraud)\b",
        ]
        
        for pattern in blocked_words:
            self._blocked_patterns.append(re.compile(pattern, re.IGNORECASE))
        
        # Sensitive entities
        self._sensitive_entities = {
            "political": ["election", "vote", "party", "candidate"],
            "religious": ["religion", "faith", "belief", "worship"],
            "medical": ["diagnosis", "treatment", "medical", "health condition"]
        }
    
    async def moderate_content(
        self,
        content_id: str,
        text: Optional[str] = None,
        transcript: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ModerationResult:
        """
        Moderate content for appropriateness.
        
        Args:
            content_id: Content identifier
            text: Title or description text
            transcript: Video transcript
            metadata: Additional content metadata
        """
        categories = []
        confidence_scores = {}
        flagged_segments = []
        
        # Combine all text for analysis
        full_text = " ".join(filter(None, [text, transcript]))
        
        # Check blocked patterns
        pattern_score = await self._check_blocked_patterns(full_text)
        if pattern_score > 0.5:
            categories.append(ContentCategory.HATE_SPEECH)
            confidence_scores["hate_speech"] = pattern_score
        
        # Detect entities
        entities = await self._detect_entities(full_text)
        
        # Check for sensitive entity combinations
        sensitive_score = await self._check_sensitive_combinations(entities)
        if sensitive_score > 0.7:
            categories.append(ContentCategory.MISINFORMATION)
            confidence_scores["misinformation"] = sensitive_score
        
        # Check transcript for inappropriate segments
        if transcript:
            segments = await self._analyze_transcript_segments(transcript)
            flagged_segments.extend(segments)
        
        # Determine overall appropriateness
        is_appropriate = len(categories) == 0 and len(flagged_segments) == 0
        
        # Determine recommended action
        if not is_appropriate:
            max_score = max(confidence_scores.values()) if confidence_scores else 0
            if max_score > 0.9:
                recommended_action = "block"
            elif max_score > 0.7:
                recommended_action = "review"
            else:
                recommended_action = "warn"
        else:
            recommended_action = "approve"
        
        result = ModerationResult(
            content_id=content_id,
            is_appropriate=is_appropriate,
            categories=categories,
            confidence_scores=confidence_scores,
            entities=entities,
            flagged_segments=flagged_segments,
            recommended_action=recommended_action,
            reviewed_at=datetime.now().isoformat()
        )
        
        self._moderation_history.append(result)
        logger.info(f"Moderated content {content_id}: {recommended_action}")
        
        return result
    
    async def _check_blocked_patterns(self, text: str) -> float:
        """Check text against blocked patterns."""
        if not text:
            return 0.0
        
        matches = 0
        for pattern in self._blocked_patterns:
            if pattern.search(text):
                matches += 1
        
        # Calculate score based on match ratio
        score = min(1.0, matches / len(self._blocked_patterns))
        return score
    
    async def _detect_entities(self, text: str) -> List[DetectedEntity]:
        """Detect named entities in text."""
        entities = []
        
        if not text:
            return entities
        
        # Simple entity detection (in production, use spaCy or NER model)
        # Person names (capitalized words)
        person_pattern = re.compile(r"\b[A-Z][a-z]+\s[A-Z][a-z]+\b")
        for match in person_pattern.finditer(text):
            entities.append(DetectedEntity(
                entity_id=f"ent_{match.start()}",
                text=match.group(),
                type=EntityType.PERSON,
                confidence=0.7,
                start_pos=match.start(),
                end_pos=match.end(),
                normalized_value=None
            ))
        
        # Organizations (Corp, Inc, etc.)
        org_pattern = re.compile(r"\b[A-Z][a-zA-Z]*(?:\s[A-Z][a-zA-Z]*)*(?:\s(?:Corp|Inc|Ltd|LLC|Company))\b")
        for match in org_pattern.finditer(text):
            entities.append(DetectedEntity(
                entity_id=f"ent_{match.start()}",
                text=match.group(),
                type=EntityType.ORGANIZATION,
                confidence=0.8,
                start_pos=match.start(),
                end_pos=match.end(),
                normalized_value=None
            ))
        
        # Locations
        locations = ["USA", "UK", "Europe", "Asia", "America", "London", "Paris", "Tokyo"]
        for loc in locations:
            if loc in text:
                start = text.find(loc)
                entities.append(DetectedEntity(
                    entity_id=f"ent_{start}",
                    text=loc,
                    type=EntityType.LOCATION,
                    confidence=0.9,
                    start_pos=start,
                    end_pos=start + len(loc),
                    normalized_value=None
                ))
        
        return entities
    
    async def _check_sensitive_combinations(
        self,
        entities: List[DetectedEntity]
    ) -> float:
        """Check for sensitive entity combinations."""
        if not entities:
            return 0.0
        
        # Check if entities span multiple sensitive categories
        categories_found = set()
        
        for entity in entities:
            for category, keywords in self._sensitive_entities.items():
                if any(keyword.lower() in entity.text.lower() for keyword in keywords):
                    categories_found.add(category)
        
        # Higher score if multiple sensitive categories present
        score = len(categories_found) / len(self._sensitive_entities)
        return min(1.0, score)
    
    async def _analyze_transcript_segments(
        self,
        transcript: str
    ) -> List[Dict[str, Any]]:
        """Analyze transcript segments for inappropriate content."""
        flagged = []
        
        # Split into sentences/segments
        segments = re.split(r'[.!?]+', transcript)
        
        for i, segment in enumerate(segments):
            segment = segment.strip()
            if not segment:
                continue
            
            # Check segment
            score = await self._check_blocked_patterns(segment)
            
            if score > 0.3:
                flagged.append({
                    "segment_index": i,
                    "text": segment[:100] + "..." if len(segment) > 100 else segment,
                    "risk_score": score,
                    "timestamp": i * 10  # Approximate timestamp
                })
        
        return flagged
    
    async def moderate_batch(
        self,
        items: List[Dict[str, Any]]
    ) -> List[ModerationResult]:
        """Moderate multiple content items."""
        results = []
        
        for item in items:
            result = await self.moderate_content(
                content_id=item["id"],
                text=item.get("text"),
                transcript=item.get("transcript"),
                metadata=item.get("metadata")
            )
            results.append(result)
        
        return results
    
    def get_moderation_stats(self) -> Dict[str, Any]:
        """Get moderation statistics."""
        total = len(self._moderation_history)
        
        if total == 0:
            return {"total": 0}
        
        appropriate = len([r for r in self._moderation_history if r.is_appropriate])
        
        category_counts = {}
        for result in self._moderation_history:
            for cat in result.categories:
                category_counts[cat.value] = category_counts.get(cat.value, 0) + 1
        
        action_counts = {}
        for result in self._moderation_history:
            action_counts[result.recommended_action] = action_counts.get(result.recommended_action, 0) + 1
        
        return {
            "total": total,
            "appropriate": appropriate,
            "flagged": total - appropriate,
            "flag_rate": (total - appropriate) / total * 100,
            "by_category": category_counts,
            "by_action": action_counts,
            "avg_confidence": sum(
                max(r.confidence_scores.values()) if r.confidence_scores else 0
                for r in self._moderation_history
            ) / total
        }
    
    async def add_custom_pattern(self, pattern: str, category: ContentCategory) -> bool:
        """Add custom moderation pattern."""
        try:
            self._blocked_patterns.append(re.compile(pattern, re.IGNORECASE))
            return True
        except re.error:
            return False


# Global instance
_moderation_service: Optional[ContentModerationAdvancedService] = None


def get_content_moderation_service() -> ContentModerationAdvancedService:
    """Get global content moderation service."""
    global _moderation_service
    if _moderation_service is None:
        _moderation_service = ContentModerationAdvancedService()
    return _moderation_service
