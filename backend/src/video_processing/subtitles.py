"""
Subtitle creation and rendering utilities.
Handles all caption styles: static, karaoke, pop, bounce, fade.
"""

from pathlib import Path
from typing import List, Dict, Any, Tuple
import logging

from moviepy import TextClip, ColorClip, VideoFileClip

logger = logging.getLogger(__name__)

# Importaciones que se harán desde video_utils o se recrearán aquí
# Para evitar imports circulares, algunas funciones se duplicarán o se importarán lazy


def get_scaled_font_size(base_size: int, video_width: int) -> int:
    """Scale font size based on video resolution for consistent readability."""
    reference_width = 1080
    scale_factor = video_width / reference_width
    scaled_size = int(base_size * scale_factor)
    return max(28, min(88, scaled_size))


def get_subtitle_max_width(video_width: int) -> int:
    """Return max subtitle text width with horizontal safe margins."""
    horizontal_padding = max(40, int(video_width * 0.06))
    return max(200, video_width - (horizontal_padding * 2))


def get_safe_vertical_position(
    video_height: int, text_height: int, position_y: float
) -> int:
    """Calculate safe vertical position keeping text within video bounds."""
    min_margin = int(video_height * 0.05)
    max_bottom = video_height - min_margin - text_height
    default_y = int(video_height * position_y)
    return max(min_margin, min(default_y, max_bottom))


def inject_emoji(text: str) -> str:
    """Add emoji emphasis to high-impact words."""
    EMOJI_MAP = {
        "WOW": "WOW ✨",
        "AMAZING": "AMAZING 🔥",
        "INCREIBLE": "INCREÍBLE 🤯",
        "DINERO": "DINERO 💰",
        "GUERRA": "GUERRA ⚔️",
        "EXITO": "ÉXITO 🚀",
        "LOCO": "LOCO 🤪",
        "CRAZY": "CRAZY 🤪",
        "BRUTAL": "BRUTAL 💪",
        "GENIAL": "GENIAL 👌",
        "BESTIAL": "BESTIAL 🐺",
    }
    return EMOJI_MAP.get(text.upper(), text)


# ─────────────────────────────────────────────────────────────────────────────
# Subtitle Style Functions
# ─────────────────────────────────────────────────────────────────────────────


def create_static_subtitles(
    relevant_words: List[Dict],
    video_width: int,
    video_height: int,
    template: Dict,
    font_path: str,
) -> List[Any]:
    """Create standard static subtitles (original behavior)."""
    from .utils import adaptive_word_groups

    subtitle_clips = []
    calculated_font_size = get_scaled_font_size(template["font_size"], video_width)
    position_y = template.get("position_y", 0.75)
    max_text_width = get_subtitle_max_width(video_width)

    # Adaptive grouping: respects frame width and speech timing
    word_groups = adaptive_word_groups(
        relevant_words, video_width, calculated_font_size
    )

    for word_group in word_groups:
        if not word_group:
            continue

        segment_start = word_group[0]["start"]
        segment_end = word_group[-1]["end"]
        segment_duration = segment_end - segment_start

        if segment_duration < 0.1:
            continue

        text = " ".join(word["text"] for word in word_group)

        try:
            stroke_color = template.get("stroke_color", "black")
            stroke_width = template.get("stroke_width", 1)

            text_clip = (
                TextClip(
                    text=text,
                    font=font_path,
                    font_size=calculated_font_size,
                    color=template["font_color"],
                    stroke_color=stroke_color if stroke_color else None,
                    stroke_width=stroke_width if stroke_color else 0,
                    method="caption",
                    size=(max_text_width, None),
                    text_align="center",
                    interline=6,
                )
                .with_duration(segment_duration)
                .with_start(segment_start)
            )

            text_height = text_clip.size[1] if text_clip.size else 40
            vertical_position = get_safe_vertical_position(
                video_height, text_height, position_y
            )
            text_clip = text_clip.with_position(("center", vertical_position))

            subtitle_clips.append(text_clip)

        except Exception as e:
            logger.warning(f"Failed to create subtitle for '{text}': {e}")
            continue

    logger.info(f"Created {len(subtitle_clips)} static subtitle elements")
    return subtitle_clips


def create_bounce_subtitles(
    relevant_words: List[Dict],
    video_width: int,
    video_height: int,
    template: Dict,
    font_path: str,
) -> List[Any]:
    """
    Create bounce-style subtitles: each word springs in with a quick
    scale-up animation (pop → overshoot → settle) for maximum visual impact.
    Uses a critically-damped spring model.
    """
    import math

    subtitle_clips = []

    calculated_font_size = get_scaled_font_size(template["font_size"], video_width)
    position_y = template.get("position_y", 0.75)

    def spring_scale(t: float) -> float:
        """Critically-damped spring: fast pop-up with slight overshoot that settles."""
        attack = 0.07
        settle = 0.17
        peak = 1.25
        if t <= 0:
            return 0.0
        if t < attack:
            return (t / attack) * peak
        if t < settle:
            progress = (t - attack) / (settle - attack)
            return peak - (peak - 1.0) * progress
        return 1.0

    # Elite V3 Upgrade: Sentiment-based coloring
    INTENSE_WORDS = {"DINERO", "CASH", "GUERRA", "MUERTE", "PELIGRO", "ERROR", "FALTA", "DANGER", "STOP"}
    EXCITED_WORDS = {"INCREÍBLE", "WOW", "LOCO", "AMAZING", "CRAZY", "BRUTAL", "GENIAL", "BESTIAL"}
    ACTION_WORDS = {"AHORA", "YA", "MIRA", "ESCUCHA", "STOP", "GO", "LISTEN", "WATCH"}

    for word in relevant_words:
        word_start = word["start"]
        word_end = word["end"]
        duration = word_end - word_start

        if duration < 0.05:
            continue

        text = word["text"].upper().strip(".,!?;:")
        display_text = inject_emoji(word["text"].upper())

        # Elite Sentiment Coloring
        word_color = template["font_color"]
        if text in INTENSE_WORDS:
            word_color = "#FF3131"  # Neon Red
        elif text in EXCITED_WORDS:
            word_color = "#39FF14"  # Neon Green
        elif text in ACTION_WORDS:
            word_color = "#00F0FF"  # Neon Cyan
        elif len(text) > 8:
            word_color = template.get("highlight_color", "#FFFF00")  # Important long words

        try:
            base_clip = TextClip(
                text=display_text,
                font=font_path,
                font_size=int(calculated_font_size * 1.15),
                color=word_color,
                stroke_color=template.get("stroke_color", "black"),
                stroke_width=template.get("stroke_width", 4),
                method="label",
            )

            bounced = base_clip.resized(lambda t: max(0.05, spring_scale(t)))

            text_height = base_clip.size[1] if base_clip.size else 40
            vertical_position = get_safe_vertical_position(
                video_height, text_height, position_y
            )

            final_clip = (
                bounced
                .with_duration(duration)
                .with_start(word_start)
                .with_position(("center", vertical_position))
            )
            subtitle_clips.append(final_clip)

        except Exception as e:
            logger.warning(f"Failed to create bounce word '{text}': {e}")
            continue

    logger.info(f"Created {len(subtitle_clips)} bounce subtitle elements")
    return subtitle_clips


def create_karaoke_subtitles(
    relevant_words: List[Dict],
    video_width: int,
    video_height: int,
    template: Dict,
    font_path: str,
) -> List[Any]:
    """Create karaoke-style subtitles with word-by-word highlighting."""
    from .utils import adaptive_word_groups

    subtitle_clips = []
    calculated_font_size = get_scaled_font_size(template["font_size"], video_width)
    position_y = template.get("position_y", 0.75)
    highlight_color = template.get("highlight_color", "#FFD700")
    normal_color = template["font_color"]
    max_text_width = get_subtitle_max_width(video_width)
    horizontal_padding = max(40, int(video_width * 0.06))

    adaptive_groups = adaptive_word_groups(relevant_words, video_width, calculated_font_size)

    def measure_word_group_width(word_group: List[Dict], font_size: int) -> List[int]:
        widths: List[int] = []
        for word in word_group:
            temp_clip = TextClip(
                text=word["text"],
                font=font_path,
                font_size=font_size,
                color=normal_color,
                stroke_color=template.get("stroke_color", "black"),
                stroke_width=template.get("stroke_width", 1),
                method="label",
            )
            widths.append(temp_clip.size[0] if temp_clip.size else 50)
            temp_clip.close()
        return widths

    for word_group in adaptive_groups:
        if not word_group:
            continue

        group_start = word_group[0]["start"]
        group_end = word_group[-1]["end"]

        font_size_for_group = calculated_font_size
        word_widths = measure_word_group_width(word_group, font_size_for_group)
        space_width = font_size_for_group * 0.28
        total_width = sum(word_widths) + space_width * (len(word_group) - 1)
        if total_width > max_text_width and total_width > 0:
            shrink_ratio = max_text_width / total_width
            font_size_for_group = max(20, int(font_size_for_group * shrink_ratio))
            word_widths = measure_word_group_width(word_group, font_size_for_group)
            space_width = font_size_for_group * 0.28
            total_width = sum(word_widths) + space_width * (len(word_group) - 1)

        for word_idx, current_word in enumerate(word_group):
            word_start = current_word["start"]
            if word_idx < len(word_group) - 1:
                word_end = word_group[word_idx + 1]["start"]
            else:
                word_end = group_end
            word_duration = word_end - word_start

            if word_duration < 0.05:
                continue

            try:
                word_clips_for_composite = []
                current_x = max(horizontal_padding, (video_width - total_width) / 2)
                text_height = 40

                for w_idx, word in enumerate(word_group):
                    is_current = w_idx == word_idx
                    color = highlight_color if is_current else normal_color
                    size_multiplier = 1.1 if is_current else 1.0

                    word_clip = (
                        TextClip(
                            text=word["text"],
                            font=font_path,
                            font_size=int(font_size_for_group * size_multiplier),
                            color=color,
                            stroke_color=template.get("stroke_color", "black"),
                            stroke_width=template.get("stroke_width", 1),
                            method="label",
                        )
                        .with_duration(word_duration)
                        .with_start(word_start)
                    )

                    text_height = max(
                        text_height, word_clip.size[1] if word_clip.size else 40
                    )
                    vertical_position = get_safe_vertical_position(
                        video_height, text_height, position_y
                    )

                    word_clip = word_clip.with_position(
                        (int(current_x), vertical_position)
                    )
                    word_clips_for_composite.append(word_clip)

                    current_x += word_widths[w_idx] + space_width

                subtitle_clips.extend(word_clips_for_composite)

            except Exception as e:
                logger.warning(
                    f"Failed to create karaoke subtitle for word '{current_word['text']}': {e}"
                )
                continue

    logger.info(f"Created {len(subtitle_clips)} karaoke subtitle elements")
    return subtitle_clips


def create_pop_subtitles(
    relevant_words: List[Dict],
    video_width: int,
    video_height: int,
    template: Dict,
    font_path: str,
) -> List[Any]:
    """Create pop-style subtitles where each word appears individually and quickly."""
    subtitle_clips = []
    calculated_font_size = get_scaled_font_size(template["font_size"], video_width)
    position_y = template.get("position_y", 0.75)

    for word_idx, word in enumerate(relevant_words):
        word_start = word["start"]
        word_end = word["end"]
        if word_idx < len(relevant_words) - 1:
            word_end = relevant_words[word_idx + 1]["start"]
        word_duration = word_end - word_start
        text = word["text"].upper()
        display_text = inject_emoji(text)

        if word_duration < 0.05:
            continue

        try:
            text_clip = (
                TextClip(
                    text=display_text,
                    font=font_path,
                    font_size=int(calculated_font_size * 1.1),
                    color=template.get("highlight_color", "#FFFF00"),
                    stroke_color=template.get("stroke_color", "black"),
                    stroke_width=template.get("stroke_width", 3),
                    method="label",
                )
                .with_duration(word_duration)
                .with_start(word_start)
            )

            text_height = text_clip.size[1] if text_clip.size else 40
            vertical_position = get_safe_vertical_position(
                video_height, text_height, position_y
            )
            text_clip = text_clip.with_position(("center", vertical_position))

            subtitle_clips.append(text_clip)

        except Exception as e:
            logger.warning(f"Failed to create pop word '{text}': {e}")
            continue

    logger.info(f"Created {len(subtitle_clips)} fast-pop subtitle elements")
    return subtitle_clips


def create_fade_subtitles(
    relevant_words: List[Dict],
    video_width: int,
    video_height: int,
    template: Dict,
    font_path: str,
) -> List[Any]:
    """Create fade-style subtitles with smooth transitions."""
    subtitle_clips = []
    calculated_font_size = get_scaled_font_size(template["font_size"], video_width)
    position_y = template.get("position_y", 0.75)
    has_background = template.get("background", False)
    background_color = template.get("background_color", "#00000080")
    max_text_width = get_subtitle_max_width(video_width)

    words_per_group = 4

    for group_idx in range(0, len(relevant_words), words_per_group):
        word_group = relevant_words[group_idx : group_idx + words_per_group]
        if not word_group:
            continue

        group_text = " ".join(w["text"] for w in word_group)
        if template.get("uppercase", False):
            group_text = group_text.upper()
        group_start = word_group[0]["start"]
        group_end = word_group[-1]["end"]
        group_duration = group_end - group_start

        if group_duration < 0.1:
            continue

        try:
            text_clip = TextClip(
                text=group_text,
                font=font_path,
                font_size=calculated_font_size,
                color=template["font_color"],
                stroke_color=template.get("stroke_color")
                if template.get("stroke_color")
                else None,
                stroke_width=template.get("stroke_width", 0),
                method="caption",
                size=(max_text_width, None),
                text_align="center",
                interline=6,
            )

            text_height = text_clip.size[1] if text_clip.size else 40
            text_width = text_clip.size[0] if text_clip.size else 200
            vertical_position = get_safe_vertical_position(
                video_height, text_height, position_y
            )

            if has_background and background_color:
                padding = 10
                bg_color_hex = (
                    background_color[:7]
                    if len(background_color) > 7
                    else background_color
                )

                bg_clip = (
                    ColorClip(
                        size=(text_width + padding * 2, text_height + padding),
                        color=tuple(
                            int(bg_color_hex[i : i + 2], 16) for i in (1, 3, 5)
                        ),
                    )
                    .with_duration(group_duration)
                    .with_start(group_start)
                )

                bg_clip = bg_clip.with_position(
                    ("center", vertical_position - padding // 2)
                )

                fade_duration = min(0.2, group_duration / 4)
                bg_clip = (
                    bg_clip.with_effects(
                        [CrossFadeIn(fade_duration), CrossFadeOut(fade_duration)]
                    )
                    if group_duration > 0.5
                    else bg_clip
                )

                subtitle_clips.append(bg_clip)

            text_clip = text_clip.with_duration(group_duration).with_start(group_start)
            text_clip = text_clip.with_position(("center", vertical_position))

            subtitle_clips.append(text_clip)

        except Exception as e:
            logger.warning(f"Failed to create fade subtitle: {e}")
            continue

    logger.info(f"Created {len(subtitle_clips)} fade subtitle elements")
    return subtitle_clips


def get_words_in_range(words: List[Dict], start_time: float, end_time: float) -> List[Dict]:
    """Get words within a specific time range."""
    return [
        word for word in words
        if word.get("start", 0) >= start_time and word.get("end", 0) <= end_time
    ]


def get_words_in_range(words: List[Dict], start_time: float, end_time: float) -> List[Dict]:
    """Get words within a specific time range."""
    return [
        word for word in words
        if word.get("start", 0) >= start_time and word.get("end", 0) <= end_time
    ]


def create_assemblyai_subtitles(
    relevant_words: List[Dict],
    video_width: int,
    video_height: int,
    template: Dict,
    font_path: str,
) -> List[Any]:
    """Create subtitles dispatching to the right animation based on template."""
    animation = template.get("animation", "none")
    if animation == "karaoke":
        return create_karaoke_subtitles(relevant_words, video_width, video_height, template, font_path)
    elif animation == "bounce":
        return create_bounce_subtitles(relevant_words, video_width, video_height, template, font_path)
    elif animation == "pop":
        return create_pop_subtitles(relevant_words, video_width, video_height, template, font_path)
    elif animation == "fade":
        return create_fade_subtitles(relevant_words, video_width, video_height, template, font_path)
    else:
        return create_static_subtitles(relevant_words, video_width, video_height, template, font_path)
