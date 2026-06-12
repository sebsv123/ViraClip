"""
vpi_animated_asset_registry.py — Selection quality rules for VPI premium animated assets.

Loads the asset registry from assets/vpi_animated_asset_registry.json and provides
selection, fallback, brand-safety, and overuse-prevention logic.

Design
------
- AssetRegistryEntry: dataclass mirroring the JSON schema for one asset.
- load_asset_registry(): loads and validates the JSON file.
- select_asset_for_intent(): picks the best asset for a given editorial intent.
- resolve_fallback(): fallback hierarchy: exact match → same-family → symbolic → None.
- check_brand_safety(): validates asset against prohibited contexts and score thresholds.
- check_asset_overuse(): prevents using the same asset too often in a single clip.
- select_asset_for_segment(): end-to-end selection with all checks applied.

Fallback hierarchy
------------------
1. Exact asset match (asset_id matches and intent is in allowed_intents)
2. Same-family match (any asset in the same visual_family with compatible intent)
3. Symbolic fallback (fallback_asset_id chain, up to 2 hops)
4. No asset (return None)

Brand safety rules
------------------
- prohibited_contexts: if segment context matches any prohibited context, reject.
- brand_fit_score >= 0.7: minimum brand alignment.
- clarity_gain_score >= 0.5: minimum clarity contribution.

"One Strong Thing" enforcement
-------------------------------
- No more than one premium visual asset at a time per segment.
- select_asset_for_segment() returns at most one asset.
- Caller should enforce across segments via visual_priority_guard.

Asset overuse prevention
------------------------
- Tracks asset usage count per clip_id.
- max_uses_per_clip = 2 (configurable).
- If an asset has been used >= max_uses_per_clip, it is excluded from selection.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

DEFAULT_REGISTRY_PATH = Path("assets/vpi_animated_asset_registry.json")
DEFAULT_MAX_USES_PER_CLIP = 2
MIN_BRAND_FIT_SCORE = 0.7
MIN_CLARITY_GAIN_SCORE = 0.5


# ── Asset registry entry dataclass ─────────────────────────────────────────────


@dataclass
class AssetRegistryEntry:
    """A single asset entry from the VPI animated asset registry."""

    asset_id: str
    name: str
    visual_family: str
    category: str
    allowed_intents: List[str]
    allowed_visual_styles: List[str]
    avoid_intents: List[str]
    tone: str
    intensity: float
    brand_fit_score: float
    clarity_gain_score: float
    safe_area_preference: str
    max_duration_frames: int
    entry_motion: str
    exit_motion: str
    remotion_component: str
    lottie_future_path: str
    static_svg_path: str
    fallback_asset_id: Optional[str] = None
    usage_examples: List[str] = field(default_factory=list)
    prohibited_contexts: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AssetRegistryEntry:
        """Create an AssetRegistryEntry from a JSON dict."""
        return cls(
            asset_id=data["asset_id"],
            name=data["name"],
            visual_family=data["visual_family"],
            category=data.get("category", "icon"),
            allowed_intents=data.get("allowed_intents", []),
            allowed_visual_styles=data.get("allowed_visual_styles", []),
            avoid_intents=data.get("avoid_intents", []),
            tone=data.get("tone", "neutral"),
            intensity=data.get("intensity", 0.5),
            brand_fit_score=data.get("brand_fit_score", 0.0),
            clarity_gain_score=data.get("clarity_gain_score", 0.0),
            safe_area_preference=data.get("safe_area_preference", "center"),
            max_duration_frames=data.get("max_duration_frames", 60),
            entry_motion=data.get("entry_motion", "fade_in"),
            exit_motion=data.get("exit_motion", "fade_out"),
            remotion_component=data.get("remotion_component", ""),
            lottie_future_path=data.get("lottie_future_path", ""),
            static_svg_path=data.get("static_svg_path", ""),
            fallback_asset_id=data.get("fallback_asset_id"),
            usage_examples=data.get("usage_examples", []),
            prohibited_contexts=data.get("prohibited_contexts", []),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert back to a JSON-serialisable dict."""
        return {
            "asset_id": self.asset_id,
            "name": self.name,
            "visual_family": self.visual_family,
            "category": self.category,
            "allowed_intents": self.allowed_intents,
            "allowed_visual_styles": self.allowed_visual_styles,
            "avoid_intents": self.avoid_intents,
            "tone": self.tone,
            "intensity": self.intensity,
            "brand_fit_score": self.brand_fit_score,
            "clarity_gain_score": self.clarity_gain_score,
            "safe_area_preference": self.safe_area_preference,
            "max_duration_frames": self.max_duration_frames,
            "entry_motion": self.entry_motion,
            "exit_motion": self.exit_motion,
            "remotion_component": self.remotion_component,
            "lottie_future_path": self.lottie_future_path,
            "static_svg_path": self.static_svg_path,
            "fallback_asset_id": self.fallback_asset_id,
            "usage_examples": self.usage_examples,
            "prohibited_contexts": self.prohibited_contexts,
        }


# ── Registry loader ────────────────────────────────────────────────────────────


def load_asset_registry(
    path: Optional[Path] = None,
) -> Dict[str, AssetRegistryEntry]:
    """Load the asset registry from a JSON file.

    Args:
        path: Path to the registry JSON file. Defaults to
              DEFAULT_REGISTRY_PATH.

    Returns:
        A dict mapping asset_id → AssetRegistryEntry.

    Raises:
        FileNotFoundError: If the registry file does not exist.
        json.JSONDecodeError: If the registry file is not valid JSON.
        KeyError: If required fields are missing from an asset entry.
    """
    if path is None:
        path = DEFAULT_REGISTRY_PATH

    if not path.exists():
        raise FileNotFoundError(
            f"Asset registry not found at {path}. "
            f"Ensure assets/vpi_animated_asset_registry.json exists."
        )

    with open(path, "r") as f:
        data = json.load(f)

    assets: Dict[str, AssetRegistryEntry] = {}
    for asset_data in data.get("assets", []):
        entry = AssetRegistryEntry.from_dict(asset_data)
        assets[entry.asset_id] = entry

    logger.info(
        "[asset-registry] Loaded %d assets from %s (schema v%s)",
        len(assets),
        path,
        data.get("schema_version", "unknown"),
    )
    return assets


# ── Intent-based selection ─────────────────────────────────────────────────────


def select_asset_for_intent(
    intent: str,
    assets: Dict[str, AssetRegistryEntry],
    visual_style: Optional[str] = None,
    avoid_asset_ids: Optional[Set[str]] = None,
) -> Optional[AssetRegistryEntry]:
    """Select the best asset for a given editorial intent.

    Selection logic:
    1. Filter assets where intent is in allowed_intents.
    2. If visual_style is provided, filter to assets where visual_style
       is in allowed_visual_styles.
    3. Exclude assets in avoid_asset_ids (for overuse prevention).
    4. Score remaining assets by (brand_fit_score + clarity_gain_score) / 2.
    5. Return the highest-scoring asset, or None if no match.

    Args:
        intent: The editorial intent string (e.g. "protection", "warning").
        assets: The full asset registry dict.
        visual_style: Optional visual style to filter by.
        avoid_asset_ids: Set of asset_ids to exclude (e.g. already used).

    Returns:
        The best-matching AssetRegistryEntry, or None.
    """
    avoid = avoid_asset_ids or set()

    candidates: List[AssetRegistryEntry] = []
    for entry in assets.values():
        if entry.asset_id in avoid:
            continue
        if intent not in entry.allowed_intents:
            continue
        if visual_style and visual_style not in entry.allowed_visual_styles:
            continue
        candidates.append(entry)

    if not candidates:
        logger.info(
            "[asset-registry] No asset found for intent=%s style=%s",
            intent, visual_style,
        )
        return None

    # Score by average of brand_fit and clarity_gain
    def _score(e: AssetRegistryEntry) -> float:
        return (e.brand_fit_score + e.clarity_gain_score) / 2.0

    candidates.sort(key=_score, reverse=True)
    best = candidates[0]

    logger.info(
        "[asset-registry] Selected asset=%s for intent=%s style=%s "
        "(score=%.2f, brand=%.2f, clarity=%.2f)",
        best.asset_id, intent, visual_style,
        _score(best), best.brand_fit_score, best.clarity_gain_score,
    )
    return best


# ── Fallback resolution ────────────────────────────────────────────────────────


def resolve_fallback(
    asset_id: str,
    assets: Dict[str, AssetRegistryEntry],
    intent: Optional[str] = None,
    max_hops: int = 2,
) -> Optional[AssetRegistryEntry]:
    """Resolve a fallback chain for a given asset.

    Fallback hierarchy:
    1. The asset itself (if it exists and intent is compatible).
    2. Same-family asset with compatible intent.
    3. Symbolic fallback via fallback_asset_id chain (up to max_hops).
    4. None (no asset available).

    Args:
        asset_id: The starting asset_id.
        assets: The full asset registry dict.
        intent: Optional intent to check compatibility.
        max_hops: Maximum number of fallback hops (default 2).

    Returns:
        The resolved AssetRegistryEntry, or None.
    """
    # Step 1: Try the asset itself
    entry = assets.get(asset_id)
    if entry:
        if intent is None or intent in entry.allowed_intents:
            return entry
        # Intent not compatible — try same-family fallback
        logger.info(
            "[asset-registry] Asset %s exists but intent=%s not in allowed_intents; "
            "trying same-family fallback",
            asset_id, intent,
        )

    # Step 2: Same-family fallback
    if entry:
        family = entry.visual_family
        family_candidates = [
            e for e in assets.values()
            if e.visual_family == family
            and (intent is None or intent in e.allowed_intents)
        ]
        if family_candidates:
            # Prefer the one with highest combined score
            def _score(e: AssetRegistryEntry) -> float:
                return (e.brand_fit_score + e.clarity_gain_score) / 2.0
            family_candidates.sort(key=_score, reverse=True)
            logger.info(
                "[asset-registry] Same-family fallback: %s → %s (family=%s)",
                asset_id, family_candidates[0].asset_id, family,
            )
            return family_candidates[0]

    # Step 3: Symbolic fallback chain
    current_id = asset_id
    for hop in range(max_hops):
        current_entry = assets.get(current_id)
        if not current_entry:
            break
        fb_id = current_entry.fallback_asset_id
        if not fb_id:
            break
        fb_entry = assets.get(fb_id)
        if not fb_entry:
            break
        if intent is None or intent in fb_entry.allowed_intents:
            logger.info(
                "[asset-registry] Symbolic fallback (hop %d): %s → %s",
                hop + 1, current_id, fb_id,
            )
            return fb_entry
        current_id = fb_id

    logger.info(
        "[asset-registry] No fallback found for asset=%s intent=%s",
        asset_id, intent,
    )
    return None


# ── Brand safety check ─────────────────────────────────────────────────────────


def check_brand_safety(
    entry: AssetRegistryEntry,
    segment_context: Optional[str] = None,
    segment_intent: Optional[str] = None,
) -> Tuple[bool, List[str]]:
    """Check if an asset passes brand safety rules.

    Rules:
    1. prohibited_contexts: if segment_context matches any prohibited context, reject.
    2. brand_fit_score >= MIN_BRAND_FIT_SCORE (0.7).
    3. clarity_gain_score >= MIN_CLARITY_GAIN_SCORE (0.5).

    Args:
        entry: The asset to check.
        segment_context: Optional context string for the segment (e.g. "fraud", "joke").
        segment_intent: Optional intent string for additional checks.

    Returns:
        (is_safe, reasons) tuple. is_safe is True if all checks pass.
        reasons is a list of failure reasons (empty if safe).
    """
    reasons: List[str] = []

    # Rule 1: Prohibited contexts
    if segment_context and entry.prohibited_contexts:
        for prohibited in entry.prohibited_contexts:
            if prohibited.lower() in segment_context.lower():
                reasons.append(
                    f"Context '{segment_context}' matches prohibited context "
                    f"'{prohibited}' for asset '{entry.asset_id}'"
                )

    # Rule 2: Brand fit score
    if entry.brand_fit_score < MIN_BRAND_FIT_SCORE:
        reasons.append(
            f"brand_fit_score={entry.brand_fit_score} < {MIN_BRAND_FIT_SCORE} "
            f"for asset '{entry.asset_id}'"
        )

    # Rule 3: Clarity gain score
    if entry.clarity_gain_score < MIN_CLARITY_GAIN_SCORE:
        reasons.append(
            f"clarity_gain_score={entry.clarity_gain_score} < {MIN_CLARITY_GAIN_SCORE} "
            f"for asset '{entry.asset_id}'"
        )

    # Rule 4: Avoid intents (if segment_intent provided)
    if segment_intent and segment_intent in entry.avoid_intents:
        reasons.append(
            f"Intent '{segment_intent}' is in avoid_intents for asset '{entry.asset_id}'"
        )

    is_safe = len(reasons) == 0
    if not is_safe:
        logger.info(
            "[asset-registry] Brand safety FAIL for %s: %s",
            entry.asset_id, "; ".join(reasons),
        )
    return is_safe, reasons


# ── Asset overuse check ────────────────────────────────────────────────────────


class AssetUsageTracker:
    """Tracks asset usage per clip to prevent overuse.

    The "One Strong Thing" rule means at most one premium visual asset per
    segment. This tracker additionally prevents the same asset from being
    used too many times across segments in a single clip.
    """

    def __init__(self, max_uses_per_clip: int = DEFAULT_MAX_USES_PER_CLIP):
        self._usage: Dict[str, int] = {}
        self.max_uses_per_clip = max_uses_per_clip

    def record_use(self, asset_id: str) -> None:
        """Record that an asset was used."""
        self._usage[asset_id] = self._usage.get(asset_id, 0) + 1

    def can_use(self, asset_id: str) -> bool:
        """Check if an asset can be used (under the limit)."""
        return self._usage.get(asset_id, 0) < self.max_uses_per_clip

    def usage_count(self, asset_id: str) -> int:
        """Get the current usage count for an asset."""
        return self._usage.get(asset_id, 0)

    def reset(self) -> None:
        """Reset all usage tracking (e.g. for a new clip)."""
        self._usage.clear()

    def used_asset_ids(self) -> Set[str]:
        """Get the set of asset_ids that have been used."""
        return set(self._usage.keys())


def check_asset_overuse(
    asset_id: str,
    tracker: AssetUsageTracker,
) -> bool:
    """Check if an asset has been overused.

    Args:
        asset_id: The asset to check.
        tracker: The AssetUsageTracker for the current clip.

    Returns:
        True if the asset can be used (under the limit), False if overused.
    """
    return tracker.can_use(asset_id)


# ── End-to-end segment selection ───────────────────────────────────────────────


def select_asset_for_segment(
    intent: str,
    assets: Dict[str, AssetRegistryEntry],
    tracker: AssetUsageTracker,
    visual_style: Optional[str] = None,
    segment_context: Optional[str] = None,
    preferred_asset_id: Optional[str] = None,
) -> Optional[AssetRegistryEntry]:
    """End-to-end asset selection for a single segment.

    Applies all checks in order:
    1. If preferred_asset_id is given, try it first (with fallback).
    2. Otherwise, select by intent + visual_style.
    3. Resolve fallback if needed.
    4. Check brand safety.
    5. Check asset overuse.
    6. Record usage and return.

    This enforces the "One Strong Thing" rule by returning at most one asset.

    Args:
        intent: The editorial intent for this segment.
        assets: The full asset registry dict.
        tracker: AssetUsageTracker for the current clip.
        visual_style: Optional visual style filter.
        segment_context: Optional context string for brand safety.
        preferred_asset_id: Optional preferred asset to try first.

    Returns:
        An AssetRegistryEntry if a suitable asset is found, or None.
    """
    entry: Optional[AssetRegistryEntry] = None

    # Step 1: Try preferred asset
    if preferred_asset_id and preferred_asset_id in assets:
        entry = resolve_fallback(preferred_asset_id, assets, intent=intent)
        if entry:
            logger.info(
                "[asset-registry] Using preferred asset=%s (resolved from %s)",
                entry.asset_id, preferred_asset_id,
            )

    # Step 2: Select by intent
    if entry is None:
        avoid_ids = tracker.used_asset_ids()
        entry = select_asset_for_intent(
            intent=intent,
            assets=assets,
            visual_style=visual_style,
            avoid_asset_ids=avoid_ids,
        )

    # Step 3: Resolve fallback if needed
    if entry is None:
        # Try without avoid_ids for fallback
        entry = select_asset_for_intent(
            intent=intent,
            assets=assets,
            visual_style=visual_style,
        )
        if entry:
            # Resolve fallback chain
            entry = resolve_fallback(entry.asset_id, assets, intent=intent)

    if entry is None:
        logger.info(
            "[asset-registry] No asset selected for intent=%s style=%s context=%s",
            intent, visual_style, segment_context,
        )
        return None

    # Step 4: Brand safety
    is_safe, reasons = check_brand_safety(entry, segment_context, intent)
    if not is_safe:
        logger.warning(
            "[asset-registry] Asset %s failed brand safety: %s",
            entry.asset_id, "; ".join(reasons),
        )
        # Try fallback
        fallback = resolve_fallback(entry.asset_id, assets, intent=intent)
        if fallback and fallback.asset_id != entry.asset_id:
            is_safe_fb, _ = check_brand_safety(fallback, segment_context, intent)
            if is_safe_fb:
                logger.info(
                    "[asset-registry] Fallback %s passed brand safety",
                    fallback.asset_id,
                )
                entry = fallback
            else:
                return None
        else:
            return None

    # Step 5: Asset overuse
    if not check_asset_overuse(entry.asset_id, tracker):
        logger.info(
            "[asset-registry] Asset %s overused (count=%d, max=%d); skipping",
            entry.asset_id,
            tracker.usage_count(entry.asset_id),
            tracker.max_uses_per_clip,
        )
        return None

    # Step 6: Record usage
    tracker.record_use(entry.asset_id)

    logger.info(
        "[asset-registry] Selected asset=%s for segment intent=%s "
        "(brand=%.2f, clarity=%.2f, usage=%d)",
        entry.asset_id, intent,
        entry.brand_fit_score, entry.clarity_gain_score,
        tracker.usage_count(entry.asset_id),
    )
    return entry


# ── Convenience: build asset lookup from registry ──────────────────────────────


def build_asset_lookup(
    path: Optional[Path] = None,
) -> Dict[str, AssetRegistryEntry]:
    """Load the registry and return the asset lookup dict.

    This is a convenience wrapper around load_asset_registry().
    """
    return load_asset_registry(path)


# ── Visual family helpers ──────────────────────────────────────────────────────


def get_assets_by_family(
    visual_family: str,
    assets: Dict[str, AssetRegistryEntry],
) -> List[AssetRegistryEntry]:
    """Get all assets belonging to a visual family."""
    return [
        entry for entry in assets.values()
        if entry.visual_family == visual_family
    ]


def get_assets_by_intent(
    intent: str,
    assets: Dict[str, AssetRegistryEntry],
) -> List[AssetRegistryEntry]:
    """Get all assets that support a given intent."""
    return [
        entry for entry in assets.values()
        if intent in entry.allowed_intents
    ]


def get_fallback_chain(
    asset_id: str,
    assets: Dict[str, AssetRegistryEntry],
    max_hops: int = 3,
) -> List[str]:
    """Get the full fallback chain for an asset.

    Returns a list of asset_ids from the asset itself through its fallback
    chain, up to max_hops.
    """
    chain: List[str] = []
    current_id = asset_id
    for _ in range(max_hops + 1):
        if current_id in chain:
            break
        chain.append(current_id)
        entry = assets.get(current_id)
        if not entry or not entry.fallback_asset_id:
            break
        current_id = entry.fallback_asset_id
    return chain
