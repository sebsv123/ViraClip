"""
Motion Utilities - Ken Burns and dynamic transformations.
"""

import logging
from moviepy import ImageClip, VideoClip
import numpy as np

logger = logging.getLogger(__name__)

def create_ken_burns_clip(
    image_path: str,
    duration: float = 3.0,
    fps: int = 30,
    zoom_direction: str = "in",
    target_res: tuple = (720, 1280)
) -> ImageClip:
    """
    Creates a Ken Burns effect (slow zoom) on an image.
    Returns a MoviePy VideoClip (via ImageClip with transformation).
    """
    try:
        # 1. Load Image
        clip = ImageClip(image_path, duration=duration)
        
        # 2. Define Scale Function
        # We start at 1.0 and end at 1.2 (20% zoom)
        start_scale = 1.0 if zoom_direction == "in" else 1.2
        end_scale = 1.2 if zoom_direction == "in" else 1.0
        
        def zoom_filter(get_frame, t):
            # Calculate current scale based on time
            progress = t / duration
            current_scale = start_scale + (end_scale - start_scale) * progress
            
            # Get the original frame
            frame = get_frame(t)
            h, w, _ = frame.shape
            
            # We use moviepy's internal resizing logic or just return the frame 
            # and let moviepy handle the transform if possible.
            # Actually, doing it frame-by-frame in a filter is cleaner for subtle zoom.
            return frame

        # MoviePy 2.x note: using .resized and .with_position is better than complex filters
        # But for Ken Burns, a smooth scaling effect is best done via a transform:
        
        initial_scale = 1.0 if zoom_direction == "in" else 1.3
        final_scale = 1.3 if zoom_direction == "in" else 1.0
        
        # Apply the scaling effect
        # We use the 'resized' with a lambda for dynamic scaling if supported, 
        # otherwise we use an effect.
        
        def scaling_logic(t):
            return initial_scale + (final_scale - initial_scale) * (t / duration)

        # Create the moving clip
        kb_clip = (clip
                   .resized(scaling_logic)
                   .with_position("center")
                   .resized(target_res) # Ensure final fit
                  )
        
        return kb_clip

    except Exception as e:
        logger.error(f"Failed to create Ken Burns clip: {e}")
        # Return static clip as fallback
        return ImageClip(image_path, duration=duration).resized(target_res)
