"""
Classifies task errors as transient (retriable) or permanent (fatal).
Case-insensitive, never raises exceptions.
"""
import logging

logger = logging.getLogger(__name__)

TRANSIENT_ERROR_PATTERNS = [
    "503", "502", "504",
    "timeout", "timed out",
    "rate limit", "rate_limit",
    "too many requests",
    "connection refused",
    "temporary", "temporarily",
    "groq", "deepseek",
    "whisper", "transcription",
]

PERMANENT_ERROR_PATTERNS = [
    "private video", "video private",
    "not available", "unavailable",
    "not found", "404",
    "invalid url", "unsupported url",
    "age restricted",
    "copyright",
    "deleted",
    "domain not supported",
    "private/reserved ip",
]


def classify_error(error_msg: str) -> str:
    """
    Retorna 'transient' | 'permanent' | 'unknown'.
    unknown se trata como transient (1 reintento).
    """
    if not error_msg:
        return "unknown"
    msg_lower = error_msg.lower()
    for pattern in PERMANENT_ERROR_PATTERNS:
        if pattern in msg_lower:
            return "permanent"
    for pattern in TRANSIENT_ERROR_PATTERNS:
        if pattern in msg_lower:
            return "transient"
    return "unknown"
