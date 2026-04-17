"""
Contextual B-Roll — Phase 9 Creative Engine

Unified B-roll lookup: local asset bank → multi-source (Pexels + Pixabay + Coverr) → T2V (Replicate).
Triggered by keyword events from the multimodal timeline.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_ASSET_EXTS = (".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".webp")
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# Maps keyword fragments to seed-bank category subdirectory names.
# Longest-match wins — checked in insertion order (most-specific first).
_CATEGORY_MAP: "list[tuple[str, str]]" = [
    # tech / business
    ("phone",       "tech"),       ("laptop",    "tech"),
    ("computer",    "tech"),       ("code",      "tech"),
    ("software",    "tech"),       ("data",      "tech"),
    ("crypto",      "finance"),    ("bitcoin",   "finance"),
    ("money",       "finance"),    ("stock",     "finance"),
    ("invest",      "finance"),    ("bank",      "finance"),
    ("office",      "business"),   ("meeting",   "business"),
    ("startup",     "business"),   ("entrepreneur", "business"),
    # people / lifestyle
    ("person",      "people"),     ("people",    "people"),
    ("woman",       "people"),     ("man",       "people"),
    ("crowd",       "people"),     ("audience",  "people"),
    ("health",      "health"),     ("fitness",   "health"),
    ("workout",     "sport"),      ("gym",       "sport"),
    ("sport",       "sport"),      ("athlete",   "sport"),
    # nature / travel
    ("nature",      "nature"),     ("forest",    "nature"),
    ("ocean",       "nature"),     ("mountain",  "nature"),
    ("sky",         "nature"),     ("sunset",    "nature"),
    ("city",        "city"),       ("urban",     "city"),
    ("street",      "city"),       ("building",  "city"),
    ("travel",      "travel"),     ("flight",    "travel"),
    ("airport",     "travel"),     ("hotel",     "travel"),
    # food / abstract
    ("food",        "food"),       ("cook",      "food"),
    ("restaurant",  "food"),       ("coffee",    "food"),
    ("abstract",    "abstract"),   ("motivat",   "motivation"),
    ("success",     "motivation"), ("inspire",   "motivation"),
]


def _keyword_to_category(keyword: str) -> "str | None":
    """Map a keyword to the closest seed-bank category, or None."""
    kw = keyword.lower()
    for fragment, category in _CATEGORY_MAP:
        if fragment in kw:
            return category
    return None


@dataclass
class BrollAsset:
    path: str
    source: str    # "local" | "multi" | "t2v"
    keyword: str
    duration: float


class ContextualBroll:
    """
    Finds or generates a B-roll clip for a given keyword.

    Lookup order (each step only runs if the previous fails):
      1. Local asset bank directory (instant, offline, category-aware)
      2. Multi-source: Pexels + Pixabay + Coverr in parallel
      3. Replicate T2V          (requires T2V_ENABLED=true + REPLICATE_API_TOKEN)
    """

    def __init__(self) -> None:
        self._bank = Path(os.environ.get("BROLL_ASSET_BANK", "/app/assets/broll"))
        self._pexels_key = os.environ.get("PEXELS_API_KEY", "")
        self._pixabay_key = os.environ.get("PIXABAY_API_KEY", "")
        self._coverr_key = os.environ.get("COVERR_API_KEY", "")
        self._t2v_enabled = os.environ.get("T2V_ENABLED", "false").lower() == "true"
        self._replicate_token = os.environ.get("REPLICATE_API_TOKEN", "")

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_for_keyword(
        self,
        keyword: str,
        duration: float = 3.0,
        mood: str = "",
    ) -> "BrollAsset | None":
        """Return a B-roll asset for keyword, or None if nothing found.

        Lookup order:
          1. Local asset bank (instant, offline, category-aware)
          2. Multi-source: Pexels + Pixabay + Coverr in parallel
          3. Replicate T2V (only when T2V_ENABLED=true)
        """
        local = self._find_local(keyword)
        if local:
            return BrollAsset(str(local), "local", keyword, duration)

        if self._pexels_key or self._pixabay_key or self._coverr_key:
            path = await self._fetch_multi_source(keyword, duration)
            if path:
                return BrollAsset(path, "multi", keyword, duration)

        if self._t2v_enabled and self._replicate_token:
            path = await self._generate_t2v(keyword, duration, mood=mood)
            if path:
                return BrollAsset(path, "t2v", keyword, duration)

        return None

    async def get_for_timeline(
        self,
        timeline_events: list,
        max_assets: int = 3,
    ) -> "list[tuple]":
        """
        Fetch B-roll for up to max_assets hook/impact keyword events.

        Returns [(event, BrollAsset), ...] for events where an asset was found.
        """
        candidates = [
            e for e in timeline_events
            if e.type == "keyword"
            and e.payload.get("category") in ("hook", "impact")
        ][:max_assets]

        results = await asyncio.gather(
            *[self.get_for_keyword(
                e.payload.get("word", ""),
                duration=e.duration + 1.0,
                mood=e.payload.get("mood", ""),
              )
              for e in candidates],
            return_exceptions=True,
        )

        return [
            (ev, res)
            for ev, res in zip(candidates, results)
            if isinstance(res, BrollAsset)
        ]

    # ── Lookup strategies ─────────────────────────────────────────────────────

    def _find_local(self, keyword: str) -> "Path | None":
        """Search asset bank by keyword. Category-mapped lookup first, then filename glob."""
        if not self._bank.exists():
            return None
        kw = keyword.lower()

        # 1. Category-based lookup: map keyword → category subdir
        category = _keyword_to_category(kw)
        if category:
            cat_dir = self._bank / category
            if cat_dir.is_dir():
                for ext in _ASSET_EXTS:
                    candidates = list(cat_dir.glob(f"*{ext}"))
                    if candidates:
                        import random
                        return random.choice(candidates)

        # 2. Exact keyword subdir match
        for subdir in (self._bank / kw, self._bank / kw[:4]):
            if subdir.is_dir():
                for ext in _ASSET_EXTS:
                    candidates = list(subdir.glob(f"*{ext}"))
                    if candidates:
                        return candidates[0]

        # 3. Filename contains keyword (flat bank or uncategorized)
        for ext in _ASSET_EXTS:
            for p in self._bank.rglob(f"*{kw}*{ext}"):
                if p.is_file():
                    return p

        return None

    @staticmethod
    def _is_image(path: str) -> bool:
        return Path(path).suffix.lower() in _IMAGE_EXTS

    async def _fetch_multi_source(self, keyword: str, duration: float) -> "str | None":
        """Delegate to BrollService — queries Pexels + Pixabay + Coverr in parallel."""
        try:
            from .broll_service import BrollService
            result = await BrollService().fetch_broll_asset(keyword)
            return str(result) if result else None
        except Exception as exc:
            logger.debug("Multi-source B-roll failed for '%s': %s", keyword, exc)
            return None

    async def _generate_t2v(
        self, keyword: str, duration: float, mood: str = ""
    ) -> "str | None":
        """Delegate to T2V service — Replicate API (CogVideoX / Wan2.1)."""
        try:
            from .t2v_broll_service import T2VBrollService
            mood_tag = f", {mood}" if mood else ", cinematic"
            prompt = (
                f"Cinematic 4K vertical footage of {keyword}, "
                f"smooth camera motion{mood_tag}, no text, no watermark"
            )
            return await T2VBrollService().generate(prompt=prompt, duration=duration)
        except Exception as exc:
            logger.debug("T2V B-roll failed for '%s': %s", keyword, exc)
            return None


# ── Singleton ─────────────────────────────────────────────────────────────────

_contextual_broll: "ContextualBroll | None" = None


def get_contextual_broll() -> ContextualBroll:
    global _contextual_broll
    if _contextual_broll is None:
        _contextual_broll = ContextualBroll()
    return _contextual_broll
