"""
Trending Audio Service — match clips to trending sounds.

Sources (in priority order):
1. TikTok Creative Center trending sounds (public endpoint, no auth required)
2. Spotify Charts API (weekly top-50 per territory)
3. Local curated cache fallback (always available)

Returns a ranked list of TrendingSound objects with metadata for the
variant_generator to select BGM that maximises algorithmic reach.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
TIKTOK_CC_BASE = "https://ads.tiktok.com/creative_radar_api/v1/popular_trend/list"
CACHE_DIR = Path(os.getenv("AUDIO_CACHE_DIR", "/app/datasets/trending_audio"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_SECONDS = 3600 * 6   # refresh every 6 hours


@dataclass
class TrendingSound:
    title: str
    artist: str
    platform: str                         # tiktok | spotify | local
    genre: str = "pop"
    territory: str = "global"
    rank: int = 0
    bpm: float = 0.0
    duration_seconds: float = 30.0
    preview_url: str = ""
    local_path: str = ""                  # if cached locally
    tags: list[str] = field(default_factory=list)

    def matches_genre(self, genre: str) -> bool:
        if genre == "auto":
            return True
        return self.genre.lower() == genre.lower() or genre.lower() in self.tags

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "artist": self.artist,
            "platform": self.platform,
            "genre": self.genre,
            "territory": self.territory,
            "rank": self.rank,
            "bpm": self.bpm,
            "duration_seconds": self.duration_seconds,
            "preview_url": self.preview_url,
            "local_path": self.local_path,
            "tags": self.tags,
        }


# ── Local curated fallback ─────────────────────────────────────────────────────

_LOCAL_SOUNDS: list[TrendingSound] = [
    TrendingSound("Aesthetic", "Xilo", "local", genre="chill", bpm=72,
                  tags=["chill", "lofi", "lifestyle"]),
    TrendingSound("Phonk Drive", "Ghostemane", "local", genre="hype", bpm=140,
                  tags=["hype", "fitness", "gaming"]),
    TrendingSound("Lofi Study", "ChillHop", "local", genre="lofi", bpm=85,
                  tags=["lofi", "education", "finance"]),
    TrendingSound("Upbeat Pop", "ViraClip Stock", "local", genre="pop", bpm=120,
                  tags=["pop", "comedy", "beauty"]),
    TrendingSound("Epic Cinematic", "ViraClip Stock", "local", genre="cinematic", bpm=90,
                  tags=["cinematic", "travel", "motivation"]),
    TrendingSound("Hip Hop Beat", "ViraClip Stock", "local", genre="hip_hop", bpm=95,
                  tags=["hip_hop", "gaming", "tech"]),
]


def _cache_file(name: str) -> Path:
    return CACHE_DIR / f"{name}.json"


def _load_cache(name: str) -> Optional[list[dict]]:
    p = _cache_file(name)
    if p.exists():
        try:
            data = json.loads(p.read_text())
            if time.time() - data.get("ts", 0) < CACHE_TTL_SECONDS:
                return data.get("sounds", [])
        except Exception:
            pass
    return None


def _save_cache(name: str, sounds: list[dict]) -> None:
    try:
        _cache_file(name).write_text(
            json.dumps({"ts": time.time(), "sounds": sounds}, indent=2)
        )
    except Exception as e:
        logger.debug("Cache write failed: %s", e)


# ── Spotify ────────────────────────────────────────────────────────────────────

async def _spotify_token() -> Optional[str]:
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return None
    try:
        import base64
        creds = base64.b64encode(
            f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()
        ).decode()
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://accounts.spotify.com/api/token",
                headers={"Authorization": f"Basic {creds}"},
                data={"grant_type": "client_credentials"},
            )
            r.raise_for_status()
            return r.json().get("access_token")
    except Exception as e:
        logger.debug("Spotify token error: %s", e)
        return None


async def fetch_spotify_trending(territory: str = "US") -> list[TrendingSound]:
    cached = _load_cache(f"spotify_{territory}")
    if cached is not None:
        return [TrendingSound(**s) for s in cached]

    token = await _spotify_token()
    if not token:
        return []

    # Spotify Charts playlist for territory (viral-50 is public)
    playlist_id = "37i9dQZEVXbLiRSasKsNU9"  # Global Viral 50
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={"limit": 20, "fields": "items(track(name,artists,duration_ms,preview_url))"},
            )
            r.raise_for_status()
            items = r.json().get("items", [])
            sounds = []
            for i, item in enumerate(items):
                t = item.get("track") or {}
                artist = (t.get("artists") or [{}])[0].get("name", "Unknown")
                sounds.append(TrendingSound(
                    title=t.get("name", "Unknown"),
                    artist=artist,
                    platform="spotify",
                    territory=territory,
                    rank=i + 1,
                    duration_seconds=t.get("duration_ms", 30000) / 1000,
                    preview_url=t.get("preview_url") or "",
                ))
            _save_cache(f"spotify_{territory}", [s.to_dict() for s in sounds])
            return sounds
    except Exception as e:
        logger.warning("Spotify charts fetch failed: %s", e)
        return []


# ── TikTok Creative Center ─────────────────────────────────────────────────────

async def fetch_tiktok_trending(territory: str = "US") -> list[TrendingSound]:
    cached = _load_cache(f"tiktok_{territory}")
    if cached is not None:
        return [TrendingSound(**s) for s in cached]
    try:
        params = {"period": 7, "page": 1, "limit": 20, "region_code": territory}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(TIKTOK_CC_BASE, params=params,
                                 headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            data = r.json().get("data", {}).get("list", [])
            sounds = []
            for i, item in enumerate(data):
                sounds.append(TrendingSound(
                    title=item.get("music_info", {}).get("title", "Unknown"),
                    artist=item.get("music_info", {}).get("author", "Unknown"),
                    platform="tiktok",
                    territory=territory,
                    rank=i + 1,
                    bpm=float(item.get("music_info", {}).get("bpm", 0)),
                    duration_seconds=float(item.get("music_info", {}).get("duration", 30)),
                    preview_url=item.get("music_info", {}).get("play_url", ""),
                ))
            _save_cache(f"tiktok_{territory}", [s.to_dict() for s in sounds])
            return sounds
    except Exception as e:
        logger.debug("TikTok CC fetch failed (non-critical): %s", e)
        return []


# ── Main entry ─────────────────────────────────────────────────────────────────

async def get_trending_sounds(
    genre: str = "auto",
    territory: str = "global",
    limit: int = 10,
) -> list[TrendingSound]:
    """
    Return top trending sounds ranked by platform + genre match.
    Falls back gracefully to local curated list.
    """
    sounds: list[TrendingSound] = []

    tiktok_territory = territory.upper() if territory != "global" else "US"
    tiktok = await fetch_tiktok_trending(tiktok_territory)
    sounds.extend(tiktok)

    spotify = await fetch_spotify_trending(tiktok_territory)
    sounds.extend(spotify)

    if not sounds:
        sounds = list(_LOCAL_SOUNDS)

    # Filter by genre if not auto
    if genre != "auto":
        genre_match = [s for s in sounds if s.matches_genre(genre)]
        sounds = genre_match if genre_match else sounds

    return sounds[:limit]


def recommend_sound_for_clip(
    clip_features: dict,
    trending: list[TrendingSound],
) -> Optional[TrendingSound]:
    """
    Pick the best trending sound for a clip given its features.

    clip_features: {niche, tone, bpm_hint, duration}
    """
    if not trending:
        return None

    niche = clip_features.get("niche", "lifestyle")
    bpm_hint = float(clip_features.get("bpm_hint", 0))

    scored: list[tuple[float, TrendingSound]] = []
    for s in trending:
        score = 0.0
        if s.matches_genre(niche):
            score += 2.0
        if bpm_hint and s.bpm:
            bpm_diff = abs(s.bpm - bpm_hint)
            score += max(0, 1.0 - bpm_diff / 60)
        score += max(0, 1.0 - s.rank / 20)
        scored.append((score, s))

    scored.sort(key=lambda x: -x[0])
    return scored[0][1] if scored else trending[0]
