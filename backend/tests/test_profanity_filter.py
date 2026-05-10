"""Tests for profanity filter."""
from src.core.profanity_filter import filter_caption_text, _censor_word


def test_clean_text_unchanged():
    """Clean text → unchanged."""
    result = filter_caption_text("Hola mundo", mode="censor")
    assert result.text == "Hola mundo"
    assert result.was_filtered is False


def test_censor_mode_replaces_word():
    """Censor mode replaces badword."""
    from src.core.profanity_filter import _WORDLIST
    _WORDLIST.append("badword")
    try:
        result = filter_caption_text("This is badword here", mode="censor")
        assert "badword" not in result.text
        assert result.was_filtered is True
    finally:
        _WORDLIST.remove("badword")


def test_warn_mode_keeps_original():
    """Warn mode keeps original text."""
    from src.core.profanity_filter import _WORDLIST
    _WORDLIST.append("badword")
    try:
        result = filter_caption_text("This is badword", mode="warn")
        assert "badword" in result.text
        assert result.was_filtered is True
        assert "badword" in result.matches
    finally:
        _WORDLIST.remove("badword")


def test_off_mode_returns_unchanged():
    """Off mode returns unchanged."""
    result = filter_caption_text("badword content", mode="off")
    assert result.text == "badword content"
    assert result.was_filtered is False


def test_censor_preserves_first_last_letter():
    """Censor preserves first and last letter."""
    result = _censor_word("hello")
    assert result.startswith("h")
    assert result.endswith("o")
    assert len(result) == 5


def test_case_insensitive_match():
    """Case insensitive matching."""
    from src.core.profanity_filter import _WORDLIST
    _WORDLIST.append("badword")
    try:
        result = filter_caption_text("BADWORD en texto", mode="censor")
        assert result.was_filtered is True
    finally:
        _WORDLIST.remove("badword")
