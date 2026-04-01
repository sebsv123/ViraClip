"""
Dynamic Template System by Niche
Generates video templates optimized for specific content niches.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class NicheTemplateType(Enum):
    """Types of niche-specific templates."""
    GAMING = "gaming"
    FINANCE = "finance"
    FITNESS = "fitness"
    TECH = "tech"
    COOKING = "cooking"
    FASHION = "fashion"
    TRAVEL = "travel"
    EDUCATION = "education"
    COMEDY = "comedy"
    MOTIVATION = "motivation"


@dataclass
class TemplateStyle:
    """Visual style configuration for templates."""
    primary_color: str
    secondary_color: str
    accent_color: str
    font_family: str
    title_style: str
    animation_speed: str  # slow, normal, fast
    effect_intensity: int  # 1-10


@dataclass
class NicheTemplate:
    """Template configuration for a specific niche."""
    niche: NicheTemplateType
    name: str
    description: str
    style: TemplateStyle
    intro_duration: float  # seconds
    outro_duration: float
    caption_style: str
    recommended_music_genres: List[str]
    suggested_effects: List[str]
    optimal_duration_range: Tuple[int, int]  # min, max seconds
    best_posting_times: List[str]
    hashtag_recommendations: List[str]


class DynamicTemplateSystem:
    """
    Dynamic template system optimized for content niches.
    """
    
    # Niche-specific template definitions
    TEMPLATES = {
        NicheTemplateType.GAMING: NicheTemplate(
            niche=NicheTemplateType.GAMING,
            name="Gaming Pro",
            description="High-energy template for gaming content with fast cuts and gaming aesthetics",
            style=TemplateStyle(
                primary_color="#9146FF",  # Twitch purple
                secondary_color="#00FFFF",  # Cyan
                accent_color="#FF4655",  # Valorant red
                font_family="Rajdhani-Bold",
                title_style="glitch",
                animation_speed="fast",
                effect_intensity=8
            ),
            intro_duration=2.0,
            outro_duration=3.0,
            caption_style="gaming_overlay",
            recommended_music_genres=["electronic", "dubstep", "gaming_mix"],
            suggested_effects=["glitch", "flash", "zoom_pulse", "shake"],
            optimal_duration_range=(15, 60),
            best_posting_times=["18:00-22:00", "12:00-14:00"],
            hashtag_recommendations=["gaming", "gamer", "gameplay", "twitch", "streaming"]
        ),
        
        NicheTemplateType.FINANCE: NicheTemplate(
            niche=NicheTemplateType.FINANCE,
            name="Finance Pro",
            description="Professional template for finance and investment content with data visualizations",
            style=TemplateStyle(
                primary_color="#1A3A5C",  # Deep blue
                secondary_color="#2E8B57",  # Money green
                accent_color="#FFD700",  # Gold
                font_family="Inter-Bold",
                title_style="professional",
                animation_speed="normal",
                effect_intensity=4
            ),
            intro_duration=3.0,
            outro_duration=4.0,
            caption_style="financial_ticker",
            recommended_music_genres=["corporate", "ambient", "lo-fi"],
            suggested_effects=["ken_burns", "fade", "slide"],
            optimal_duration_range=(30, 90),
            best_posting_times=["07:00-09:00", "17:00-19:00"],
            hashtag_recommendations=["finance", "investing", "money", "crypto", "stocks"]
        ),
        
        NicheTemplateType.FITNESS: NicheTemplate(
            niche=NicheTemplateType.FITNESS,
            name="Fitness Power",
            description="Energetic template for workout and fitness content with motivation vibes",
            style=TemplateStyle(
                primary_color="#FF6B35",  # Energy orange
                secondary_color="#004E89",  # Athletic blue
                accent_color="#00FF7F",  # Neon green
                font_family="Oswald-Bold",
                title_style="bold_impact",
                animation_speed="fast",
                effect_intensity=7
            ),
            intro_duration=2.5,
            outro_duration=3.5,
            caption_style="workout_counter",
            recommended_music_genres=["edm", "hip_hop", "workout_mix"],
            suggested_effects=["zoom_pulse", "shake", "flash", "motion_blur"],
            optimal_duration_range=(20, 75),
            best_posting_times=["06:00-08:00", "17:00-19:00"],
            hashtag_recommendations=["fitness", "workout", "gym", "health", "motivation"]
        ),
        
        NicheTemplateType.TECH: NicheTemplate(
            niche=NicheTemplateType.TECH,
            name="Tech Modern",
            description="Clean modern template for technology reviews and tutorials",
            style=TemplateStyle(
                primary_color="#0D1117",  # GitHub dark
                secondary_color="#58A6FF",  # Tech blue
                accent_color="#238636",  # Code green
                font_family="JetBrains-Mono-Bold",
                title_style="minimal",
                animation_speed="normal",
                effect_intensity=5
            ),
            intro_duration=2.5,
            outro_duration=3.0,
            caption_style="code_block",
            recommended_music_genres=["electronic", "ambient", "future_bass"],
            suggested_effects=["typing", "cursor", "window_slide"],
            optimal_duration_range=(30, 120),
            best_posting_times=["12:00-14:00", "19:00-22:00"],
            hashtag_recommendations=["tech", "technology", "coding", "programming", "developer"]
        ),
        
        NicheTemplateType.COOKING: NicheTemplate(
            niche=NicheTemplateType.COOKING,
            name="Culinary Delight",
            description="Warm inviting template for cooking and food content with appetizing aesthetics",
            style=TemplateStyle(
                primary_color="#8B4513",  # Warm brown
                secondary_color="#FFA500",  # Orange
                accent_color="#32CD32",  # Fresh green
                font_family="Playfair-Display-Bold",
                title_style="elegant",
                animation_speed="slow",
                effect_intensity=4
            ),
            intro_duration=3.0,
            outro_duration=4.0,
            caption_style="recipe_card",
            recommended_music_genres=["jazz", "acoustic", "bossa_nova"],
            suggested_effects=["ken_burns", "fade", "gentle_zoom"],
            optimal_duration_range=(30, 180),
            best_posting_times=["11:00-13:00", "17:00-19:00"],
            hashtag_recommendations=["cooking", "food", "recipe", "foodie", "chef"]
        ),
        
        NicheTemplateType.COMEDY: NicheTemplate(
            niche=NicheTemplateType.COMEDY,
            name="Comedy Central",
            description="Fun energetic template for comedy and entertainment content",
            style=TemplateStyle(
                primary_color="#FF1493",  # Hot pink
                secondary_color="#FFD700",  # Gold
                accent_color="#00CED1",  # Turquoise
                font_family="Comic-Neue-Bold",
                title_style="fun_bounce",
                animation_speed="fast",
                effect_intensity=9
            ),
            intro_duration=1.5,
            outro_duration=2.5,
            caption_style="comedy_bubble",
            recommended_music_genres=["comedy", "cartoon", "upbeat"],
            suggested_effects=["bounce", "wiggle", "shake", "random_zoom"],
            optimal_duration_range=(15, 90),
            best_posting_times=["19:00-23:00", "12:00-14:00"],
            hashtag_recommendations=["comedy", "funny", "laugh", "humor", "trending"]
        ),
        
        NicheTemplateType.EDUCATION: NicheTemplate(
            niche=NicheTemplateType.EDUCATION,
            name="EduSmart",
            description="Clean educational template optimized for learning and knowledge sharing",
            style=TemplateStyle(
                primary_color="#FFFFFF",  # Clean white
                secondary_color="#3498DB",  # Educational blue
                accent_color="#E74C3C",  # Attention red
                font_family="Open-Sans-Bold",
                title_style="clear",
                animation_speed="normal",
                effect_intensity=3
            ),
            intro_duration=3.0,
            outro_duration=4.0,
            caption_style="educational_card",
            recommended_music_genres=["ambient", "classical", "focus"],
            suggested_effects=["ken_burns", "highlight", "draw_circle"],
            optimal_duration_range=(45, 180),
            best_posting_times=["08:00-10:00", "15:00-17:00"],
            hashtag_recommendations=["education", "learn", "study", "facts", "knowledge"]
        ),
        
        NicheTemplateType.MOTIVATION: NicheTemplate(
            niche=NicheTemplateType.MOTIVATION,
            name="Inspire Pro",
            description="Powerful motivational template with inspiring visuals and quotes",
            style=TemplateStyle(
                primary_color="#1C1C1C",  # Dark
                secondary_color="#F5F5F5",  # Light
                accent_color="#FF6B35",  # Fire orange
                font_family="Montserrat-Black",
                title_style="impact",
                animation_speed="slow",
                effect_intensity=6
            ),
            intro_duration=2.5,
            outro_duration=4.0,
            caption_style="quote_overlay",
            recommended_music_genres=["epic", "orchestral", "motivational"],
            suggested_effects=["dramatic_zoom", "fade_black", "text_glow"],
            optimal_duration_range=(30, 90),
            best_posting_times=["06:00-08:00", "20:00-22:00"],
            hashtag_recommendations=["motivation", "inspiration", "success", "mindset", "grind"]
        ),
    }
    
    def get_template(self, niche: NicheTemplateType) -> NicheTemplate:
        """Get template for a specific niche."""
        return self.TEMPLATES.get(niche, self.TEMPLATES[NicheTemplateType.EDUCATION])
    
    def get_template_by_niche_name(self, niche_name: str) -> NicheTemplate:
        """Get template by niche name string."""
        try:
            niche = NicheTemplateType(niche_name.lower())
            return self.get_template(niche)
        except ValueError:
            logger.warning(f"Unknown niche: {niche_name}, using default")
            return self.TEMPLATES[NicheTemplateType.EDUCATION]
    
    def get_optimal_settings(
        self,
        niche: NicheTemplateType,
        content_duration: int,
        target_platform: str = "tiktok"
    ) -> Dict[str, Any]:
        """Get optimal rendering settings for a niche."""
        template = self.get_template(niche)
        
        # Adjust duration if needed
        min_dur, max_dur = template.optimal_duration_range
        adjusted_duration = max(min_dur, min(content_duration, max_dur))
        
        return {
            "template": template.name,
            "style_config": {
                "primary_color": template.style.primary_color,
                "secondary_color": template.style.secondary_color,
                "accent_color": template.style.accent_color,
                "font_family": template.style.font_family,
                "title_style": template.style.title_style,
                "animation_speed": template.style.animation_speed,
                "effect_intensity": template.style.effect_intensity,
            },
            "timing": {
                "intro_seconds": template.intro_duration,
                "outro_seconds": template.outro_duration,
                "recommended_duration": adjusted_duration,
            },
            "content": {
                "caption_style": template.caption_style,
                "recommended_music": template.recommended_music_genres,
                "suggested_effects": template.suggested_effects,
                "hashtag_recommendations": template.hashtag_recommendations,
            },
            "posting": {
                "best_times": template.best_posting_times,
            },
            "platform_adjustments": self._get_platform_adjustments(target_platform)
        }
    
    def _get_platform_adjustments(self, platform: str) -> Dict[str, Any]:
        """Get platform-specific adjustments."""
        adjustments = {
            "tiktok": {
                "aspect_ratio": "9:16",
                "safe_zones": {"top": 120, "bottom": 250},
                "max_duration": 180,
                "caption_position": "bottom",
            },
            "youtube_shorts": {
                "aspect_ratio": "9:16",
                "safe_zones": {"top": 100, "bottom": 200},
                "max_duration": 60,
                "caption_position": "bottom",
            },
            "instagram_reels": {
                "aspect_ratio": "9:16",
                "safe_zones": {"top": 150, "bottom": 280},
                "max_duration": 90,
                "caption_position": "bottom",
            },
        }
        
        return adjustments.get(platform, adjustments["tiktok"])
    
    def generate_complete_style_config(
        self,
        niche_name: str,
        content_type: str = "general",
        target_platform: str = "tiktok"
    ) -> Dict[str, Any]:
        """
        Generate complete style configuration for a video.
        
        Args:
            niche_name: Name of the content niche
            content_type: Type of content (tutorial, review, etc.)
            target_platform: Target social platform
        """
        template = self.get_template_by_niche_name(niche_name)
        
        # Base configuration
        config = {
            "template_name": template.name,
            "niche": template.niche.value,
            "colors": {
                "primary": template.style.primary_color,
                "secondary": template.style.secondary_color,
                "accent": template.style.accent_color,
                "background": "#000000" if template.niche == NicheTemplateType.GAMING else "#FFFFFF",
            },
            "typography": {
                "main_font": template.style.font_family,
                "backup_fonts": ["Arial", "Helvetica"],
                "title_size": 48 if template.style.animation_speed == "fast" else 42,
                "caption_size": 24,
                "highlight_size": 32,
            },
            "effects": {
                "intro_effect": template.suggested_effects[0] if template.suggested_effects else "fade",
                "outro_effect": template.suggested_effects[-1] if template.suggested_effects else "fade",
                "caption_effects": template.suggested_effects[:3],
                "intensity": template.style.effect_intensity,
            },
            "audio": {
                "recommended_genres": template.recommended_music_genres,
                "volume_music": 0.15,
                "volume_voice": 1.0,
                "fade_in": template.intro_duration,
                "fade_out": template.outro_duration,
            },
            "platform": self._get_platform_adjustments(target_platform),
            "recommendations": {
                "best_posting_times": template.best_posting_times,
                "optimal_duration": template.optimal_duration_range,
                "hashtags": template.hashtag_recommendations,
            }
        }
        
        return config
    
    def suggest_templates_for_content(
        self,
        content_description: str,
        keywords: List[str]
    ) -> List[Dict[str, Any]]:
        """Suggest templates based on content analysis."""
        suggestions = []
        
        # Score each template based on keyword matching
        for niche, template in self.TEMPLATES.items():
            score = 0
            
            # Check hashtag matches
            for keyword in keywords:
                keyword_lower = keyword.lower()
                if any(tag in keyword_lower for tag in template.hashtag_recommendations):
                    score += 10
            
            # Check content description match
            desc_lower = content_description.lower()
            if niche.value in desc_lower:
                score += 20
            
            if score > 0:
                suggestions.append({
                    "niche": niche.value,
                    "template_name": template.name,
                    "score": score,
                    "confidence": min(100, score * 5),
                    "config_preview": {
                        "primary_color": template.style.primary_color,
                        "font": template.style.font_family,
                    }
                })
        
        # Sort by score
        suggestions.sort(key=lambda x: x["score"], reverse=True)
        return suggestions[:3]  # Top 3


# Global instance
_template_system: Optional[DynamicTemplateSystem] = None


def get_dynamic_template_system() -> DynamicTemplateSystem:
    """Get global template system instance."""
    global _template_system
    if _template_system is None:
        _template_system = DynamicTemplateSystem()
    return _template_system


def get_niche_optimized_settings(
    niche_name: str,
    content_duration: int = 60,
    target_platform: str = "tiktok"
) -> Dict[str, Any]:
    """
    Convenience function to get optimized settings for a niche.
    
    Args:
        niche_name: Name of the content niche
        content_duration: Expected content duration in seconds
        target_platform: Target social platform
    
    Returns:
        Dict with complete style configuration
    """
    system = get_dynamic_template_system()
    
    # Get template settings
    template_settings = system.get_optimal_settings(
        NicheTemplateType(niche_name.lower()) if niche_name.lower() in [n.value for n in NicheTemplateType] else NicheTemplateType.EDUCATION,
        content_duration,
        target_platform
    )
    
    # Get complete style config
    style_config = system.generate_complete_style_config(niche_name, target_platform=target_platform)
    
    return {
        "template_settings": template_settings,
        "style_config": style_config,
        "rendering_recommendations": {
            "resolution": "1080x1920",
            "fps": 30,
            "bitrate": "8M",
            "codec": "libx264",
        }
    }
