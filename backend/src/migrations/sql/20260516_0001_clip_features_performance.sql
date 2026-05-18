-- Clip Features & Performance Metrics
-- Stores extracted features from each generated clip and real-world performance data.
-- Idempotent migration.

-- ── Clip Features ──────────────────────────────────────────────────────────────
-- Captures the creative/technical characteristics of each clip for later analysis.
CREATE TABLE IF NOT EXISTS clip_features (
    id              VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    clip_id         VARCHAR(36) NOT NULL REFERENCES generated_clips(id) ON DELETE CASCADE,

    -- Temporal
    duration_s      REAL NOT NULL DEFAULT 0,
    fps             REAL,

    -- Editing structure
    num_cuts        INTEGER NOT NULL DEFAULT 0,
    num_brolls      INTEGER NOT NULL DEFAULT 0,
    talking_head_ratio REAL,          -- 0.0 (no talking head) to 1.0 (full talking head)
    cut_density     REAL,             -- cuts per second

    -- B-roll distribution
    broll_ratio_first_10s REAL,       -- fraction of first 10s covered by B-roll

    -- Hook
    has_visual_hook     BOOLEAN NOT NULL DEFAULT FALSE,
    hook_type           VARCHAR(64),  -- "question", "statistic", "story", "provocative", etc.
    hook_duration_s     REAL,         -- seconds from start to hook completion

    -- Caption style
    caption_style       VARCHAR(64),  -- "tiktok_auto", "lower_third", "karaoke", "none"
    caption_word_count  INTEGER,

    -- Visual treatment
    lut_used            VARCHAR(128),
    color_grade_applied BOOLEAN NOT NULL DEFAULT FALSE,
    zoom_punch_applied  BOOLEAN NOT NULL DEFAULT FALSE,
    slowmo_applied      BOOLEAN NOT NULL DEFAULT FALSE,

    -- Audio
    music_present       BOOLEAN NOT NULL DEFAULT FALSE,
    sfx_count           INTEGER NOT NULL DEFAULT 0,
    voice_enhancement_applied BOOLEAN NOT NULL DEFAULT FALSE,

    -- Derived
    creative_quality_score REAL,      -- 0-100 aggregate from creative pipeline

    -- Metadata
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    extraction_version  VARCHAR(16) NOT NULL DEFAULT '1.0',

    UNIQUE(clip_id)
);

CREATE INDEX IF NOT EXISTS idx_clip_features_clip
    ON clip_features (clip_id);

CREATE INDEX IF NOT EXISTS idx_clip_features_hook_type
    ON clip_features (hook_type);

CREATE INDEX IF NOT EXISTS idx_clip_features_caption_style
    ON clip_features (caption_style);

-- ── Clip Performance Metrics ───────────────────────────────────────────────────
-- Real-world performance data imported from external platforms.
CREATE TABLE IF NOT EXISTS clip_performance_metrics (
    id              VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    clip_id         VARCHAR(36) NOT NULL REFERENCES generated_clips(id) ON DELETE CASCADE,

    -- Platform identification
    platform        VARCHAR(32) NOT NULL,  -- "tiktok", "instagram", "youtube_shorts", "twitter", etc.
    external_post_id VARCHAR(256),         -- ID on the external platform

    -- Core metrics
    views           INTEGER NOT NULL DEFAULT 0,
    likes           INTEGER NOT NULL DEFAULT 0,
    comments        INTEGER NOT NULL DEFAULT 0,
    shares          INTEGER NOT NULL DEFAULT 0,
    saves           INTEGER NOT NULL DEFAULT 0,

    -- Watch time / retention
    watch_time_s    REAL,                 -- total watch time in seconds
    avg_watch_pct   REAL,                 -- average watch percentage (0.0 to 1.0)
    avg_watch_duration_s REAL,            -- average watch duration in seconds

    -- Engagement rates (computed)
    like_rate       REAL,                 -- likes / views
    comment_rate    REAL,                 -- comments / views
    share_rate      REAL,                 -- shares / views
    engagement_rate REAL,                 -- (likes + comments + shares + saves) / views

    -- CTR (click-through rate, if applicable)
    ctr             REAL,                 -- 0.0 to 1.0

    -- Timing
    posted_at       TIMESTAMPTZ,          -- when the clip was posted on the platform
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(clip_id, platform)
);

CREATE INDEX IF NOT EXISTS idx_clip_perf_metrics_clip
    ON clip_performance_metrics (clip_id);

CREATE INDEX IF NOT EXISTS idx_clip_perf_metrics_platform
    ON clip_performance_metrics (platform);

CREATE INDEX IF NOT EXISTS idx_clip_perf_metrics_recorded_at
    ON clip_performance_metrics (recorded_at DESC);

-- ── Creative Hints ─────────────────────────────────────────────────────────────
-- Stores computed recommendations derived from analyzing clip features + performance.
-- These hints are consumed by the creative pipeline to adjust parameters.
CREATE TABLE IF NOT EXISTS creative_hints (
    id              VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    workspace_id    VARCHAR(36) NOT NULL,  -- user or channel scope
    hint_type       VARCHAR(64) NOT NULL,  -- "hook", "broll", "duration", "caption_style", "pacing", etc.
    pattern         TEXT NOT NULL,         -- human-readable description of the pattern found
    metric          VARCHAR(64) NOT NULL,  -- "avg_watch_pct", "engagement_rate", "views", etc.
    delta           REAL NOT NULL,         -- the measured improvement (e.g., +0.15 for +15%)
    confidence      VARCHAR(16) NOT NULL DEFAULT 'medium',  -- "low", "medium", "high"
    sample_size     INTEGER NOT NULL DEFAULT 0,  -- number of clips supporting this hint
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,  -- structured data for pipeline consumption
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(workspace_id, hint_type, pattern)
);

CREATE INDEX IF NOT EXISTS idx_creative_hints_workspace
    ON creative_hints (workspace_id, active);

CREATE INDEX IF NOT EXISTS idx_creative_hints_type
    ON creative_hints (workspace_id, hint_type, active);
