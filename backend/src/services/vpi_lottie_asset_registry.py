"""
vpi_lottie_asset_registry.py — Lottie asset registry for optional animated icons.

Provides a registry of Lottie JSON assets mapped to semantic categories.
This is a *pure data registry* — no rendering, no network downloads,
no LottieFiles API calls.

Design
------
- LottieAsset: dataclass with category, path, fallback_static_icon, metadata.
- CATEGORY_MAP: maps semantic categories to one or more LottieAsset entries.
- get_lottie_asset(): returns the best match for a category.
- get_fallback_icon(): returns a static SVG/PNG path when Lottie is unavailable.

Categories (mapped to visual_style from vpi_remotion_scene_plan):
  life_insurance    → revelation_hook (HookCard)
  paperwork         → paperwork (DocumentReveal)
  risk_warning      → risk_warning / serious_warning (WarningBadge)
  health            → calm_trust (LowerThird / SemanticObject)
  protection_calm   → calm_trust (LowerThird / SemanticObject)
  advice_action     → advice / practical_advice (ChecklistReveal)
  savings_finance   → clear_explanation (SemanticObject / CaptionEmphasis)

Integration
-----------
- vpi_remotion_scene_plan.py: style tokens reference Lottie categories.
- vpi_overlay_renderer_adapter.py: RemotionAdapter can embed Lottie paths.
- editing_pipeline.py: passes Lottie asset paths to overlay renderer.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Lottie asset dataclass ──────────────────────────────────────────────────────


@dataclass
class LottieAsset:
    """A Lottie animation asset entry.

    Fields
    ------
    asset_id : str
        Unique identifier for this asset.
    category : str
        Semantic category (e.g. "life_insurance", "paperwork").
    path : str
        Path to the Lottie JSON file.  Empty string if not yet acquired.
    fallback_static_icon : str
        Path to a static SVG/PNG fallback when Lottie is unavailable.
    metadata : dict
        Additional metadata: source, license, tags, etc.
    """
    asset_id: str
    category: str
    path: str = ""
    fallback_static_icon: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Category → visual_style mapping ─────────────────────────────────────────────

# Maps Lottie categories to the visual_style values they support.
CATEGORY_VISUAL_STYLE_MAP: Dict[str, List[str]] = {
    "life_insurance":    ["revelation_hook"],
    "paperwork":         ["paperwork"],
    "risk_warning":      ["risk_warning", "serious_warning"],
    "health":            ["calm_trust"],
    "protection_calm":   ["calm_trust"],
    "advice_action":     ["advice", "practical_advice"],
    "savings_finance":   ["clear_explanation"],
}

# Reverse map: visual_style → preferred category
VISUAL_STYLE_CATEGORY_MAP: Dict[str, str] = {
    "revelation_hook":   "life_insurance",
    "paperwork":         "paperwork",
    "risk_warning":      "risk_warning",
    "serious_warning":   "risk_warning",
    "calm_trust":        "protection_calm",
    "clear_explanation": "savings_finance",
    "advice":            "advice_action",
    "practical_advice":  "advice_action",
    "emotional_closure": "protection_calm",
}


# ── Asset registry ──────────────────────────────────────────────────────────────


# Base directory for Lottie assets
LOTTIE_ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "assets",
    "overlays",
    "lottie",
)

# Base directory for static fallback icons
STATIC_ICONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "assets",
    "overlays",
    "generated_icons",
)


def _build_default_registry() -> Dict[str, List[LottieAsset]]:
    """Build the default Lottie asset registry.

    Returns a dict mapping category → list of LottieAsset entries.
    Paths are set to empty strings by default (assets not yet acquired).
    Fallback static icons point to existing generated_icons where available.
    """
    registry: Dict[str, List[LottieAsset]] = {}

    # ── life_insurance ──────────────────────────────────────────────────────
    registry["life_insurance"] = [
        LottieAsset(
            asset_id="life_insurance_shield",
            category="life_insurance",
            path="",  # Not yet acquired
            fallback_static_icon=os.path.join(STATIC_ICONS_DIR, "shield.svg"),
            metadata={
                "source": "lottiefiles_community",
                "license": "free_cc",
                "tags": ["shield", "protection", "life", "insurance"],
                "intended_event": "hook_card",
            },
        ),
        LottieAsset(
            asset_id="life_insurance_heart",
            category="life_insurance",
            path="",
            fallback_static_icon=os.path.join(STATIC_ICONS_DIR, "heart.svg"),
            metadata={
                "source": "lottiefiles_community",
                "license": "free_cc",
                "tags": ["heart", "care", "family", "protection"],
                "intended_event": "hook_card",
            },
        ),
    ]

    # ── paperwork ───────────────────────────────────────────────────────────
    registry["paperwork"] = [
        LottieAsset(
            asset_id="paperwork_document",
            category="paperwork",
            path="",
            fallback_static_icon=os.path.join(STATIC_ICONS_DIR, "file-text.svg"),
            metadata={
                "source": "lottiefiles_community",
                "license": "free_cc",
                "tags": ["document", "paper", "file", "contract"],
                "intended_event": "document_reveal",
            },
        ),
        LottieAsset(
            asset_id="paperwork_clipboard",
            category="paperwork",
            path="",
            fallback_static_icon=os.path.join(STATIC_ICONS_DIR, "clipboard.svg"),
            metadata={
                "source": "lottiefiles_community",
                "license": "free_cc",
                "tags": ["clipboard", "checklist", "form"],
                "intended_event": "document_reveal",
            },
        ),
    ]

    # ── risk_warning ────────────────────────────────────────────────────────
    registry["risk_warning"] = [
        LottieAsset(
            asset_id="risk_warning_triangle",
            category="risk_warning",
            path="",
            fallback_static_icon=os.path.join(STATIC_ICONS_DIR, "alert-triangle.svg"),
            metadata={
                "source": "lottiefiles_community",
                "license": "free_cc",
                "tags": ["warning", "danger", "alert", "triangle"],
                "intended_event": "warning_badge",
            },
        ),
        LottieAsset(
            asset_id="risk_warning_shield_alert",
            category="risk_warning",
            path="",
            fallback_static_icon=os.path.join(STATIC_ICONS_DIR, "shield-alert.svg"),
            metadata={
                "source": "lottiefiles_community",
                "license": "free_cc",
                "tags": ["shield", "alert", "warning", "protection"],
                "intended_event": "warning_badge",
            },
        ),
    ]

    # ── health ───────────────────────────────────────────────────────────────
    registry["health"] = [
        LottieAsset(
            asset_id="health_heart_pulse",
            category="health",
            path="",
            fallback_static_icon=os.path.join(STATIC_ICONS_DIR, "heart-pulse.svg"),
            metadata={
                "source": "lottiefiles_community",
                "license": "free_cc",
                "tags": ["heart", "pulse", "health", "medical"],
                "intended_event": "semantic_object",
            },
        ),
        LottieAsset(
            asset_id="health_activity",
            category="health",
            path="",
            fallback_static_icon=os.path.join(STATIC_ICONS_DIR, "activity.svg"),
            metadata={
                "source": "lottiefiles_community",
                "license": "free_cc",
                "tags": ["activity", "health", "wellness", "chart"],
                "intended_event": "semantic_object",
            },
        ),
    ]

    # ── protection_calm ──────────────────────────────────────────────────────
    registry["protection_calm"] = [
        LottieAsset(
            asset_id="protection_calm_shield_check",
            category="protection_calm",
            path="",
            fallback_static_icon=os.path.join(STATIC_ICONS_DIR, "shield-check.svg"),
            metadata={
                "source": "lottiefiles_community",
                "license": "free_cc",
                "tags": ["shield", "check", "protection", "secure"],
                "intended_event": "lower_third",
            },
        ),
        LottieAsset(
            asset_id="protection_calm_leaf",
            category="protection_calm",
            path="",
            fallback_static_icon=os.path.join(STATIC_ICONS_DIR, "leaf.svg"),
            metadata={
                "source": "lottiefiles_community",
                "license": "free_cc",
                "tags": ["leaf", "nature", "calm", "peace"],
                "intended_event": "lower_third",
            },
        ),
    ]

    # ── advice_action ────────────────────────────────────────────────────────
    registry["advice_action"] = [
        LottieAsset(
            asset_id="advice_action_lightbulb",
            category="advice_action",
            path="",
            fallback_static_icon=os.path.join(STATIC_ICONS_DIR, "lightbulb.svg"),
            metadata={
                "source": "lottiefiles_community",
                "license": "free_cc",
                "tags": ["lightbulb", "idea", "advice", "tip"],
                "intended_event": "checklist_reveal",
            },
        ),
        LottieAsset(
            asset_id="advice_action_checklist",
            category="advice_action",
            path="",
            fallback_static_icon=os.path.join(STATIC_ICONS_DIR, "check-square.svg"),
            metadata={
                "source": "lottiefiles_community",
                "license": "free_cc",
                "tags": ["checklist", "todo", "action", "advice"],
                "intended_event": "checklist_reveal",
            },
        ),
    ]

    # ── savings_finance ──────────────────────────────────────────────────────
    registry["savings_finance"] = [
        LottieAsset(
            asset_id="savings_finance_piggy_bank",
            category="savings_finance",
            path="",
            fallback_static_icon=os.path.join(STATIC_ICONS_DIR, "piggy-bank.svg"),
            metadata={
                "source": "lottiefiles_community",
                "license": "free_cc",
                "tags": ["piggy", "bank", "savings", "money", "finance"],
                "intended_event": "semantic_object",
            },
        ),
        LottieAsset(
            asset_id="savings_finance_trending_up",
            category="savings_finance",
            path="",
            fallback_static_icon=os.path.join(STATIC_ICONS_DIR, "trending-up.svg"),
            metadata={
                "source": "lottiefiles_community",
                "license": "free_cc",
                "tags": ["trending", "up", "growth", "finance", "chart"],
                "intended_event": "semantic_object",
            },
        ),
    ]

    return registry


# Singleton registry
_ASSET_REGISTRY: Dict[str, List[LottieAsset]] = _build_default_registry()


# ── Public API ──────────────────────────────────────────────────────────────────


def get_lottie_asset(
    category: str,
    index: int = 0,
) -> Optional[LottieAsset]:
    """Get a Lottie asset by category.

    Args:
        category: Semantic category (e.g. "life_insurance", "paperwork").
        index: Index within the category list (default 0 = first match).

    Returns:
        A LottieAsset if found, or None if the category doesn't exist.
    """
    assets = _ASSET_REGISTRY.get(category)
    if not assets:
        logger.warning(
            "[lottie-registry] No assets found for category '%s'",
            category,
        )
        return None
    if index >= len(assets):
        logger.warning(
            "[lottie-registry] Index %d out of range for category '%s' (max %d)",
            index,
            category,
            len(assets) - 1,
        )
        return None
    return assets[index]


def get_lottie_asset_for_visual_style(
    visual_style: str,
    index: int = 0,
) -> Optional[LottieAsset]:
    """Get a Lottie asset by visual_style.

    Args:
        visual_style: Visual style string (e.g. "revelation_hook").
        index: Index within the category list.

    Returns:
        A LottieAsset if found, or None.
    """
    category = VISUAL_STYLE_CATEGORY_MAP.get(visual_style)
    if category is None:
        logger.warning(
            "[lottie-registry] No category mapping for visual_style '%s'",
            visual_style,
        )
        return None
    return get_lottie_asset(category, index)


def get_fallback_icon(
    category: str,
    index: int = 0,
) -> str:
    """Get a static fallback icon path for a category.

    Returns the fallback_static_icon path from the first matching asset,
    or an empty string if no asset is found.

    This is the safe path when Lottie rendering is not available.
    """
    asset = get_lottie_asset(category, index)
    if asset is None:
        return ""
    return asset.fallback_static_icon


def get_fallback_icon_for_visual_style(
    visual_style: str,
    index: int = 0,
) -> str:
    """Get a static fallback icon path for a visual_style."""
    category = VISUAL_STYLE_CATEGORY_MAP.get(visual_style)
    if category is None:
        return ""
    return get_fallback_icon(category, index)


def list_categories() -> List[str]:
    """List all registered Lottie categories."""
    return list(_ASSET_REGISTRY.keys())


def list_assets_for_category(category: str) -> List[LottieAsset]:
    """List all Lottie assets for a given category."""
    return _ASSET_REGISTRY.get(category, [])


def register_asset(asset: LottieAsset) -> None:
    """Register a new Lottie asset at runtime.

    Args:
        asset: The LottieAsset to register.
    """
    if asset.category not in _ASSET_REGISTRY:
        _ASSET_REGISTRY[asset.category] = []
    _ASSET_REGISTRY[asset.category].append(asset)
    logger.info(
        "[lottie-registry] Registered asset '%s' in category '%s'",
        asset.asset_id,
        asset.category,
    )


def is_lottie_available() -> bool:
    """Check if any Lottie assets have been acquired (path is non-empty).

    Returns True if at least one asset has a non-empty path.
    """
    for assets in _ASSET_REGISTRY.values():
        for asset in assets:
            if asset.path and os.path.isfile(asset.path):
                return True
    return False


def get_asset_path(
    category: str,
    index: int = 0,
) -> str:
    """Get the Lottie JSON path for a category.

    Returns the path if the file exists, or an empty string if not acquired.
    """
    asset = get_lottie_asset(category, index)
    if asset is None:
        return ""
    if asset.path and os.path.isfile(asset.path):
        return asset.path
    return ""


def get_asset_path_for_visual_style(
    visual_style: str,
    index: int = 0,
) -> str:
    """Get the Lottie JSON path for a visual_style."""
    category = VISUAL_STYLE_CATEGORY_MAP.get(visual_style)
    if category is None:
        return ""
    return get_asset_path(category, index)
