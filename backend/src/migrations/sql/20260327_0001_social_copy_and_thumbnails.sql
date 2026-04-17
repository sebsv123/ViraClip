-- Migration: 20260327_0001 — Add social copy fields and thumbnail to generated_clips
-- Phase 1 (P3 + P4): social_title, social_description, suggested_hashtags, thumbnail_filename

-- Add social copy columns (nullable so existing rows are unaffected)
ALTER TABLE generated_clips
    ADD COLUMN IF NOT EXISTS social_title        VARCHAR(120),
    ADD COLUMN IF NOT EXISTS social_description  VARCHAR(300),
    ADD COLUMN IF NOT EXISTS suggested_hashtags  TEXT[],          -- e.g. ARRAY['#motivation', '#mindset']
    ADD COLUMN IF NOT EXISTS thumbnail_filename  VARCHAR(255),    -- e.g. 'abc123_thumb.jpg'
    ADD COLUMN IF NOT EXISTS face_detected       BOOLEAN;

-- Index thumbnail_filename for quick lookups (cleanup guard etc.)
CREATE INDEX IF NOT EXISTS idx_generated_clips_thumbnail
    ON generated_clips (thumbnail_filename)
    WHERE thumbnail_filename IS NOT NULL;

-- P2.4: Hook preview score (added same session)
ALTER TABLE generated_clips
    ADD COLUMN IF NOT EXISTS hook_preview_score  SMALLINT DEFAULT 0;
