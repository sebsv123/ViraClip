"""
Contextual B-Roll — Phase 9 Creative Engine

Unified B-roll lookup: local asset bank → Pexels API → T2V generation.
Triggered by keyword events from the multimodal timeline.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class BrollAsset:
    path: str
    source: str    # "local" | "pexels" | "t2v"
    keyword: str
    duration: float


class ContextualBroll:
    """
    Finds or generates a B-roll clip for a given keyword.

    Lookup order (each step only runs if the previous fails):
      1. Local asset bank directory (instant, offline)
      2. Pexels API            (requires PEXELS_API_KEY)
      3. T2V generation        (requires T2V_ENABLED=true + GPU)
    """

    def __init__(self) -> None:
        self._bank = Path(os.environ.get("BROLL_ASSET_BANK", "/app/assets/broll"))
        self._pexels_key = os.environ.get("PEXELS_API_KEY", "")
        self._t2v_enabled = os.environ.get("T2V_ENABLED", "false").lower() == "true"

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_for_keyword(
        self,
        keyword: str,
        duration: float = 3.0,
    ) -> "BrollAsset | None":
        """Return a B-roll asset for keyword, or None if nothing found."""
        local = self._find_local(keyword)
        if local:
            return BrollAsset(str(local), "local", keyword, duration)

        if self._pexels_key:
            path = await self._fetch_pexels(keyword, duration)
            if path:
                return BrollAsset(path, "pexels", keyword, duration)

        if self._t2v_enabled:
            path = await self._generate_t2v(keyword, duration)
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
            *[self.get_for_keyword(e.payload.get("word", ""), duration=e.duration + 1.0)
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
        """Search asset bank by keyword in filename or sub-folder name."""
        if not self._bank.exists():
            return None
        kw = keyword.lower()
        for ext in (".mp4", ".mov", ".webm"):
            for p in self._bank.glob(f"*{kw}*{ext}"):
                if p.is_file():
                    return p
        for subdir in (self._bank / kw, self._bank / kw[:4]):
            if subdir.is_dir():
                for ext in (".mp4", ".mov", ".webm"):
                    candidates = list(subdir.glob(f"*{ext}"))
                    if candidates:
                        return candidates[0]
        return None

    async def _fetch_pexels(self, keyword: str, duration: float) -> "str | None":
        """Delegate to existing broll_service which owns Pexels integration."""
        try:
            from .broll_service import BrollService
            result = await BrollService().get_broll_clip(keyword, duration=duration)
            return result if isinstance(result, str) else None
        except Exception as exc:
            logger.debug("Pexels B-roll failed for '%s': %s", keyword, exc)
            return None

    async def _generate_t2v(self, keyword: str, duration: float) -> "str | None":
        """Delegate to T2V service for GPU-backed clip generation."""
        try:
            from .t2v_broll_service import T2VBrollService
            prompt = f"4K cinematic footage of {keyword}, smooth motion, professional"
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
