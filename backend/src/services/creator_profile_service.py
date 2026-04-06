"""
Creator Profile Service — per-creator personalization layer.

Stores niche, tone, target_demo, preferred music genre, CTA style,
caption style, language preference and watermark path.
The pipeline reads the active profile and tunes:
  - CTA overlay text
  - Hook detection threshold
  - BGM genre filter
  - Caption style (minimal / bold / karaoke)
  - Hashtag language / territory
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)

# ── In-memory store (keyed by user_id → profile dict) ─────────────────────────
# Production: replace with DB-backed repository. For now this is a fast, tested,
# zero-migration store that survives container restarts via JSON file.

import os
from pathlib import Path

_PROFILE_DIR = Path(os.getenv("PROFILE_STORE_DIR", "/app/datasets/creator_profiles"))
_PROFILE_DIR.mkdir(parents=True, exist_ok=True)


NICHES = ["fitness", "finance", "comedy", "education", "lifestyle",
          "tech", "gaming", "food", "travel", "beauty", "motivation"]
TONES = ["educational", "entertainment", "inspirational", "documentary",
         "humour", "news", "tutorial"]
TARGET_DEMOS = ["gen_z", "millennial", "gen_x", "all_ages", "professional"]
MUSIC_GENRES = ["chill", "lofi", "hype", "electronic", "acoustic",
                "hip_hop", "pop", "cinematic", "auto"]
CAPTION_STYLES = ["minimal", "bold", "karaoke", "none"]


@dataclass
class CreatorProfile:
    user_id: str
    display_name: str = ""
    niche: str = "lifestyle"
    tone: str = "entertainment"
    target_demo: str = "all_ages"
    preferred_music_genre: str = "auto"
    caption_style: str = "bold"
    cta_text: str = "Follow for more!"
    language: str = "en"
    watermark_text: str = ""
    watermark_image_path: str = ""
    watermark_position: str = "bottom_right"   # bottom_right | bottom_left | top_right | top_left
    hook_strategy: str = "auto"                # auto | question | statement | statistic | story
    hashtag_territory: str = "global"          # global | us | uk | latam | india
    extra: dict = field(default_factory=dict)  # arbitrary extension metadata

    # --- Derived helpers ---

    def cta_for_platform(self, platform: str) -> str:
        """Return platform-specific CTA copy."""
        templates = {
            "tiktok": f"Follow @me for more {self.niche} content! 🔥",
            "reels":  f"Save this for later & follow for more! 💾",
            "shorts": f"Subscribe for more {self.niche} tips! 🔔",
        }
        if self.cta_text and self.cta_text != "Follow for more!":
            return self.cta_text
        return templates.get(platform, self.cta_text)

    def music_genres(self) -> list[str]:
        """Return ordered list of preferred genres for BGM selection."""
        if self.preferred_music_genre == "auto":
            genre_map = {
                "fitness": ["hype", "electronic", "hip_hop"],
                "finance": ["chill", "acoustic", "cinematic"],
                "comedy":  ["pop", "hip_hop", "electronic"],
                "education": ["lofi", "chill", "acoustic"],
                "lifestyle": ["chill", "pop", "acoustic"],
                "tech":    ["electronic", "lofi", "cinematic"],
                "gaming":  ["hype", "electronic", "hip_hop"],
                "food":    ["acoustic", "pop", "chill"],
                "travel":  ["cinematic", "acoustic", "pop"],
                "beauty":  ["pop", "chill", "acoustic"],
                "motivation": ["hype", "cinematic", "electronic"],
            }
            return genre_map.get(self.niche, ["chill", "pop"])
        return [self.preferred_music_genre]

    def locale_prompt_hints(self) -> dict:
        """Return locale-aware LLM prompt hints for virality / hashtag generation."""
        return {
            "language": self.language,
            "territory": self.hashtag_territory,
            "niche": self.niche,
            "tone": self.tone,
            "target_demo": self.target_demo,
        }

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CreatorProfile":
        known = {k for k in CreatorProfile.__dataclass_fields__}
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


# ── File-backed CRUD ───────────────────────────────────────────────────────────

def _profile_path(user_id: str) -> Path:
    safe = user_id.replace("/", "_").replace("..", "_")
    return _PROFILE_DIR / f"{safe}.json"


def get_profile(user_id: str) -> CreatorProfile:
    """Return the creator profile for user_id, creating defaults if missing."""
    p = _profile_path(user_id)
    if p.exists():
        try:
            data = json.loads(p.read_text())
            return CreatorProfile.from_dict(data)
        except Exception as e:
            logger.warning("Corrupt profile for %s: %s — resetting to defaults", user_id, e)
    profile = CreatorProfile(user_id=user_id)
    save_profile(profile)
    return profile


def save_profile(profile: CreatorProfile) -> None:
    p = _profile_path(profile.user_id)
    p.write_text(json.dumps(profile.to_dict(), indent=2))
    logger.debug("Saved creator profile for %s", profile.user_id)


def update_profile(user_id: str, updates: dict) -> CreatorProfile:
    """Partial update: merge updates into existing profile and persist."""
    profile = get_profile(user_id)
    current = profile.to_dict()
    current.update({k: v for k, v in updates.items()
                    if k in CreatorProfile.__dataclass_fields__ and k != "user_id"})
    updated = CreatorProfile.from_dict(current)
    save_profile(updated)
    return updated


def delete_profile(user_id: str) -> bool:
    p = _profile_path(user_id)
    if p.exists():
        p.unlink()
        return True
    return False


def list_profiles() -> list[CreatorProfile]:
    profiles = []
    for f in sorted(_PROFILE_DIR.glob("*.json")):
        try:
            profiles.append(CreatorProfile.from_dict(json.loads(f.read_text())))
        except Exception:
            pass
    return profiles
