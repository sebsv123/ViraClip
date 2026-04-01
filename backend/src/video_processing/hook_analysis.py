"""
Viral Hook Analysis Module
Detects viral content patterns in transcripts for optimal clip selection.
Comparable to Opus AI and Clio AI hook detection capabilities.
"""

import re
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass


@dataclass
class HookPattern:
    """Represents a detected viral hook pattern."""
    pattern_type: str
    text: str
    confidence: float  # 0.0 to 1.0
    position: str  # "start", "middle", "end"
    keywords: List[str]


# Viral hook pattern definitions with regex
HOOK_PATTERNS = {
    "curiosity_gap": {
        "patterns": [
            r"you won't believe",
            r"wait until you see",
            r"this is crazy",
            r"i can't believe",
            r"guess what happened",
            r"prepare to be shocked",
            r"mind blown",
            r"unbelievable",
        ],
        "weight": 1.0,
    },
    "controversial_take": {
        "patterns": [
            r"the truth about",
            r"what (?:they|nobody) don't want you to know",
            r"the real reason",
            r"here's what actually happened",
            r"unpopular opinion",
            r"hot take",
            r"controversial but",
        ],
        "weight": 0.95,
    },
    "transformation": {
        "patterns": [
            r"before and after",
            r"this changed everything",
            r"life changing",
            r"transformed my",
            r"the result",
            r"look at this now",
            r"can't believe the difference",
        ],
        "weight": 0.9,
    },
    "number_list": {
        "patterns": [
            r"(\d+) (?:things?|ways?|tips?|secrets?|hacks?|mistakes?|reasons?)",
            r"top (\d+)",
            r"number (\d+)",
        ],
        "weight": 0.85,
    },
    "how_to": {
        "patterns": [
            r"how to",
            r"here'?s how",
            r"the best way to",
            r"step by step",
            r"tutorial",
            r"guide to",
        ],
        "weight": 0.8,
    },
    "emotional_trigger": {
        "patterns": [
            r"heartwarming",
            r"touching",
            r"emotional",
            r"made me cry",
            r"so inspiring",
            r"restore your faith",
        ],
        "weight": 0.85,
    },
    "urgency_scarcity": {
        "patterns": [
            r"don't miss",
            r"before it's too late",
            r"limited time",
            r"act now",
            r"urgent",
            r"last chance",
        ],
        "weight": 0.75,
    },
    "story_hook": {
        "patterns": [
            r"story time",
            r"let me tell you",
            r"once upon a time",
            r"true story",
            r"this actually happened",
            r"i remember when",
        ],
        "weight": 0.8,
    },
    "mystery": {
        "patterns": [
            r"the mystery of",
            r"unsolved",
            r"what really happened",
            r"the secret behind",
            r"nobody knows",
        ],
        "weight": 0.9,
    },
    "authority": {
        "patterns": [
            r"experts say",
            r"science says",
            r"studies show",
            r"research proves",
            r"according to",
        ],
        "weight": 0.7,
    },
}


def detect_hooks_in_text(text: str, position: str = "unknown") -> List[HookPattern]:
    """
    Detect viral hook patterns in text.
    
    Args:
        text: The text to analyze
        position: Position in segment ("start", "middle", "end")
        
    Returns:
        List of detected HookPattern objects
    """
    detected = []
    text_lower = text.lower()
    
    for hook_type, config in HOOK_PATTERNS.items():
        for pattern in config["patterns"]:
            matches = re.finditer(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                # Calculate confidence based on pattern weight and match quality
                confidence = config["weight"]
                
                # Boost confidence for early matches in the text
                match_pos = match.start() / len(text) if text else 0
                if match_pos < 0.1:  # Within first 10% of text
                    confidence *= 1.2  # 20% boost for early hooks
                
                # Cap at 1.0
                confidence = min(1.0, confidence)
                
                hook = HookPattern(
                    pattern_type=hook_type,
                    text=match.group(),
                    confidence=confidence,
                    position=position,
                    keywords=[match.group()],
                )
                detected.append(hook)
    
    return detected


def score_segment_hooks(segment_text: str) -> Dict[str, Any]:
    """
    Score a segment's hook potential.
    
    Returns dict with:
    - total_hook_score: 0-100
    - detected_hooks: list of HookPattern
    - hook_density: hooks per sentence
    - primary_hook_type: strongest pattern type
    """
    # Split into parts (first 3 seconds, middle, last 3 seconds)
    sentences = re.split(r'[.!?]+', segment_text)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    if not sentences:
        return {
            "total_hook_score": 0,
            "detected_hooks": [],
            "hook_density": 0,
            "primary_hook_type": None,
        }
    
    all_hooks = []
    
    # Analyze different parts with different weights
    # First sentence gets 2x weight (opening hook is crucial)
    if sentences:
        first_hooks = detect_hooks_in_text(sentences[0], "start")
        for hook in first_hooks:
            hook.confidence *= 2.0  # Double weight for opening
        all_hooks.extend(first_hooks)
    
    # Last sentence gets 1.5x weight (closing hook for retention)
    if len(sentences) > 1:
        last_hooks = detect_hooks_in_text(sentences[-1], "end")
        for hook in last_hooks:
            hook.confidence *= 1.5
        all_hooks.extend(last_hooks)
    
    # Middle sentences get normal weight
    for sentence in sentences[1:-1]:
        middle_hooks = detect_hooks_in_text(sentence, "middle")
        all_hooks.extend(middle_hooks)
    
    if not all_hooks:
        return {
            "total_hook_score": 0,
            "detected_hooks": [],
            "hook_density": 0,
            "primary_hook_type": None,
        }
    
    # Calculate scores
    total_score = sum(hook.confidence * 25 for hook in all_hooks)  # 25 pts per hook max
    total_score = min(100, total_score)  # Cap at 100
    
    hook_density = len(all_hooks) / len(sentences)
    
    # Find primary hook type (highest confidence)
    primary_hook = max(all_hooks, key=lambda h: h.confidence)
    
    return {
        "total_hook_score": total_score,
        "detected_hooks": all_hooks,
        "hook_density": hook_density,
        "primary_hook_type": primary_hook.pattern_type,
    }


def detect_retention_mechanisms(text: str) -> Dict[str, Any]:
    """
    Detect retention mechanisms that keep viewers watching.
    
    Returns:
        Dict with retention scores and mechanisms detected
    """
    mechanisms = {
        "open_loop": False,
        "pattern_interrupt": False,
        "cliffhanger": False,
        "visual_trigger": False,
        "emotional_escalation": False,
    }
    
    text_lower = text.lower()
    
    # Open loops - phrases that promise future payoff
    open_loop_patterns = [
        r"wait (?:for|until)",
        r"keep watching",
        r"(?:coming up|up next)",
        r"(?:you'll|you will) see",
        r"stay tuned",
    ]
    for pattern in open_loop_patterns:
        if re.search(pattern, text_lower):
            mechanisms["open_loop"] = True
            break
    
    # Pattern interrupts - sudden changes in topic or style
    interrupt_patterns = [
        r"but (?:then|suddenly)",
        r"(?:plot twist|twist)",
        r"(?:however|but wait)",
        r"(?:and then|suddenly)",
    ]
    for pattern in interrupt_patterns:
        if re.search(pattern, text_lower):
            mechanisms["pattern_interrupt"] = True
            break
    
    # Cliffhangers - suspense at the end
    cliffhanger_patterns = [
        r"what happened next",
        r"(?:find out|discover) (?:in|at)",
        r"(?:to be continued|continued)",
        r"the ending will shock you",
    ]
    for pattern in cliffhanger_patterns:
        if re.search(pattern, text_lower):
            mechanisms["cliffhanger"] = True
            break
    
    # Visual triggers - words that make viewers look
    visual_patterns = [
        r"look at this",
        r"watch this",
        r"(?:check|peep) this out",
        r"(?:look|see) what happens",
    ]
    for pattern in visual_patterns:
        if re.search(pattern, text_lower):
            mechanisms["visual_trigger"] = True
            break
    
    # Emotional escalation - building intensity
    escalation_words = ["amazing", "incredible", "unbelievable", "shocking", "insane", "crazy"]
    escalation_count = sum(1 for word in escalation_words if word in text_lower)
    if escalation_count >= 2:
        mechanisms["emotional_escalation"] = True
    
    # Calculate retention score
    active_mechanisms = sum(1 for v in mechanisms.values() if v)
    retention_score = (active_mechanisms / len(mechanisms)) * 100
    
    return {
        "retention_score": retention_score,
        "mechanisms": mechanisms,
        "active_count": active_mechanisms,
    }


def analyze_segment_virality(segment_text: str) -> Dict[str, Any]:
    """
    Complete viral analysis of a segment.
    
    Returns comprehensive virality metrics including:
    - Hook analysis
    - Retention mechanisms
    - Combined virality score
    - Recommendations
    """
    hook_analysis = score_segment_hooks(segment_text)
    retention_analysis = detect_retention_mechanisms(segment_text)
    
    # Combined virality score (0-100)
    # 50% hook score, 30% retention score, 20% density bonus
    density_bonus = min(20, hook_analysis["hook_density"] * 10)
    
    combined_score = (
        hook_analysis["total_hook_score"] * 0.5 +
        retention_analysis["retention_score"] * 0.3 +
        density_bonus
    )
    
    return {
        "virality_score": combined_score,
        "hook_analysis": hook_analysis,
        "retention_analysis": retention_analysis,
        "recommendations": generate_virality_recommendations(
            hook_analysis, retention_analysis
        ),
    }


def generate_virality_recommendations(
    hook_analysis: Dict[str, Any],
    retention_analysis: Dict[str, Any]
) -> List[str]:
    """Generate actionable recommendations based on analysis."""
    recommendations = []
    
    if hook_analysis["total_hook_score"] < 30:
        recommendations.append("Add a stronger hook in the first 3 seconds")
        recommendations.append("Use curiosity gaps or controversial takes")
    
    if not retention_analysis["mechanisms"]["open_loop"]:
        recommendations.append("Add open loops to keep viewers watching")
    
    if not retention_analysis["mechanisms"]["visual_trigger"]:
        recommendations.append("Include visual language to engage viewers")
    
    if hook_analysis["hook_density"] < 0.3:
        recommendations.append("Increase hook density throughout the clip")
    
    if not retention_analysis["mechanisms"]["cliffhanger"]:
        recommendations.append("End with a cliffhanger or strong payoff")
    
    return recommendations


def compare_hook_strength(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Compare and rank multiple segments by hook strength.
    
    Args:
        segments: List of dicts with 'text' key
        
    Returns:
        Segments sorted by virality score with added analysis
    """
    analyzed = []
    
    for segment in segments:
        text = segment.get("text", "")
        analysis = analyze_segment_virality(text)
        
        segment_with_analysis = {
            **segment,
            "virality_analysis": analysis,
            "virality_score": analysis["virality_score"],
        }
        analyzed.append(segment_with_analysis)
    
    # Sort by virality score descending
    analyzed.sort(key=lambda x: x["virality_score"], reverse=True)
    
    return analyzed
