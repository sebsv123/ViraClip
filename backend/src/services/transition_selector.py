"""
Transition Auto-Selection

Automatically selects appropriate transition types based on:
- Template style (hormozi, mrbeast, vlog, etc.)
- Energy level (from audio analysis)
- Content type
"""

import logging
from typing import Optional
from .transition_service import TransitionType

logger = logging.getLogger(__name__)


class TransitionSelector:
    """Auto-selects transitions based on context."""
    
    def __init__(self):
        # Template-specific transition preferences
        self.template_transitions = {
            "hormozi": [TransitionType.GLITCH, TransitionType.FLASH_WHITE],
            "mrbeast": [TransitionType.FLASH_WHITE, TransitionType.GLITCH, TransitionType.SWIPE_LEFT],
            "vlog": [TransitionType.BLUR],
            "tutorial": [TransitionType.BLUR],
            "motivation": [TransitionType.FLASH_WHITE],
        }
        
        # Energy-based transition map
        self.energy_transitions = {
            "low": TransitionType.BLUR,
            "medium": TransitionType.SWIPE_LEFT,
            "high": TransitionType.FLASH_WHITE,
            "very_high": TransitionType.GLITCH,
        }
    
    def select_transition(
        self,
        template_style: str = "viral",
        energy_level: float = 0.5,
        use_morph: bool = False
    ) -> TransitionType:
        """
        Select appropriate transition type.
        
        Args:
            template_style: Template name (hormozi, mrbeast, etc.)
            energy_level: Audio energy level (0.0-1.0)
            use_morph: Use RAFT optical flow morph
            
        Returns:
            Selected TransitionType
        """
        # RAFT morph if requested and available
        if use_morph:
            return TransitionType.MORPH
        
        # Template-based selection
        template_lower = template_style.lower()
        if template_lower in self.template_transitions:
            transitions = self.template_transitions[template_lower]
            # Return first preferred transition for this template
            return transitions[0]
        
        # Energy-based selection as fallback
        energy_category = self._categorize_energy(energy_level)
        return self.energy_transitions.get(energy_category, TransitionType.BLUR)
    
    def _categorize_energy(self, energy: float) -> str:
        """Categorize energy level into bins."""
        if energy < 0.3:
            return "low"
        elif energy < 0.6:
            return "medium"
        elif energy < 0.8:
            return "high"
        else:
            return "very_high"
    
    def should_use_transition(
        self,
        clip_index: int,
        total_clips: int,
        viral_score: float = 50.0
    ) -> bool:
        """
        Determine if a transition should be applied.
        
        Args:
            clip_index: Current clip index
            total_clips: Total number of clips
            viral_score: Virality score (0-100)
            
        Returns:
            True if transition should be applied
        """
        # Skip first clip (no transition before it)
        if clip_index == 0:
            return False
        
        # Higher viral score = more likely to use transitions
        if viral_score > 70:
            return True  # Always use for high viral content
        elif viral_score > 50:
            return clip_index % 2 == 0  # Every other clip
        else:
            return clip_index % 3 == 0  # Every third clip


# Singleton
_selector_instance: Optional[TransitionSelector] = None


def get_transition_selector() -> TransitionSelector:
    """Get or create singleton transition selector."""
    global _selector_instance
    if _selector_instance is None:
        _selector_instance = TransitionSelector()
    return _selector_instance
