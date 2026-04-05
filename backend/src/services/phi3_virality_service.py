"""
Phi-3-mini Virality Scoring Service
Replaces generalist Ollama models with specialized viral content analysis
Microsoft Phi-3-mini via Ollama - 3.8B parameters, MIT License

Phase 4.3 Enhancement: Integrates viral trend boosting from trending hashtags/topics
"""
import httpx
import json
import os
import re
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Import viral trend service (Phase 4.3)
try:
    from services.viral_trend_service import get_trend_service
    TREND_SERVICE_AVAILABLE = True
except ImportError:
    TREND_SERVICE_AVAILABLE = False
    logger.warning("Viral trend service not available")

# Phi-3-mini Scroll Stop Test Prompt - The key differentiator
SCROLL_STOP_TEST_PROMPT = """You are a viral content expert trained on the SCROLL STOP TEST methodology.

Analyze this video segment using the 5 dimensions that predict organic reach:

Segment Text: {segment_text}
Duration: {duration}s
Audio Tempo: {tempo_bpm} BPM
Energy Peaks: {energy_peak_count}

Score each dimension 0-100:

1. PATTERN_INTERRUPT (0-100)
   - Does the first 3 seconds break viewer expectations?
   - Unexpected visual/audio change, controversial statement, or shocking fact
   - Score 90+ only if it creates immediate cognitive dissonance

2. CURIOSITY_GAP (0-100)
   - Does it create an unanswered question that demands resolution?
   - Open loops, cliffhangers, "what happens next" moments
   - Score 85+ for strong information gaps that persist 5+ seconds

3. EMOTIONAL_SPIKE (0-100)
   - Peak emotional intensity (anger, joy, fear, surprise, awe)
   - Measured by word choice intensity and context
   - Score 90+ for genuine emotional triggers, not manufactured outrage

4. SHAREABILITY (0-100)
   - Would someone send this to a specific friend with context?
   - "This is so you" or "You need to see this" moments
   - Score 85+ for high-identification content

5. LOOP_POTENTIAL (0-100)
   - Does it reward re-watching to catch missed details?
   - Easter eggs, hidden meanings, satisfying payoffs
   - Score 90+ for TikTok-style organic boost potential

Total Virality Score = average of 5 dimensions (0-100)

Return ONLY valid JSON:
{{
    "pattern_interrupt": 85,
    "curiosity_gap": 78,
    "emotional_spike": 92,
    "shareability": 81,
    "loop_potential": 76,
    "total_score": 82,
    "primary_hook_type": "emotional_spike",
    "scroll_stop_probability": 0.82,
    "recommended_duration": "15-25s",
    "edit_suggestions": ["fast_zoom", "caption_bounce"],
    "hashtag_themes": ["#emotion", "#storytime"]
}}

No explanation. JSON only."""


@dataclass
class ViralityScore:
    """Structured virality scoring result"""
    pattern_interrupt: int
    curiosity_gap: int
    emotional_spike: int
    shareability: int
    loop_potential: int
    total_score: int
    primary_hook_type: str
    scroll_stop_probability: float
    recommended_duration: str
    edit_suggestions: List[str]
    hashtag_themes: List[str]
    
    @property
    def is_viral(self) -> bool:
        """Content likely to go viral (score > 75)"""
        return self.total_score >= 75
    
    @property
    def is_hook_strong(self) -> bool:
        """First 3 seconds can stop scrolls"""
        return self.pattern_interrupt >= 80


class Phi3ViralityService:
    """
    Phi-3-mini specialized virality scoring
    Replaces generalist LLMs with viral-content-trained model
    """
    
    def __init__(self, ollama_url: Optional[str] = None):
        raw_url = (ollama_url or
                   os.environ.get("OLLAMA_BASE_URL") or
                   "http://ollama:11434").rstrip("/")
        self.ollama_url = re.sub(r"/v1$", "", raw_url)
        self.model = "phi3:mini"  # 3.8B params, MIT license
        self.timeout = httpx.Timeout(30.0, connect=5.0)
        try:
            from .viral_trend_service import ViralTrendService
            self.trend_service = ViralTrendService()
        except Exception:
            self.trend_service = None
        
        logger.info(f"Phi-3-mini Virality Service initialized: {self.ollama_url}")
    
    async def score_segment(
        self, 
        segment_text: str,
        duration: float = 15.0,
        audio_features: Optional[Dict] = None
    ) -> ViralityScore:
        """
        Score a transcript segment using Phi-3-mini + Scroll Stop Test
        
        Args:
            segment_text: The transcript text to analyze
            duration: Segment duration in seconds
            audio_features: Optional audio analysis results
            
        Returns:
            ViralityScore with 5-dimension breakdown
        """
        # Prepare audio context if available
        tempo = audio_features.get("tempo_bpm", 0) if audio_features else 0
        energy_peaks = len(audio_features.get("energy_peaks_timestamps", [])) if audio_features else 0
        
        # Build prompt
        prompt = SCROLL_STOP_TEST_PROMPT.format(
            segment_text=segment_text[:500],  # Limit context
            duration=duration,
            tempo_bpm=tempo,
            energy_peak_count=energy_peaks
        )
        
        try:
            # Auto-pull model if missing (fixes Ollama 404 on first run)
            await self._ensure_model_pulled()

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                        "options": {
                            "temperature": 0.3,  # Low temp for consistent scoring
                            "num_predict": 300
                        }
                    }
                )
                
                response.raise_for_status()
                result = response.json()
                
                # Parse JSON response
                raw_json = result.get("response", "{}")
                score_data = json.loads(raw_json)
                
                return ViralityScore(
                    pattern_interrupt=score_data.get("pattern_interrupt", 50),
                    curiosity_gap=score_data.get("curiosity_gap", 50),
                    emotional_spike=score_data.get("emotional_spike", 50),
                    shareability=score_data.get("shareability", 50),
                    loop_potential=score_data.get("loop_potential", 50),
                    total_score=score_data.get("total_score", 50),
                    primary_hook_type=score_data.get("primary_hook_type", "unknown"),
                    scroll_stop_probability=score_data.get("scroll_stop_probability", 0.5),
                    recommended_duration=score_data.get("recommended_duration", "15-30s"),
                    edit_suggestions=score_data.get("edit_suggestions", []),
                    hashtag_themes=score_data.get("hashtag_themes", [])
                )
                
        except Exception as e:
            logger.error(f"Phi-3-mini scoring failed: {e}")
            # Fallback to heuristic scoring
            return self._fallback_score(segment_text, duration)
    
    def _fallback_score(self, text: str, duration: float) -> ViralityScore:
        """Heuristic scoring when Phi-3-mini unavailable"""
        # Simple keyword-based fallback
        viral_keywords = ["secret", "never", "shocking", "revealed", "must", "urgent"]
        emotional_keywords = ["love", "hate", "angry", "amazing", "terrible", "incredible"]
        
        text_lower = text.lower()
        viral_count = sum(1 for kw in viral_keywords if kw in text_lower)
        emotional_count = sum(1 for kw in emotional_keywords if kw in text_lower)
        
        # Heuristic scores
        pattern = min(95, 50 + viral_count * 10)
        emotion = min(95, 50 + emotional_count * 10)
        
        total = int((pattern + emotion + 60 + 55 + 50) / 5)
        
        return ViralityScore(
            pattern_interrupt=pattern,
            curiosity_gap=60,
            emotional_spike=emotion,
            shareability=55,
            loop_potential=50,
            total_score=total,
            primary_hook_type="keyword_match",
            scroll_stop_probability=total / 100,
            recommended_duration="15-30s",
            edit_suggestions=["add_captions"],
            hashtag_themes=["#viral"]
        )
    
    async def score_segment_with_trends(
        self,
        segment_text: str,
        duration: float,
        audio_features: Optional[Dict] = None,
        hashtags: List[str] = None,
        platform: str = "tiktok"
    ) -> ViralityScore:
        """
        Score segment with viral trend boosting (Phase 4.3).
        
        Args:
            segment_text: Transcript text
            duration: Segment duration
            audio_features: Audio analysis data
            hashtags: Hashtags used in content
            platform: Target platform
            
        Returns:
            ViralityScore with trend-boosted total_score
        """
        # Get base score
        base_score = await self.score_segment(segment_text, duration, audio_features)
        
        # Apply trend boost if service available
        if TREND_SERVICE_AVAILABLE:
            try:
                trend_service = await get_trend_service()
                boosted_total = trend_service.apply_trend_boost(
                    base_score=base_score.total_score,
                    transcript=segment_text,
                    hashtags=hashtags or [],
                    platform=platform
                )
                
                # Update total score with boost
                base_score.total_score = int(boosted_total)
                base_score.scroll_stop_probability = boosted_total / 100.0
                
            except Exception as e:
                logger.warning(f"Trend boost failed: {e}")
        
        return base_score
    
    async def batch_score_segments(
        self,
        segments: List[Dict[str, Any]],
        audio_features: Optional[Dict] = None
    ) -> List[ViralityScore]:
        """Score multiple segments in parallel"""
        import asyncio
        
        tasks = []
        for seg in segments:
            text = seg.get("text", "")
            duration = seg.get("duration", 15.0)
            tasks.append(self.score_segment(text, duration, audio_features))
        
        return await asyncio.gather(*tasks, return_exceptions=True)
    
    async def check_model_available(self) -> bool:
        """Check if Phi-3-mini is pulled and ready"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.ollama_url}/api/tags")
                if response.status_code == 200:
                    models = response.json()
                    return any(m.get("name") == self.model for m in models.get("models", []))
                return False
        except Exception:
            return False

    async def _ensure_model_pulled(self) -> bool:
        """Pull phi3:mini if not present. Returns True if model is ready."""
        if await self.check_model_available():
            return True
        logger.info(f"[Phi-3] Model '{self.model}' not found — pulling from Ollama (this may take a few minutes)...")
        try:
            pull_timeout = httpx.Timeout(300.0, connect=10.0)
            async with httpx.AsyncClient(timeout=pull_timeout) as client:
                resp = await client.post(
                    f"{self.ollama_url}/api/pull",
                    json={"name": self.model, "stream": False},
                )
                if resp.status_code == 200:
                    logger.info(f"[Phi-3] Model '{self.model}' pulled successfully")
                    return True
                logger.warning(f"[Phi-3] Pull returned {resp.status_code}: {resp.text[:200]}")
                return False
        except Exception as pull_err:
            logger.warning(f"[Phi-3] Auto-pull failed: {pull_err}")
            return False


# Singleton instance
_phi3_service: Optional[Phi3ViralityService] = None


def get_phi3_service() -> Phi3ViralityService:
    """Get or create Phi-3-mini service singleton"""
    global _phi3_service
    if _phi3_service is None:
        _phi3_service = Phi3ViralityService()
    return _phi3_service


# Command to pull model: ollama pull phi3:mini
SETUP_INSTRUCTIONS = """
To use Phi-3-mini virality scoring:

1. Ensure Ollama is running
2. Pull the model: ollama pull phi3:mini
3. Set environment variable (optional):
   OLLAMA_BASE_URL=http://ollama:11434

The model is 3.8B parameters, runs on 4GB RAM,
and is MIT licensed (free for commercial use).
"""
