"""
Improved LLM Service with robust validation and text-based fallback.

Addresses virality scoring unreliability by:
1. Strict JSON schema validation with Pydantic
2. Retry logic with exponential backoff
3. Text-based fallback when Ollama is unavailable
4. Few-shot examples for better LLM performance
"""

import logging
import httpx
import json
import os
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator
from enum import Enum

logger = logging.getLogger(__name__)


class HookType(str, Enum):
    """Valid hook types for viral content."""
    CURIOSITY_GAP = "Curiosity Gap"
    NEGATIVE_HOOK = "Negative Hook"
    BOLD_CLAIM = "Bold Claim"
    STORY = "Story"
    STATISTIC = "Statistic"
    QUESTION = "Question"
    CONTRAST = "Contrast"
    VALUE = "Value"


class ViralityScores(BaseModel):
    """Strict validation for virality sub-scores."""
    hook_score: int = Field(ge=0, le=25, description="Hook strength (0-25)")
    engagement_score: int = Field(ge=0, le=25, description="Engagement potential (0-25)")
    value_score: int = Field(ge=0, le=25, description="Educational/informational value (0-25)")
    shareability_score: int = Field(ge=0, le=25, description="Share likelihood (0-25)")
    virality_score: int = Field(ge=0, le=100, description="Total score (sum of 4 sub-scores)")
    
    @field_validator('virality_score')
    @classmethod
    def validate_total(cls, v, info):
        """Ensure virality_score equals sum of sub-scores."""
        data = info.data
        expected_total = (
            data.get('hook_score', 0) +
            data.get('engagement_score', 0) +
            data.get('value_score', 0) +
            data.get('shareability_score', 0)
        )
        if abs(v - expected_total) > 1:  # Allow 1pt rounding error
            logger.warning(f"Virality score mismatch: {v} != {expected_total}, using {expected_total}")
            return expected_total
        return v


class SegmentAnalysis(BaseModel):
    """Analysis for a single transcript segment."""
    segment_index: int = Field(ge=0)
    hook_score: int = Field(ge=0, le=25)
    engagement_score: int = Field(ge=0, le=25)
    value_score: int = Field(ge=0, le=25)
    shareability_score: int = Field(ge=0, le=25)
    virality_score: int = Field(ge=0, le=100)
    hook_type: HookType
    suggested_title: str = Field(default="")
    suggested_hashtags: List[str] = Field(default_factory=list)
    reasoning: str
    viral_cues: str = Field(default="")


class ViralityAnalysis(BaseModel):
    """Complete virality analysis response."""
    analysis: List[SegmentAnalysis]


class ImprovedLLMService:
    """Enhanced LLM service with validation and fallback."""
    
    def __init__(self):
        self.ollama_url = (
            os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OLLAMA_URL")
            or "http://ollama:11434"
        ).rstrip("/")
        self.model = os.environ.get("VIRALITY_MODEL") or os.environ.get("OLLAMA_VISION_MODEL", "qwen3-vl:8b")
        self.timeout = httpx.Timeout(120.0, connect=10.0)
        self.max_retries = 2
    
    async def get_virality_analysis(self, transcript_segments: List[str]) -> Dict[str, Any]:
        """
        Get virality analysis with validation and fallback.
        
        Returns:
            Dict with "analysis" key containing validated segment analyses
        """
        # Try Ollama with retries
        for attempt in range(self.max_retries + 1):
            try:
                result = await self._try_ollama_analysis(transcript_segments)
                if result:
                    logger.info(f"✓ Ollama analysis successful (attempt {attempt + 1})")
                    return result
            except Exception as e:
                logger.warning(f"Ollama attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        # Fallback to text-based analysis
        logger.warning("⚠️ Ollama unavailable, using text-based fallback")
        return self._text_based_fallback(transcript_segments)
    
    async def _try_ollama_analysis(self, segments: List[str]) -> Optional[Dict[str, Any]]:
        """Attempt Ollama analysis with strict validation."""
        prompt = self._build_improved_prompt(segments)
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.3,  # Lower temp for more consistent output
                        "top_p": 0.9,
                    }
                }
            )
            
            if response.status_code != 200:
                logger.error(f"Ollama returned {response.status_code}")
                return None
            
            full_response = response.json()
            inner_content = full_response.get("response", "{}")
            
            # Parse and validate with Pydantic
            raw_data = json.loads(inner_content)
            validated = ViralityAnalysis(**raw_data)
            
            # Convert back to dict
            return {"analysis": [seg.model_dump() for seg in validated.analysis]}
    
    def _build_improved_prompt(self, segments: List[str]) -> str:
        """Build prompt with few-shot examples for better performance."""
        examples = """
Example 1:
Segment: "Most people don't realize this, but AI is already writing 40% of code on GitHub"
Output: {
  "segment_index": 0,
  "hook_score": 22,
  "engagement_score": 18,
  "value_score": 20,
  "shareability_score": 19,
  "virality_score": 79,
  "hook_type": "Statistic",
  "suggested_title": "AI writes 40% of GitHub code",
  "suggested_hashtags": ["#ai", "#coding", "#tech", "#viral", "#programming"],
  "reasoning": "Opens with surprising statistic that challenges assumptions",
  "viral_cues": "Zoom on '40%' number, fast captions"
}

Example 2:
Segment: "I'm going to show you exactly how I made $10k in one weekend"
Output: {
  "segment_index": 1,
  "hook_score": 24,
  "engagement_score": 20,
  "value_score": 15,
  "shareability_score": 17,
  "virality_score": 76,
  "hook_type": "Bold Claim",
  "suggested_title": "How I made $10k in a weekend",
  "suggested_hashtags": ["#money", "#sidehustle", "#entrepreneur", "#shorts"],
  "reasoning": "Strong financial hook with promise of actionable value",
  "viral_cues": "Emphasize '$10k' with zoom, suspenseful music"
}
"""
        
        segments_text = "\n".join(f"{i}. {seg}" for i, seg in enumerate(segments[:20]))
        
        return f"""You are a Viral Growth Expert for TikTok/Shorts/Reels.

Analyze each transcript segment and provide virality scores.

CRITICAL RULES:
1. Each segment MUST have ALL 4 sub-scores: hook_score, engagement_score, value_score, shareability_score (0-25 each)
2. virality_score MUST equal the sum of the 4 sub-scores (0-100 total)
3. hook_type MUST be one of: "Curiosity Gap", "Negative Hook", "Bold Claim", "Story", "Statistic", "Question", "Contrast", "Value"
4. Return VALID JSON only, no markdown

{examples}

Now analyze these segments:
{segments_text}

Return JSON in this EXACT format:
{{
  "analysis": [
    {{
      "segment_index": 0,
      "hook_score": <0-25>,
      "engagement_score": <0-25>,
      "value_score": <0-25>,
      "shareability_score": <0-25>,
      "virality_score": <sum of 4 scores>,
      "hook_type": "<one of the 8 types>",
      "suggested_title": "<catchy title or empty string>",
      "suggested_hashtags": ["#tag1", "#tag2", ...],
      "reasoning": "<why this segment is viral>",
      "viral_cues": "<editing suggestions>"
    }}
  ]
}}"""
    
    def _text_based_fallback(self, segments: List[str]) -> Dict[str, Any]:
        """
        Text-based virality scoring when Ollama is unavailable.
        
        Uses keyword matching and heuristics for basic scoring.
        """
        analysis = []
        
        # Viral keywords by category
        viral_keywords = {
            "money": ["money", "cash", "dollars", "profit", "income", "earn", "$", "paid"],
            "shock": ["shocking", "unbelievable", "insane", "crazy", "wild", "mind-blowing"],
            "value": ["how to", "tutorial", "learn", "trick", "hack", "secret", "tip"],
            "emotion": ["love", "hate", "angry", "sad", "happy", "amazing", "terrible"],
            "numbers": ["million", "thousand", "billion", "%", "times", "doubled"],
        }
        
        for i, segment in enumerate(segments):
            text_lower = segment.lower()
            
            # Calculate scores based on keyword presence
            hook_score = 10  # Base score
            engagement_score = 10
            value_score = 10
            shareability_score = 10
            
            # Bonus for viral keywords
            for category, keywords in viral_keywords.items():
                if any(kw in text_lower for kw in keywords):
                    if category == "money":
                        hook_score += 4
                        shareability_score += 3
                    elif category == "shock":
                        hook_score += 5
                        engagement_score += 4
                    elif category == "value":
                        value_score += 5
                        shareability_score += 2
                    elif category == "emotion":
                        engagement_score += 4
                        shareability_score += 2
                    elif category == "numbers":
                        hook_score += 3
                        value_score += 2
            
            # Question detection
            if "?" in segment:
                hook_score += 3
                engagement_score += 2
            
            # Length penalty (too short or too long)
            word_count = len(segment.split())
            if word_count < 10:
                value_score -= 3
            elif word_count > 100:
                engagement_score -= 3
            
            # Clamp to 0-25 range
            hook_score = max(0, min(25, hook_score))
            engagement_score = max(0, min(25, engagement_score))
            value_score = max(0, min(25, value_score))
            shareability_score = max(0, min(25, shareability_score))
            
            virality_score = hook_score + engagement_score + value_score + shareability_score
            
            # Determine hook type
            hook_type = "Value"
            if "?" in segment:
                hook_type = "Question"
            elif any(kw in text_lower for kw in viral_keywords["money"]):
                hook_type = "Bold Claim"
            elif any(kw in text_lower for kw in viral_keywords["shock"]):
                hook_type = "Negative Hook"
            elif any(kw in text_lower for kw in viral_keywords["numbers"]):
                hook_type = "Statistic"
            
            analysis.append({
                "segment_index": i,
                "hook_score": hook_score,
                "engagement_score": engagement_score,
                "value_score": value_score,
                "shareability_score": shareability_score,
                "virality_score": virality_score,
                "hook_type": hook_type,
                "suggested_title": "",
                "suggested_hashtags": [],
                "reasoning": f"Text-based fallback analysis (score: {virality_score})",
                "viral_cues": ""
            })
        
        logger.info(f"✓ Text-based fallback generated {len(analysis)} analyses")
        return {"analysis": analysis}
