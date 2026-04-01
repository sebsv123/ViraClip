"""
Shared utility functions for video processing.

Contains common helpers used across multiple modules.
"""

from typing import Dict, List


# Sentiment emoji mappings
SENTIMENT_EMOJIS = {
    "WOW": "😮", "OMG": "😱", "YES": "🙌", "NO": "🚫", "STOP": "✋",
    "FIRE": "🔥", "LOVE": "❤️", "HAPPY": "😊", "SAD": "😢", "ANGRY": "😠",
    "THINK": "🤔", "WIN": "🏆", "GOAL": "⚽", "TIME": "⏰", "MONEY": "💸", "SECRET": "🤫"
}


def inject_emoji(text: str) -> str:
    """Inject a relevant emoji if the uppercase word matches a sentiment key."""
    clean_text = text.upper().strip(".,!?;:")
    emoji = SENTIMENT_EMOJIS.get(clean_text)
    return f"{text} {emoji}" if emoji else text


def format_ms_to_timestamp(ms: int) -> str:
    """Format milliseconds to MM:SS format."""
    seconds = ms // 1000
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


def round_to_even(value: int) -> int:
    """Round integer to nearest even number for H.264 compatibility."""
    return value - (value % 2)


def get_scaled_font_size(base_font_size: int, video_width: int) -> int:
    """
    Scale caption font size by output width with sensible bounds.
    Optimized for mobile vertical video (9:16) visibility.
    
    - 1080p vertical (1080w): ~72px
    - 720p vertical (720w): ~48px
    - Minimum 28px, maximum 88px
    """
    scaled_size = int(base_font_size * (video_width / 1080))
    return max(28, min(88, scaled_size))


def get_subtitle_max_width(video_width: int) -> int:
    """Get maximum subtitle width in pixels."""
    return int(video_width * 0.9)


def get_safe_vertical_position(video_height: int, position: str = "bottom") -> int:
    """Get safe vertical position for subtitles avoiding edges."""
    if position == "bottom":
        return int(video_height * 0.85)
    elif position == "top":
        return int(video_height * 0.15)
    return int(video_height * 0.5)


def parse_timestamp_to_seconds(timestamp: str) -> float:
    """Parse MM:SS or HH:MM:SS timestamp to seconds."""
    parts = timestamp.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return 0.0


def adaptive_word_groups(words: List[Dict], max_group_size: int = 3, max_gap: float = 0.5) -> List[List[Dict]]:
    """
    Group words adaptively for subtitle display.
    
    Args:
        words: List of word dicts with 'start', 'end', 'text'
        max_group_size: Maximum words per group
        max_gap: Maximum time gap between words in a group
    
    Returns:
        List of word groups
    """
    if not words:
        return []
    
    groups = []
    current_group = [words[0]]
    
    for i in range(1, len(words)):
        word = words[i]
        last_word = current_group[-1]
        
        gap = word.get("start", 0) - last_word.get("end", 0)
        
        if gap > max_gap or len(current_group) >= max_group_size:
            groups.append(current_group)
            current_group = [word]
        else:
            current_group.append(word)
    
    if current_group:
        groups.append(current_group)
    
    return groups


def get_subtitle_max_width(video_width: int) -> int:
    """Return max subtitle text width with horizontal safe margins."""
    horizontal_padding = max(40, int(video_width * 0.06))
    return max(200, video_width - (horizontal_padding * 2))


def get_safe_vertical_position(
    video_height: int, text_height: int, position_y: float
) -> int:
    """
    Return a safe Y coordinate for subtitle positioning.
    Ensures text stays within video bounds with padding.
    """
    min_top_padding = 40
    max_bottom_padding = 60
    desired_y = int(position_y * video_height)
    max_y = video_height - text_height - max_bottom_padding
    return max(min_top_padding, min(desired_y, max_y))


def parse_timestamp_to_seconds(timestamp_str: str) -> float:
    """Parse timestamp string to seconds.
    
    Supports formats:
    - MM:SS
    - HH:MM:SS
    - SS (plain seconds)
    """
    try:
        timestamp_str = timestamp_str.strip()
        parts = timestamp_str.split(":")
        
        if len(parts) == 1:
            # Plain seconds
            return float(parts[0])
        elif len(parts) == 2:
            # MM:SS
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
        elif len(parts) == 3:
            # HH:MM:SS
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        else:
            return 0.0
    except (ValueError, IndexError):
        return 0.0
