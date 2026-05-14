"""
ClipSuggestionStatus — shared enum for clip suggestion status values.

All code that reads or writes clip_suggestions.status should use this enum
instead of hardcoded string literals. This prevents typos and makes it easy
to add/rename statuses in one place.

Usage:
    from .clip_suggestion_status import ClipSuggestionStatus

    # Compare
    if s["status"] == ClipSuggestionStatus.PENDING.value:
        ...

    # Assign
    await repo.update_status(db, s["id"], ClipSuggestionStatus.APPLIED.value)
"""

from enum import Enum


class ClipSuggestionStatus(str, Enum):
    """Valid statuses for a clip suggestion row."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    READY_FOR_REVIEW = "ready_for_review"
    APPLIED = "applied"

    @classmethod
    def valid_statuses(cls) -> set[str]:
        """Return the set of all valid status string values."""
        return {m.value for m in cls}

    @classmethod
    def validate(cls, status: str) -> str:
        """Validate a status string, raising ValueError if invalid."""
        if status not in cls.valid_statuses():
            raise ValueError(
                f"Invalid status '{status}'. "
                f"Allowed: {sorted(cls.valid_statuses())}"
            )
        return status
