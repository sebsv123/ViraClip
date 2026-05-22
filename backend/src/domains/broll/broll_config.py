"""
B-roll configuration constants — single source of truth.

All B-roll duration, fade, and gap values must be imported from here.
No consumer file should define its own magic numbers for these values.
"""

# ── Minimum overlay duration (seconds) ──────────────────────────────────────
# No B-roll overlay shorter than this will be rendered.
# 4.0s is the minimum to allow 0.4s fade-in + content + 0.4s fade-out.
# Must match _MIN_BROLL_DUR in broll_compositor.py.
MIN_OVERLAY_DURATION_S = 4.0

# ── Minimum asset duration (seconds) ────────────────────────────────────────
# B-roll assets shorter than this are rejected before download/processing.
MIN_ASSET_DURATION_S = 2.0

# ── Fade duration (seconds) ─────────────────────────────────────────────────
# Fade-in and fade-out length for all B-roll overlays.
# 0.4s is the standard broadcast fade — visible but not sluggish.
FADE_DURATION_S = 0.4

# ── Overlap tolerance (seconds) ─────────────────────────────────────────────
# Minimum gap between the end of one overlay and the start of the next.
MIN_GAP_BETWEEN_OVERLAYS_S = 2.0

# ── Default overlay play duration (seconds) ─────────────────────────────────
# How long each B-roll overlay plays by default.
# Overridden per-clip by ClipIntelligenceProfile.broll_duration.
DEFAULT_OVERLAY_DURATION_S = 3.5

# ── Category cooldown (seconds) ─────────────────────────────────────────────
# Don't repeat the same visual category within this many seconds.
CATEGORY_COOLDOWN_S = 6.0

# ── Discourse window (seconds) ──────────────────────────────────────────────
# Merge micro-cues within this window into one overlay.
DISCOURSE_WINDOW_S = 10.0
