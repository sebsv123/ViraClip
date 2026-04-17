"""
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
    OLLAMA_DSPY = "ollama_dspy"
    OLLAMA_FINETUNED = "ollama_finetuned"


class LLMRouter:
    """Route LLM requests to appropriate backend based on dataset size."""
    
    def __init__(self):
        self.current_backend = LLMBackend.GROQ
        self.dataset_size = 0
        self.dspy_available = False
        self.finetuned_available = False
    
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
            backend = LLMBackend.GROQ
            logger.info(
                f"☁️  Using Groq (fallback: {dataset_size} examples, "
                f"need 50 for DSPy, 200 for fine-tuning)"
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
        
        elif backend == LLMBackend.OLLAMA_DSPY:
            return await self._score_with_ollama_dspy(transcript, language, num_clips)
        
        elif backend == LLMBackend.OLLAMA_FINETUNED:
            return await self._score_with_ollama_finetuned(transcript, language, num_clips)
        
        else:
            raise ValueError(f"Unknown backend: {backend}")
    
    async def _score_with_groq(
        self,
        transcript: str,
        language: str,
        num_clips: int
    ) -> Dict[str, Any]:
        """Score using Groq (teacher model)."""
        from ..services.ai_prompts import VIRAL_SCORER_SYSTEM_PROMPT, build_dynamic_user_prompt
        import httpx
        import os
        
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set")
        
        user_prompt = build_dynamic_user_prompt(
            transcript=transcript,
            language=language,
            num_clips=num_clips
        )
        
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
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
    
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
