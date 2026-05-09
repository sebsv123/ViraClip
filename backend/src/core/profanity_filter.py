"""
Profanity filter for caption text.
Synchronous, no I/O after initialization.
"""
import os
import re
from typing import NamedTuple


class FilterResult(NamedTuple):
    text: str
    was_filtered: bool
    matches: list[str]


_DEFAULT_WORDS: list[str] = []


def _load_wordlist() -> list[str]:
    words = [w.strip().lower() for w in os.getenv("PROFANITY_WORDS", "").split(",") if w.strip()]
    wordlist_path = os.getenv("PROFANITY_WORDLIST_PATH", "")
    if wordlist_path:
        try:
            with open(wordlist_path) as f:
                words += [l.strip().lower() for l in f if l.strip()]
        except Exception:
            pass
    return words or _DEFAULT_WORDS


_WORDLIST: list[str] = _load_wordlist()


def _censor_word(word: str) -> str:
    if len(word) <= 2:
        return word[0] + "*"
    return word[0] + "*" * (len(word) - 2) + word[-1]


def filter_caption_text(text: str, mode: str = "censor") -> FilterResult:
    """
    Filter sensitive words in caption text.
    mode: 'censor' | 'warn' | 'off'
    """
    if mode == "off" or not _WORDLIST:
        return FilterResult(text, False, [])

    matches: list[str] = []
    result = text

    for word in _WORDLIST:
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        if pattern.search(result):
            matches.append(word)
            if mode == "censor":
                def replacer(m):
                    return _censor_word(m.group(0))
                result = pattern.sub(replacer, result)

    return FilterResult(result, bool(matches), matches)
