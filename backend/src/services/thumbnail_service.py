import logging
from pathlib import Path
from typing import Optional
from moviepy import VideoFileClip, TextClip, CompositeVideoClip, ColorClip
import os

logger = logging.getLogger(__name__)

def generate_viral_thumbnail(
    video_path: str,
    output_path: str,
    text: str = "WATCH THIS",
    font_path: Optional[str] = None,
    font_size: int = 120,
    font_color: str = "yellow",
    stroke_color: str = "black",
    stroke_width: int = 5
) -> bool:
    """
    Generate a high-contrast, viral-style thumbnail from a video clip.
    Takes a single frame (middle of the clip) and overlays bold text.
    """
    try:
        video_path_obj = Path(video_path)
        output_path_obj = Path(output_path)
        
        if not video_path_obj.exists():
            logger.error(f"Video file not found for thumbnail: {video_path}")
            return False

        with VideoFileClip(str(video_path_obj)) as clip:
            # Extract frame at 1/3 of duration (often where the hook payoff starts)
            frame_time = clip.duration / 3.0
            frame = clip.get_frame(frame_time)
            
            # Create a static image clip from the frame
            from moviepy import ImageClip
            img_clip = ImageClip(frame).with_duration(1)
            
            # Resize for vertical quality (1080x1920)
            img_clip = img_clip.resized(height=1920)
            if img_clip.w < 1080:
                img_clip = img_clip.resized(width=1080)
            img_clip = img_clip.cropped(
                x_center=img_clip.w/2, 
                y_center=img_clip.h/2, 
                width=1080, 
                height=1920
            )

            # Overlay high-impact text
            # We use a simple bold font if the provided one isn't found
            try:
                txt_clip = TextClip(
                    text=text.upper(),
                    font_size=font_size,
                    color=font_color,
                    stroke_color=stroke_color,
                    stroke_width=stroke_width,
                    font="THEBOLDFONT" if not font_path else font_path,
                    method="caption",
                    size=(900, None)
                ).with_duration(1).with_position(("center", 400))
                
                # Add a subtle background glow behind text for legibility
                bg_glow = ColorClip(
                    size=(txt_clip.w + 40, txt_clip.h + 20),
                    color=(0, 0, 0)
                ).with_opacity(0.6).with_duration(1).with_position(("center", 400))
                
                final_thumb = CompositeVideoClip([img_clip, bg_glow, txt_clip])
            except Exception as e:
                logger.warning(f"TextClip failed for thumbnail, using raw frame: {e}")
                final_thumb = img_clip

            # Save as PNG
            final_thumb.save_frame(str(output_path_obj))
            logger.info(f"✅ Viral Thumbnail Generated: {output_path_obj.name}")
            return True

    except Exception as e:
        logger.error(f"Failed to generate thumbnail for {video_path}: {e}")
        return False
