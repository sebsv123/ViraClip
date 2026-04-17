"""
Thumbnail Text Service — hook-text overlays on clip thumbnails.

Adds the "face reaction + bold callout text + arrow" format that drives
click-through rates on YouTube Shorts, Reels, and TikTok cover frames.

Dependencies: Pillow (already in requirements via ai_thumbnail_service)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_FONT_PATH = os.getenv("THUMBNAIL_FONT_PATH", "/app/fonts/TikTokSans-Regular.ttf")
_FALLBACK_FONT_SIZE = 64
_OUTPUT_DIR = Path(os.getenv("THUMBNAIL_TEXT_DIR", "/app/clips"))


@dataclass
class ThumbnailTextConfig:
    hook_text: str                         # Main bold callout line
    sub_text: str = ""                     # Optional smaller sub-line
    arrow_enabled: bool = True             # Draw a pointing arrow toward subject
    arrow_direction: str = "right"         # left | right | up | down
    text_position: str = "top"            # top | bottom | center
    font_size: int = _FALLBACK_FONT_SIZE
    text_color: str = "#FFFFFF"
    stroke_color: str = "#000000"
    stroke_width: int = 4
    background_opacity: float = 0.45      # semi-transparent text bg bar
    emoji_prefix: str = ""                # e.g. "🔥" prepended to hook_text


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))  # type: ignore


def _load_font(size: int):
    """Load TikTokSans font; fall back to default PIL font."""
    try:
        from PIL import ImageFont
        if os.path.exists(_FONT_PATH):
            return ImageFont.truetype(_FONT_PATH, size)
        # Try system fonts
        for candidate in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                          "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]:
            if os.path.exists(candidate):
                return ImageFont.truetype(candidate, size)
        return ImageFont.load_default()
    except Exception:
        try:
            from PIL import ImageFont
            return ImageFont.load_default()
        except Exception:
            return None


def add_hook_text(
    image_path: str,
    config: ThumbnailTextConfig,
    output_path: Optional[str] = None,
) -> str:
    """
    Overlay hook text (and optional arrow) on thumbnail image.
    Returns path to the new file (overwrites if output_path is None).
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.warning("Pillow not available — skipping thumbnail text overlay")
        return image_path

    if not os.path.exists(image_path):
        logger.warning("Thumbnail not found: %s", image_path)
        return image_path

    output = output_path or image_path
    try:
        img = Image.open(image_path).convert("RGBA")
        W, H = img.size

        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Determine text block position
        font_main = _load_font(config.font_size)
        font_sub = _load_font(max(28, config.font_size // 2))

        full_text = (config.emoji_prefix + " " + config.hook_text).strip()

        # Measure text
        try:
            bbox = draw.textbbox((0, 0), full_text, font=font_main)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
        except AttributeError:
            tw, th = draw.textsize(full_text, font=font_main)  # type: ignore

        pad = 20
        bar_h = th + pad * 2 + (40 if config.sub_text else 0)

        if config.text_position == "top":
            bar_y = 0
            text_y = pad
        elif config.text_position == "center":
            bar_y = (H - bar_h) // 2
            text_y = bar_y + pad
        else:  # bottom
            bar_y = H - bar_h
            text_y = bar_y + pad

        # Semi-transparent background bar
        alpha = int(config.background_opacity * 255)
        draw.rectangle([(0, bar_y), (W, bar_y + bar_h)], fill=(0, 0, 0, alpha))

        # Main hook text (centered)
        text_x = (W - tw) // 2
        txt_rgb = _hex_to_rgb(config.text_color)
        str_rgb = _hex_to_rgb(config.stroke_color)

        # Draw stroke by offsetting
        sw = config.stroke_width
        for dx in range(-sw, sw + 1):
            for dy in range(-sw, sw + 1):
                if dx != 0 or dy != 0:
                    draw.text(
                        (text_x + dx, text_y + dy),
                        full_text, font=font_main,
                        fill=(*str_rgb, 255),
                    )
        draw.text((text_x, text_y), full_text, font=font_main,
                  fill=(*txt_rgb, 255))

        # Sub-text
        if config.sub_text and font_sub:
            try:
                sbbox = draw.textbbox((0, 0), config.sub_text, font=font_sub)
                stw = sbbox[2] - sbbox[0]
                sth = sbbox[3] - sbbox[1]
            except AttributeError:
                stw, sth = draw.textsize(config.sub_text, font=font_sub)  # type: ignore
            sx = (W - stw) // 2
            sy = text_y + th + 8
            draw.text((sx, sy), config.sub_text, font=font_sub,
                      fill=(*txt_rgb, 200))

        # Arrow
        if config.arrow_enabled:
            _draw_arrow(draw, W, H, config.arrow_direction, bar_y, bar_h, txt_rgb)

        # Composite and save
        composite = Image.alpha_composite(img, overlay).convert("RGB")
        composite.save(output, quality=92)
        logger.debug("Thumbnail text overlay saved to %s", output)
        return output

    except Exception as e:
        logger.warning("Thumbnail text overlay failed: %s", e)
        return image_path


def _draw_arrow(
    draw,
    W: int, H: int,
    direction: str,
    bar_y: int, bar_h: int,
    color: tuple,
) -> None:
    """Draw a simple filled triangle arrow pointing away from the text bar."""
    try:
        aw = 60
        ah = 50
        cx = W // 2
        if direction == "right":
            # Arrow pointing right, centered vertically in remaining space
            mid_y = (H + bar_y + bar_h) // 2 if bar_y == 0 else bar_y // 2
            pts = [(cx + 20, mid_y - aw // 2),
                   (cx + 20 + ah, mid_y),
                   (cx + 20, mid_y + aw // 2)]
        elif direction == "left":
            mid_y = (H + bar_y + bar_h) // 2 if bar_y == 0 else bar_y // 2
            pts = [(cx - 20, mid_y - aw // 2),
                   (cx - 20 - ah, mid_y),
                   (cx - 20, mid_y + aw // 2)]
        elif direction == "down":
            pts = [(cx - aw // 2, bar_y + bar_h + 10),
                   (cx, bar_y + bar_h + 10 + ah),
                   (cx + aw // 2, bar_y + bar_h + 10)]
        else:  # up
            pts = [(cx - aw // 2, bar_y - 10),
                   (cx, bar_y - 10 - ah),
                   (cx + aw // 2, bar_y - 10)]
        draw.polygon(pts, fill=(*color, 220))
    except Exception:
        pass


async def generate_hook_thumbnail(
    source_thumbnail: str,
    hook_text: str,
    sub_text: str = "",
    platform: str = "tiktok",
    emoji: str = "",
    position: str = "top",
) -> str:
    """
    Convenience async wrapper.
    Generates hook-text overlay and returns the new file path.
    """
    stem = Path(source_thumbnail).stem
    suffix = Path(source_thumbnail).suffix
    output_dir = Path(source_thumbnail).parent
    output = str(output_dir / f"{stem}_hook{suffix}")

    font_sizes = {"tiktok": 68, "reels": 64, "shorts": 72, "default": 64}
    fs = font_sizes.get(platform, 64)

    cfg = ThumbnailTextConfig(
        hook_text=hook_text,
        sub_text=sub_text,
        text_position=position,
        font_size=fs,
        emoji_prefix=emoji,
        arrow_enabled=True,
        arrow_direction="right" if position == "top" else "down",
    )
    return add_hook_text(source_thumbnail, cfg, output)
