"""
AI-related functions for transcript analysis with enhanced precision and virality scoring.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Literal
import asyncio
import logging
import re

try:
    from pydantic_ai import Agent
    PYDANTIC_AI_AVAILABLE = True
except ImportError:
    PYDANTIC_AI_AVAILABLE = False
    Agent = None
from pydantic import BaseModel, Field, field_validator, model_validator, computed_field

from .config import Config

logger = logging.getLogger(__name__)
config = Config()


class CampaignStrategy(BaseModel):
    """V3 Phase 5: Holistic social media strategy for a collection of clips."""
    campaign_theme: str = Field(description="The overarching theme or narrative of the campaign")
    posting_schedule: List[str] = Field(description="Suggested relative timing for each clip (e.g. 'Day 1: Morning')")
    hashtags: List[str] = Field(description="Recommended trending and niche hashtags")
    target_audience: str = Field(description="Detailed profile of the viewer most likely to engage")
    cta_variation: str = Field(description="A specific call-to-action that ties the clips together")


class ViralityAnalysis(BaseModel):
    """Detailed virality breakdown for a segment."""

    hook_score: int = Field(
        description="How strong is the opening hook (0-25)", ge=0, le=25
    )
    engagement_score: Optional[int] = Field(
        default=None, description="How engaging/entertaining is the content (0-25)", ge=0, le=25
    )
    value_score: Optional[int] = Field(
        default=None, description="Educational/informational value (0-25)", ge=0, le=25
    )
    shareability_score: int = Field(
        description="Likelihood of being shared (0-25)", ge=0, le=25
    )
    total_score: Optional[int] = Field(
        default=None, description="Combined virality score (0-100)", ge=0, le=100
    )
    hook_type: Optional[
        Literal["question", "statement", "statistic", "story", "contrast", "none"]
    ] = Field(
        default="none",
        description="Type of hook: question, statement, statistic, story, contrast, or none",
    )
    virality_reasoning: str = Field(description="Explanation of the virality score")

    @model_validator(mode="after")
    def compute_total_score(self) -> "ViralityAnalysis":
        if self.total_score is None:
            self.total_score = min(100, (
                (self.hook_score or 0)
                + (self.engagement_score or 0)
                + (self.value_score or 0)
                + (self.shareability_score or 0)
            ))
        return self


class _TimestampStr(str):
    """String subclass that supports float arithmetic for duration calculations."""
    @staticmethod
    def _to_secs(v: "_TimestampStr") -> float:
        try:
            parts = str(v).strip().split(":")
            if len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
            return float(parts[0])
        except Exception:
            return 0.0

    def __sub__(self, other):
        return self._to_secs(self) - self._to_secs(other)  # type: ignore

    def __rsub__(self, other):
        return self._to_secs(other) - self._to_secs(self)  # type: ignore

    def __float__(self):
        return self._to_secs(self)

    def __ge__(self, other):
        if isinstance(other, str):
            return self._to_secs(self) >= self._to_secs(_TimestampStr(other))
        return self._to_secs(self) >= other

    def __le__(self, other):
        if isinstance(other, str):
            return self._to_secs(self) <= self._to_secs(_TimestampStr(other))
        return self._to_secs(self) <= other


class TranscriptSegment(BaseModel):
    """Represents a relevant segment of transcript with precise timing and virality analysis."""

    start_time: str = Field(description="Start timestamp in MM:SS format")
    end_time: str = Field(description="End timestamp in MM:SS format")
    text: str = Field(
        description=(
            "Transcript text taken only from the selected timestamp range. "
            "Keep it verbatim or near-verbatim, and do not paraphrase or merge non-contiguous lines."
        )
    )
    relevance_score: float = Field(
        description="Relevance score from 0.0 to 1.0", ge=0.0, le=1.0
    )
    reasoning: str = Field(
        description=(
            "Brief factual explanation of why this exact segment works as a clip. "
            "Base it only on the provided transcript content."
        )
    )
    virality: ViralityAnalysis = Field(description="Detailed virality score breakdown")
    theme: Optional[str] = Field(
        default="General",
        description="Thematic category of the clip (e.g. Motivational, Controversy, Edu-tainment)"
    )
    suggested_edits: Optional[str] = Field(
        default="Standard viral zoom and captions",
        description="Creative suggestions for editing this specific segment to maximize impact"
    )
    virality_score: float = Field(
        default=0.0,
        description="Composite virality score 0-10 (computed from virality breakdown)"
    )
    hook_title: str = Field(
        default="",
        description="Short viral-optimized hook title for the segment"
    )

    @field_validator("start_time", "end_time", mode="after")
    @classmethod
    def wrap_as_timestamp_str(cls, v: str) -> _TimestampStr:
        return _TimestampStr(v)

    @field_validator("relevance_score", mode="before")
    @classmethod
    def normalize_relevance_score(cls, v: float) -> float:
        """Normalize relevance_score from 0-100 scale to 0-1 before field constraint fires."""
        if isinstance(v, (int, float)) and v > 1.0:
            normalized = round(float(v) / 100.0, 4)
            logger.warning(
                f"[VALIDATOR] relevance_score {v} out of [0,1] range — normalizing to {normalized}"
            )
            return min(normalized, 1.0)
        return v

    @model_validator(mode="after")
    def enforce_business_rules(self) -> "TranscriptSegment":
        """
        Enforce all business invariants regardless of what the LLM returned.
        Schema-first: TranscriptSegment must be impossible to construct with invalid data.
        """
        def _ts_to_secs(ts: str) -> float:
            try:
                parts = ts.strip().split(":")
                if len(parts) == 2:
                    return int(parts[0]) * 60 + float(parts[1])
                return float(parts[0])
            except Exception:
                return 0.0

        def _secs_to_ts(s: float) -> str:
            m = int(s) // 60
            sec = int(s) % 60
            return f"{m:02d}:{sec:02d}"

        start = _ts_to_secs(self.start_time)
        end = _ts_to_secs(self.end_time)

        # Regla 1: timestamps coherentes
        if end <= start:
            raise ValueError(
                f"end_time ({self.end_time}) must be > start_time ({self.start_time})"
            )

        # Populate derived fields
        if self.virality:
            self.virality_score = round(self.virality.total_score / 10.0, 2) if self.virality.total_score else 0.0
        if not self.hook_title and self.reasoning:
            self.hook_title = self.reasoning[:80]

        # Regla 2: duración mínima 30s (con límite de video_duration)
        # TODO(future): contar cuántas veces se dispara por vídeo/modelo.
        # Si un LLM concreto lo dispara siempre → ajustar el prompt, no el validator.
        MIN_DURATION = 30.0
        duration = end - start
        if duration < MIN_DURATION:
            logger.warning(
                f"[VALIDATOR] Segment too short ({duration:.1f}s): "
                f"{self.start_time}→{self.end_time} — extending end_time to +{MIN_DURATION}s"
            )
            # Clamp extended end_time to video duration - 0.5s buffer
            extended_end = start + MIN_DURATION
            max_end = getattr(self, '_video_duration', float('inf')) - 0.5
            end = min(extended_end, max_end)
            self.end_time = _secs_to_ts(end)
            logger.info(f"[VALIDATOR] Extended segment: {self.start_time}→{self.end_time} (clamped to video bounds)")

        return self


class BRollOpportunity(BaseModel):
    """Identifies an opportunity to insert B-roll footage."""

    timestamp: str = Field(description="When to insert B-roll (MM:SS format)")
    duration: float = Field(
        description="How long to show B-roll (2-5 seconds)", ge=2.0, le=5.0
    )
    search_term: str = Field(description="Keyword to search for B-roll footage")
    context: str = Field(description="What's being discussed at this point")


class TranscriptAnalysis(BaseModel):
    """Analysis result for transcript segments with virality and B-roll opportunities."""

    most_relevant_segments: List[TranscriptSegment]
    summary: str = Field(description="Brief summary of the video content")
    key_topics: List[str] = Field(description="List of main topics discussed")
    broll_opportunities: Optional[List[BRollOpportunity]] = Field(
        default=None, description="Opportunities to insert B-roll footage"
    )
    campaign_strategy: Optional[CampaignStrategy] = Field(None, description="Global campaign blueprint (Phase 5)")


# Enhanced system prompt with virality scoring and B-roll detection
transcript_analysis_system_prompt = """You are an expert transcript analyst for short-form video editing.

Your job is extraction and ranking, not creative rewriting. You must stay fully grounded in the transcript and choose the best clip candidates that already exist in the source material.

CORE OBJECTIVES:
1. Identify segments that would be compelling on social media platforms
2. Focus on complete thoughts, insights, or entertaining moments
3. Prioritize content with hooks, emotional moments, or valuable information
4. Each segment should be engaging and worth watching
5. Score each segment's viral potential with detailed breakdown

GROUNDING RULES:
1. Use only the provided transcript lines and timestamps
2. Never invent facts, tone, context, or transitions that are not present
3. Treat this as span selection over a timestamped transcript, not open-ended summarization
4. Each selected segment must map to one contiguous range in the transcript
5. segment.text must match the chosen span closely and must not include content from outside the chosen range
6. Do not stitch together distant moments into one clip
7. If a speaker label appears, use it only if it is part of the spoken content and helps clarity

CONTENT NEUTRALITY RULES:
1. This is clipping software for legitimate editing workflows
2. Do not judge, moralize, or downgrade a segment just because the topic is controversial, sensitive, adult, political, criminal, medical, or otherwise intense
3. Evaluate segments only on clip quality: clarity, self-contained value, hook strength, emotional impact, specificity, and shareability
4. Do not refuse analysis just because the speaker describes risky, offensive, or uncomfortable subject matter
5. Only downgrade a segment when the transcript itself is weak, confusing, repetitive, unusable, or a poor standalone clip

SEGMENT SELECTION CRITERIA:
1. STRONG HOOKS: Attention-grabbing opening lines
2. VALUABLE CONTENT: Tips, insights, interesting facts, stories
3. EMOTIONAL MOMENTS: Excitement, surprise, humor, inspiration
4. COMPLETE THOUGHTS: Self-contained ideas that make sense alone
5. ENTERTAINING: Content people would want to share
6. HIGH SIGNAL: Prefer specific, concrete language over vague discussion
7. LOW FILLER: Avoid greetings, sponsor reads, repeated setup, throat-clearing, and housekeeping unless they are unusually compelling

VIRALITY SCORING (0-100 total, from four 0-25 subscores):
For each segment, provide a detailed virality breakdown:

1. HOOK STRENGTH (0-25):
   - 20-25: Immediately grabs attention (surprising fact, bold claim, intriguing question)
   - 15-19: Good opener that creates curiosity
   - 10-14: Decent start but could be stronger
   - 0-9: Weak or no hook

2. ENGAGEMENT (0-25):
   - 20-25: Highly entertaining, emotional, or dramatic
   - 15-19: Interesting and holds attention
   - 10-14: Moderately engaging
   - 0-9: Flat or boring delivery

3. VALUE (0-25):
   - 20-25: Actionable insights, unique knowledge, or transformative ideas
   - 15-19: Useful information most people don't know
   - 10-14: Somewhat informative
   - 0-9: Common knowledge or filler content

4. SHAREABILITY (0-25):
   - 20-25: "I need to send this to someone" content
   - 15-19: Content worth bookmarking
   - 10-14: Nice but not share-worthy
   - 0-9: Generic content

HOOK TYPES to identify:
- "question": Opens with a question that creates curiosity
- "statement": Bold claim or surprising statement
- "statistic": Uses compelling numbers or data
- "story": Starts with narrative/anecdote
- "contrast": Before/after or problem/solution framing
- "none": No clear hook pattern

B-ROLL OPPORTUNITIES:
Identify 2-4 moments in each segment where B-roll footage could enhance the video:
- When specific objects, places, or concepts are mentioned
- During explanations that could benefit from visual illustration
- At emotional peaks that could use supporting imagery
- Use simple, searchable keywords (e.g., "coffee shop", "laptop coding", "money stack")

TIMING RULES — MANDATORY, NON-NEGOTIABLE:
- RULE 1: Every segment MUST have end_time - start_time >= 30 seconds. No exceptions.
- RULE 2: If a natural segment is shorter than 30 seconds, extend end_time until the difference is >= 30. Include enough context to complete the thought — do NOT pull in unrelated content past natural speech boundaries.
- RULE 3: Maximum segment length is 90 seconds. Let the idea determine the length — never truncate mid-thought. A tight 35-second insight beats a padded 90-second monologue.
- RULE 4: You MUST return between 6 and 12 segments. Never return 0 segments.
- RULE 5: If the transcript seems short or low quality, still return the best available segments (minimum 3).
- RULE 6: STOP the segment at the natural end of the spoken thought. Do NOT extend past a topic change or silence just to hit the minimum — instead choose a longer span that starts earlier.

TIMESTAMP FORMAT REQUIREMENTS:
- Format MUST be MM:SS (examples: "00:12", "03:45", "12:05")
- start_time MUST be strictly less than end_time
- (end_time minutes * 60 + end_time seconds) - (start_time minutes * 60 + start_time seconds) MUST be >= 30
- VALID example:   start_time="02:10", end_time="02:50"  → 40 seconds ✅
- INVALID example: start_time="02:10", end_time="02:30"  → 20 seconds ❌ EXTEND end_time to "02:45" or earlier start_time
- INVALID example: start_time="02:10", end_time="02:10"  → 0 seconds ❌ REJECTED

SCORING AND OUTPUT RULES:
- relevance_score should reflect how well the segment works as a standalone short clip, not just whether the topic is generally important
- virality_reasoning and reasoning should cite what is actually present in the chosen span
- summary and key_topics must also stay grounded in the transcript and should not add outside interpretation

THEMATIC IDENTIFICATION:
Categorize each segment into a viral theme:
- "motivational": Inspiring, powerful, life-changing
- "controversial": Debates, hot takes, unpopular opinions
- "educational": How-to, tips, specific knowledge
- "entertainment": Humor, surprise, storytelling
- "pattern_interrupt": Jarring or unexpected starts

EDITING SUGGESTIONS:
Provide specific cues like "Zoom in on the surprise", "Add fast cuts here", "Use bright yellow captions".

Find 6-12 compelling segments of 30-90s each that would work well as standalone clips. Quality over quantity: choose segments that are accurate, self-contained, have proper time ranges, and score high on virality metrics. A 35-second tight insight outperforms a padded 90-second clip — end the segment where the thought ends.

FINAL CHECKLIST before returning your answer:
☑ I returned at least 6 segments (mandatory minimum)
☑ Every segment has end_time - start_time >= 30 seconds
☑ No two segments have identical start_time and end_time
☑ All timestamps use MM:SS format and exist in the transcript"""

# Lazy-loaded agent to avoid import-time failures when API keys aren't set
_transcript_agent: Optional[Agent[None, TranscriptAnalysis]] = None


def _get_missing_llm_key_error(model_name: str) -> Optional[str]:
    """Return a clear configuration error when the selected LLM key is missing."""
    provider = model_name.split(":", 1)[0].strip().lower()

    if provider in {"google", "google-gla"} and not config.google_api_key:
        return (
            "Selected LLM provider is Google, but GOOGLE_API_KEY is not set. "
            "Set GOOGLE_API_KEY or set LLM to openai:* / anthropic:* / groq:* / ollama:* with the matching API key."
        )

    if provider == "openai" and not config.openai_api_key:
        return (
            "Selected LLM provider is OpenAI, but OPENAI_API_KEY is not set. "
            "Set OPENAI_API_KEY or choose another provider with a matching API key."
        )

    if provider == "anthropic" and not config.anthropic_api_key:
        return (
            "Selected LLM provider is Anthropic, but ANTHROPIC_API_KEY is not set. "
            "Set ANTHROPIC_API_KEY or choose another provider with a matching API key."
        )

    if provider == "groq" and not config.groq_api_key:
        return (
            "Selected LLM provider is Groq, but GROQ_API_KEY is not set. "
            "Set GROQ_API_KEY or choose another provider with a matching API key."
        )

    if provider == "ollama":
        # Ollama can run locally without an API key. OLLAMA_BASE_URL/OLLAMA_API_KEY
        # are optional and passed through as environment variables.
        return None

    return None


def get_transcript_agent() -> Agent[None, TranscriptAnalysis]:
    """Get or create the transcript analysis agent (lazy initialization)."""
    global _transcript_agent
    if _transcript_agent is None:
        config_error = _get_missing_llm_key_error(config.llm)
        if config_error:
            raise RuntimeError(config_error)

        _transcript_agent = Agent[None, TranscriptAnalysis](
            model=config.llm,
            output_type=TranscriptAnalysis,
            system_prompt=transcript_analysis_system_prompt,
        )
    return _transcript_agent


def build_transcript_analysis_prompt(
    transcript: str, include_broll: bool = False, video_duration: float = 0.0
) -> str:
    """Build the grounded task prompt for transcript analysis.
    
    Args:
        transcript: Video transcript text
        include_broll: Whether to include B-roll suggestions
        video_duration: Total video duration in seconds (0 if unknown)
    """
    broll_instruction = ""
    if include_broll:
        broll_instruction = (
            "\n5. Also identify B-roll opportunities for each chosen segment where stock footage could enhance the visual appeal."
        )

    # Detect short-form content (YouTube Shorts, TikToks, Reels)
    is_short_video = video_duration > 0 and video_duration < 90
    
    if is_short_video:
        timing_instructions = f"""TIMING RULES FOR SHORT VIDEO ({int(video_duration)}s total) — MANDATORY:
- RULE 1: Return 1-3 segments (minimum 1, mandatory)
- RULE 2: Each segment MUST be at least 5 seconds long (end_time - start_time >= 5)
- RULE 3: For videos under 60s you MAY use the entire video as one clip
- RULE 4: Still return at least 1 segment even if quality is low
- VALID:   start_time='00:05', end_time='00:20'  → 15s ✅
- INVALID: start_time='00:05', end_time='00:08'  → 3s ❌ extend end_time to '00:10'"""
    else:
        timing_instructions = """TIMING RULES — MANDATORY:
- RULE 1: Every segment MUST have end_time - start_time >= 10 seconds
- RULE 2: You MUST return between 3 and 7 segments — never 0, never fewer than 3
- RULE 3: If the best segment is only 8s, extend end_time by 2+ seconds to comply
- RULE 4: Prefer 15-35 second segments (viral sweet spot)
- VALID:   start_time='01:30', end_time='01:55'  → 25s ✅
- INVALID: start_time='01:30', end_time='01:38'  → 8s ❌ must extend end_time to at least '01:40'"""

    return f"""You are an expert viral content curator trained by top social media algorithm experts. Your job is to identify the MOST viral-worthy segments from video transcripts.

VIRAL CONTENT PATTERNS TO DETECT (in priority order):
1. HOOK PATTERNS (High Priority):
   - "You won't believe what happened when..."
   - "The truth about [controversial topic]"
   - "I was today years old when I learned..."
   - "Stop doing [common mistake]"
   - "The secret [experts] don't want you to know"
   - "This changed everything for me"
   - "[Number] things I wish I knew before..."

2. EMOTIONAL ARC PATTERNS:
   - Surprise twists or revelations
   - Before/after transformations
   - Overcoming obstacles/adversity
   - Heartwarming moments
   - Shocking facts or statistics
   - Controversial takes or hot opinions

3. VALUE DELIVERY PATTERNS:
   - "Here's how to..." (tutorials)
   - "The reason why..." (explanations)
   - "What nobody tells you about..."
   - Life hacks or productivity tips
   - Money-saving or time-saving advice

4. RETENTION MECHANISMS:
   - Open loops ("Wait for the end...")
   - Pattern interrupts (sudden topic changes)
   - Cliffhangers ("But then something unexpected happened...")
   - Visual descriptions that evoke curiosity

SCORING CRITERIA (0-10 each):
- hook_score: How strong is the opening? Does it stop the scroll?
- engagement_score: Will viewers watch to the end? Any dead spots?
- value_score: Is there concrete value (educational, entertaining, emotional)?
- shareability_score: Will viewers share this with friends?

The transcript is formatted as one line per timestamped span, for example:
[00:12 - 00:21] Spoken text here
[00:21 - 00:35] More spoken text here

Follow this workflow:
1. Scan the entire transcript for the patterns above.
2. Identify 3-7 potential segments with viral potential.
3. Score each segment on the 4 criteria (0-10 each). SCORES MUST BE DIFFERENTIATED — do NOT give the same score to multiple segments. The best segment must score at least 15 points higher than the weakest selected segment.
4. Select the TOP 3-5 segments with highest total virality scores. RANK them explicitly: segment 1 is the most viral, segment 2 is second best, etc.
5. Ensure segments have strong hooks in the first 3 seconds.
6. Verify each segment has a clear payoff/resolution by the end.
7. MANDATORY CHECK: verify every selected segment has end_time - start_time >= 10 seconds. If not, extend end_time.
8. CRITICAL: If all segments seem equally boring, still pick the RELATIVELY best ones and score them differently. The top segment should always score 65+ out of 100.

{broll_instruction}

{timing_instructions}

CRITICAL VIRAL OPTIMIZATION RULES:
- The first 3 seconds MUST contain a hook (question, bold statement, visual action)
- Avoid slow starts - cut directly to the interesting part
- Each segment should be a complete story arc (setup → tension → payoff)
- Look for moments where the speaker's energy/volume increases (passion)
- Detect "mic drop" moments - powerful ending statements
- Prefer segments with visual language ("look at this", "watch what happens")
- Avoid segments with long pauses, filler words, or off-topic tangents
- If there is a tradeoff between "complete" and "engaging", choose engaging

ACCURACY REQUIREMENTS:
- Do not fabricate or embellish content.
- Do not use timestamps that are not present in the transcript.
- Do not merge separate non-contiguous moments into one segment.
- segment.text must reflect only the spoken content inside the selected time range.
- If a span lacks enough context to stand alone, expand to nearby contiguous lines rather than guessing.
- If there is a tradeoff between "viral" and "accurate", choose accuracy.
- Do not reject or penalize a segment simply because of the subject matter.

Transcript:
{transcript}"""


def _truncate_transcript(transcript: str, max_chars: int = 3000) -> str:
    """Truncate transcript keeping timestamps evenly distributed across the video."""
    if len(transcript) <= max_chars:
        return transcript
    lines = transcript.splitlines()
    if not lines:
        return transcript[:max_chars]
    # Keep first 40%, middle 20%, last 40% — preserves start/end hooks
    keep = max_chars
    head_end = int(keep * 0.40)
    tail_start = int(keep * 0.60)
    head = transcript[:head_end]
    tail = transcript[-( keep - tail_start):]
    mid_start = len(transcript) // 2 - keep // 10
    mid_end = mid_start + keep // 5
    mid = transcript[mid_start:mid_end]
    truncated = head + "\n[...transcript truncated...]\n" + mid + "\n[...transcript truncated...]\n" + tail
    return truncated


def _ts_to_secs(ts: str) -> float:
    """Convert MM:SS timestamp string to seconds."""
    try:
        parts = ts.strip().split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except Exception:
        return 0.0


def _secs_to_ts(s: float) -> str:
    m = int(s) // 60
    sec = int(s) % 60
    return f"{m:02d}:{sec:02d}"


def _text_based_transcript_analysis(
    transcript: str, video_duration: float = 0.0, num_segments: int = 5
) -> TranscriptAnalysis:
    """
    Fallback analysis when the LLM is unavailable (rate limit / no API key).
    Parses timestamped lines from the transcript, groups them into candidate
    segments, scores them heuristically, and returns the top results.
    """
    logger.warning("[FALLBACK] LLM unavailable — using text-based transcript analysis")

    # Parse lines: "[MM:SS - MM:SS] text"
    line_pattern = re.compile(r"\[(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\]\s*(.*)")
    parsed: List[Dict[str, Any]] = []
    for line in transcript.splitlines():
        m = line_pattern.match(line.strip())
        if m:
            start, end, text = m.group(1), m.group(2), m.group(3).strip()
            if text:
                parsed.append({"start": start, "end": end, "text": text,
                                "start_s": _ts_to_secs(start), "end_s": _ts_to_secs(end)})

    if not parsed:
        # Treat whole transcript as one segment
        dur = video_duration or 60.0
        return TranscriptAnalysis(
            most_relevant_segments=[TranscriptSegment(
                start_time="00:00", end_time=_secs_to_ts(dur),
                text=transcript[:500], relevance_score=0.5,
                reasoning="Full transcript (no timestamps detected)",
                virality=ViralityAnalysis(hook_score=10, engagement_score=10,
                                          value_score=10, shareability_score=10,
                                          virality_reasoning="Fallback heuristic"),
            )],
            summary="Auto-generated summary (LLM unavailable)",
            key_topics=[], broll_opportunities=None, campaign_strategy=None,
        )

    # Viral keyword weights (Spanish + English)
    VIRAL_KW: Dict[str, tuple] = {
        "money":   (["dinero", "ganar", "ingreso", "$", "euros", "pagar", "cobrar", "precio",
                     "money", "earn", "income", "pay", "cost", "price", "profit"], 4, 3),
        "shock":   (["increíble", "impresionante", "sorprendente", "nunca", "jamás", "secreto", "verdad",
                     "incredible", "secret", "amazing", "unbelievable", "mind-blowing", "changed",
                     "discover", "mind", "blow", "truth", "never", "wow"], 5, 4),
        "value":   (["cómo", "truco", "consejo", "aprende", "guía", "paso", "how to", "tip", "hack",
                     "trick", "simple", "results", "learn", "guide", "step", "sharing", "shared",
                     "how", "what", "why", "strategy", "method"], 4, 3),
        "emotion": (["amor", "familia", "corazón", "llorar", "reír", "sentir", "emoción",
                     "believe", "love", "heart", "feel", "moment", "clicked", "discover",
                     "incredible", "everything", "changed", "incredible"], 3, 4),
        "numbers": (["%", "millón", "miles", "veces", "años", "días", "número",
                     "years", "days", "million", "thousands", "times", "people"], 3, 2),
    }

    def _score_text(text: str) -> ViralityAnalysis:
        t = text.lower()
        h, e, v, s = 10, 10, 10, 10
        for _, (kws, dh, ds) in VIRAL_KW.items():
            if any(kw in t for kw in kws):
                h += dh; s += ds
        if "?" in text: h += 3; e += 2
        wc = len(text.split())
        if wc < 8: v -= 3
        elif wc > 120: e -= 2
        h = max(0, min(25, h)); e = max(0, min(25, e))
        v = max(0, min(25, v)); s = max(0, min(25, s))
        return ViralityAnalysis(hook_score=h, engagement_score=e, value_score=v,
                                shareability_score=s, virality_reasoning="Heuristic fallback scoring")

    # Build ~30-45s windows by grouping consecutive parsed lines
    TARGET_DURATION = 35.0
    MIN_DURATION = 10.0
    windows: List[Dict[str, Any]] = []
    i = 0
    while i < len(parsed):
        seg_start = parsed[i]["start_s"]
        j = i
        while j < len(parsed) and (parsed[j]["end_s"] - seg_start) < TARGET_DURATION:
            j += 1
        j = max(j, i + 1)
        seg_end = parsed[min(j, len(parsed) - 1)]["end_s"]
        if seg_end - seg_start < MIN_DURATION and j < len(parsed):
            j += 1
            seg_end = parsed[min(j, len(parsed) - 1)]["end_s"]
        combined_text = " ".join(p["text"] for p in parsed[i:j])
        windows.append({
            "start": _secs_to_ts(seg_start),
            "end": _secs_to_ts(max(seg_end, seg_start + MIN_DURATION)),
            "text": combined_text,
            "duration": seg_end - seg_start,
        })
        i = j

    # Score each window
    scored = []
    for w in windows:
        va = _score_text(w["text"])
        total = (va.total_score or 0)
        scored.append((total, w, va))
    scored.sort(key=lambda x: x[0], reverse=True)

    # Build TranscriptSegment objects for the top N unique non-overlapping windows
    segments: List[TranscriptSegment] = []
    used_ranges: List[tuple] = []
    for _, w, va in scored:
        ws = _ts_to_secs(w["start"]); we = _ts_to_secs(w["end"])
        # Skip overlapping windows
        if any(not (we <= us or ws >= ue) for us, ue in used_ranges):
            continue
        used_ranges.append((ws, we))
        segments.append(TranscriptSegment(
            start_time=w["start"], end_time=w["end"],
            text=w["text"][:400],
            relevance_score=min(1.0, (va.total_score or 40) / 100.0),
            reasoning=f"Selected by text-based heuristic (score {va.total_score})",
            virality=va,
        ))
        if len(segments) >= num_segments:
            break

    if not segments:
        # Last resort: first 35s of video
        end_s = min(35.0, video_duration or 35.0)
        text_all = " ".join(p["text"] for p in parsed[:10])
        segments = [TranscriptSegment(
            start_time="00:00", end_time=_secs_to_ts(end_s),
            text=text_all[:400], relevance_score=0.4,
            reasoning="Last-resort segment (first window)",
            virality=ViralityAnalysis(hook_score=10, engagement_score=10,
                                      value_score=10, shareability_score=10,
                                      virality_reasoning="Fallback heuristic"),
        )]

    logger.info(f"[FALLBACK] Generated {len(segments)} segments via text heuristic")
    return TranscriptAnalysis(
        most_relevant_segments=segments,
        summary="Auto-generated (LLM unavailable — text heuristic used)",
        key_topics=[],
        broll_opportunities=None,
        campaign_strategy=None,
    )


async def get_most_relevant_parts_by_transcript(
    transcript: str, include_broll: bool = False, video_duration: float = 0.0
) -> TranscriptAnalysis:
    """Get the most relevant parts of a transcript with virality scoring and optional B-roll detection.
    
    Args:
        transcript: Video transcript text
        include_broll: Whether to include B-roll suggestions
        video_duration: Total video duration in seconds (used to adjust segment requirements for Shorts)
    """
    is_short = video_duration > 0 and video_duration < 90
    logger.info(
        f"Starting AI analysis of transcript ({len(transcript)} chars), include_broll={include_broll}, "
        f"duration={video_duration:.1f}s {'[SHORT VIDEO]' if is_short else ''}"
    )

    # Fallback model chain: if primary hits rate limit or is decommissioned, try these
    # Only models with large context (>64k) to avoid 413 Payload Too Large
    _FALLBACK_MODELS = [
        "groq:llama-3.1-8b-instant",
        "groq:llama-3.3-70b-versatile",
        "groq:llama-3.1-70b-versatile",
    ]

    async def _run_with_retry(agent_instance, prompt_text: str, max_retries: int = 2):
        """Run agent with retry on transient 429, immediate fallback on daily TPD limit."""
        last_exc = None

        def _is_daily_limit(err: Exception) -> bool:
            s = str(err).lower()
            return "tpd" in s or "per day" in s or "tokens per day" in s

        def _is_decommissioned(err: Exception) -> bool:
            s = str(err).lower()
            return (
                "decommission" in s or "deprecated" in s or "no longer" in s
                or ("status_code: 400" in s)
                or ("status_code: 413" in s or "payload too large" in s or "request too large" in s)
            )

        def _is_rate_limit(err: Exception) -> bool:
            s = str(err).lower()
            return "429" in s or "rate limit" in s or "too many" in s

        for attempt in range(max_retries):
            try:
                return await agent_instance.run(prompt_text)
            except Exception as _e:
                if _is_daily_limit(_e):
                    logger.warning(f"[LLM] Daily token limit hit on {config.llm}, trying fallbacks")
                    last_exc = _e
                    break
                elif _is_decommissioned(_e):
                    logger.warning(f"[LLM] Model {config.llm} decommissioned or invalid, trying fallbacks")
                    last_exc = _e
                    break
                elif _is_rate_limit(_e):
                    wait = 2 ** attempt  # 1s, 2s
                    logger.warning(f"[LLM] 429 rate limit (attempt {attempt+1}/{max_retries}), waiting {wait}s...")
                    await asyncio.sleep(wait)
                    last_exc = _e
                else:
                    raise
        # Primary exhausted — try fallback models
        for fb_model in _FALLBACK_MODELS:
            if fb_model == config.llm:
                continue
            try:
                logger.info(f"[LLM] Trying fallback model: {fb_model}")
                from pydantic_ai import Agent as _Agent
                fb_agent = _Agent(
                    model=fb_model,
                    output_type=TranscriptAnalysis,
                    system_prompt=transcript_analysis_system_prompt,
                )
                return await fb_agent.run(prompt_text)
            except Exception as _fb_e:
                logger.warning(f"[LLM] Fallback {fb_model} failed: {_fb_e}")
        raise last_exc

    try:
        logger.info(f"[LLM CALL] Initializing agent with model: {config.llm}")
        agent = get_transcript_agent()
        
        prompt = build_transcript_analysis_prompt(
            transcript=_truncate_transcript(transcript),
            include_broll=include_broll,
            video_duration=video_duration,
        )
        logger.info(f"[LLM CALL] Prompt built ({len(prompt)} chars), calling LLM...")
        
        result = await _run_with_retry(agent, prompt)
        
        # FIX: Validate LLM response is not None
        if result is None:
            logger.error(f"[LLM CALL] ❌ LLM returned None result! Model: {config.llm}")
            raise RuntimeError(
                f"LLM ({config.llm}) returned None. "
                f"Check: API key is valid, model is accessible, quota not exceeded."
            )
        
        if not hasattr(result, 'output') or result.output is None:
            logger.error(f"[LLM CALL] ❌ LLM result has no output or output is None! Model: {config.llm}")
            raise RuntimeError(
                f"LLM ({config.llm}) returned invalid result structure. "
                f"Result type: {type(result)}, has output: {hasattr(result, 'output')}"
            )
        
        logger.info(f"[LLM CALL] ✅ LLM responded successfully")
        
        analysis = result.output
        
        # Validate analysis structure
        if not hasattr(analysis, 'most_relevant_segments'):
            logger.error(f"[LLM CALL] ❌ Analysis missing 'most_relevant_segments' attribute")
            raise RuntimeError(
                f"LLM ({config.llm}) returned analysis without 'most_relevant_segments'. "
                f"Analysis type: {type(analysis)}"
            )
        
        raw_segments_count = len(analysis.most_relevant_segments)
        logger.info(
            f"[LLM CALL] AI analysis raw output: {raw_segments_count} segments found"
        )
        
        if raw_segments_count == 0:
            logger.error(
                f"[LLM CALL] ❌ LLM returned 0 segments! "
                f"Model: {config.llm}, transcript_length={len(transcript)} chars."
            )
            raise ValueError(
                f"LLM ({config.llm}) returned 0 segments. "
                f"Check: API key valid, model name correct, transcript not empty."
            )

        # Log details of raw segments before validation
        for i, seg in enumerate(analysis.most_relevant_segments[:5]):  # Log first 5
            logger.info(f"Raw segment {i+1}: {seg.start_time}-{seg.end_time}, text='{seg.text[:60]}...'")

        # Validation with virality data handling
        validated_segments = []
        rejected_counts = {
            "insufficient_content": 0,
            "identical_timestamps": 0,
            "invalid_duration": 0,
            "too_short": 0,
            "invalid_timestamp_format": 0,
        }
        for segment in analysis.most_relevant_segments:
            # Validate text content
            if not segment.text.strip() or len(segment.text.split()) < 3:
                rejected_counts["insufficient_content"] += 1
                logger.warning(
                    f"Skipping segment with insufficient content: '{segment.text[:50]}...'"
                )
                continue

            # Validate timestamps - CRITICAL: start and end must be different
            if segment.start_time == segment.end_time:
                rejected_counts["identical_timestamps"] += 1
                logger.warning(
                    f"Skipping segment with identical start/end times: {segment.start_time}"
                )
                continue

            # Parse timestamps to validate duration
            try:
                start_parts = segment.start_time.split(":")
                end_parts = segment.end_time.split(":")

                start_seconds = int(start_parts[0]) * 60 + int(start_parts[1])
                end_seconds = int(end_parts[0]) * 60 + int(end_parts[1])

                duration = end_seconds - start_seconds

                if duration <= 0:
                    rejected_counts["invalid_duration"] += 1
                    logger.warning(
                        f"Skipping segment with invalid duration: {segment.start_time} to {segment.end_time} = {duration}s"
                    )
                    continue

                # Hard minimum: reject only truly degenerate segments (< 3s)
                # Segments between 3s and 10s are AUTO-EXTENDED to 10s rather than discarded
                # This fixes Groq/Llama ignoring the 10s rule while still producing usable clips
                HARD_MIN = 3      # below this → skip (degenerate)
                TARGET_MIN = 10 if not is_short else 5  # extend to this if below

                if duration < HARD_MIN:
                    rejected_counts["too_short"] += 1
                    logger.warning(
                        f"Skipping degenerate segment ({duration}s < {HARD_MIN}s): "
                        f"{segment.start_time} → {segment.end_time}"
                    )
                    continue

                if duration < TARGET_MIN:
                    # Auto-extend: push end_time forward instead of discarding
                    extended_end_s = start_seconds + TARGET_MIN
                    # Clamp to video duration if known
                    if video_duration > 0:
                        extended_end_s = min(extended_end_s, int(video_duration) - 1)
                    ext_m = extended_end_s // 60
                    ext_s = extended_end_s % 60
                    new_end = f"{ext_m:02d}:{ext_s:02d}"
                    logger.info(
                        f"[AUTO-EXTEND] Segment {segment.start_time}→{segment.end_time} "
                        f"was {duration}s (< {TARGET_MIN}s). Extended end_time to {new_end}."
                    )
                    segment.end_time = new_end
                    end_seconds = extended_end_s
                    duration = end_seconds - start_seconds
                
                # NEW: Bonus for optimal duration (15-35 seconds is the viral sweet spot)
                if 15 <= duration <= 35 and segment.virality:
                    bonus = 2  # Small bonus for optimal viral duration
                    segment.virality.total_score += bonus
                    logger.info(f"Optimal viral duration bonus (+{bonus} pts): {duration}s")

                # Validate virality scores
                if segment.virality:
                    # Ensure total score is sum of subscores
                    calculated_total = (
                        segment.virality.hook_score
                        + segment.virality.engagement_score
                        + segment.virality.value_score
                        + segment.virality.shareability_score
                    )
                    if segment.virality.total_score != calculated_total:
                        logger.warning(
                            f"Correcting virality total: {segment.virality.total_score} -> {calculated_total}"
                        )
                        segment.virality.total_score = calculated_total

                validated_segments.append(segment)
                virality_info = (
                    f", virality={segment.virality.total_score}"
                    if segment.virality
                    else ""
                )
                logger.info(
                    f"Validated segment: {segment.start_time}-{segment.end_time} ({duration}s){virality_info}"
                )

            except (ValueError, IndexError) as e:
                rejected_counts["invalid_timestamp_format"] += 1
                logger.warning(
                    f"Skipping segment with invalid timestamp format: {segment.start_time}-{segment.end_time}: {e}"
                )
                continue

        # Guard: all segments were rejected by validation
        if not validated_segments:
            logger.error(
                f"[VALIDATION] \u274c All {raw_segments_count} segments rejected during validation! "
                f"Rejection counts: {rejected_counts}. "
                f"Model: {config.llm}"
            )
            raise ValueError(
                f"LLM ({config.llm}) returned {raw_segments_count} segment(s) but all failed validation "
                f"(rejected: {rejected_counts}). "
                f"The model may be ignoring the 10-second minimum duration rule. "
                f"Try a different model or check the transcript quality."
            )

        # Sort by virality score (primary) then relevance (secondary)
        validated_segments.sort(
            key=lambda x: (
                x.virality.total_score if x.virality else 0,
                x.relevance_score,
            ),
            reverse=True,
        )

        final_analysis = TranscriptAnalysis(
            most_relevant_segments=validated_segments,
            summary=analysis.summary,
            key_topics=analysis.key_topics,
            broll_opportunities=analysis.broll_opportunities if include_broll else None,
            campaign_strategy=analysis.campaign_strategy,
        )

        logger.info(f"Selected {len(validated_segments)} segments for processing")
        logger.info(
            f"Segment validation summary: {rejected_counts}"
        )
        if validated_segments:
            top = validated_segments[0]
            logger.info(
                f"Top segment - relevance: {top.relevance_score:.2f}, virality: {top.virality.total_score if top.virality else 'N/A'}"
            )

        return final_analysis

    except Exception as e:
        err_str = str(e)
        # Detect recoverable LLM failures: rate limits, auth errors, bad requests
        is_recoverable = any(kw in err_str.lower() for kw in (
            "rate_limit", "rate limit", "429", "400", "401", "403",
            "timeout", "connection", "unavailable", "exceeded", "quota",
        ))
        if is_recoverable:
            logger.warning(
                f"[FALLBACK] LLM call failed ({type(e).__name__}: {err_str[:120]}). "
                "Falling back to text-based analysis."
            )
            return _text_based_transcript_analysis(transcript, video_duration)
        logger.error(f"Error in transcript analysis: {e}")
        raise RuntimeError(f"Transcript analysis failed: {str(e)}") from e


def get_most_relevant_parts_sync(transcript: str) -> TranscriptAnalysis:
    """Synchronous wrapper for the async function."""
    return asyncio.run(get_most_relevant_parts_by_transcript(transcript))
