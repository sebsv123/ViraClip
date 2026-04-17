"""
Caption template definitions for animated subtitles.
Each template defines styling and animation properties for different caption styles.
"""

import logging
from typing import Dict, Any, Literal

logger = logging.getLogger(__name__)

# All animation types that are actually implemented in video_utils.py
AnimationType = Literal["none", "karaoke", "pop", "fade", "bounce"]

CAPTION_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "default": {
        "name": "Default",
        "description": "Clean white text with black outline",
        "font_family": "THEBOLDFONT",
        "font_size": 28,
        "font_color": "#FFFFFF",
        "highlight_color": "#FFD700",  # Gold for current word in karaoke mode
        "stroke_color": "#000000",
        "stroke_width": 2,
        "background": False,
        "background_color": None,
        "animation": "none",
        "shadow": False,
        "position_y": 0.75,  # 75% down the video
    },
    "hormozi": {
        "name": "Hormozi",
        "description": "Bold green highlights like Alex Hormozi's videos",
        "font_family": "THEBOLDFONT",
        "font_size": 36,
        "font_color": "#FFFFFF",
        "highlight_color": "#00FF00",  # Bright green
        "stroke_color": "#000000",
        "stroke_width": 3,
        "background": True,
        "background_color": "#000000AA",  # Semi-transparent black
        "animation": "karaoke",
        "shadow": True,
        "position_y": 0.75,
    },
    "mrbeast": {
        "name": "MrBeast",
        "description": "Large yellow text with red highlights",
        "font_family": "THEBOLDFONT",
        "font_size": 42,
        "font_color": "#FFFF00",  # Yellow
        "highlight_color": "#FF0000",  # Red
        "stroke_color": "#000000",
        "stroke_width": 4,
        "background": False,
        "background_color": None,
        "animation": "pop",
        "shadow": True,
        "position_y": 0.70,  # Slightly higher
    },
    "minimal": {
        "name": "Minimal",
        "description": "Clean, subtle captions with transparent background",
        "font_family": "TikTokSans-Regular",
        "font_size": 24,
        "font_color": "#FFFFFF",
        "highlight_color": "#CCCCCC",
        "stroke_color": None,
        "stroke_width": 0,
        "background": True,
        "background_color": "#00000080",  # 50% transparent black
        "animation": "fade",
        "shadow": False,
        "position_y": 0.80,
    },
    "tiktok": {
        "name": "TikTok",
        "description": "TikTok-style with pink highlights",
        "font_family": "TikTokSans-Regular",
        "font_size": 32,
        "font_color": "#FFFFFF",
        "highlight_color": "#FE2C55",  # TikTok pink
        "stroke_color": "#000000",
        "stroke_width": 2,
        "background": False,
        "background_color": None,
        "animation": "karaoke",
        "shadow": True,
        "position_y": 0.75,
    },
    "neon": {
        "name": "Neon",
        "description": "Glowing neon effect with cyan highlights",
        "font_family": "THEBOLDFONT",
        "font_size": 34,
        "font_color": "#00FFFF",  # Cyan
        "highlight_color": "#FF00FF",  # Magenta
        "stroke_color": "#000066",  # Dark blue
        "stroke_width": 2,
        "background": False,
        "background_color": None,
        "animation": "karaoke",
        "shadow": True,
        "position_y": 0.75,
    },
    "podcast": {
        "name": "Podcast",
        "description": "Professional podcast-style captions",
        "font_family": "TikTokSans-Regular",
        "font_size": 26,
        "font_color": "#FFFFFF",
        "highlight_color": "#FFB800",  # Warm gold
        "stroke_color": "#333333",
        "stroke_width": 1,
        "background": True,
        "background_color": "#1A1A1ACC",  # Dark semi-transparent
        "animation": "fade",
        "shadow": False,
        "position_y": 0.78,
    },
    "viral_pro": {
        "name": "Viral Pro",
        "description": "Ultra-bold, yellow highlights, heavy stroke (Viral top quality)",
        "font_family": "THEBOLDFONT",
        "font_size": 40,
        "font_color": "#FFFFFF",
        "highlight_color": "#FFFF00",  # Yellow
        "stroke_color": "#000000",
        "stroke_width": 4,
        "background": False,
        "background_color": None,
        "animation": "pop",
        "shadow": True,
        "position_y": 0.75,
    },
    "minimal_box": {
        "name": "Minimal Box",
        "description": "Clean text with semi-transparent background box",
        "font_family": "TikTokSans-Regular",
        "font_size": 28,
        "font_color": "#FFFFFF",
        "highlight_color": "#00FF00",  # Green
        "stroke_color": None,
        "stroke_width": 0,
        "background": True,
        "background_color": "#000000CC",  # 80% transparent black
        "animation": "karaoke",
        "shadow": False,
        "position_y": 0.82,
    },
    "bounce": {
        "name": "Bounce",
        "description": "Each word springs in with a fast pop animation — high-energy viral style",
        "font_family": "THEBOLDFONT",
        "font_size": 38,
        "font_color": "#FFFFFF",
        "highlight_color": "#FFFF00",  # Yellow
        "stroke_color": "#000000",
        "stroke_width": 4,
        "background": False,
        "background_color": None,
        "animation": "bounce",
        "shadow": True,
        "position_y": 0.75,
    },
    "fire": {
        "name": "Fire",
        "description": "Intense orange-red bouncing captions for maximum hype content",
        "font_family": "THEBOLDFONT",
        "font_size": 42,
        "font_color": "#FF6600",   # Deep orange
        "highlight_color": "#FF0000",  # Red for emphasis
        "stroke_color": "#1A0000",  # Near-black red
        "stroke_width": 4,
        "background": False,
        "background_color": None,
        "animation": "bounce",
        "shadow": True,
        "position_y": 0.73,
    },
    "subtitles": {
        "name": "Subtitles",
        "description": "Clean, accessible subtitle style with high-contrast background — great for podcasts and interviews",
        "font_family": "TikTokSans-Regular",
        "font_size": 26,
        "font_color": "#FFFFFF",
        "highlight_color": "#FFFFFF",
        "stroke_color": None,
        "stroke_width": 0,
        "background": True,
        "background_color": "#000000CC",
        "animation": "fade",
        "shadow": False,
        "position_y": 0.83,
    },
    "tiktok_word": {
        "name": "TikTok Word",
        "description": "Active word highlighted in yellow, rest white — karaoke style viral captions",
        "font_family": "THEBOLDFONT",
        "font_size": 52,
        "font_color": "#FFFFFF",
        "highlight_color": "#FFFF00",
        "stroke_color": "#000000",
        "stroke_width": 3,
        "background": False,
        "background_color": None,
        "animation": "karaoke",
        "shadow": True,
        "position_y": 0.78,
    },
    "bold": {
        "name": "Bold",
        "description": "Uppercase black text on white background — maximum readability contrast",
        "font_family": "THEBOLDFONT",
        "font_size": 56,
        "font_color": "#000000",
        "highlight_color": "#000000",
        "stroke_color": None,
        "stroke_width": 0,
        "background": True,
        "background_color": "#FFFFFF",
        "uppercase": True,
        "animation": "fade",
        "shadow": False,
        "position_y": 0.50,
    },
}


def get_template(template_name: str) -> Dict[str, Any]:
    """Get a caption template by name, returns default if not found."""
    return CAPTION_TEMPLATES.get(template_name, CAPTION_TEMPLATES["default"])


def get_all_templates() -> Dict[str, Dict[str, Any]]:
    """Get all available caption templates."""
    return CAPTION_TEMPLATES


def get_template_names() -> list:
    """Get list of all template names."""
    return list(CAPTION_TEMPLATES.keys())


def get_template_info() -> list:
    """Get list of template info for API response."""
    return [
        {
            "id": name,
            "name": template["name"],
            "description": template["description"],
            "animation": template["animation"],
            "font_family": template["font_family"],
            "font_size": template["font_size"],
            "font_color": template["font_color"],
            "highlight_color": template["highlight_color"],
        }
        for name, template in CAPTION_TEMPLATES.items()
    ]
