"""
Smart Auto-Editing System based on Viral Content Rules
Automatically applies editing decisions based on viral content patterns.
"""

import asyncio
import re
import logging
import tempfile
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class EditRuleType(Enum):
    """Types of auto-editing rules."""
    JUMP_CUT_SILENCE = "jump_cut_silence"  # Remove pauses
    ZOOM_ON_IMPACT = "zoom_on_impact"      # Zoom on key words
    SPEED_RAMP = "speed_ramp"              # Speed up/slow down
    SPLIT_SCREEN = "split_screen"          # Add reaction/context
    TEXT_POP = "text_pop"                  # Text overlay on key phrase
    TRANSITION = "transition"              # Add transition effect
    STABILIZE = "stabilize"                # Smooth camera movement
    COLOR_BOOST = "color_boost"            # Enhance colors


@dataclass
class EditDecision:
    """A single editing decision."""
    rule_type: EditRuleType
    timestamp: float
    duration: float
    confidence: float
    parameters: Dict[str, Any]
    reason: str


@dataclass
class ViralEditRules:
    """Rules for viral content editing."""
    # Hook optimization
    hook_zoom_enabled: bool = True
    hook_zoom_intensity: float = 1.15  # 15% zoom
    
    # Silence removal
    silence_threshold_db: float = -40
    min_silence_sec: float = 0.3
    max_silence_sec: float = 1.5
    
    # Jump cuts
    jump_cut_enabled: bool = True
    jump_cut_min_gap: float = 0.2  # Minimum time between cuts
    
    # Speed ramping
    speed_ramp_enabled: bool = True
    normal_speed: float = 1.0
    speed_up_sections: float = 1.25  # Speed up boring parts
    slow_mo_impact: float = 0.75     # Slow down on impact
    
    # Color enhancement
    color_boost_enabled: bool = True
    saturation_boost: float = 1.1
    contrast_boost: float = 1.05


class SmartAutoEditor:
    """
    Intelligent auto-editing system for viral content.
    Applies editing rules based on content analysis.
    """
    
    # Viral editing patterns
    IMPACT_PHRASES = [
        r"(you won'?t believe)",
        r"(the truth about)",
        r"(secret [\w]+)",
        r"(stop doing)",
        r"(this changed everything)",
        r"(i wish i knew)",
        r"(here'?s why)",
        r"(the reason)",
        r"(what nobody tells you)",
        r"(the (real|actual) reason)",
    ]
    
    # Filler words to remove
    FILLER_WORDS = [
        "um", "uh", "like", "you know", "basically",
        "actually", "literally", "honestly", "so yeah",
        "right", "okay so", "i mean"
    ]
    
    # Energy markers
    HIGH_ENERGY_MARKERS = [
        "!", "wow", "omg", "amazing", "incredible",
        "unbelievable", "crazy", "insane"
    ]
    
    def __init__(self, rules: Optional[ViralEditRules] = None):
        self.rules = rules or ViralEditRules()
    
    async def analyze_and_edit(
        self,
        transcript: str,
        word_timings: List[Dict[str, Any]],
        video_path: Optional[Path] = None,
        emotion_data: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Analyze content and generate editing decisions.
        """
        decisions = []
        
        # 1. Find hook moments for zoom
        if self.rules.hook_zoom_enabled:
            hook_decisions = self._detect_hook_zooms(transcript, word_timings)
            decisions.extend(hook_decisions)
        
        # 2. Detect silence for jump cuts
        if self.rules.jump_cut_enabled:
            silence_decisions = self._detect_silence_gaps(word_timings)
            decisions.extend(silence_decisions)
        
        # 3. Find impact phrases for effects
        if self.rules.text_pop_enabled:
            text_decisions = self._detect_text_pop_moments(transcript, word_timings)
            decisions.extend(text_decisions)
        
        # 4. Detect energy changes for speed ramping
        if self.rules.speed_ramp_enabled:
            speed_decisions = self._detect_speed_ramp_opportunities(
                transcript, word_timings, emotion_data
            )
            decisions.extend(speed_decisions)
        
        # 5. Detect repetitive content for cuts
        repetitive_decisions = self._detect_repetitive_sections(transcript, word_timings)
        decisions.extend(repetitive_decisions)
        
        # Sort by timestamp
        decisions.sort(key=lambda x: x.timestamp)
        
        # Merge overlapping decisions
        final_decisions = self._merge_decisions(decisions)
        
        return {
            "total_decisions": len(final_decisions),
            "estimated_time_saved": self._calculate_time_saved(final_decisions),
            "decisions": [
                {
                    "type": d.rule_type.value,
                    "timestamp": d.timestamp,
                    "duration": d.duration,
                    "confidence": d.confidence,
                    "parameters": d.parameters,
                    "reason": d.reason
                }
                for d in final_decisions
            ],
            "edit_summary": self._generate_summary(final_decisions)
        }
    
    def _detect_hook_zooms(
        self,
        transcript: str,
        word_timings: List[Dict[str, Any]]
    ) -> List[EditDecision]:
        """Detect hook phrases that need zoom effect."""
        decisions = []
        
        # Check first 3 seconds for hooks using word_timings
        hook_words = [w for w in word_timings if float(w.get("start", 99)) < 3.0]
        first_segment = " ".join(w.get("word", w.get("text", "")) for w in hook_words)
        
        for pattern in self.IMPACT_PHRASES:
            match = re.search(pattern, first_segment, re.IGNORECASE)
            if match:
                # Found hook phrase
                decisions.append(EditDecision(
                    rule_type=EditRuleType.ZOOM_ON_IMPACT,
                    timestamp=0.0,
                    duration=2.0,
                    confidence=0.9,
                    parameters={
                        "zoom_factor": self.rules.hook_zoom_intensity,
                        "easing": "ease_out",
                        "target": "center_face"  # Zoom on speaker face
                    },
                    reason=f"Hook phrase detected: '{match.group(1)}'"
                ))
                break  # Only one hook zoom needed
        
        return decisions
    
    def _detect_silence_gaps(
        self,
        word_timings: List[Dict[str, Any]]
    ) -> List[EditDecision]:
        """Detect silence gaps for jump cuts."""
        decisions = []
        
        if not word_timings or len(word_timings) < 2:
            return decisions
        
        for i in range(len(word_timings) - 1):
            current_word = word_timings[i]
            next_word = word_timings[i + 1]
            
            # Calculate gap
            gap = next_word.get("start", 0) - current_word.get("end", 0)
            
            # Check if gap is in removable range
            if self.rules.min_silence_sec <= gap <= self.rules.max_silence_sec:
                # Check if word is filler
                word_text = current_word.get("word", current_word.get("text", "")).lower().strip()
                next_text = next_word.get("word", next_word.get("text", "")).lower().strip()
                
                is_filler = any(filler in word_text for filler in self.FILLER_WORDS)  # noqa
                
                confidence = 0.7 if is_filler else 0.5
                
                decisions.append(EditDecision(
                    rule_type=EditRuleType.JUMP_CUT_SILENCE,
                    timestamp=current_word.get("end", 0),
                    duration=gap,
                    confidence=confidence,
                    parameters={
                        "cut_type": "jump_cut",
                        "remove_filler": is_filler,
                        "audio_crossfade": 0.02
                    },
                    reason=f"Remove silence ({gap:.2f}s){' with filler word' if is_filler else ''}"
                ))
        
        return decisions
    
    def _detect_text_pop_moments(
        self,
        transcript: str,
        word_timings: List[Dict[str, Any]]
    ) -> List[EditDecision]:
        """Detect moments for text overlay pop."""
        decisions = []
        
        if not word_timings:
            return decisions
        
        for i, word_timing in enumerate(word_timings):
            word = word_timing.get("word", word_timing.get("text", "")).lower().strip()
            word_score = word_timing.get("score", 0.0)

            # Check if word has high alignment score (clear/emphatic pronunciation)
            if word_score >= 0.88:
                # Find phrase boundary
                phrase_start = word_timing.get("start", 0)
                phrase_end = word_timing.get("end", 0)

                # Extend to next few words for context
                if i < len(word_timings) - 1:
                    phrase_end = word_timings[i + 1].get("end", phrase_end)

                decisions.append(EditDecision(
                    rule_type=EditRuleType.TEXT_POP,
                    timestamp=phrase_start,
                    duration=phrase_end - phrase_start + 0.5,
                    confidence=word_score,
                    parameters={
                        "text": word.upper(),
                        "style": "bounce_in",
                        "position": "top_safe",  # y=h*0.22 safe zone
                        "color": "#FF0050"  # TikTok red
                    },
                    reason=f"High score emphasis: '{word}' (score={word_score:.2f})"
                ))
        
        return decisions
    
    def _detect_speed_ramp_opportunities(
        self,
        transcript: str,
        word_timings: List[Dict[str, Any]],
        emotion_data: Optional[List[Dict]]
    ) -> List[EditDecision]:
        """Detect sections for speed ramping."""
        decisions = []
        
        if not word_timings or len(word_timings) < 3:
            return decisions
        
        # Look for boring/repetitive sections (slow speech rate)
        for i in range(0, len(word_timings) - 2, 3):
            window = word_timings[i:i+3]
            if len(window) < 3:
                continue
            
            # Calculate speech rate in this window
            duration = window[-1].get("end", 0) - window[0].get("start", 0)
            word_count = len(window)
            
            if duration > 0:
                words_per_sec = word_count / duration
                
                # Slow speech = speed up
                if words_per_sec < 2.0 and duration > 2.0:
                    decisions.append(EditDecision(
                        rule_type=EditRuleType.SPEED_RAMP,
                        timestamp=window[0].get("start", 0),
                        duration=duration,
                        confidence=0.6,
                        parameters={
                            "speed": self.rules.speed_up_sections,
                            "type": "speed_up",
                            "reason": "slow speech"
                        },
                        reason="Speed up slow-speaking section"
                    ))
        
        # Check for high energy moments to slow down
        if emotion_data:
            for emotion in emotion_data:
                if emotion.get("intensity", 0) > 0.8:
                    decisions.append(EditDecision(
                        rule_type=EditRuleType.SPEED_RAMP,
                        timestamp=emotion.get("timestamp", 0),
                        duration=1.0,
                        confidence=0.8,
                        parameters={
                            "speed": self.rules.slow_mo_impact,
                            "type": "slow_mo",
                            "reason": "high emotion"
                        },
                        reason="Slow motion for emotional impact"
                    ))
        
        return decisions
    
    def _detect_repetitive_sections(
        self,
        transcript: str,
        word_timings: List[Dict[str, Any]]
    ) -> List[EditDecision]:
        """Detect repetitive content that can be trimmed."""
        decisions = []
        
        # Look for repeated phrases
        words = [w.get("word", w.get("text", "")).lower() for w in word_timings]
        
        for i in range(len(words) - 4):
            phrase = " ".join(words[i:i+3])
            
            # Check if phrase appears again nearby
            for j in range(i + 3, min(i + 15, len(words) - 2)):
                check_phrase = " ".join(words[j:j+3])
                if phrase == check_phrase and phrase not in ["and", "the", "this"]:
                    # Found repetition
                    start_time = word_timings[i].get("start", 0)
                    end_time = word_timings[j+2].get("end", 0)
                    
                    decisions.append(EditDecision(
                        rule_type=EditRuleType.JUMP_CUT_SILENCE,
                        timestamp=start_time,
                        duration=end_time - start_time,
                        confidence=0.65,
                        parameters={
                            "cut_type": "trim_repetition",
                            "keep_first": True
                        },
                        reason=f"Remove repeated phrase: '{phrase}'"
                    ))
                    break
        
        return decisions
    
    def _merge_decisions(self, decisions: List[EditDecision]) -> List[EditDecision]:
        """Merge overlapping or close decisions."""
        if not decisions:
            return decisions
        
        merged = [decisions[0]]
        
        for decision in decisions[1:]:
            last = merged[-1]
            
            # Check if overlapping or too close
            if decision.timestamp < (last.timestamp + last.duration + 0.3):
                # Merge - keep the higher confidence one
                if decision.confidence > last.confidence:
                    merged[-1] = decision
            else:
                merged.append(decision)
        
        return merged
    
    def _calculate_time_saved(self, decisions: List[EditDecision]) -> float:
        """Estimate time saved by edits."""
        saved = 0.0
        
        for d in decisions:
            if d.rule_type == EditRuleType.JUMP_CUT_SILENCE:
                saved += d.duration * 0.9  # 90% of silence removed
            elif d.rule_type == EditRuleType.SPEED_RAMP:
                if d.parameters.get("type") == "speed_up":
                    saved += d.duration * (1 - 1/d.parameters.get("speed", 1.25))
        
        return saved
    
    def _generate_summary(self, decisions: List[EditDecision]) -> str:
        """Generate human-readable summary of edits."""
        if not decisions:
            return "No auto-edits needed. Content is already well-paced."
        
        by_type = {}
        for d in decisions:
            by_type[d.rule_type] = by_type.get(d.rule_type, 0) + 1
        
        parts = [f"Generated {len(decisions)} auto-edit decisions:"]
        
        for rule_type, count in sorted(by_type.items(), key=lambda x: x[1], reverse=True):
            parts.append(f"  - {count}x {rule_type.value.replace('_', ' ')}")
        
        return "\n".join(parts)

    async def apply_text_pops(
        self,
        clip_path: Path,
        output_path: Path,
        decisions: List[Dict[str, Any]],
        hook_offset: float = 0.0,
    ) -> "Path | None":
        """
        Render TEXT_POP decisions onto the clip using FFmpeg drawtext.
        hook_offset (seconds) is added to all timestamps — use 1.0 when
        hook-flash reorder prepended 1 s to the clip.

        Returns output_path on success, None if nothing to apply or on error.
        """
        text_decisions = [
            d for d in decisions
            if d.get("type") == EditRuleType.TEXT_POP.value
            and d.get("parameters", {}).get("text")
        ]
        if not text_decisions:
            return None

        vf_parts: list[str] = []
        for d in text_decisions[:5]:  # cap at 5 overlays
            raw_text = d["parameters"]["text"]
            # Escape special drawtext chars
            safe_text = (
                raw_text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
            )
            t_start = round(float(d["timestamp"]) + hook_offset, 3)
            t_end   = round(float(d["timestamp"]) + float(d["duration"]) + hook_offset, 3)
            hex_color = d["parameters"].get("color", "#FF0050").lstrip("#")

            vf_parts.append(
                f"drawtext=text='{safe_text}'"
                f":fontsize=72"
                f":fontcolor=white"
                f":borderw=5"
                f":bordercolor=0x{hex_color}@0.95"
                f":x=(w-text_w)/2"
                f":y=h*0.65"
                f":enable='between(t,{t_start},{t_end})'"
            )

        if not vf_parts:
            return None

        vf_chain = ",".join(vf_parts)
        tmp = Path(tempfile.mktemp(suffix=clip_path.suffix, dir=clip_path.parent))
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-hide_banner", "-loglevel", "quiet", "-y",
                "-i", str(clip_path),
                "-vf", vf_chain,
                "-c:a", "copy",
                str(tmp),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=300.0)
            if tmp.exists() and tmp.stat().st_size > 0:
                return tmp
            tmp.unlink(missing_ok=True)
            return None
        except (asyncio.TimeoutError, Exception) as exc:
            logger.debug("apply_text_pops failed: %s", exc)
            tmp.unlink(missing_ok=True)
            return None
    
    def apply_preset(self, preset_name: str) -> None:
        """Apply a predefined editing preset."""
        presets = {
            "aggressive_viral": ViralEditRules(
                hook_zoom_intensity=1.25,
                min_silence_sec=0.15,
                speed_up_sections=1.4,
                text_pop_enabled=True
            ),
            "conservative": ViralEditRules(
                hook_zoom_intensity=1.08,
                min_silence_sec=0.5,
                jump_cut_enabled=True,
                speed_ramp_enabled=False
            ),
            "tutorial": ViralEditRules(
                hook_zoom_intensity=1.1,
                min_silence_sec=0.4,
                text_pop_keywords=["step", "tip", "important", "remember", "key"]
            ),
            "reaction": ViralEditRules(
                hook_zoom_intensity=1.2,
                speed_ramp_enabled=True,
                slow_mo_impact=0.5,  # More dramatic slow-mo
                color_boost_enabled=True
            )
        }
        
        if preset_name in presets:
            self.rules = presets[preset_name]
            logger.info(f"Applied editing preset: {preset_name}")
        else:
            logger.warning(f"Unknown preset: {preset_name}")


def get_smart_auto_editor(rules: Optional[ViralEditRules] = None) -> SmartAutoEditor:
    """Create new SmartAutoEditor instance per call (no singleton for parallel safety)."""
    return SmartAutoEditor(rules)


async def generate_smart_edits(
    transcript: str,
    word_timings: List[Dict[str, Any]],
    video_path: Optional[Path] = None,
    preset: str = "default"
) -> Dict[str, Any]:
    """
    Convenience function to generate smart editing decisions.
    
    Args:
        transcript: Video transcript
        word_timings: Word-level timing data
        video_path: Path to video file (optional)
        preset: Editing preset to use
    
    Returns:
        Dict with editing decisions and metadata
    """
    editor = get_smart_auto_editor()
    
    if preset != "default":
        editor.apply_preset(preset)
    
    return await editor.analyze_and_edit(transcript, word_timings, video_path)
