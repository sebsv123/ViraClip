import logging
import httpx
import json
import os
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class LLMService:
    """Service to interact with local Ollama for virality scoring and hook detection."""

    def __init__(self):
        # Use OLLAMA_BASE_URL (set by docker-compose to http://ollama:11434) with fallback chain
        self.ollama_url = (
            os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OLLAMA_URL")
            or "http://ollama:11434"
        ).rstrip("/")
        # qwen3-vl:8b is the installed model; llama3.1:8b is the legacy default
        self.model = os.environ.get("VIRALITY_MODEL") or os.environ.get("OLLAMA_VISION_MODEL", "qwen3-vl:8b")
        self.timeout = httpx.Timeout(120.0, connect=10.0)

    async def get_virality_analysis(self, transcript_segments: List[str]) -> Dict[str, Any]:
        """
        Analyzes transcript segments using a local Ollama model to predict virality and extract hooks.
        Returns hook_score, engagement_score, value_score, shareability_score (0-25 each)
        plus a virality_score total (0-100) for each segment.
        """
        prompt = f"""You are a Viral Growth Expert for social media (TikTok/Shorts/Reels).
Analyze the following video transcript segments and score their viral potential.

For each segment provide ALL of these fields:
- hook_score (0-25): How strongly the opening grabs attention
- engagement_score (0-25): How entertaining or emotionally engaging the content is
- value_score (0-25): Educational or informational value
- shareability_score (0-25): How likely viewers are to share it
- virality_score (0-100): Sum of the four scores above
- hook_type: One of: "Curiosity Gap", "Negative Hook", "Bold Claim", "Story", "Statistic", "Question", "Contrast", "Value"
- suggested_title: A catchy, high-CTR title (leave empty string if nothing compelling)
- reasoning: Brief explanation of the viral strategy
- viral_cues: Specific editing suggestions (e.g. "Fast zoom on key claim", "Split screen")

Transcript segments:
{chr(10).join(f"{i}. {seg}" for i, seg in enumerate(transcript_segments[:20]))}

Return a JSON object with this exact structure:
{{
    "analysis": [
        {{
            "segment_index": 0,
            "hook_score": 20,
            "engagement_score": 18,
            "value_score": 22,
            "shareability_score": 19,
            "virality_score": 79,
            "hook_type": "Curiosity Gap",
            "suggested_title": "The mindset hack you have been missing",
            "reasoning": "Opens with a pattern interrupt that creates immediate curiosity.",
            "viral_cues": "Fast-paced captions, zoom in on the main claim at 0:03"
        }}
    ]
}}"""

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json"
                    }
                )
                response.raise_for_status()
                # result = response.json() # This is the Ollama API envelope
                # return json.loads(result.get("response", "{}")) # This might fail if response is not valid JSON
                
                # Hardened parsing
                try:
                    full_response = response.json()
                    inner_content = full_response.get("response", "{}")
                    return json.loads(inner_content)
                except (json.JSONDecodeError, KeyError) as parse_err:
                    logger.error(f"Failed to parse LLM inner JSON: {parse_err}")
                    return self._get_fallback_analysis(len(transcript_segments))

        except Exception as e:
            logger.error(f"Ollama analysis failed (probably offline or network): {e}")
            # Fallback to basic dummy scores if LLM is offline
            return self._get_fallback_analysis(len(transcript_segments))

    async def generate_image_prompt(self, segment_text: str, video_context: str = "Cinematic video") -> str:
        """
        Generates a visually rich image prompt for AI generation based on transcript context.
        """
        prompt = f"""
        You are a Visual Director. Based on this video script segment, describe a SINGLE cinematic scene that captures the essence of the words.
        
        Script: "{segment_text}"
        Video Context: {video_context}
        
        Rules:
        1. Describe one clear, high-impact visual scene.
        2. Use vivid adjectives (lighting, texture, atmosphere).
        3. Standard output: "A cinematic shot of [description]..."
        4. ABSOLUTELY NO text in the image.
        5. Output ONLY the prompt string.
        
        Creative Prompt:
        """
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False
                    }
                )
                response.raise_for_status()
                result = response.json()
                return result.get("response", segment_text).strip()
        except Exception as e:
            logger.error(f"Image prompt generation failed: {e}")
            return f"Cinematic shot illustrating: {segment_text}"

    def _get_fallback_analysis(self, count: int) -> Dict[str, Any]:
        """Fallback when Ollama is unavailable. Provides all expected score fields."""
        return {
            "analysis": [
                {
                    "segment_index": i,
                    "virality_score": 50,
                    "hook_score": 12,
                    "engagement_score": 13,
                    "value_score": 13,
                    "shareability_score": 12,
                    "hook_strength": "Medium",
                    "hook_type": "Value",
                    "suggested_title": "",  # empty → _build_hook_title uses segment text
                    "reasoning": "Automated fallback analysis (Ollama offline)."
                }
                for i in range(count)
            ]
        }
