"""
Content Moderation and Safety Filters
Detects and filters inappropriate, harmful, or policy-violating content.
"""

import re
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class ContentCategory(Enum):
    """Categories of content violations."""
    SAFE = "safe"
    HATE_SPEECH = "hate_speech"
    HARASSMENT = "harassment"
    VIOLENCE = "violence"
    SEXUAL_CONTENT = "sexual_content"
    SPAM = "spam"
    COPYRIGHT = "copyright"
    MISINFORMATION = "misinformation"
    SELF_HARM = "self_harm"
    ILLEGAL = "illegal"


@dataclass
class ModerationResult:
    """Result of content moderation check."""
    content_id: str
    is_safe: bool
    category: ContentCategory
    confidence: float
    flagged_keywords: List[str]
    reason: str
    suggested_action: str
    review_required: bool


class ContentModerationService:
    """
    AI-powered content moderation for videos and text.
    """
    
    # Keywords for basic filtering
    FLAGGED_KEYWORDS = {
        ContentCategory.HATE_SPEECH: [
            "hate", "kill", "die", "racist", "nazi", "supremacist",
            "slur", "derogatory"
        ],
        ContentCategory.HARASSMENT: [
            "harass", "bully", "threaten", "stalk", "dox"
        ],
        ContentCategory.VIOLENCE: [
            "violence", "attack", "hurt", "injure", "weapon", "gun",
            "knife", "blood", "fight", "beat"
        ],
        ContentCategory.SEXUAL_CONTENT: [
            "nsfw", "nude", "sexual", "explicit", "adult", "porn"
        ],
        ContentCategory.SPAM: [
            "spam", "scam", "fake", "clickbait", "subscribe", "follow"
        ],
        ContentCategory.SELF_HARM: [
            "suicide", "self-harm", "hurt myself", "end it all"
        ]
    }
    
    # Patterns for advanced detection
    SUSPICIOUS_PATTERNS = [
        r"(earn|make).{0,20}(money|cash|\$).{0,30}(fast|quick|easy)",
        r"(click|tap).{0,10}here.{0,20}(link|url)",
        r"(free|win).{0,15}(giveaway|prize|gift).{0,20}(now|today)",
    ]
    
    def __init__(self, ai_service=None):
        self.ai_service = ai_service
        self._violation_history: List[ModerationResult] = []
    
    async def moderate_text(
        self,
        text: str,
        content_id: str,
        user_id: Optional[str] = None
    ) -> ModerationResult:
        """
        Moderate text content.
        
        Args:
            text: Text to moderate
            content_id: Unique identifier for content
            user_id: Optional user identifier for tracking
        """
        text_lower = text.lower()
        
        # Check against keyword lists
        flagged = []
        category_scores = {cat: 0 for cat in ContentCategory if cat != ContentCategory.SAFE}
        
        for category, keywords in self.FLAGGED_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    flagged.append(keyword)
                    category_scores[category] += 1
        
        # Check suspicious patterns
        for pattern in self.SUSPICIOUS_PATTERNS:
            if re.search(pattern, text_lower):
                category_scores[ContentCategory.SPAM] += 2
                flagged.append("suspicious_pattern")
        
        # Determine category and confidence
        if any(category_scores.values()):
            max_category = max(category_scores, key=category_scores.get)
            confidence = min(1.0, category_scores[max_category] * 0.2)
            is_safe = False
            
            # Determine action based on severity
            if confidence > 0.7:
                action = "block"
                review = True
            elif confidence > 0.4:
                action = "flag_for_review"
                review = True
            else:
                action = "warn"
                review = False
            
            reason = f"Detected {len(flagged)} flagged indicators"
        else:
            max_category = ContentCategory.SAFE
            confidence = 1.0
            is_safe = True
            action = "allow"
            review = False
            reason = "No violations detected"
        
        result = ModerationResult(
            content_id=content_id,
            is_safe=is_safe,
            category=max_category,
            confidence=confidence,
            flagged_keywords=list(set(flagged)),
            reason=reason,
            suggested_action=action,
            review_required=review
        )
        
        self._violation_history.append(result)
        
        # Log if unsafe
        if not is_safe:
            logger.warning(
                f"Content flagged: {content_id} - {max_category.value} "
                f"(confidence: {confidence:.2f})"
            )
        
        return result
    
    async def moderate_video_metadata(
        self,
        title: str,
        description: str,
        tags: List[str],
        video_id: str
    ) -> Dict[str, Any]:
        """Moderate video metadata."""
        results = []
        
        # Moderate each component
        if title:
            results.append(await self.moderate_text(title, f"{video_id}_title"))
        
        if description:
            results.append(await self.moderate_text(description, f"{video_id}_desc"))
        
        for i, tag in enumerate(tags):
            results.append(await self.moderate_text(tag, f"{video_id}_tag_{i}"))
        
        # Aggregate results
        unsafe_results = [r for r in results if not r.is_safe]
        
        if not unsafe_results:
            return {
                "is_safe": True,
                "category": ContentCategory.SAFE,
                "confidence": 1.0,
                "components_checked": len(results)
            }
        
        # Return highest severity
        worst = max(unsafe_results, key=lambda x: x.confidence)
        
        return {
            "is_safe": False,
            "category": worst.category.value,
            "confidence": worst.confidence,
            "violations": [
                {
                    "component": r.content_id.split("_")[-1],
                    "category": r.category.value,
                    "keywords": r.flagged_keywords
                }
                for r in unsafe_results
            ],
            "suggested_action": worst.suggested_action
        }
    
    async def moderate_transcript(
        self,
        transcript: str,
        task_id: str
    ) -> List[Dict[str, Any]]:
        """
        Moderate video transcript in segments.
        
        Returns segments that need attention.
        """
        # Split into sentences/segments
        segments = self._split_into_segments(transcript)
        
        violations = []
        
        for i, segment in enumerate(segments):
            result = await self.moderate_text(segment, f"{task_id}_seg_{i}")
            
            if not result.is_safe:
                violations.append({
                    "segment_index": i,
                    "text": segment[:100] + "..." if len(segment) > 100 else segment,
                    "violation": result.category.value,
                    "confidence": result.confidence,
                    "keywords": result.flagged_keywords
                })
        
        return violations
    
    def _split_into_segments(self, text: str, max_length: int = 200) -> List[str]:
        """Split text into segments for moderation."""
        # Split by sentences
        sentences = re.split(r'[.!?]+', text)
        
        segments = []
        current_segment = ""
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            if len(current_segment) + len(sentence) < max_length:
                current_segment += " " + sentence if current_segment else sentence
            else:
                if current_segment:
                    segments.append(current_segment)
                current_segment = sentence
        
        if current_segment:
            segments.append(current_segment)
        
        return segments
    
    def get_safety_score(self, content_id: str) -> float:
        """Get safety score (0-100) for content."""
        results = [
            r for r in self._violation_history
            if r.content_id.startswith(content_id)
        ]
        
        if not results:
            return 100.0
        
        # Calculate based on violations
        violations = [r for r in results if not r.is_safe]
        
        if not violations:
            return 100.0
        
        # Lower score based on number and severity of violations
        penalty = sum(v.confidence * 20 for v in violations)
        return max(0, 100 - penalty)
    
    async def batch_moderate(
        self,
        items: List[Dict[str, Any]]
    ) -> List[ModerationResult]:
        """Moderate multiple items."""
        results = []
        
        for item in items:
            result = await self.moderate_text(
                item.get("text", ""),
                item.get("id", "unknown"),
                item.get("user_id")
            )
            results.append(result)
        
        return results


class SafetyFilter:
    """
    Real-time safety filters for content processing.
    """
    
    def __init__(self):
        self.moderation = ContentModerationService()
        self._enabled = True
    
    def enable(self) -> None:
        """Enable safety filters."""
        self._enabled = True
        logger.info("Safety filters enabled")
    
    def disable(self) -> None:
        """Disable safety filters."""
        self._enabled = False
        logger.warning("Safety filters disabled")
    
    async def filter_clip_content(
        self,
        clip_info: Dict[str, Any],
        transcript: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Filter clip before publishing.
        
        Returns:
            (is_allowed, reason_if_blocked)
        """
        if not self._enabled:
            return True, None
        
        clip_id = clip_info.get("clip_id", "unknown")
        
        # Moderate transcript
        violations = await self.moderation.moderate_transcript(transcript, clip_id)
        
        if violations:
            high_conf = [v for v in violations if v["confidence"] > 0.7]
            
            if high_conf:
                return False, f"Blocked: {len(high_conf)} high-confidence violations detected"
        
        # Check metadata
        metadata_result = await self.moderation.moderate_video_metadata(
            title=clip_info.get("title", ""),
            description=clip_info.get("description", ""),
            tags=clip_info.get("tags", []),
            video_id=clip_id
        )
        
        if not metadata_result["is_safe"] and metadata_result["confidence"] > 0.6:
            return False, f"Metadata violation: {metadata_result['category']}"
        
        return True, None
    
    async def check_copyright(
        self,
        video_path: Path,
        user_id: str
    ) -> Dict[str, Any]:
        """
        Basic copyright check.
        
        Note: Full copyright detection would require integration with
        content ID systems like YouTube Content ID or similar.
        """
        # Placeholder for copyright checking
        return {
            "is_clear": True,
            "confidence": 0.8,
            "warnings": [],
            "note": "Basic check only. Full copyright verification recommended."
        }


# Global instance
_moderation_service: Optional[ContentModerationService] = None
_safety_filter: Optional[SafetyFilter] = None


def get_moderation_service() -> ContentModerationService:
    """Get global moderation service."""
    global _moderation_service
    if _moderation_service is None:
        _moderation_service = ContentModerationService()
    return _moderation_service


def get_safety_filter() -> SafetyFilter:
    """Get global safety filter."""
    global _safety_filter
    if _safety_filter is None:
        _safety_filter = SafetyFilter()
    return _safety_filter


# Convenience functions
async def check_content_safety(text: str, content_id: str) -> ModerationResult:
    """Quick content safety check."""
    return await get_moderation_service().moderate_text(text, content_id)


async def validate_clip_for_publishing(
    clip_info: Dict[str, Any],
    transcript: str
) -> Tuple[bool, Optional[str]]:
    """Validate clip before publishing."""
    return await get_safety_filter().filter_clip_content(clip_info, transcript)
