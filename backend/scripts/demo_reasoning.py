"""
Reasoning System Demo

Interactive demonstration of structured Chain-of-Thought reasoning.
Shows transparent reasoning steps for virality analysis.
"""

import asyncio
import sys
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.reasoning.virality_pipeline import get_virality_pipeline


# Sample video content for testing
SAMPLE_CONTENT = {
    "high_viral": {
        "transcript": "You won't believe what happened next! I was walking down the street when suddenly...",
        "duration": 18.5,
        "audio_features": {
            "tempo_bpm": 140,
            "energy_peak_count": 5
        }
    },
    "medium_viral": {
        "transcript": "Today I'm going to show you how to make the perfect morning routine that changed my life.",
        "duration": 32.0,
        "audio_features": {
            "tempo_bpm": 100,
            "energy_peak_count": 2
        }
    },
    "low_viral": {
        "transcript": "This is a video about my day. I woke up, had breakfast, and then went to work.",
        "duration": 45.0,
        "audio_features": {
            "tempo_bpm": 80,
            "energy_peak_count": 1
        }
    }
}


def print_separator(title: str):
    """Print section separator."""
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80 + "\n")


def print_reasoning_trace(trace: list):
    """Print reasoning trace in readable format."""
    print("\n📝 Reasoning Trace:")
    print("-" * 80)
    
    for step in trace:
        print(f"\n{step['step']}:")
        print(f"  {step['summary']}")
    
    print("-" * 80)


def print_virality_scores(result: dict):
    """Print virality scores."""
    print("\n📊 Virality Scores:")
    print("-" * 80)
    
    dimensions = [
        ("Pattern Interrupt", result.get("pattern_interrupt", 0)),
        ("Curiosity Gap", result.get("curiosity_gap", 0)),
        ("Emotional Spike", result.get("emotional_spike", 0)),
        ("Shareability", result.get("shareability", 0)),
        ("Loop Potential", result.get("loop_potential", 0)),
    ]
    
    for name, score in dimensions:
        bar = "█" * (score // 5) + "░" * (20 - score // 5)
        print(f"{name:20s} [{bar}] {score}/100")
    
    print("-" * 80)
    print(f"Total Score: {result.get('total_score', 0)}/100")
    print(f"Primary Hook: {result.get('primary_hook_type', 'N/A')}")
    print(f"Scroll Stop Probability: {result.get('scroll_stop_probability', 0):.1%}")


def print_recommendations(result: dict):
    """Print recommendations."""
    print("\n💡 Recommendations:")
    print("-" * 80)
    
    print(f"Recommended Duration: {result.get('recommended_duration', 'N/A')}")
    print(f"Edit Suggestions: {', '.join(result.get('edit_suggestions', []))}")
    print(f"Hashtag Themes: {', '.join(result.get('hashtag_themes', []))}")
    
    print("-" * 80)


def print_metadata(result: dict):
    """Print metadata."""
    print("\n⚙️ Metadata:")
    print(f"Reasoning Mode: {result.get('reasoning_mode', 'N/A')}")
    print(f"Total Tokens: {result.get('total_tokens', 0)}")


async def demo_content(name: str, content: dict):
    """Demo reasoning on sample content."""
    print_separator(f"Analyzing: {name}")
    
    # Display input
    print("📝 Input:")
    print(f"Transcript: {content['transcript'][:100]}...")
    print(f"Duration: {content['duration']}s")
    print(f"Audio: {json.dumps(content['audio_features'], indent=2)}")
    
    # Get pipeline (no LLM client = rule-based fallback)
    pipeline = get_virality_pipeline(llm_client=None)
    
    # Analyze
    print("\n🔍 Running structured reasoning pipeline...")
    result = await pipeline.analyze_virality(
        transcript=content["transcript"],
        duration=content["duration"],
        audio_features=content["audio_features"]
    )
    
    # Display results
    print_reasoning_trace(result.get("reasoning_trace", []))
    print_virality_scores(result)
    print_recommendations(result)
    print_metadata(result)


async def main():
    """Run demo."""
    print_separator("ViraClip Structured Reasoning System - Demo")
    
    print("""
This demo shows the 5-step Chain-of-Thought reasoning pipeline:

1. OBSERVE - Extract objective facts
2. ANALYZE - Identify patterns
3. HYPOTHESIZE - Generate theories
4. SCORE - Quantify dimensions
5. RECOMMEND - Actionable suggestions

Running without LLM (rule-based fallback mode)...
""")
    
    # Demo each content type
    for name, content in SAMPLE_CONTENT.items():
        await demo_content(name, content)
        
        # Pause between demos
        if name != list(SAMPLE_CONTENT.keys())[-1]:
            input("\nPress Enter to continue...")
    
    # Summary
    print_separator("Demo Complete")
    
    print("""
💡 Key Benefits of Structured Reasoning:

✅ Transparent - See each reasoning step
✅ Debuggable - Trace errors to specific steps
✅ Auditable - Save reasoning traces for review
✅ Reusable - Same pipeline for multiple tasks
✅ Testable - Each step can be unit tested

To enable LLM-powered reasoning:
1. Set REASONING_MODE=structured in .env
2. Configure LLM client (Ollama, Groq, etc.)
3. Set SAVE_REASONING_TRACES=true to save traces

Reasoning traces saved to: /app/data/reasoning_traces/
""")


if __name__ == "__main__":
    asyncio.run(main())
