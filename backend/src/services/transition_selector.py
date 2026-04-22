"""
Transition Selector

Automatically selects appropriate transition types based on context.
"""

import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class TransitionType(str, Enum):
    """Available transition types."""
    NONE = "none"
    CUT = "cut"
    ZOOM_IN = "zoom_in"
    FADE = "fade"
    GLITCH = "glitch"


class TransitionSelector:
    """Auto-selects transitions based on context."""

    def should_use_transition(
        self,
        clip_index: int,
        total_clips: int,
        viral_score: float,
    ) -> bool:
        """
        Determine if a transition should be applied.

        Args:
            clip_index: Current clip index (0-based)
            total_clips: Total number of clips
            viral_score: Virality score (0-100)

        Returns:
            True if transition should be applied
        """
        # Only apply transitions to clips after the first one
        # and when we have multiple clips with decent viral score
        return clip_index > 0 and viral_score > 40.0 and total_clips > 1

    def select_transition(
        self,
        template_style: str,
        energy_level: float,
        use_morph: bool,
    ) -> TransitionType:
        """
        Select appropriate transition type.

        Args:
            template_style: Template style name
            energy_level: Audio energy level (0.0-1.0)
            use_morph: Whether to use morph transition

        Returns:
            Selected TransitionType
        """
        # Morph transition takes priority if enabled
        if use_morph:
            return TransitionType.GLITCH

        # High energy clips get zoom_in
        if energy_level > 0.7:
            return TransitionType.ZOOM_IN

        # Cinematic styles get fade
        if template_style in ("cinematic", "cinematic_calm"):
            return TransitionType.FADE

        # Default is cut
        return TransitionType.CUT


# Singleton
_selector_instance: Optional[TransitionSelector] = None


def get_transition_selector() -> TransitionSelector:
    """Get or create singleton transition selector."""
    global _selector_instance
    if _selector_instance is None:
        _selector_instance = TransitionSelector()
    return _selector_instance
