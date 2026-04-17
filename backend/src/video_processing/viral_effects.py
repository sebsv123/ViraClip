"""
Viral Visual Effects Module
Advanced visual effects for creating engaging short-form content.
Comparable to Opus AI and Clio AI visual enhancement capabilities.
"""

from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
import logging

# Optional imports - cv2 not required for basic functionality
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    cv2 = None
    np = None

logger = logging.getLogger(__name__)


class ViralVisualEffects:
    """
    Collection of viral-optimized visual effects for short-form content.
    Designed to maximize engagement and retention.
    """
    
    @staticmethod
    def apply_zoom_pulse(frame: np.ndarray, intensity: float = 1.05, 
                         center: Optional[Tuple[float, float]] = None) -> np.ndarray:
        """
        Apply a subtle zoom pulse effect to create visual interest.
        Perfect for emphasizing key moments.
        
        Args:
            frame: Input frame
            intensity: Zoom multiplier (1.0 = no zoom, 1.05 = 5% zoom)
            center: Zoom center point (x, y) normalized 0-1, defaults to center
        """
        h, w = frame.shape[:2]
        
        if center is None:
            center = (0.5, 0.5)
        
        cx, cy = int(center[0] * w), int(center[1] * h)
        
        # Calculate crop region
        new_w, new_h = int(w / intensity), int(h / intensity)
        x1 = max(0, cx - new_w // 2)
        y1 = max(0, cy - new_h // 2)
        x2 = min(w, x1 + new_w)
        y2 = min(h, y1 + new_h)
        
        # Crop and resize
        cropped = frame[y1:y2, x1:x2]
        return cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)
    
    @staticmethod
    def apply_shake_effect(frame: np.ndarray, magnitude: float = 2.0,
                          seed: int = 42) -> np.ndarray:
        """
        Apply subtle camera shake for energy and urgency.
        Used sparingly for impact moments.
        
        Args:
            frame: Input frame
            magnitude: Shake intensity in pixels
            seed: Random seed for reproducibility
        """
        np.random.seed(seed)
        h, w = frame.shape[:2]
        
        # Generate random offset
        dx = int(np.random.randn() * magnitude)
        dy = int(np.random.randn() * magnitude)
        
        # Create translation matrix
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        
        # Apply transformation with border replication
        return cv2.warpAffine(frame, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
    
    @staticmethod
    def apply_motion_blur(frame: np.ndarray, intensity: float = 0.3,
                         direction: str = "horizontal") -> np.ndarray:
        """
        Apply directional motion blur for speed/energy effect.
        
        Args:
            frame: Input frame
            intensity: Blur intensity 0-1
            direction: "horizontal", "vertical", or "radial"
        """
        if intensity <= 0:
            return frame
        
        h, w = frame.shape[:2]
        kernel_size = int(max(3, intensity * 15)) | 1  # Ensure odd
        
        if direction == "horizontal":
            kernel = np.zeros((1, kernel_size))
            kernel[0, :] = 1.0 / kernel_size
        elif direction == "vertical":
            kernel = np.zeros((kernel_size, 1))
            kernel[:, 0] = 1.0 / kernel_size
        else:  # radial
            kernel = np.zeros((kernel_size, kernel_size))
            center = kernel_size // 2
            for i in range(kernel_size):
                for j in range(kernel_size):
                    dist = np.sqrt((i-center)**2 + (j-center)**2)
                    if dist <= center:
                        kernel[i, j] = 1.0
            kernel /= kernel.sum()
        
        return cv2.filter2D(frame, -1, kernel)
    
    @staticmethod
    def apply_flash_effect(frame: np.ndarray, brightness: float = 1.3) -> np.ndarray:
        """
        Apply flash/brightness spike for impact moments.
        
        Args:
            frame: Input frame
            brightness: Brightness multiplier
        """
        frame_float = frame.astype(np.float32) * brightness
        return np.clip(frame_float, 0, 255).astype(np.uint8)
    
    @staticmethod
    def apply_vignette(frame: np.ndarray, intensity: float = 0.3) -> np.ndarray:
        """
        Apply vignette effect to draw focus to center.
        
        Args:
            frame: Input frame
            intensity: Vignette darkness 0-1
        """
        h, w = frame.shape[:2]
        
        # Create radial gradient
        X = np.linspace(-1, 1, w)
        Y = np.linspace(-1, 1, h)
        x, y = np.meshgrid(X, Y)
        
        # Calculate radial distance
        r = np.sqrt(x**2 + y**2)
        
        # Create vignette mask
        mask = 1 - np.clip(r * intensity, 0, 1)
        mask = np.stack([mask] * 3, axis=2)
        
        # Apply mask
        return (frame.astype(np.float32) * mask).astype(np.uint8)
    
    @staticmethod
    def apply_color_pop(frame: np.ndarray, saturation_boost: float = 1.3) -> np.ndarray:
        """
        Boost saturation for more vibrant, engaging visuals.
        
        Args:
            frame: Input frame
            saturation_boost: Saturation multiplier
        """
        # Convert to HSV
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
        
        # Boost saturation channel
        hsv[:, :, 1] *= saturation_boost
        hsv[:, :, 1] = np.clip(hsv[:, :, 1], 0, 255)
        
        # Convert back to BGR
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    
    @staticmethod
    def apply_glitch_effect(frame: np.ndarray, intensity: float = 0.1,
                           seed: int = 42) -> np.ndarray:
        """
        Apply subtle digital glitch for edgy/tech content.
        
        Args:
            frame: Input frame
            intensity: Glitch intensity 0-1
            seed: Random seed
        """
        np.random.seed(seed)
        h, w = frame.shape[:2]
        result = frame.copy()
        
        # Number of glitch lines
        num_lines = int(intensity * 10)
        
        for _ in range(num_lines):
            y = np.random.randint(0, h)
            shift = np.random.randint(-20, 20)
            thickness = np.random.randint(1, 3)
            
            # Shift the line horizontally
            line = result[y:y+thickness, :]
            if shift > 0:
                result[y:y+thickness, shift:] = line[:, :-shift]
            elif shift < 0:
                result[y:y+thickness, :shift] = line[:, -shift:]
        
        return result
    
    @staticmethod
    def apply_ken_burns(frame: np.ndarray, zoom: float = 1.1,
                       pan_direction: str = "center") -> np.ndarray:
        """
        Apply Ken Burns effect (slow zoom + pan).
        Classic documentary technique for static images.
        
        Args:
            frame: Input frame
            zoom: Zoom level
            pan_direction: "left", "right", "up", "down", "center"
        """
        h, w = frame.shape[:2]
        
        # Calculate crop size
        new_h, new_w = int(h / zoom), int(w / zoom)
        
        # Calculate offset based on pan direction
        if pan_direction == "left":
            x_offset = 0
        elif pan_direction == "right":
            x_offset = w - new_w
        elif pan_direction == "up":
            x_offset = (w - new_w) // 2
            # Would need separate y_offset logic
        elif pan_direction == "down":
            x_offset = (w - new_w) // 2
        else:  # center
            x_offset = (w - new_w) // 2
        
        y_offset = (h - new_h) // 2
        
        # Crop and resize
        cropped = frame[y_offset:y_offset+new_h, x_offset:x_offset+new_w]
        return cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)


class ViralTransitionEffects:
    """
    Viral-optimized transitions between clips.
    """
    
    @staticmethod
    def zoom_transition(clip1: np.ndarray, clip2: np.ndarray, 
                       progress: float, direction: str = "in") -> np.ndarray:
        """
        Zoom transition between two clips.
        
        Args:
            clip1: First clip frame
            clip2: Second clip frame
            progress: Transition progress 0-1
            direction: "in" (zoom in to clip2) or "out" (zoom out from clip1)
        """
        h, w = clip1.shape[:2]
        
        if direction == "in":
            # Zoom in to clip2
            zoom = 1.0 + (0.3 * progress)
            clip1_scaled = ViralVisualEffects.apply_zoom_pulse(clip1, zoom)
            
            # Crossfade
            alpha = progress
            return cv2.addWeighted(clip1_scaled, 1-alpha, clip2, alpha, 0)
        else:
            # Zoom out from clip1
            zoom = 1.0 + (0.3 * (1 - progress))
            clip1_scaled = ViralVisualEffects.apply_zoom_pulse(clip1, zoom)
            
            alpha = progress
            return cv2.addWeighted(clip1_scaled, 1-alpha, clip2, alpha, 0)
    
    @staticmethod
    def slide_transition(clip1: np.ndarray, clip2: np.ndarray,
                        progress: float, direction: str = "right") -> np.ndarray:
        """
        Slide transition between clips.
        
        Args:
            clip1: First clip frame
            clip2: Second clip frame
            progress: Transition progress 0-1
            direction: "left", "right", "up", "down"
        """
        h, w = clip1.shape[:2]
        offset = int(progress * w) if direction in ["left", "right"] else int(progress * h)
        
        result = np.zeros_like(clip1)
        
        if direction == "right":
            result[:, :w-offset] = clip1[:, offset:]
            result[:, w-offset:] = clip2[:, :offset] if offset > 0 else 0
        elif direction == "left":
            result[:, offset:] = clip1[:, :w-offset]
            result[:, :offset] = clip2[:, w-offset:] if offset > 0 else 0
        elif direction == "down":
            result[:h-offset, :] = clip1[offset:, :]
            result[h-offset:, :] = clip2[:offset, :] if offset > 0 else 0
        elif direction == "up":
            result[offset:, :] = clip1[:h-offset, :]
            result[:offset, :] = clip2[h-offset:, :] if offset > 0 else 0
        
        return result
    
    @staticmethod
    def glitch_transition(clip1: np.ndarray, clip2: np.ndarray,
                         progress: float) -> np.ndarray:
        """
        Digital glitch transition for edgy content.
        """
        # Glitch is strongest at middle of transition
        glitch_intensity = 0.2 * np.sin(progress * np.pi)
        
        # Apply glitch to both frames
        clip1_glitch = ViralVisualEffects.apply_glitch_effect(
            clip1, intensity=glitch_intensity, seed=int(progress * 100)
        )
        clip2_glitch = ViralVisualEffects.apply_glitch_effect(
            clip2, intensity=glitch_intensity, seed=int(progress * 100) + 50
        )
        
        # Crossfade
        return cv2.addWeighted(clip1_glitch, 1-progress, clip2_glitch, progress, 0)


class EffectPresets:
    """
    Pre-configured effect combinations for common viral content types.
    """
    
    @staticmethod
    def get_high_energy_preset() -> List[Dict[str, Any]]:
        """Effects for fast-paced, high-energy content (gaming, sports, pranks)."""
        return [
            {"effect": "zoom_pulse", "intensity": 1.05, "trigger": "impact"},
            {"effect": "shake", "magnitude": 1.5, "trigger": "continuous"},
            {"effect": "color_pop", "saturation": 1.4},
            {"effect": "flash", "brightness": 1.2, "trigger": "beat"},
        ]
    
    @staticmethod
    def get_emotional_preset() -> List[Dict[str, Any]]:
        """Effects for emotional/story content (inspirational, heartwarming)."""
        return [
            {"effect": "vignette", "intensity": 0.4},
            {"effect": "ken_burns", "zoom": 1.08, "pan": "slow"},
            {"effect": "color_pop", "saturation": 1.15},
        ]
    
    @staticmethod
    def get_tutorial_preset() -> List[Dict[str, Any]]:
        """Effects for educational/tutorial content."""
        return [
            {"effect": "zoom_pulse", "intensity": 1.03, "trigger": "key_point"},
            {"effect": "color_pop", "saturation": 1.2},
        ]
    
    @staticmethod
    def get_comedy_preset() -> List[Dict[str, Any]]:
        """Effects for comedy/humor content."""
        return [
            {"effect": "zoom_pulse", "intensity": 1.08, "trigger": "punchline"},
            {"effect": "shake", "magnitude": 2.0, "trigger": "reaction"},
            {"effect": "flash", "brightness": 1.15, "trigger": "surprise"},
        ]


def analyze_content_type_for_effects(transcript_text: str) -> str:
    """
    Analyze transcript to determine best effect preset.
    
    Returns: "high_energy", "emotional", "tutorial", "comedy", or "default"
    """
    text_lower = transcript_text.lower()
    
    # High energy indicators
    energy_words = ["game", "win", "fight", "battle", "epic", "insane", "crazy", "fast"]
    energy_score = sum(1 for word in energy_words if word in text_lower)
    
    # Emotional indicators
    emotion_words = ["love", "heart", "cry", "emotional", "inspiring", "touching", "beautiful"]
    emotion_score = sum(1 for word in emotion_words if word in text_lower)
    
    # Tutorial indicators
    tutorial_words = ["how to", "tutorial", "learn", "step", "guide", "explain", "tip"]
    tutorial_score = sum(1 for word in tutorial_words if word in text_lower)
    
    # Comedy indicators
    comedy_words = ["funny", "laugh", "joke", "hilarious", "comedy", "prank"]
    comedy_score = sum(1 for word in comedy_words if word in text_lower)
    
    scores = {
        "high_energy": energy_score,
        "emotional": emotion_score,
        "tutorial": tutorial_score,
        "comedy": comedy_score,
    }
    
    best_match = max(scores, key=scores.get)
    
    # Only return if score is meaningful
    if scores[best_match] >= 2:
        return best_match
    
    return "default"


def get_effects_for_content(content_type: str) -> List[Dict[str, Any]]:
    """
    Get recommended effects for a content type.
    """
    presets = {
        "high_energy": EffectPresets.get_high_energy_preset(),
        "emotional": EffectPresets.get_emotional_preset(),
        "tutorial": EffectPresets.get_tutorial_preset(),
        "comedy": EffectPresets.get_comedy_preset(),
        "default": [{"effect": "color_pop", "saturation": 1.1}],
    }
    
    return presets.get(content_type, presets["default"])
