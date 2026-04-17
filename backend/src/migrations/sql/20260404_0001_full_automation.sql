-- Migration: Full Automation Support
-- Adds columns for auto-upload, analytics, A/B testing, and scheduling

-- Add platform OAuth credentials to users
ALTER TABLE users ADD COLUMN IF NOT EXISTS youtube_credentials TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS tiktok_credentials TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS instagram_credentials TEXT;

-- Add notification preferences to users
ALTER TABLE users ADD COLUMN IF NOT EXISTS slack_webhook_url VARCHAR(500);
ALTER TABLE users ADD COLUMN IF NOT EXISTS discord_webhook_url VARCHAR(500);
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_notifications BOOLEAN NOT NULL DEFAULT TRUE;

-- Add viral metadata and thumbnail to generated_clips
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS clip_metadata TEXT;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS thumbnail_path VARCHAR(500);

-- Add platform publishing tracking
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS youtube_video_id VARCHAR(50);
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS tiktok_video_id VARCHAR(50);
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS instagram_media_id VARCHAR(50);

-- Add YouTube analytics metrics
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS youtube_views INTEGER DEFAULT 0;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS youtube_likes INTEGER DEFAULT 0;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS youtube_comments INTEGER DEFAULT 0;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS youtube_watch_time FLOAT;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS youtube_ctr FLOAT;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS youtube_engagement_rate FLOAT;

-- Add TikTok analytics metrics
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS tiktok_views INTEGER DEFAULT 0;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS tiktok_likes INTEGER DEFAULT 0;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS tiktok_comments INTEGER DEFAULT 0;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS tiktok_shares INTEGER DEFAULT 0;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS tiktok_completion_rate FLOAT;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS tiktok_engagement_rate FLOAT;

-- Add Instagram analytics metrics
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS instagram_impressions INTEGER DEFAULT 0;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS instagram_reach INTEGER DEFAULT 0;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS instagram_engagement INTEGER DEFAULT 0;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS instagram_likes INTEGER DEFAULT 0;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS instagram_comments INTEGER DEFAULT 0;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS instagram_shares INTEGER DEFAULT 0;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS instagram_saves INTEGER DEFAULT 0;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS instagram_engagement_rate FLOAT;

-- Add metrics tracking
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS metrics_last_updated TIMESTAMP WITH TIME ZONE;

-- Add A/B testing tracking
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS ab_test_id VARCHAR(36);
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS ab_variant VARCHAR(50);

-- Create index for fast analytics queries
CREATE INDEX IF NOT EXISTS idx_clips_youtube_id ON generated_clips(youtube_video_id) WHERE youtube_video_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_clips_tiktok_id ON generated_clips(tiktok_video_id) WHERE tiktok_video_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_clips_instagram_id ON generated_clips(instagram_media_id) WHERE instagram_media_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_clips_ab_test ON generated_clips(ab_test_id) WHERE ab_test_id IS NOT NULL;

-- Create table for scheduled jobs (persisted in Redis but backup here)
CREATE TABLE IF NOT EXISTS scheduled_jobs (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    trigger_type VARCHAR(50) NOT NULL,
    frequency VARCHAR(50),
    cron_expression VARCHAR(100),
    source_config JSONB NOT NULL,
    processing_config JSONB NOT NULL,
    publish_config JSONB NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_run TIMESTAMP WITH TIME ZONE,
    next_run TIMESTAMP WITH TIME ZONE,
    run_count INTEGER DEFAULT 0,
    total_clips_generated INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_user ON scheduled_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_next_run ON scheduled_jobs(next_run) WHERE is_active = TRUE;

-- Create table for A/B tests
CREATE TABLE IF NOT EXISTS ab_tests (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    original_clip_id VARCHAR(36) NOT NULL REFERENCES generated_clips(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'created',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    test_duration_hours INTEGER NOT NULL DEFAULT 24,
    winner_variant_id VARCHAR(36),
    confidence_level FLOAT,
    test_accounts JSONB,
    variants JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ab_tests_user ON ab_tests(user_id);
CREATE INDEX IF NOT EXISTS idx_ab_tests_status ON ab_tests(status);

-- Create table for trend triggers
CREATE TABLE IF NOT EXISTS trend_triggers (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    keywords JSONB NOT NULL,
    min_virality_score FLOAT NOT NULL DEFAULT 70.0,
    processing_config JSONB NOT NULL,
    publish_config JSONB NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_triggered_at TIMESTAMP WITH TIME ZONE,
    trigger_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_trend_triggers_user ON trend_triggers(user_id);

-- Create table for platform analytics sync log
CREATE TABLE IF NOT EXISTS analytics_sync_log (
    id SERIAL PRIMARY KEY,
    clip_id VARCHAR(36) NOT NULL REFERENCES generated_clips(id) ON DELETE CASCADE,
    platform VARCHAR(50) NOT NULL,
    sync_time TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    success BOOLEAN NOT NULL,
    error_message TEXT,
    views_before INTEGER,
    views_after INTEGER,
    engagement_rate_before FLOAT,
    engagement_rate_after FLOAT
);

CREATE INDEX IF NOT EXISTS idx_analytics_sync_clip ON analytics_sync_log(clip_id);
CREATE INDEX IF NOT EXISTS idx_analytics_sync_time ON analytics_sync_log(sync_time);

-- Add notification log
CREATE TABLE IF NOT EXISTS notification_log (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type VARCHAR(100) NOT NULL,
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    data JSONB,
    channels JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    sent BOOLEAN NOT NULL DEFAULT FALSE,
    read_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_notifications_user ON notification_log(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notification_log(user_id, read_at) WHERE read_at IS NULL;

-- Migration complete
SELECT 'Full automation migration complete' AS status;
