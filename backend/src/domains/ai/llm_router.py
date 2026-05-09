"""
MEJORA — Motor de scoring viral con DeepSeek + datos reales

1. Hook Score en los primeros 3 segundos:
   El sistema debe analizar específicamente el segmento 0-3s de cada
   clip candidato y puntuarlo con criterios como pregunta directa,
   afirmacion shock, numero especifico, etc.

2. Retention curve predictor:
   Analizar la densidad de informacion por segmento de 5 segundos.

3. Trending keywords en prompts LTX:
   Consultar tendencias para sugerir keywords visuales.

Progressive LLM routing with fallback logic.

Routes requests based on dataset size and model availability:
- < 50 examples: Groq (teacher model)
- 50-199 examples: Ollama + DSPy-optimized prompts
- 200+ examples: Ollama + Fine-tuned model
"""

import logging
from typing import Dict, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class LLMBackend(str, Enum):
    """Available LLM backends."""
    GROQ = "groq"
    DEEPSEEK = "deepseek"
    OLLAMA_DSPY = "ollama_dspy"
    OLLAMA_FINETUNED = "ollama_finetuned"


class LLMRouter:
    """Route LLM requests to appropriate backend based on dataset size."""
    
    def __init__(self):
        self.current_backend = LLMBackend.GROQ
        self.dataset_size = 0
        self.dspy_available = False
        self.finetuned_available = False
        # FIX Problema 3: Validar GROQ_API_KEY en init
        import os
        _groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        self.groq_available = bool(_groq_key)
        if not self.groq_available:
            logger.warning(
                "[LLMRouter] WARNING: GROQ_API_KEY not set — all LLM calls will use rule-based fallback"
            )
    
    async def select_backend(
        self,
        dataset_size: int,
        language: str = "es",
        force_backend: Optional[LLMBackend] = None
    ) -> LLMBackend:
        """
        Select appropriate LLM backend based on dataset size and availability.
        
        Args:
            dataset_size: Number of training examples collected
            language: Video language (some models support more languages)
            force_backend: Override automatic selection
            
        Returns:
            Selected backend
        """
        if force_backend:
            logger.info(f"🎯 Forced backend: {force_backend}")
            return force_backend
        
        self.dataset_size = dataset_size
        
        # Progressive thresholds
        if dataset_size >= 200 and self.finetuned_available and self._language_supported(language):
            backend = LLMBackend.OLLAMA_FINETUNED
            logger.info(f"🎓 Using fine-tuned model ({dataset_size} examples)")
        
        elif dataset_size >= 50 and self.dspy_available and self._language_supported(language):
            backend = LLMBackend.OLLAMA_DSPY
            logger.info(f"📚 Using DSPy-optimized Ollama ({dataset_size} examples)")
        
        else:
            # DeepSeek is primary, Groq is fallback
            _deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
            if _deepseek_key:
                backend = LLMBackend.DEEPSEEK
                logger.info(
                    f"🔷 Using DeepSeek V3 (primary: {dataset_size} examples, "
                    f"need 50 for DSPy, 200 for fine-tuning)"
                )
            else:
                backend = LLMBackend.GROQ
                logger.info(
                    f"☁️  Using Groq (fallback: DEEPSEEK_API_KEY not set, "
                    f"{dataset_size} examples)"
                )
        
        self.current_backend = backend
        return backend
    
    async def score_segments(
        self,
        transcript: str,
        language: str,
        num_clips: int,
        backend: Optional[LLMBackend] = None
    ) -> Dict[str, Any]:
        """
        Score video segments using selected backend.
        
        Args:
            transcript: Video transcript
            language: Video language
            num_clips: Number of clips to generate
            backend: Override backend selection
            
        Returns:
            Scoring response
        """
        if backend is None:
            backend = await self.select_backend(self.dataset_size, language)
        
        if backend == LLMBackend.GROQ:
            return await self._score_with_groq(transcript, language, num_clips)
        
        elif backend == LLMBackend.DEEPSEEK:
            return await self._score_with_deepseek(transcript, language, num_clips)
        
        elif backend == LLMBackend.OLLAMA_DSPY:
            return await self._score_with_ollama_dspy(transcript, language, num_clips)
        
        elif backend == LLMBackend.OLLAMA_FINETUNED:
            return await self._score_with_ollama_finetuned(transcript, language, num_clips)
        
        else:
            raise ValueError(f"Unknown backend: {backend}")
    
    async def _score_with_deepseek(
        self,
        transcript: str,
        language: str,
        num_clips: int
    ) -> Dict[str, Any]:
        """Score using DeepSeek V3 (superior analytical reasoning for viral scoring)."""
        import httpx
        import os
        
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            logger.warning("[LLMRouter] DEEPSEEK_API_KEY not set — falling back to Groq")
            return await self._score_with_groq(transcript, language, num_clips)
        
        system_prompt = (
            "You are a viral content analyst. Analyze the transcript and score each segment "
            "for viral potential. Return a JSON object with:\n"
            "- segments: array of {start, end, text, hook_strength (0-10), "
            "emotional_peak (0-10), shareability (0-10), retention (0-10), "
            "viral_score (0-10), reason}\n"
            "- viral_potential: 'low' | 'medium' | 'high'\n\n"
            "Scoring criteria:\n"
            "1. First 3 seconds: strong hook? (question, shocking statement, number)\n"
            "2. Information density per second\n"
            "3. Tension/resolution moments\n"
            "4. Natural vs forced CTA\n"
            "5. Emotional triggers (fear, surprise, curiosity, aspiration)"
        )
        
        user_prompt = (
            f"Transcript ({language}):\n{transcript[:3000]}\n\n"
            f"Generate {num_clips} viral clip segments. "
            "Focus on moments with highest retention potential."
        )
        
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.3,
                    "max_tokens": 2000,
                }
            )
            response.raise_for_status()
            result = response.json()
            logger.info("[LLMRouter] DeepSeek V3 scoring complete")
            return result["choices"][0]["message"]["content"]

    async def _score_with_groq(
        self,
        transcript: str,
        language: str,
        num_clips: int
    ) -> Dict[str, Any]:
        """Score using Groq (teacher model) with retry on 429 rate limiting."""
        from ...domains.ai.ai_prompts import VIRAL_SCORER_SYSTEM_PROMPT, build_dynamic_user_prompt
        import httpx
        import os
        import asyncio
        
        # Check groq_available flag before calling API
        if not getattr(self, 'groq_available', True):
            logger.warning("[LLMRouter] Groq unavailable — using rule-based fallback")
            return self._rule_based_fallback(transcript, language, num_clips)
        
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set")
        
        user_prompt = build_dynamic_user_prompt(
            transcript=transcript,
            language=language,
            num_clips=num_clips
        )
        
        # Retry configuration for Groq 429 rate limiting
        max_retries = int(os.environ.get("LLM_MAX_RETRIES", "3"))
        base_delay = float(os.environ.get("LLM_RETRY_DELAY", "5"))
        
        last_exception: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    response = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={
                            "model": "llama-3.3-70b-versatile",
                            "messages": [
                                {"role": "system", "content": VIRAL_SCORER_SYSTEM_PROMPT},
                                {"role": "user", "content": user_prompt}
                            ],
                            "response_format": {"type": "json_object"},
                            "temperature": 0.3
                        }
                    )
                    
                    if response.status_code == 429:
                        retry_after = int(response.headers.get("Retry-After", str(base_delay * (2 ** attempt))))
                        logger.warning(
                            "[LLMRouter] Groq 429 rate limited (attempt %d/%d). "
                            "Retrying in %ds...",
                            attempt + 1, max_retries + 1, retry_after
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    
                    response.raise_for_status()
                    result = response.json()
                    return result["choices"][0]["message"]["content"]
                    
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exception = exc
                status_code = getattr(exc, 'response', None) and exc.response.status_code
                
                if status_code == 429:
                    # Already handled above, but catch if it came via raise_for_status
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "[LLMRouter] Groq 429 (attempt %d/%d). Retrying in %ds...",
                        attempt + 1, max_retries + 1, delay
                    )
                    await asyncio.sleep(delay)
                    continue
                
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "[LLMRouter] Groq API error (attempt %d/%d): %s. "
                        "Retrying in %ds...",
                        attempt + 1, max_retries + 1, exc, delay
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "[LLMRouter] Groq API failed after %d attempts: %s",
                        max_retries + 1, exc
                    )
        
        # All retries exhausted — fall back to rule-based scoring
        logger.warning(
            "[LLMRouter] Groq API unavailable after %d attempts — "
            "falling back to rule-based scoring",
            max_retries + 1
        )
        return self._rule_based_fallback(transcript, language, num_clips)
    
    async def _score_with_ollama_dspy(
        self,
        transcript: str,
        language: str,
        num_clips: int
    ) -> Dict[str, Any]:
        """Score using Ollama with DSPy-optimized prompts."""
        # TODO: Load optimized prompt from file
        logger.info("📚 Using DSPy-optimized Ollama (not yet implemented)")
        # Fallback to Groq for now
        return await self._score_with_groq(transcript, language, num_clips)
    
    async def _score_with_ollama_finetuned(
        self,
        transcript: str,
        language: str,
        num_clips: int
    ) -> Dict[str, Any]:
        """Score using fine-tuned Ollama model."""
        # TODO: Load fine-tuned model
        logger.info("🎓 Using fine-tuned Ollama (not yet implemented)")
        # Fallback to Groq for now
        return await self._score_with_groq(transcript, language, num_clips)
    
    def _rule_based_fallback(self, transcript: str, language: str, num_clips: int) -> str:
        """Rule-based scoring when Groq is unavailable.
        Segments arrive as joined text blocks (one per line). Each gets a
        heuristic score based on simple text signals rather than returning 0 segments.
        """
        import json, re
        logger.warning("[LLMRouter] Rule-based fallback activated — using heuristic scoring")
        blocks = [b.strip() for b in transcript.split("\n") if b.strip()]
        if not blocks:
            blocks = [transcript[:500]] if transcript else []
        segments = []
        for i, block in enumerate(blocks[:num_clips]):
            # Simple text-signal heuristics (0-10 scale each)
            hook_strength = min(10.0, 4.0
                + (2.0 if "?" in block else 0)
                + (1.5 if "!" in block else 0)
                + (1.0 if any(w in block.lower() for w in ["secreto", "nadie", "clave", "nunca", "siempre", "error", "truth", "secret", "nobody"]) else 0)
                + (0.5 if re.search(r"\d+", block) else 0))
            retention = min(10.0, 5.0 + min(2.5, len(block) / 200))
            emotional_peak = min(10.0, 3.0
                + (2.0 if "!" in block else 0)
                + (1.5 if any(w in block.lower() for w in ["increíble", "sorprendente", "amazing", "shocking", "brutal"]) else 0)
                + (1.0 if len(re.findall(r"[A-ZÁÉÍÓÚ]{3,}", block)) > 0 else 0))
            shareability = min(10.0, 4.0
                + (1.5 if re.search(r"\d+%|\d+ (segundos|minutos|pasos|razones|tips)", block.lower()) else 0)
                + (1.0 if "?" in block else 0))
            viral_score = round((hook_strength + retention + emotional_peak + shareability) / 4, 2)
            segments.append({
                "hook_strength": round(hook_strength, 1),
                "emotional_peak": round(emotional_peak, 1),
                "shareability": round(shareability, 1),
                "retention": round(retention, 1),
                "viral_score": viral_score,
                "reason": f"[heuristic] {block[:80]}",
            })
        return json.dumps({"segments": segments, "viral_potential": "medium"})

    def _language_supported(self, language: str) -> bool:
        """Check if language is supported by local models."""
        # For now, support common languages
        supported = ["es", "en", "fr", "de", "pt", "it"]
        return language in supported
    
    async def get_routing_stats(self) -> Dict[str, Any]:
        """Get routing statistics."""
        return {
            "current_backend": self.current_backend,
            "dataset_size": self.dataset_size,
            "dspy_available": self.dspy_available,
            "finetuned_available": self.finetuned_available,
            "thresholds": {
                "dspy_minimum": 50,
                "finetuning_minimum": 200
            }
        }


# Singleton instance
_llm_router: Optional[LLMRouter] = None


def get_llm_router() -> LLMRouter:
    """Get or create LLM router singleton."""
    global _llm_router
    if _llm_router is None:
        _llm_router = LLMRouter()
    return _llm_router
