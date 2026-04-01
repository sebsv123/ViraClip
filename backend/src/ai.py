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
from pydantic import BaseModel, Field, field_validator, model_validator

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
    engagement_score: int = Field(
        description="How engaging/entertaining is the content (0-25)", ge=0, le=25
    )
    value_score: int = Field(
        description="Educational/informational value (0-25)", ge=0, le=25
    )
    shareability_score: int = Field(
        description="Likelihood of being shared (0-25)", ge=0, le=25
    )
    total_score: int = Field(
        description="Combined virality score (0-100)", ge=0, le=100
    )
    hook_type: Optional[
        Literal["question", "statement", "statistic", "story", "contrast", "none"]
    ] = Field(
        default="none",
        description="Type of hook: question, statement, statistic, story, contrast, or none",
    )
    virality_reasoning: str = Field(description="Explanation of the virality score")


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

        # Regla 2: duración mínima 10s (con límite de video_duration)
        # TODO(future): contar cuántas veces se dispara por vídeo/modelo.
        # Si un LLM concreto lo dispara siempre → ajustar el prompt, no el validator.
        MIN_DURATION = 10.0
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

TIMING GUIDELINES - ABSOLUTELY CRITICAL:
- ⚠️ MINIMUM DURATION: 10 SECONDS - NO EXCEPTIONS
- ⚠️ If end_time - start_time < 10 seconds, THE SEGMENT WILL BE REJECTED
- Segments MUST be between 10-45 seconds for optimal engagement
- Prefer roughly 15-35 seconds when possible (viral sweet spot)
- Focus on natural content boundaries rather than arbitrary time limits
- Include enough context for the segment to be understandable
- Start as late as possible while preserving the hook, and end as early as possible after the payoff

TIMESTAMP REQUIREMENTS - EXTREMELY IMPORTANT:
- Use EXACT timestamps as they appear in the transcript
- Never modify timestamp format (keep MM:SS structure)
- start_time MUST be LESS THAN end_time (start_time < end_time)
- ⚠️ CRITICAL: end_time - start_time MUST BE >= 10 SECONDS
- Example VALID: start_time: "02:25", end_time: "02:37" (12 seconds ✅)
- Example INVALID: start_time: "02:25", end_time: "02:28" (3 seconds ❌ REJECTED)
- Look at transcript ranges like [02:25 - 02:45] and ensure 10+ second difference
- NEVER use the same timestamp for both start_time and end_time

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

Find 3-7 compelling segments that would work well as standalone clips. Quality over quantity: choose segments that are accurate, self-contained, have proper time ranges, and score high on virality metrics."""

# Lazy-loaded agent to avoid import-time failures when API keys aren't set
_transcript_agent: Optional[Agent[None, TranscriptAnalysis]] = None


def _get_missing_llm_key_error(model_name: str) -> Optional[str]:
    """Return a clear configuration error when the selected LLM key is missing."""
    provider = model_name.split(":", 1)[0].strip().lower()

    if provider in {"google", "google-gla"} and not config.google_api_key:
        return (
            "Selected LLM provider is Google, but GOOGLE_API_KEY is not set. "
            "Set GOOGLE_API_KEY or set LLM to openai:* / anthropic:* / ollama:* with the matching API key."
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
        timing_instructions = f"""TIMING GUIDELINES FOR SHORT VIDEO ({int(video_duration)}s total):
- This is already a short-form video (Shorts/TikTok/Reel)
- Create 1-3 clips maximum from the best moments
- Clips can be 5-{int(video_duration)} seconds (flexible based on content)
- For videos under 60s, consider using the ENTIRE video as one clip if it's cohesive
- MINIMUM segment duration: 5 seconds (not 10)
- Focus on the most viral/engaging portions
- It's OK to have just 1 clip if the whole video is one strong moment"""
    else:
        timing_instructions = """TIMING GUIDELINES:
- Segments MUST be between 10-45 seconds for optimal engagement
- CRITICAL: start_time MUST be different from end_time (minimum 10 seconds apart)
- Focus on natural content boundaries rather than arbitrary time limits
- Include enough context for the segment to be understandable
- Prefer roughly 15-35 seconds when possible
- Start as late as possible while preserving the hook, and end as early as possible after the payoff"""

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
3. Score each segment on the 4 criteria (0-10 each).
4. Select the TOP 3-5 segments with highest total virality scores.
5. Ensure segments have strong hooks in the first 3 seconds.
6. Verify each segment has a clear payoff/resolution by the end.

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

Transcript:
{transcript}"""


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

    try:
        agent = get_transcript_agent()

        result = await agent.run(
            build_transcript_analysis_prompt(
                transcript=transcript, include_broll=include_broll, video_duration=video_duration
            )
        )

        analysis = result.output
        raw_segments_count = len(analysis.most_relevant_segments)
        logger.info(
            f"AI analysis raw output: {raw_segments_count} segments found"
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

                # Flexible duration based on video length AND content quality
                # UPDATED: Allow 5+ second clips for both shorts and long videos
                # Short impactful clips (5-7s) can be highly viral
                min_duration = 5
                
                logger.debug(f"Segment duration: {duration}s (min required: {min_duration}s)")
                
                if duration < min_duration:
                    rejected_counts["too_short"] += 1
                    logger.warning(
                        f"Skipping segment too short: {duration}s (min {min_duration}s required for {'short' if is_short else 'long'} video)"
                    )
                    continue
                
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
        logger.error(f"Error in transcript analysis: {e}")
        raise RuntimeError(f"Transcript analysis failed: {str(e)}") from e


def get_most_relevant_parts_sync(transcript: str) -> TranscriptAnalysis:
    """Synchronous wrapper for the async function."""
    return asyncio.run(get_most_relevant_parts_by_transcript(transcript))
