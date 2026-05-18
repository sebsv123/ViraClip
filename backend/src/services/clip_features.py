"""
ClipFeatures data model — captures creative/technical characteristics of each clip.

Provides dataclasses and repository methods for:
- ClipFeatures: extracted features from each generated clip
- PerformanceMetrics: real-world performance data from external platforms
- CreativeHint: computed recommendations for the creative pipeline

All operations use raw SQL via SQLAlchemy text() for simplicity.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional
import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text as sa_text

logger = logging.getLogger(__name__)

# ── Dataclasses ─────────────────────────────────────────────────────────────────


@dataclass
class ClipFeatures:
    """Captures the creative/technical characteristics of a single clip."""

    clip_id: str

    # Temporal
    duration_s: float = 0.0
    fps: Optional[float] = None

    # Editing structure
    num_cuts: int = 0
    num_brolls: int = 0
    talking_head_ratio: Optional[float] = None  # 0.0–1.0
    cut_density: Optional[float] = None  # cuts per second

    # B-roll distribution
    broll_ratio_first_10s: Optional[float] = None

    # Hook
    has_visual_hook: bool = False
    hook_type: Optional[str] = None
    hook_duration_s: Optional[float] = None

    # Caption style
    caption_style: Optional[str] = None
    caption_word_count: Optional[int] = None

    # Visual treatment
    lut_used: Optional[str] = None
    color_grade_applied: bool = False
    zoom_punch_applied: bool = False
    slowmo_applied: bool = False

    # Audio
    music_present: bool = False
    sfx_count: int = 0
    voice_enhancement_applied: bool = False

    # Derived
    creative_quality_score: Optional[float] = None

    # Metadata
    extracted_at: Optional[datetime] = None
    extraction_version: str = "1.0"

    id: Optional[str] = None  # DB primary key


@dataclass
class PerformanceMetrics:
    """Real-world performance data for a clip on a specific platform."""

    clip_id: str
    platform: str

    # Core metrics
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0

    # Watch time / retention
    watch_time_s: Optional[float] = None
    avg_watch_pct: Optional[float] = None
    avg_watch_duration_s: Optional[float] = None

    # Engagement rates (computed)
    like_rate: Optional[float] = None
    comment_rate: Optional[float] = None
    share_rate: Optional[float] = None
    engagement_rate: Optional[float] = None

    # CTR
    ctr: Optional[float] = None

    # Timing
    posted_at: Optional[datetime] = None
    recorded_at: Optional[datetime] = None

    # External reference
    external_post_id: Optional[str] = None

    id: Optional[str] = None  # DB primary key


@dataclass
class CreativeHint:
    """A computed recommendation derived from analyzing clip features + performance."""

    workspace_id: str
    hint_type: str  # "hook", "broll", "duration", "caption_style", "pacing", etc.
    pattern: str  # human-readable description
    metric: str  # "avg_watch_pct", "engagement_rate", "views", etc.
    delta: float  # measured improvement (e.g., 0.15 for +15%)
    confidence: str = "medium"  # "low", "medium", "high"
    sample_size: int = 0
    payload: dict = field(default_factory=dict)
    active: bool = True

    id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── Repository methods ──────────────────────────────────────────────────────────


class ClipFeaturesRepository:
    """Repository for clip_features, clip_performance_metrics, and creative_hints."""

    # ── Clip Features ───────────────────────────────────────────────────────

    @staticmethod
    async def upsert_features(db: AsyncSession, features: ClipFeatures) -> str:
        """Insert or update clip features. Returns the row ID."""
        payload = asdict(features)
        # Remove None values so DB defaults apply
        payload = {k: v for k, v in payload.items() if v is not None}
        row_id = payload.pop("id", None)

        result = await db.execute(
            sa_text(
                """
                INSERT INTO clip_features
                    (clip_id, duration_s, fps, num_cuts, num_brolls,
                     talking_head_ratio, cut_density, broll_ratio_first_10s,
                     has_visual_hook, hook_type, hook_duration_s,
                     caption_style, caption_word_count,
                     lut_used, color_grade_applied, zoom_punch_applied, slowmo_applied,
                     music_present, sfx_count, voice_enhancement_applied,
                     creative_quality_score, extraction_version)
                VALUES
                    (:clip_id, :duration_s, :fps, :num_cuts, :num_brolls,
                     :talking_head_ratio, :cut_density, :broll_ratio_first_10s,
                     :has_visual_hook, :hook_type, :hook_duration_s,
                     :caption_style, :caption_word_count,
                     :lut_used, :color_grade_applied, :zoom_punch_applied, :slowmo_applied,
                     :music_present, :sfx_count, :voice_enhancement_applied,
                     :creative_quality_score, :extraction_version)
                ON CONFLICT (clip_id)
                DO UPDATE SET
                    duration_s             = EXCLUDED.duration_s,
                    fps                    = EXCLUDED.fps,
                    num_cuts               = EXCLUDED.num_cuts,
                    num_brolls             = EXCLUDED.num_brolls,
                    talking_head_ratio     = EXCLUDED.talking_head_ratio,
                    cut_density            = EXCLUDED.cut_density,
                    broll_ratio_first_10s  = EXCLUDED.broll_ratio_first_10s,
                    has_visual_hook        = EXCLUDED.has_visual_hook,
                    hook_type              = EXCLUDED.hook_type,
                    hook_duration_s        = EXCLUDED.hook_duration_s,
                    caption_style          = EXCLUDED.caption_style,
                    caption_word_count     = EXCLUDED.caption_word_count,
                    lut_used               = EXCLUDED.lut_used,
                    color_grade_applied    = EXCLUDED.color_grade_applied,
                    zoom_punch_applied     = EXCLUDED.zoom_punch_applied,
                    slowmo_applied         = EXCLUDED.slowmo_applied,
                    music_present          = EXCLUDED.music_present,
                    sfx_count              = EXCLUDED.sfx_count,
                    voice_enhancement_applied = EXCLUDED.voice_enhancement_applied,
                    creative_quality_score = EXCLUDED.creative_quality_score,
                    extraction_version     = EXCLUDED.extraction_version,
                    extracted_at           = NOW()
                RETURNING id
                """
            ),
            payload,
        )
        await db.commit()
        returned_id = result.scalar()
        logger.debug("Upserted clip_features for clip %s (id=%s)", features.clip_id, returned_id)
        return str(returned_id)

    @staticmethod
    async def get_features(
        db: AsyncSession, clip_id: str
    ) -> Optional[ClipFeatures]:
        """Retrieve clip features by clip_id."""
        result = await db.execute(
            sa_text(
                "SELECT * FROM clip_features WHERE clip_id = :clip_id"
            ),
            {"clip_id": clip_id},
        )
        row = result.fetchone()
        if not row:
            return None
        return _row_to_clip_features(row)

    @staticmethod
    async def get_features_batch(
        db: AsyncSession, clip_ids: list[str]
    ) -> dict[str, ClipFeatures]:
        """Return a dict mapping clip_id → ClipFeatures for the given IDs."""
        if not clip_ids:
            return {}
        result = await db.execute(
            sa_text(
                """
                SELECT * FROM clip_features
                WHERE clip_id = ANY(:clip_ids)
                """
            ),
            {"clip_ids": clip_ids},
        )
        rows = result.fetchall()
        return {row.clip_id: _row_to_clip_features(row) for row in rows}

    @staticmethod
    async def get_all_features_for_workspace(
        db: AsyncSession, workspace_id: str
    ) -> list[ClipFeatures]:
        """Get all clip features for clips belonging to a workspace."""
        result = await db.execute(
            sa_text(
                """
                SELECT cf.* FROM clip_features cf
                JOIN generated_clips gc ON gc.id = cf.clip_id
                JOIN tasks t ON t.id = gc.task_id
                WHERE t.user_id = :workspace_id
                """
            ),
            {"workspace_id": workspace_id},
        )
        return [_row_to_clip_features(row) for row in result.fetchall()]

    # ── Performance Metrics ─────────────────────────────────────────────────

    @staticmethod
    async def upsert_metrics(db: AsyncSession, metrics: PerformanceMetrics) -> str:
        """Insert or update performance metrics. Returns the row ID."""
        payload = asdict(metrics)
        payload = {k: v for k, v in payload.items() if v is not None}
        row_id = payload.pop("id", None)

        result = await db.execute(
            sa_text(
                """
                INSERT INTO clip_performance_metrics
                    (clip_id, platform, external_post_id,
                     views, likes, comments, shares, saves,
                     watch_time_s, avg_watch_pct, avg_watch_duration_s,
                     like_rate, comment_rate, share_rate, engagement_rate,
                     ctr, posted_at)
                VALUES
                    (:clip_id, :platform, :external_post_id,
                     :views, :likes, :comments, :shares, :saves,
                     :watch_time_s, :avg_watch_pct, :avg_watch_duration_s,
                     :like_rate, :comment_rate, :share_rate, :engagement_rate,
                     :ctr, :posted_at)
                ON CONFLICT (clip_id, platform)
                DO UPDATE SET
                    views               = EXCLUDED.views,
                    likes               = EXCLUDED.likes,
                    comments            = EXCLUDED.comments,
                    shares              = EXCLUDED.shares,
                    saves               = EXCLUDED.saves,
                    watch_time_s        = EXCLUDED.watch_time_s,
                    avg_watch_pct       = EXCLUDED.avg_watch_pct,
                    avg_watch_duration_s = EXCLUDED.avg_watch_duration_s,
                    like_rate           = EXCLUDED.like_rate,
                    comment_rate        = EXCLUDED.comment_rate,
                    share_rate          = EXCLUDED.share_rate,
                    engagement_rate     = EXCLUDED.engagement_rate,
                    ctr                 = EXCLUDED.ctr,
                    posted_at           = EXCLUDED.posted_at,
                    recorded_at         = NOW()
                RETURNING id
                """
            ),
            payload,
        )
        await db.commit()
        returned_id = result.scalar()
        logger.debug("Upserted performance metrics for clip %s on %s", metrics.clip_id, metrics.platform)
        return str(returned_id)

    @staticmethod
    async def get_metrics(
        db: AsyncSession, clip_id: str, platform: str
    ) -> Optional[PerformanceMetrics]:
        """Retrieve performance metrics for a clip on a specific platform."""
        result = await db.execute(
            sa_text(
                """
                SELECT * FROM clip_performance_metrics
                WHERE clip_id = :clip_id AND platform = :platform
                """
            ),
            {"clip_id": clip_id, "platform": platform},
        )
        row = result.fetchone()
        if not row:
            return None
        return _row_to_performance_metrics(row)

    @staticmethod
    async def get_all_metrics_for_clip(
        db: AsyncSession, clip_id: str
    ) -> list[PerformanceMetrics]:
        """Get all platform metrics for a single clip."""
        result = await db.execute(
            sa_text(
                """
                SELECT * FROM clip_performance_metrics
                WHERE clip_id = :clip_id
                ORDER BY recorded_at DESC
                """
            ),
            {"clip_id": clip_id},
        )
        return [_row_to_performance_metrics(row) for row in result.fetchall()]

    @staticmethod
    async def get_all_metrics_for_workspace(
        db: AsyncSession, workspace_id: str
    ) -> list[PerformanceMetrics]:
        """Get all performance metrics for clips belonging to a workspace."""
        result = await db.execute(
            sa_text(
                """
                SELECT cpm.* FROM clip_performance_metrics cpm
                JOIN generated_clips gc ON gc.id = cpm.clip_id
                JOIN tasks t ON t.id = gc.task_id
                WHERE t.user_id = :workspace_id
                ORDER BY cpm.recorded_at DESC
                """
            ),
            {"workspace_id": workspace_id},
        )
        return [_row_to_performance_metrics(row) for row in result.fetchall()]

    # ── Creative Hints ──────────────────────────────────────────────────────

    @staticmethod
    async def upsert_hint(db: AsyncSession, hint: CreativeHint) -> str:
        """Insert or update a creative hint. Returns the row ID."""
        payload = asdict(hint)
        payload = {k: v for k, v in payload.items() if v is not None}
        row_id = payload.pop("id", None)
        payload["payload"] = json.dumps(payload.get("payload", {}))

        result = await db.execute(
            sa_text(
                """
                INSERT INTO creative_hints
                    (workspace_id, hint_type, pattern, metric, delta,
                     confidence, sample_size, payload, active)
                VALUES
                    (:workspace_id, :hint_type, :pattern, :metric, :delta,
                     :confidence, :sample_size, CAST(:payload AS JSONB), :active)
                ON CONFLICT (workspace_id, hint_type, pattern)
                DO UPDATE SET
                    metric      = EXCLUDED.metric,
                    delta       = EXCLUDED.delta,
                    confidence  = EXCLUDED.confidence,
                    sample_size = EXCLUDED.sample_size,
                    payload     = CAST(EXCLUDED.payload AS JSONB),
                    active      = EXCLUDED.active,
                    updated_at  = NOW()
                RETURNING id
                """
            ),
            payload,
        )
        await db.commit()
        returned_id = result.scalar()
        logger.debug("Upserted creative hint %s for workspace %s", hint.hint_type, hint.workspace_id)
        return str(returned_id)

    @staticmethod
    async def get_active_hints(
        db: AsyncSession, workspace_id: str, hint_type: Optional[str] = None
    ) -> list[CreativeHint]:
        """Get active creative hints for a workspace, optionally filtered by type."""
        if hint_type:
            result = await db.execute(
                sa_text(
                    """
                    SELECT * FROM creative_hints
                    WHERE workspace_id = :workspace_id
                      AND hint_type = :hint_type
                      AND active = TRUE
                    ORDER BY delta DESC, sample_size DESC
                    """
                ),
                {"workspace_id": workspace_id, "hint_type": hint_type},
            )
        else:
            result = await db.execute(
                sa_text(
                    """
                    SELECT * FROM creative_hints
                    WHERE workspace_id = :workspace_id
                      AND active = TRUE
                    ORDER BY hint_type, delta DESC, sample_size DESC
                    """
                ),
                {"workspace_id": workspace_id},
            )
        return [_row_to_creative_hint(row) for row in result.fetchall()]

    @staticmethod
    async def get_all_hints_for_workspace(
        db: AsyncSession, workspace_id: str
    ) -> list[CreativeHint]:
        """Get all hints (active + inactive) for a workspace."""
        result = await db.execute(
            sa_text(
                """
                SELECT * FROM creative_hints
                WHERE workspace_id = :workspace_id
                ORDER BY created_at DESC
                """
            ),
            {"workspace_id": workspace_id},
        )
        return [_row_to_creative_hint(row) for row in result.fetchall()]

    @staticmethod
    async def deactivate_hint(db: AsyncSession, hint_id: str) -> bool:
        """Soft-deactivate a hint by ID."""
        result = await db.execute(
            sa_text(
                "UPDATE creative_hints SET active = FALSE, updated_at = NOW() WHERE id = :id"
            ),
            {"id": hint_id},
        )
        await db.commit()
        return (result.rowcount or 0) > 0

    @staticmethod
    async def delete_hints_for_workspace(
        db: AsyncSession, workspace_id: str, hint_type: Optional[str] = None
    ) -> int:
        """Delete hints for a workspace, optionally filtered by type. Returns count."""
        if hint_type:
            result = await db.execute(
                sa_text(
                    "DELETE FROM creative_hints WHERE workspace_id = :ws AND hint_type = :ht"
                ),
                {"ws": workspace_id, "ht": hint_type},
            )
        else:
            result = await db.execute(
                sa_text("DELETE FROM creative_hints WHERE workspace_id = :ws"),
                {"ws": workspace_id},
            )
        await db.commit()
        return result.rowcount or 0


# ── Feature extraction helper ───────────────────────────────────────────────────


def extract_clip_features_from_meta(
    clip_id: str,
    creative_meta: dict,
    duration_s: Optional[float] = None,
) -> ClipFeatures:
    """
    Build a ClipFeatures dataclass from the creative pipeline metadata dict.

    This is the primary way features are populated — called after the creative
    pipeline finishes for a clip.
    """
    return ClipFeatures(
        clip_id=clip_id,
        duration_s=duration_s or creative_meta.get("duration_s", 0.0),
        fps=creative_meta.get("fps"),
        num_cuts=creative_meta.get("num_cuts", 0),
        num_brolls=creative_meta.get("broll_overlays", 0),
        talking_head_ratio=creative_meta.get("talking_head_ratio"),
        cut_density=creative_meta.get("cut_density"),
        broll_ratio_first_10s=creative_meta.get("broll_ratio_first_10s"),
        has_visual_hook=bool(creative_meta.get("hook_reorder_applied", False)
                             or creative_meta.get("hook_text")),
        hook_type=creative_meta.get("hook_type"),
        hook_duration_s=creative_meta.get("hook_duration_s"),
        caption_style=creative_meta.get("caption_style"),
        caption_word_count=creative_meta.get("caption_word_count"),
        lut_used=creative_meta.get("lut_used"),
        color_grade_applied=bool(creative_meta.get("color_grade_applied", False)),
        zoom_punch_applied=bool(creative_meta.get("zoom_punch_applied", False)),
        slowmo_applied=bool(creative_meta.get("speed_control_applied", False)),
        music_present=bool(creative_meta.get("music_present", False)),
        sfx_count=creative_meta.get("sfx_injected", 0),
        voice_enhancement_applied=bool(creative_meta.get("loudnorm_applied", False)),
        creative_quality_score=creative_meta.get("viral_score"),
        extraction_version="1.0",
    )


# ── Row → Dataclass helpers ─────────────────────────────────────────────────────


def _row_to_clip_features(row) -> ClipFeatures:
    """Convert a DB row (namedtuple) to a ClipFeatures dataclass."""
    return ClipFeatures(
        id=getattr(row, "id", None),
        clip_id=row.clip_id,
        duration_s=float(row.duration_s or 0),
        fps=float(row.fps) if row.fps is not None else None,
        num_cuts=int(row.num_cuts or 0),
        num_brolls=int(row.num_brolls or 0),
        talking_head_ratio=float(row.talking_head_ratio) if row.talking_head_ratio is not None else None,
        cut_density=float(row.cut_density) if row.cut_density is not None else None,
        broll_ratio_first_10s=float(row.broll_ratio_first_10s) if row.broll_ratio_first_10s is not None else None,
        has_visual_hook=bool(row.has_visual_hook),
        hook_type=row.hook_type,
        hook_duration_s=float(row.hook_duration_s) if row.hook_duration_s is not None else None,
        caption_style=row.caption_style,
        caption_word_count=int(row.caption_word_count) if row.caption_word_count is not None else None,
        lut_used=row.lut_used,
        color_grade_applied=bool(row.color_grade_applied),
        zoom_punch_applied=bool(row.zoom_punch_applied),
        slowmo_applied=bool(row.slowmo_applied),
        music_present=bool(row.music_present),
        sfx_count=int(row.sfx_count or 0),
        voice_enhancement_applied=bool(row.voice_enhancement_applied),
        creative_quality_score=float(row.creative_quality_score) if row.creative_quality_score is not None else None,
        extracted_at=row.extracted_at,
        extraction_version=row.extraction_version or "1.0",
    )


def _row_to_performance_metrics(row) -> PerformanceMetrics:
    """Convert a DB row to a PerformanceMetrics dataclass."""
    return PerformanceMetrics(
        id=getattr(row, "id", None),
        clip_id=row.clip_id,
        platform=row.platform,
        external_post_id=row.external_post_id,
        views=int(row.views or 0),
        likes=int(row.likes or 0),
        comments=int(row.comments or 0),
        shares=int(row.shares or 0),
        saves=int(row.saves or 0),
        watch_time_s=float(row.watch_time_s) if row.watch_time_s is not None else None,
        avg_watch_pct=float(row.avg_watch_pct) if row.avg_watch_pct is not None else None,
        avg_watch_duration_s=float(row.avg_watch_duration_s) if row.avg_watch_duration_s is not None else None,
        like_rate=float(row.like_rate) if row.like_rate is not None else None,
        comment_rate=float(row.comment_rate) if row.comment_rate is not None else None,
        share_rate=float(row.share_rate) if row.share_rate is not None else None,
        engagement_rate=float(row.engagement_rate) if row.engagement_rate is not None else None,
        ctr=float(row.ctr) if row.ctr is not None else None,
        posted_at=row.posted_at,
        recorded_at=row.recorded_at,
    )


def _row_to_creative_hint(row) -> CreativeHint:
    """Convert a DB row to a CreativeHint dataclass."""
    payload_raw = getattr(row, "payload", {})
    if isinstance(payload_raw, str):
        try:
            payload_raw = json.loads(payload_raw)
        except (json.JSONDecodeError, TypeError):
            payload_raw = {}
    elif payload_raw is None:
        payload_raw = {}

    return CreativeHint(
        id=getattr(row, "id", None),
        workspace_id=row.workspace_id,
        hint_type=row.hint_type,
        pattern=row.pattern,
        metric=row.metric,
        delta=float(row.delta or 0),
        confidence=row.confidence or "medium",
        sample_size=int(row.sample_size or 0),
        payload=payload_raw if isinstance(payload_raw, dict) else {},
        active=bool(row.active),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
