"""
Contextual B-Roll — Phase 9 Creative Engine

Unified B-roll lookup that delegates provider priority to broll_provider_strategy.
Local asset bank is checked first (instant/offline), then BrollService.fetch_broll_asset()
handles the full provider cascade according to BROLL_PROVIDER_PRIORITY.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Import unified provider strategy (single source of truth)
from .broll_provider_strategy import (
    BROLL_PROVIDER_PRIORITY,
    get_provider_order,
    passes_quality_gate,
)

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
    source: str    # "local" | "multi" | "image" | "ltxv" | "t2v"
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
        self._ltxv_enabled = os.environ.get("LTXV_ENABLED", "false").lower() == "true"

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_for_keyword(
        self,
        keyword: str,
        duration: float = 3.0,
        mood: str = "",
        priority: str = "NORMAL",  # HIGH, MED, NORMAL (priority affects provider order via strategy)
    ) -> "BrollAsset | None":
        """Return a B-roll asset for keyword, or None if nothing found.

        Single-source-of-truth lookup:
          1. Local asset bank (instant, offline, category-aware) — handled here
          2. Everything else delegated to BrollService.fetch_broll_asset()
             which uses broll_provider_strategy.get_provider_order() for ordering

        The priority parameter is passed to the strategy module; no manual branching here.
        """
        _timeout = float(os.environ.get("BROLL_SLOT_TIMEOUT_SEC", "30"))
        _prio = priority.upper()

        try:
            # ── 1. Local asset bank (always first — instant, offline) ────────
            local = self._find_local(keyword)
            if local:
                logger.info("[BRoll] %s slot '%s' → local", _prio, keyword)
                return BrollAsset(str(local), "local", keyword, duration)

            # ── 2. Delegate to unified BrollService (strategy-driven) ─────────
            # This handles LTXV → T2V → Stock → Image according to BROLL_PROVIDER_PRIORITY
            from .broll_service import BrollService

            result = await asyncio.wait_for(
                BrollService().fetch_broll_asset(keyword),
                timeout=_timeout,
            )
            if result:
                # Determine source type from the result path/name for logging
                source_type = self._infer_source_type(result)
                logger.info("[BRoll] %s slot '%s' → %s (via strategy)", _prio, keyword, source_type)
                return BrollAsset(str(result), source_type, keyword, duration)

            logger.warning("[BRoll] %s slot '%s' → no asset found (priority=%s)",
                          _prio, keyword, BROLL_PROVIDER_PRIORITY)
            return None

        except asyncio.TimeoutError:
            logger.warning("B-roll lookup timed out (%.0fs) for '%s'", _timeout, keyword)
            return None

    @staticmethod
    def _infer_source_type(path: Path) -> str:
        """Infer source type from path name for logging purposes."""
        name = path.name.lower()
        if name.startswith("gen_"):
            return "ltxv"
        if name.startswith("t2v_"):
            return "t2v"
        if name.startswith("pexels_") or name.startswith("pixabay_") or name.startswith("coverr_"):
            return "multi"
        if path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            return "image"
        return "multi"

    # ── Internal helpers ─────────────────────────────────────────────────────
    # Note: _cascade_lookup removed — all cascade logic now in broll_provider_strategy
    # ContextualBroll only handles: 1) local asset bank, 2) delegation to BrollService

    async def get_for_timeline(
        self,
        timeline_events: list,
        max_assets: int = 3,
    ) -> "list[tuple]":
        """
        Fetch B-roll for up to max_assets hook/impact keyword events.

        Returns [(event, BrollAsset), ...] for events where an asset was found.
        """
        # Include hook, impact, energy keywords AND silence gaps ≥2s for B-roll
        candidates = [
            e for e in timeline_events
            if (e.type == "keyword"
                and e.payload.get("category") in ("hook", "impact", "energy", "broll_llm"))
            or (e.type == "silence" and e.duration >= 2.0)
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

    # ── Singleton ─────────────────────────────────────────────────────────────────

_contextual_broll: "ContextualBroll | None" = None


def get_contextual_broll() -> ContextualBroll:
    global _contextual_broll
    if _contextual_broll is None:
        _contextual_broll = ContextualBroll()
    return _contextual_broll
