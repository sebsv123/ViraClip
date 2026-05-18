"""
Clip Performance Analyzer — Feature + Metrics Joiner & CreativeHints Generator.

Closes the feedback loop between real clip performance metrics and the creative
pipeline. Operates in offline batch mode (cron/worker), never during real-time render.

Key capabilities:
  - Join ClipFeatures + PerformanceMetrics for a single clip or workspace.
  - Compute aggregate statistics across clips (e.g. "hooks with questions have +15% watch_pct").
  - Generate CreativeHints using descriptive statistics + clear heuristics.
  - Threshold: >10 clips per pattern before generating recommendations.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.services.clip_features import (
    ClipFeatures,
    ClipFeaturesRepository,
    CreativeHint,
    PerformanceMetrics,
)

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────────
MIN_SAMPLE_SIZE = 10  # minimum clips needed to generate a hint
MIN_DELTA = 0.05      # minimum absolute improvement to consider meaningful (5%)
HIGH_CONFIDENCE_SAMPLE = 30
MEDIUM_CONFIDENCE_SAMPLE = 15

# ── Aggregated result types ───────────────────────────────────────────────────────


@dataclass
class JoinedClipData:
    """A single clip with both features and performance metrics joined."""

    clip_id: str
    features: Optional[ClipFeatures] = None
    metrics: Optional[PerformanceMetrics] = None


@dataclass
class AggregateStat:
    """Aggregate statistics for a group of clips sharing a characteristic."""

    group_label: str
    count: int
    avg_watch_pct: Optional[float] = None
    avg_engagement_rate: Optional[float] = None
    avg_views: Optional[float] = None
    avg_like_rate: Optional[float] = None


@dataclass
class PatternAnalysis:
    """Result of comparing two groups of clips to find a performance pattern."""

    pattern: str
    hint_type: str
    metric: str
    delta: float  # absolute difference (e.g., 0.15 for +15%)
    pct_change: float  # relative change
    sample_size: int
    baseline_avg: float
    variant_avg: float
    confidence: str  # "low", "medium", "high"


# ── Analyzer ──────────────────────────────────────────────────────────────────────


class ClipPerformanceAnalyzer:
    """
    Joins clip features with performance metrics and generates creative hints.

    All methods are async and accept an AsyncSession for database access.
    Designed for offline batch execution (worker/cron), not real-time rendering.
    """

    # ── Joiner methods ────────────────────────────────────────────────────────

    @staticmethod
    async def get_joined_clip_data(
        db: AsyncSession, clip_id: str
    ) -> JoinedClipData:
        """Return features + metrics for a single clip."""
        features = await ClipFeaturesRepository.get_features(db, clip_id)
        metrics_list = await ClipFeaturesRepository.get_all_metrics_for_clip(db, clip_id)
        # Return the first metrics entry (most recent) if available
        primary_metrics = metrics_list[0] if metrics_list else None
        return JoinedClipData(
            clip_id=clip_id,
            features=features,
            metrics=primary_metrics,
        )

    @staticmethod
    async def get_joined_data_for_workspace(
        db: AsyncSession, workspace_id: str
    ) -> list[JoinedClipData]:
        """Return all joined data for a workspace."""
        features_list = await ClipFeaturesRepository.get_all_features_for_workspace(
            db, workspace_id
        )
        metrics_list = await ClipFeaturesRepository.get_all_metrics_for_workspace(
            db, workspace_id
        )

        # Index metrics by clip_id (take first/most recent per clip)
        metrics_by_clip: dict[str, PerformanceMetrics] = {}
        for m in metrics_list:
            if m.clip_id not in metrics_by_clip:
                metrics_by_clip[m.clip_id] = m

        # Index features by clip_id
        features_by_clip: dict[str, ClipFeatures] = {
            f.clip_id: f for f in features_list
        }

        # Merge all clip IDs
        all_clip_ids = set(features_by_clip.keys()) | set(metrics_by_clip.keys())
        return [
            JoinedClipData(
                clip_id=cid,
                features=features_by_clip.get(cid),
                metrics=metrics_by_clip.get(cid),
            )
            for cid in sorted(all_clip_ids)
        ]

    # ── Aggregate statistics ──────────────────────────────────────────────────

    @staticmethod
    def compute_aggregates(
        joined_data: list[JoinedClipData],
    ) -> dict[str, Any]:
        """
        Compute aggregate statistics across all joined clips.

        Returns a dict with keys like:
          - total_clips
          - avg_duration_s
          - hook_type_distribution
          - caption_style_distribution
          - avg_watch_pct_by_hook_type
          - avg_engagement_by_caption_style
          - etc.
        """
        total = len(joined_data)
        if total == 0:
            return {"total_clips": 0}

        # Filter to clips that have both features and metrics
        valid = [j for j in joined_data if j.features and j.metrics]
        if not valid:
            return {"total_clips": total, "clips_with_data": 0}

        result: dict[str, Any] = {
            "total_clips": total,
            "clips_with_data": len(valid),
        }

        # Duration stats
        durations = [j.features.duration_s for j in valid if j.features.duration_s > 0]
        if durations:
            result["avg_duration_s"] = sum(durations) / len(durations)
            result["min_duration_s"] = min(durations)
            result["max_duration_s"] = max(durations)

        # Hook type distribution + performance
        hook_groups: dict[str, list[float]] = defaultdict(list)
        hook_engagement: dict[str, list[float]] = defaultdict(list)
        for j in valid:
            ht = j.features.hook_type or "none"
            if j.metrics.avg_watch_pct is not None:
                hook_groups[ht].append(j.metrics.avg_watch_pct)
            if j.metrics.engagement_rate is not None:
                hook_engagement[ht].append(j.metrics.engagement_rate)

        result["hook_type_distribution"] = {
            ht: len(vals) for ht, vals in hook_groups.items()
        }
        result["avg_watch_pct_by_hook_type"] = {
            ht: (sum(vals) / len(vals)) for ht, vals in hook_groups.items() if vals
        }
        result["avg_engagement_by_hook_type"] = {
            ht: (sum(vals) / len(vals)) for ht, vals in hook_engagement.items() if vals
        }

        # Caption style distribution + performance
        caption_groups: dict[str, list[float]] = defaultdict(list)
        for j in valid:
            cs = j.features.caption_style or "none"
            if j.metrics.avg_watch_pct is not None:
                caption_groups[cs].append(j.metrics.avg_watch_pct)

        result["caption_style_distribution"] = {
            cs: len(vals) for cs, vals in caption_groups.items()
        }
        result["avg_watch_pct_by_caption_style"] = {
            cs: (sum(vals) / len(vals)) for cs, vals in caption_groups.items() if vals
        }

        # B-roll presence
        with_broll = [j for j in valid if j.features.num_brolls > 0]
        without_broll = [j for j in valid if j.features.num_brolls == 0]
        if with_broll and without_broll:
            wb_watch = [
                j.metrics.avg_watch_pct
                for j in with_broll
                if j.metrics.avg_watch_pct is not None
            ]
            nb_watch = [
                j.metrics.avg_watch_pct
                for j in without_broll
                if j.metrics.avg_watch_pct is not None
            ]
            if wb_watch and nb_watch:
                result["avg_watch_pct_with_broll"] = sum(wb_watch) / len(wb_watch)
                result["avg_watch_pct_without_broll"] = sum(nb_watch) / len(nb_watch)

        # Music presence
        with_music = [j for j in valid if j.features.music_present]
        without_music = [j for j in valid if not j.features.music_present]
        if with_music and without_music:
            wm_watch = [
                j.metrics.avg_watch_pct
                for j in with_music
                if j.metrics.avg_watch_pct is not None
            ]
            nm_watch = [
                j.metrics.avg_watch_pct
                for j in without_music
                if j.metrics.avg_watch_pct is not None
            ]
            if wm_watch and nm_watch:
                result["avg_watch_pct_with_music"] = sum(wm_watch) / len(wm_watch)
                result["avg_watch_pct_without_music"] = sum(nm_watch) / len(nm_watch)

        # Visual hook presence
        with_hook = [j for j in valid if j.features.has_visual_hook]
        without_hook = [j for j in valid if not j.features.has_visual_hook]
        if with_hook and without_hook:
            wh_watch = [
                j.metrics.avg_watch_pct
                for j in with_hook
                if j.metrics.avg_watch_pct is not None
            ]
            nh_watch = [
                j.metrics.avg_watch_pct
                for j in without_hook
                if j.metrics.avg_watch_pct is not None
            ]
            if wh_watch and nh_watch:
                result["avg_watch_pct_with_visual_hook"] = sum(wh_watch) / len(wh_watch)
                result["avg_watch_pct_without_visual_hook"] = sum(nh_watch) / len(nh_watch)

        # Zoom punch
        with_zoom = [j for j in valid if j.features.zoom_punch_applied]
        without_zoom = [j for j in valid if not j.features.zoom_punch_applied]
        if with_zoom and without_zoom:
            wz_watch = [
                j.metrics.avg_watch_pct
                for j in with_zoom
                if j.metrics.avg_watch_pct is not None
            ]
            nz_watch = [
                j.metrics.avg_watch_pct
                for j in without_zoom
                if j.metrics.avg_watch_pct is not None
            ]
            if wz_watch and nz_watch:
                result["avg_watch_pct_with_zoom"] = sum(wz_watch) / len(wz_watch)
                result["avg_watch_pct_without_zoom"] = sum(nz_watch) / len(nz_watch)

        # Duration buckets
        duration_buckets: dict[str, list[float]] = defaultdict(list)
        for j in valid:
            d = j.features.duration_s
            if d <= 15:
                bucket = "0-15s"
            elif d <= 30:
                bucket = "15-30s"
            elif d <= 60:
                bucket = "30-60s"
            else:
                bucket = "60s+"
            if j.metrics.avg_watch_pct is not None:
                duration_buckets[bucket].append(j.metrics.avg_watch_pct)

        result["avg_watch_pct_by_duration_bucket"] = {
            bucket: (sum(vals) / len(vals))
            for bucket, vals in duration_buckets.items()
            if vals
        }

        return result

    # ── Pattern analysis ──────────────────────────────────────────────────────

    @staticmethod
    def _compute_confidence(sample_size: int) -> str:
        """Determine confidence level based on sample size."""
        if sample_size >= HIGH_CONFIDENCE_SAMPLE:
            return "high"
        elif sample_size >= MEDIUM_CONFIDENCE_SAMPLE:
            return "medium"
        return "low"

    @staticmethod
    def _analyze_binary_pattern(
        label: str,
        hint_type: str,
        metric_key: str,
        variant_group: list[JoinedClipData],
        baseline_group: list[JoinedClipData],
        metric_extractor: callable,
    ) -> Optional[PatternAnalysis]:
        """
        Compare two groups on a given metric.

        Args:
            label: Human-readable pattern description.
            hint_type: Category ("hook", "broll", "duration", etc.).
            metric_key: Metric name ("avg_watch_pct", "engagement_rate", etc.).
            variant_group: Clips with the characteristic.
            baseline_group: Clips without the characteristic.
            metric_extractor: Function to extract the metric value from a JoinedClipData.

        Returns:
            PatternAnalysis if both groups have enough data, else None.
        """
        variant_vals = [
            metric_extractor(j)
            for j in variant_group
            if metric_extractor(j) is not None
        ]
        baseline_vals = [
            metric_extractor(j)
            for j in baseline_group
            if metric_extractor(j) is not None
        ]

        total_samples = len(variant_vals) + len(baseline_vals)
        if total_samples < MIN_SAMPLE_SIZE:
            return None
        if not variant_vals or not baseline_vals:
            return None

        variant_avg = sum(variant_vals) / len(variant_vals)
        baseline_avg = sum(baseline_vals) / len(baseline_vals)
        delta = variant_avg - baseline_avg

        if abs(delta) < MIN_DELTA:
            return None

        pct_change = delta / baseline_avg if baseline_avg != 0 else 0.0

        return PatternAnalysis(
            pattern=label,
            hint_type=hint_type,
            metric=metric_key,
            delta=delta,
            pct_change=pct_change,
            sample_size=total_samples,
            baseline_avg=baseline_avg,
            variant_avg=variant_avg,
            confidence=ClipPerformanceAnalyzer._compute_confidence(total_samples),
        )

    @staticmethod
    def _analyze_multi_category_pattern(
        label_template: str,
        hint_type: str,
        metric_key: str,
        groups: dict[str, list[JoinedClipData]],
        metric_extractor: callable,
    ) -> list[PatternAnalysis]:
        """
        Compare multiple category groups against the overall average.

        For each category with enough samples, compares its average against
        the average of all other clips combined.
        """
        # Compute overall average
        all_vals = [
            metric_extractor(j)
            for group_list in groups.values()
            for j in group_list
            if metric_extractor(j) is not None
        ]
        if not all_vals:
            return []
        overall_avg = sum(all_vals) / len(all_vals)

        results: list[PatternAnalysis] = []
        for category, group_list in groups.items():
            cat_vals = [
                metric_extractor(j)
                for j in group_list
                if metric_extractor(j) is not None
            ]
            if len(cat_vals) < MIN_SAMPLE_SIZE:
                continue
            cat_avg = sum(cat_vals) / len(cat_vals)
            delta = cat_avg - overall_avg
            if abs(delta) < MIN_DELTA:
                continue

            pct_change = delta / overall_avg if overall_avg != 0 else 0.0
            results.append(
                PatternAnalysis(
                    pattern=label_template.format(category=category),
                    hint_type=hint_type,
                    metric=metric_key,
                    delta=delta,
                    pct_change=pct_change,
                    sample_size=len(cat_vals),
                    baseline_avg=overall_avg,
                    variant_avg=cat_avg,
                    confidence=ClipPerformanceAnalyzer._compute_confidence(
                        len(cat_vals)
                    ),
                )
            )

        return results

    # ── CreativeHints generation ──────────────────────────────────────────────

    @staticmethod
    async def suggest_creative_adjustments(
        db: AsyncSession,
        workspace_id: str,
    ) -> list[CreativeHint]:
        """
        Analyze all clips for a workspace and generate CreativeHints.

        This is the main entry point for the optimization loop. It:
        1. Loads all joined clip data for the workspace.
        2. Runs pattern analysis across multiple dimensions.
        3. Persists the resulting hints to the database.
        4. Returns the list of generated hints.

        Designed for offline batch execution (worker/cron).
        """
        joined_data = await ClipPerformanceAnalyzer.get_joined_data_for_workspace(
            db, workspace_id
        )

        # Filter to clips that have both features and metrics
        valid = [j for j in joined_data if j.features and j.metrics]
        if len(valid) < MIN_SAMPLE_SIZE:
            logger.info(
                "Workspace %s: only %d clips with data (need %d). Skipping hint generation.",
                workspace_id,
                len(valid),
                MIN_SAMPLE_SIZE,
            )
            return []

        patterns = ClipPerformanceAnalyzer._run_all_pattern_analyses(valid)
        logger.info(
            "Workspace %s: found %d patterns from %d clips.",
            workspace_id,
            len(patterns),
            len(valid),
        )

        # Convert patterns to CreativeHint dataclasses and persist
        hints: list[CreativeHint] = []
        for p in patterns:
            hint = CreativeHint(
                workspace_id=workspace_id,
                hint_type=p.hint_type,
                pattern=p.pattern,
                metric=p.metric,
                delta=p.delta,
                confidence=p.confidence,
                sample_size=p.sample_size,
                payload={
                    "pct_change": round(p.pct_change, 4),
                    "baseline_avg": round(p.baseline_avg, 4),
                    "variant_avg": round(p.variant_avg, 4),
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
                active=True,
            )
            await ClipFeaturesRepository.upsert_hint(db, hint)
            hints.append(hint)

        return hints

    @staticmethod
    def _run_all_pattern_analyses(
        valid: list[JoinedClipData],
    ) -> list[PatternAnalysis]:
        """Run all pattern analyses on the valid clip set."""
        patterns: list[PatternAnalysis] = []

        # ── Hook type analysis ────────────────────────────────────────────────
        hook_groups: dict[str, list[JoinedClipData]] = defaultdict(list)
        for j in valid:
            ht = j.features.hook_type or "none"
            hook_groups[ht].append(j)

        patterns.extend(
            ClipPerformanceAnalyzer._analyze_multi_category_pattern(
                label_template="Hook type '{category}' outperforms average",
                hint_type="hook",
                metric_key="avg_watch_pct",
                groups=hook_groups,
                metric_extractor=lambda j: j.metrics.avg_watch_pct,
            )
        )

        # ── Caption style analysis ────────────────────────────────────────────
        caption_groups: dict[str, list[JoinedClipData]] = defaultdict(list)
        for j in valid:
            cs = j.features.caption_style or "none"
            caption_groups[cs].append(j)

        patterns.extend(
            ClipPerformanceAnalyzer._analyze_multi_category_pattern(
                label_template="Caption style '{category}' outperforms average",
                hint_type="caption_style",
                metric_key="avg_watch_pct",
                groups=caption_groups,
                metric_extractor=lambda j: j.metrics.avg_watch_pct,
            )
        )

        # ── B-roll presence ───────────────────────────────────────────────────
        with_broll = [j for j in valid if j.features.num_brolls > 0]
        without_broll = [j for j in valid if j.features.num_brolls == 0]
        broll_pattern = ClipPerformanceAnalyzer._analyze_binary_pattern(
            label="Clips with B-roll outperform clips without B-roll",
            hint_type="broll",
            metric_key="avg_watch_pct",
            variant_group=with_broll,
            baseline_group=without_broll,
            metric_extractor=lambda j: j.metrics.avg_watch_pct,
        )
        if broll_pattern:
            patterns.append(broll_pattern)

        # ── Music presence ────────────────────────────────────────────────────
        with_music = [j for j in valid if j.features.music_present]
        without_music = [j for j in valid if not j.features.music_present]
        music_pattern = ClipPerformanceAnalyzer._analyze_binary_pattern(
            label="Clips with background music outperform clips without",
            hint_type="audio",
            metric_key="avg_watch_pct",
            variant_group=with_music,
            baseline_group=without_music,
            metric_extractor=lambda j: j.metrics.avg_watch_pct,
        )
        if music_pattern:
            patterns.append(music_pattern)

        # ── Visual hook presence ──────────────────────────────────────────────
        with_hook = [j for j in valid if j.features.has_visual_hook]
        without_hook = [j for j in valid if not j.features.has_visual_hook]
        hook_pattern = ClipPerformanceAnalyzer._analyze_binary_pattern(
            label="Clips with visual hook outperform clips without",
            hint_type="hook",
            metric_key="avg_watch_pct",
            variant_group=with_hook,
            baseline_group=without_hook,
            metric_extractor=lambda j: j.metrics.avg_watch_pct,
        )
        if hook_pattern:
            patterns.append(hook_pattern)

        # ── Zoom punch ────────────────────────────────────────────────────────
        with_zoom = [j for j in valid if j.features.zoom_punch_applied]
        without_zoom = [j for j in valid if not j.features.zoom_punch_applied]
        zoom_pattern = ClipPerformanceAnalyzer._analyze_binary_pattern(
            label="Clips with zoom punch outperform clips without",
            hint_type="pacing",
            metric_key="avg_watch_pct",
            variant_group=with_zoom,
            baseline_group=without_zoom,
            metric_extractor=lambda j: j.metrics.avg_watch_pct,
        )
        if zoom_pattern:
            patterns.append(zoom_pattern)

        # ── Duration bucket analysis ──────────────────────────────────────────
        duration_groups: dict[str, list[JoinedClipData]] = defaultdict(list)
        for j in valid:
            d = j.features.duration_s
            if d <= 15:
                bucket = "0-15s"
            elif d <= 30:
                bucket = "15-30s"
            elif d <= 60:
                bucket = "30-60s"
            else:
                bucket = "60s+"
            duration_groups[bucket].append(j)

        patterns.extend(
            ClipPerformanceAnalyzer._analyze_multi_category_pattern(
                label_template="Duration bucket '{category}' outperforms average",
                hint_type="duration",
                metric_key="avg_watch_pct",
                groups=duration_groups,
                metric_extractor=lambda j: j.metrics.avg_watch_pct,
            )
        )

        # ── SFX count analysis ────────────────────────────────────────────────
        sfx_groups: dict[str, list[JoinedClipData]] = defaultdict(list)
        for j in valid:
            if j.features.sfx_count == 0:
                sfx_groups["no_sfx"].append(j)
            elif j.features.sfx_count <= 3:
                sfx_groups["1-3_sfx"].append(j)
            else:
                sfx_groups["4+_sfx"].append(j)

        patterns.extend(
            ClipPerformanceAnalyzer._analyze_multi_category_pattern(
                label_template="SFX count '{category}' outperforms average",
                hint_type="audio",
                metric_key="avg_watch_pct",
                groups=sfx_groups,
                metric_extractor=lambda j: j.metrics.avg_watch_pct,
            )
        )

        # ── Talking head ratio analysis ───────────────────────────────────────
        th_groups: dict[str, list[JoinedClipData]] = defaultdict(list)
        for j in valid:
            ratio = j.features.talking_head_ratio
            if ratio is None:
                th_groups["unknown"].append(j)
            elif ratio < 0.3:
                th_groups["low_talking_head"].append(j)
            elif ratio < 0.7:
                th_groups["mixed_talking_head"].append(j)
            else:
                th_groups["high_talking_head"].append(j)

        patterns.extend(
            ClipPerformanceAnalyzer._analyze_multi_category_pattern(
                label_template="Talking head '{category}' outperforms average",
                hint_type="pacing",
                metric_key="avg_watch_pct",
                groups=th_groups,
                metric_extractor=lambda j: j.metrics.avg_watch_pct,
            )
        )

        return patterns

    # ── Dashboard data preparation ────────────────────────────────────────────

    @staticmethod
    async def get_dashboard_data(
        db: AsyncSession,
        workspace_id: str,
    ) -> dict[str, Any]:
        """
        Prepare data for the "What works on your channel" dashboard.

        Returns a dict with:
          - aggregates: aggregate statistics across all clips.
          - hints: active creative hints for the workspace.
          - top_performers: clips sorted by avg_watch_pct (top 10).
          - recent_clips: clips sorted by recorded_at (last 10).
        """
        joined_data = await ClipPerformanceAnalyzer.get_joined_data_for_workspace(
            db, workspace_id
        )
        aggregates = ClipPerformanceAnalyzer.compute_aggregates(joined_data)
        hints = await ClipFeaturesRepository.get_active_hints(db, workspace_id)

        # Top performers by avg_watch_pct
        with_metrics = [
            j for j in joined_data if j.metrics and j.metrics.avg_watch_pct is not None
        ]
        top_performers = sorted(
            with_metrics,
            key=lambda j: j.metrics.avg_watch_pct or 0,
            reverse=True,
        )[:10]

        # Recent clips by recorded_at
        with_recorded = [
            j for j in joined_data if j.metrics and j.metrics.recorded_at
        ]
        recent_clips = sorted(
            with_recorded,
            key=lambda j: j.metrics.recorded_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )[:10]

        return {
            "aggregates": aggregates,
            "hints": [
                {
                    "id": h.id,
                    "hint_type": h.hint_type,
                    "pattern": h.pattern,
                    "metric": h.metric,
                    "delta": h.delta,
                    "confidence": h.confidence,
                    "sample_size": h.sample_size,
                    "payload": h.payload,
                }
                for h in hints
            ],
            "top_performers": [
                {
                    "clip_id": j.clip_id,
                    "avg_watch_pct": j.metrics.avg_watch_pct,
                    "views": j.metrics.views,
                    "engagement_rate": j.metrics.engagement_rate,
                    "hook_type": j.features.hook_type if j.features else None,
                    "caption_style": j.features.caption_style if j.features else None,
                    "duration_s": j.features.duration_s if j.features else None,
                }
                for j in top_performers
            ],
            "recent_clips": [
                {
                    "clip_id": j.clip_id,
                    "recorded_at": j.metrics.recorded_at.isoformat() if j.metrics.recorded_at else None,
                    "avg_watch_pct": j.metrics.avg_watch_pct,
                    "views": j.metrics.views,
                }
                for j in recent_clips
            ],
        }
