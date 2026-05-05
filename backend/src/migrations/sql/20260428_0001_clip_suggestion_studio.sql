-- Suggestion Studio: per-clip lifecycle + per-suggestion approval rows.
-- Idempotent migration.

ALTER TABLE generated_clips
    ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'final';

CREATE TABLE IF NOT EXISTS clip_suggestions (
    id          VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    clip_id     VARCHAR(36) NOT NULL REFERENCES generated_clips(id) ON DELETE CASCADE,
    kind        VARCHAR(64) NOT NULL,
    category    VARCHAR(32) NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    status      VARCHAR(16) NOT NULL DEFAULT 'pending',
    label       TEXT,
    score       REAL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_clip_suggestions_clip
    ON clip_suggestions (clip_id, category, sort_order);

CREATE INDEX IF NOT EXISTS idx_clip_suggestions_status
    ON clip_suggestions (clip_id, status);
