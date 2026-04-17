"""
LangChain Service — AI Orchestration Layer
==========================================

Wraps ViraClip's existing LLM pipeline with LangChain chains for:
- Structured virality analysis (with retry + output parsing)
- Viral metadata generation (title, description, hashtags)
- Hook detection and script rewriting
- Multi-step reasoning chains with memory
- Tool-augmented agents

Falls back gracefully if LangChain or provider keys are unavailable.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── lazy imports so the service loads even without langchain installed ─────────

def _get_chat_model(provider: Optional[str] = None):
    """Return a LangChain chat model based on available API keys."""
    import os

    provider = provider or os.environ.get("LLM_PROVIDER", "auto")

    if provider in ("openai", "auto") and os.environ.get("OPENAI_API_KEY"):
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                temperature=0.3,
                max_tokens=1024,
            )
        except ImportError:
            pass

    if provider in ("anthropic", "auto") and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=os.environ.get("ANTHROPIC_MODEL", "claude-3-haiku-20240307"),
                temperature=0.3,
                max_tokens=1024,
            )
        except ImportError:
            pass

    if provider in ("google", "auto") and os.environ.get("GOOGLE_API_KEY"):
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=os.environ.get("GOOGLE_MODEL", "gemini-2.0-flash"),
                temperature=0.3,
            )
        except ImportError:
            pass

    raise RuntimeError(
        "No LangChain-compatible LLM available. "
        "Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY."
    )


# ── Virality Analysis Chain ────────────────────────────────────────────────────

VIRALITY_PROMPT = """\
You are an expert viral content analyst. Analyze this video transcript segment and return a JSON object.

Transcript: {transcript}
Platform: {platform}
Duration (seconds): {duration}

Return ONLY valid JSON with these fields:
{{
  "virality_score": <int 0-100>,
  "hook_quality": <int 0-100>,
  "emotional_intensity": <int 0-100>,
  "shareability": <int 0-100>,
  "top_moments": [<list of up to 3 short strings describing the best moments>],
  "weakness": <string, main weakness>,
  "recommendation": <string, single most impactful improvement>
}}"""


async def analyze_virality_with_langchain(
    transcript: str,
    platform: str = "tiktok",
    duration: float = 30.0,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run a structured virality analysis chain using LangChain.
    Returns a dict with score, moments, and recommendations.
    Falls back to heuristic scoring if LangChain is unavailable.
    """
    try:
        from langchain_core.output_parsers import JsonOutputParser
        from langchain_core.prompts import PromptTemplate

        llm = _get_chat_model(provider)
        prompt = PromptTemplate.from_template(VIRALITY_PROMPT)
        chain = prompt | llm | JsonOutputParser()

        result = await chain.ainvoke({
            "transcript": transcript[:2000],
            "platform": platform,
            "duration": duration,
        })
        result["source"] = "langchain"
        return result

    except Exception as e:
        logger.warning("[langchain] Virality chain failed, using fallback: %s", e)
        return _fallback_virality(transcript, duration)


def _fallback_virality(transcript: str, duration: float) -> Dict[str, Any]:
    words = transcript.split()
    hook_words = {"secret", "never", "always", "why", "how", "stop", "wait", "shocking"}
    hook_quality = min(100, sum(20 for w in words[:10] if w.lower() in hook_words))
    score = min(100, 40 + len(words) // 5 + hook_quality // 4)
    return {
        "virality_score": score,
        "hook_quality": hook_quality,
        "emotional_intensity": 50,
        "shareability": 50,
        "top_moments": [],
        "weakness": "Analysis unavailable",
        "recommendation": "Add a stronger hook in the first 3 seconds",
        "source": "fallback",
    }


# ── Viral Metadata Chain ───────────────────────────────────────────────────────

METADATA_PROMPT = """\
You are a viral content strategist. Generate platform-optimised metadata for this clip.

Transcript excerpt: {transcript}
Platform: {platform}
Niche: {niche}

Return ONLY valid JSON:
{{
  "title": <string, punchy title max 60 chars>,
  "description": <string, 2-3 sentence description with keywords>,
  "hashtags": [<list of 10-15 relevant hashtags without #>],
  "cta": <string, call-to-action for the end of the video>,
  "best_posting_time": <string, e.g. "Tuesday 7pm EST">
}}"""


async def generate_viral_metadata(
    transcript: str,
    platform: str = "tiktok",
    niche: str = "general",
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate title, description, hashtags, and CTA using a LangChain chain."""
    try:
        from langchain_core.output_parsers import JsonOutputParser
        from langchain_core.prompts import PromptTemplate

        llm = _get_chat_model(provider)
        prompt = PromptTemplate.from_template(METADATA_PROMPT)
        chain = prompt | llm | JsonOutputParser()

        result = await chain.ainvoke({
            "transcript": transcript[:1500],
            "platform": platform,
            "niche": niche,
        })
        result["source"] = "langchain"
        return result

    except Exception as e:
        logger.warning("[langchain] Metadata chain failed, using fallback: %s", e)
        return {
            "title": transcript[:60].strip(),
            "description": transcript[:200].strip(),
            "hashtags": ["viral", "trending", "fyp", "foryou"],
            "cta": "Follow for more!",
            "best_posting_time": "Weekdays 7-9pm",
            "source": "fallback",
        }


# ── Hook Rewrite Chain ─────────────────────────────────────────────────────────

HOOK_REWRITE_PROMPT = """\
You are a viral hook writer. Rewrite the opening of this script to maximize viewer retention.

Original opening (first 5 seconds): {hook_text}
Platform: {platform}
Content type: {content_type}

Return ONLY valid JSON:
{{
  "rewritten_hook": <string, new opening line max 15 words>,
  "hook_type": <"question" | "statement" | "curiosity_gap" | "bold_claim">,
  "retention_improvement": <int, estimated % improvement in 3s retention>,
  "reasoning": <string, brief explanation>
}}"""


async def rewrite_hook(
    hook_text: str,
    platform: str = "tiktok",
    content_type: str = "talking_head",
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Rewrite a video hook for maximum retention using LangChain."""
    try:
        from langchain_core.output_parsers import JsonOutputParser
        from langchain_core.prompts import PromptTemplate

        llm = _get_chat_model(provider)
        prompt = PromptTemplate.from_template(HOOK_REWRITE_PROMPT)
        chain = prompt | llm | JsonOutputParser()

        result = await chain.ainvoke({
            "hook_text": hook_text[:500],
            "platform": platform,
            "content_type": content_type,
        })
        result["source"] = "langchain"
        return result

    except Exception as e:
        logger.warning("[langchain] Hook rewrite chain failed: %s", e)
        return {
            "rewritten_hook": hook_text[:100],
            "hook_type": "statement",
            "retention_improvement": 0,
            "reasoning": "LangChain unavailable",
            "source": "fallback",
        }


# ── Multi-turn Conversation Chain (with memory) ────────────────────────────────

class ViraClipChatChain:
    """
    A stateful conversation chain with memory for interactive clip editing sessions.
    The user can refine clips, ask questions about content, and get suggestions
    across multiple turns.
    """

    def __init__(self, provider: Optional[str] = None):
        self._provider = provider
        self._history: List[Dict[str, str]] = []
        self._chain = None

    def _build_chain(self):
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

        llm = _get_chat_model(self._provider)

        prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=(
                "You are ViraClip AI, an expert video editing assistant. "
                "Help users create viral short-form video content. "
                "When asked about clips, provide specific, actionable advice about "
                "timing, hooks, transitions, captions, and platform optimisation."
            )),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{input}"),
        ])

        self._chain = prompt | llm
        return self._chain

    async def chat(self, message: str) -> str:
        """Send a message and get a response, maintaining conversation history."""
        try:
            from langchain_core.messages import AIMessage, HumanMessage

            if self._chain is None:
                self._build_chain()

            history_msgs = []
            for turn in self._history:
                history_msgs.append(HumanMessage(content=turn["human"]))
                history_msgs.append(AIMessage(content=turn["ai"]))

            response = await self._chain.ainvoke({
                "history": history_msgs,
                "input": message,
            })
            reply = response.content

            self._history.append({"human": message, "ai": reply})
            return reply

        except Exception as e:
            logger.warning("[langchain] Chat chain failed: %s", e)
            return f"AI unavailable: {e}"

    def clear_history(self):
        self._history = []

    def get_history(self) -> List[Dict[str, str]]:
        return list(self._history)


# ── Singleton ──────────────────────────────────────────────────────────────────

_instance: Optional["LangChainService"] = None


class LangChainService:
    """Unified access point for all LangChain-powered features."""

    async def analyze_virality(self, transcript: str, platform: str = "tiktok",
                               duration: float = 30.0) -> Dict[str, Any]:
        return await analyze_virality_with_langchain(transcript, platform, duration)

    async def generate_metadata(self, transcript: str, platform: str = "tiktok",
                                niche: str = "general") -> Dict[str, Any]:
        return await generate_viral_metadata(transcript, platform, niche)

    async def rewrite_hook(self, hook_text: str, platform: str = "tiktok",
                           content_type: str = "talking_head") -> Dict[str, Any]:
        return await rewrite_hook(hook_text, platform, content_type)

    def new_chat_session(self) -> ViraClipChatChain:
        return ViraClipChatChain()

    def is_available(self) -> bool:
        try:
            import langchain  # noqa: F401
            return True
        except ImportError:
            return False

    def get_info(self) -> Dict[str, Any]:
        import os
        return {
            "available": self.is_available(),
            "providers_configured": {
                "openai": bool(os.environ.get("OPENAI_API_KEY")),
                "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
                "google": bool(os.environ.get("GOOGLE_API_KEY")),
            },
            "chains": ["virality_analysis", "viral_metadata", "hook_rewrite", "chat"],
        }


def get_langchain_service() -> LangChainService:
    global _instance
    if _instance is None:
        _instance = LangChainService()
    return _instance
