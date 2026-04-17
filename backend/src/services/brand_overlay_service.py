"""
Brand / Watermark Overlay Service.

Composites a semi-transparent text watermark or PNG logo onto video clips
using FFmpeg drawtext / overlay filter (CPU-only, no GPU required).

Positions: bottom_right | bottom_left | top_right | top_left | center
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
FFMPEG = os.getenv("FFMPEG_PATH", "ffmpeg")

FONT_PATH = os.getenv("BRAND_FONT_PATH", "/app/fonts/TikTokSans-Regular.ttf")


@dataclass
class BrandConfig:
    # Text watermark (mutually exclusive with image_path)
    text: str = ""                      # e.g. "@myhandle" or "MyBrand"
    text_color: str = "white"
    font_size: int = 28
    font_alpha: float = 0.75            # 0-1 opacity

    # Image watermark (PNG with alpha channel recommended)
    image_path: str = ""
    image_width: int = 120              # px, preserves aspect ratio
    image_alpha: float = 0.70

    # Position
    position: str = "bottom_right"     # bottom_right | bottom_left | top_right | top_left | center
    margin_x: int = 20                 # pixels from edge
    margin_y: int = 20

    # Apply to both clip and thumbnail
    apply_to_thumbnail: bool = True


_POSITION_EXPR: dict[str, tuple[str, str]] = {
    "bottom_right": ("W-w-{mx}", "H-h-{my}"),
    "bottom_left":  ("{mx}", "H-h-{my}"),
    "top_right":    ("W-w-{mx}", "{my}"),
    "top_left":     ("{mx}", "{my}"),
    "center":       ("(W-w)/2", "(H-h)/2"),
}


def _position_xy(position: str, margin_x: int, margin_y: int) -> tuple[str, str]:
    tpl = _POSITION_EXPR.get(position, _POSITION_EXPR["bottom_right"])
    return (
        tpl[0].replace("{mx}", str(margin_x)),
        tpl[1].replace("{my}", str(margin_y)),
    )


def _text_drawtext_filter(cfg: BrandConfig) -> str:
    """Build FFmpeg drawtext filter for text watermark."""
    x, y = _position_xy(cfg.position, cfg.margin_x, cfg.margin_y)

    alpha_hex = hex(int(cfg.font_alpha * 255))[2:].zfill(2).upper()
    # FFmpeg drawtext color with alpha: colorname@alpha or #RRGGBBAA
    font_color_alpha = f"{cfg.text_color}@{cfg.font_alpha:.2f}"

    font_param = ""
    if os.path.exists(FONT_PATH):
        font_param = f":fontfile='{FONT_PATH}'"

    return (
        f"drawtext=text='{cfg.text}'"
        f":fontsize={cfg.font_size}"
        f":fontcolor={font_color_alpha}"
        f"{font_param}"
        f":x={x}:y={y}"
        f":shadowcolor=black@0.5:shadowx=1:shadowy=1"
    )


async def apply_text_watermark(
    video_path: str,
    output_path: str,
    cfg: BrandConfig,
) -> bool:
    """Apply text watermark using FFmpeg drawtext filter."""
    vf = _text_drawtext_filter(cfg)
    cmd = [
        FFMPEG, "-y", "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "copy",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("Text watermark failed: %s", stderr.decode()[-500:])
        return False
    return True


async def apply_image_watermark(
    video_path: str,
    output_path: str,
    cfg: BrandConfig,
) -> bool:
    """Overlay a PNG logo using FFmpeg overlay filter."""
    if not os.path.exists(cfg.image_path):
        logger.warning("Watermark image not found: %s", cfg.image_path)
        return False

    x, y = _position_xy(cfg.position, cfg.margin_x, cfg.margin_y)
    alpha = cfg.font_alpha   # reuse same field

    # Scale logo to desired width, apply alpha
    logo_filter = (
        f"[1:v]scale={cfg.image_width}:-1,"
        f"format=rgba,colorchannelmixer=aa={alpha:.2f}[logo];"
        f"[0:v][logo]overlay={x}:{y}"
    )
    cmd = [
        FFMPEG, "-y",
        "-i", video_path,
        "-i", cfg.image_path,
        "-filter_complex", logo_filter,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "copy",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("Image watermark failed: %s", stderr.decode()[-500:])
        return False
    return True


async def apply_brand_overlay(
    video_path: str,
    output_path: str,
    cfg: BrandConfig,
) -> str:
    """
    Apply brand overlay (text or image) and return the output path.
    Falls back to original path if overlay fails.
    """
    if cfg.image_path and os.path.exists(cfg.image_path):
        success = await apply_image_watermark(video_path, output_path, cfg)
    elif cfg.text:
        success = await apply_text_watermark(video_path, output_path, cfg)
    else:
        logger.warning("BrandConfig has neither text nor valid image_path")
        return video_path

    if success and os.path.exists(output_path):
        logger.debug("Brand overlay applied → %s", output_path)
        return output_path
    return video_path


def apply_brand_to_thumbnail(
    image_path: str,
    cfg: BrandConfig,
    output_path: Optional[str] = None,
) -> str:
    """Apply text watermark to a thumbnail image using Pillow."""
    if not cfg.text or not cfg.apply_to_thumbnail:
        return image_path
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.open(image_path).convert("RGBA")
        W, H = img.size
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        font = None
        if os.path.exists(FONT_PATH):
            try:
                font = ImageFont.truetype(FONT_PATH, cfg.font_size)
            except Exception:
                pass
        if font is None:
            font = ImageFont.load_default()

        try:
            bbox = draw.textbbox((0, 0), cfg.text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except AttributeError:
            tw, th = draw.textsize(cfg.text, font=font)  # type: ignore

        mx, my = cfg.margin_x, cfg.margin_y
        positions = {
            "bottom_right": (W - tw - mx, H - th - my),
            "bottom_left":  (mx, H - th - my),
            "top_right":    (W - tw - mx, my),
            "top_left":     (mx, my),
            "center":       ((W - tw) // 2, (H - th) // 2),
        }
        px, py = positions.get(cfg.position, (W - tw - mx, H - th - my))

        alpha = int(cfg.font_alpha * 255)
        draw.text((px + 1, py + 1), cfg.text, font=font, fill=(0, 0, 0, int(alpha * 0.6)))
        draw.text((px, py), cfg.text, font=font, fill=(255, 255, 255, alpha))

        result = Image.alpha_composite(img, overlay).convert("RGB")
        out = output_path or image_path
        result.save(out, quality=92)
        return out
    except Exception as e:
        logger.warning("Thumbnail brand overlay failed: %s", e)
        return image_path
