"""
Viral Templates — Pre-configured Viral Editing Workflows

Complete editing presets for popular viral video styles:
- Hormozi: Aggressive cuts, no music, high overlays
- MrBeast: Suspense music, very high overlays, fast pace
- Vlog: Natural pace, chill music, minimal effects
- Tutorial: Clean cuts, educational overlays
- Motivation: Slow-mo hooks, epic music
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class ViralTemplate(str, Enum):
    """Available viral template presets."""
    HORMOZI = "hormozi"
    MRBEAST = "mrbeast"
    VLOG = "vlog"
    TUTORIAL = "tutorial"
    MOTIVATION = "motivation"
    CUSTOM = "custom"


@dataclass
class ViralTemplateConfig:
    """Complete configuration for a viral editing template."""
    name: str
    
    # Jump cuts & pacing
    jump_cut_enabled: bool = True
    jump_cut_min_silence: float = 0.3
    
    # Zoom & transitions
    zoom_on_cuts: bool = True
    zoom_factor: float = 1.08
    transition_types: list = None
    
    # Audio
    bgm_enabled: bool = True
    bgm_mood: Optional[str] = None
    audio_ducking: bool = True
    sfx_intensity: str = "medium"  # low, medium, high, very_high
    
    # Captions
    caption_style: str = "tiktok"
    
    # Creative enhancements
    color_grading: Optional[str] = None
    hook_slowmo: bool = False
    
    # Contextual overlays
    overlay_enabled: bool = True
    overlay_frequency: str = "adaptive"  # low, medium, high, very_high, adaptive
    
    # AI features
    denoise_audio: bool = True
    
    # Speed control
    playback_speed: float = 1.0
    dramatic_slowmo: bool = False
    speed_ramp_enabled: bool = True
    
    # Scene detection
    use_scene_detection: bool = True
    
    def __post_init__(self):
        if self.transition_types is None:
            self.transition_types = ["jump_cut"]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API."""
        return {
            "name": self.name,
            "jump_cut": self.jump_cut_enabled,
            "jump_cut_min_silence": self.jump_cut_min_silence,
            "zoom_on_cuts": self.zoom_on_cuts,
            "zoom_factor": self.zoom_factor,
            "transition_types": self.transition_types,
            "bgm_enabled": self.bgm_enabled,
            "bgm_mood": self.bgm_mood,
            "audio_ducking": self.audio_ducking,
            "sfx_intensity": self.sfx_intensity,
            "caption_style": self.caption_style,
            "color_grading": self.color_grading,
            "hook_slowmo": self.hook_slowmo,
            "overlay_enabled": self.overlay_enabled,
            "overlay_frequency": self.overlay_frequency,
            "denoise_audio": self.denoise_audio,
        }


# Pre-configured viral templates
VIRAL_TEMPLATES: Dict[str, ViralTemplateConfig] = {
    "hormozi": ViralTemplateConfig(
        name="Hormozi Style",
        # Very aggressive cuts (business/direct style)
        jump_cut_enabled=True,
        jump_cut_min_silence=0.2,
        # Constant zoom for intensity
        zoom_on_cuts=True,
        zoom_factor=1.12,
        transition_types=["jump_cut", "zoom"],
        # No background music (voice-only)
        bgm_enabled=False,
        bgm_mood=None,
        audio_ducking=False,
        # High SFX for emphasis
        sfx_intensity="high",
        # Minimal captions (clean)
        caption_style="minimal",
        # High contrast color grading
        color_grading="high_contrast",
        # No slow-mo (stays fast)
        hook_slowmo=False,
        # Many contextual overlays
        overlay_enabled=True,
        overlay_frequency="high",
        # Professional audio
        denoise_audio=True,
    ),
    
    "mrbeast": ViralTemplateConfig(
        name="MrBeast Style",
        # Fast cuts with suspense
        jump_cut_enabled=True,
        jump_cut_min_silence=0.3,
        # Noticeable zoom
        zoom_on_cuts=True,
        zoom_factor=1.08,
        transition_types=["flash", "glitch", "zoom"],
        # Suspenseful background music
        bgm_enabled=True,
        bgm_mood="suspense",
        audio_ducking=True,
        # Very high SFX (constant engagement)
        sfx_intensity="very_high",
        # TikTok-style captions
        caption_style="tiktok",
        # Cinema-style color grading
        color_grading="cinema_cold",
        # Slow-mo for hooks
        hook_slowmo=True,
        # Maximum overlays (constant visual stimulation)
        overlay_enabled=True,
        overlay_frequency="very_high",
        # Clean audio
        denoise_audio=True,
    ),
    
    "vlog": ViralTemplateConfig(
        name="Vlog Style",
        # Natural pacing
        jump_cut_enabled=True,
        jump_cut_min_silence=0.5,
        # No aggressive zoom
        zoom_on_cuts=False,
        zoom_factor=1.0,
        transition_types=["fade", "blur"],
        # Chill background music
        bgm_enabled=True,
        bgm_mood="chill",
        audio_ducking=True,
        # Low SFX (subtle)
        sfx_intensity="low",
        # Minimal captions
        caption_style="minimal",
        # Warm vintage color grading
        color_grading="vintage_warm",
        # No slow-mo
        hook_slowmo=False,
        # Low overlays (natural feel)
        overlay_enabled=True,
        overlay_frequency="low",
        # Audio cleanup
        denoise_audio=True,
    ),
    
    "tutorial": ViralTemplateConfig(
        name="Tutorial Style",
        # Moderate pacing
        jump_cut_enabled=True,
        jump_cut_min_silence=0.4,
        # Subtle zoom for emphasis
        zoom_on_cuts=False,
        zoom_factor=1.0,
        transition_types=["cut", "fade"],
        # Neutral background music
        bgm_enabled=True,
        bgm_mood="general",
        audio_ducking=True,
        # Medium SFX
        sfx_intensity="medium",
        # Karaoke-style captions (follow-along)
        caption_style="karaoke",
        # No color grading (clean)
        color_grading=None,
        # No slow-mo
        hook_slowmo=False,
        # Medium overlays (educational context)
        overlay_enabled=True,
        overlay_frequency="medium",
        # Professional audio
        denoise_audio=True,
    ),
    
    "motivation": ViralTemplateConfig(
        name="Motivation Style",
        # Deliberate pacing
        jump_cut_enabled=True,
        jump_cut_min_silence=0.4,
        # Dramatic zoom
        zoom_on_cuts=True,
        zoom_factor=1.1,
        transition_types=["zoom", "flash"],
        # Epic/inspiring music
        bgm_enabled=True,
        bgm_mood="energetic",
        audio_ducking=True,
        # High SFX for impact
        sfx_intensity="high",
        # Highlight captions
        caption_style="highlight",
        # High contrast/saturation
        color_grading="high_contrast",
        # Slow-mo hooks for emphasis
        hook_slowmo=True,
        # High overlays (inspirational imagery)
        overlay_enabled=True,
        overlay_frequency="high",
        # Polished audio
        denoise_audio=True,
    ),
}


class ViralTemplateService:
    """Service for managing and applying viral editing templates."""
    
    def get_template(self, template_name: str) -> Optional[ViralTemplateConfig]:
        """Get a viral template by name."""
        template_name = template_name.lower()
        
        if template_name in VIRAL_TEMPLATES:
            return VIRAL_TEMPLATES[template_name]
        
        logger.warning(f"Unknown template '{template_name}', using default")
        return None
    
    def list_templates(self) -> Dict[str, str]:
        """List all available templates with descriptions."""
        return {
            name: config.name
            for name, config in VIRAL_TEMPLATES.items()
        }
    
    def get_template_config(self, template_name: str) -> Dict[str, Any]:
        """Get template configuration as dictionary."""
        template = self.get_template(template_name)
        if template:
            return template.to_dict()
        return {}
    
    def apply_template_to_params(
        self,
        template_name: str,
        existing_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Apply template configuration to existing parameters.
        Template values override existing values.
        """
        template = self.get_template(template_name)
        if not template:
            return existing_params
        
        # Merge template config into params
        template_dict = template.to_dict()
        merged = existing_params.copy()
        merged.update(template_dict)
        
        logger.info(f"Applied '{template.name}' template to parameters")
        return merged
    
    def create_custom_template(
        self,
        name: str,
        base_template: str = "vlog",
        overrides: Dict[str, Any] = None
    ) -> ViralTemplateConfig:
        """
        Create a custom template based on an existing one with overrides.
        """
        base = self.get_template(base_template)
        if not base:
            base = VIRAL_TEMPLATES["vlog"]
        
        # Create copy with overrides
        config_dict = base.to_dict()
        config_dict["name"] = name
        
        if overrides:
            config_dict.update(overrides)
        
        # Create new config (note: this won't persist unless saved)
        custom = ViralTemplateConfig(**config_dict)
        logger.info(f"Created custom template '{name}' based on '{base_template}'")
        
        return custom


# Singleton
_template_service: Optional[ViralTemplateService] = None


def get_viral_template_service() -> ViralTemplateService:
    """Get or create singleton template service."""
    global _template_service
    if _template_service is None:
        _template_service = ViralTemplateService()
    return _template_service
