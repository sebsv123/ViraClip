"""
AI response validation with automatic retry loop.
"""

import json
import re
import logging
from typing import List, Optional
from pydantic import ValidationError

from ..models.viral_segment import ScoringResponse, ViralSegment

logger = logging.getLogger(__name__)


async def get_validated_segments(
    scoring_function,
    transcript: str,
    language: str,
    num_clips: int,
    max_retries: int = 3
) -> List[ViralSegment]:
    """
    Get validated segments from LLM with automatic retry on validation failure.
    
    Args:
        scoring_function: Async function that calls the LLM (Groq, Ollama, etc.)
        transcript: Video transcript
        language: Video language
        num_clips: Number of clips requested
        max_retries: Maximum retry attempts
        
    Returns:
        List of validated ViralSegment objects
        
    Raises:
        RuntimeError: If all retry attempts fail
    """
    last_error = None
    
    for attempt in range(1, max_retries + 1):
        try:
            # Call the LLM scoring function with optional error context
            raw_response = await scoring_function(
                transcript=transcript,
                language=language,
                num_clips=num_clips,
                previous_error=last_error if attempt > 1 else None
            )
            
            # Extract JSON from response (LLMs sometimes add text around JSON)
            json_match = re.search(r'\{.*\}', raw_response, re.DOTALL)
            if not json_match:
                raise ValueError("No JSON object found in LLM response")
            
            json_str = json_match.group()
            data = json.loads(json_str)
            
            # Validate with Pydantic
            validated = ScoringResponse(**data)
            
            logger.info(f"✅ Validated {len(validated.segments)} segments on attempt {attempt}")
            return validated.segments
            
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            last_error = str(e)
            logger.warning(f"[Attempt {attempt}/{max_retries}] Validation failed: {e}")
            
            if attempt == max_retries:
                logger.error(f"❌ All {max_retries} validation attempts failed")
                raise RuntimeError(
                    f"LLM output validation failed after {max_retries} attempts. "
                    f"Last error: {last_error}"
                )
    
    # Should never reach here, but satisfy type checker
    raise RuntimeError("Unexpected error in validation loop")


def extract_json_safely(text: str) -> Optional[dict]:
    """
    Extract JSON from text that may contain additional content.
    
    Args:
        text: Raw text potentially containing JSON
        
    Returns:
        Parsed dict if JSON found, None otherwise
    """
    # Try multiple patterns
    patterns = [
        r'\{.*\}',  # Basic JSON object
        r'```json\s*(\{.*?\})\s*```',  # Markdown code block
        r'```\s*(\{.*?\})\s*```',  # Generic code block
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                json_str = match.group(1) if match.lastindex else match.group()
                return json.loads(json_str)
            except json.JSONDecodeError:
                continue
    
    return None
