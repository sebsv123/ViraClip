-- Migration: Campaigns table for P5 A/B Performance Engine
-- Created: 2026-03-28

CREATE TABLE IF NOT EXISTS campaigns (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::varchar,
    user_id         VARCHAR(36) NOT NULL,
    name            VARCHAR(200) NOT NULL,
    description     TEXT,
    platform        VARCHAR(50) DEFAULT 'all',
    status          VARCHAR(50) DEFAULT 'active',
    task_ids        TEXT[] DEFAULT '{}',
    ab_test_config  JSONB DEFAULT '{}',
    performance     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_campaigns_user_id ON campaigns (user_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns (status);

-- Tabla de performance analytics por clip
CREATE TABLE IF NOT EXISTS clip_performance (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::varchar,
    clip_id         VARCHAR(36) NOT NULL REFERENCES generated_clips(id) ON DELETE CASCADE,
    campaign_id     VARCHAR(36) REFERENCES campaigns(id) ON DELETE SET NULL,
    platform        VARCHAR(50),
    views           INTEGER DEFAULT 0,
    likes           INTEGER DEFAULT 0,
    shares          INTEGER DEFAULT 0,
    comments        INTEGER DEFAULT 0,
    watch_rate      FLOAT DEFAULT 0,  -- % que ve el clip completo
    user_rating     SMALLINT,          -- Rating manual del usuario (1-5)
    recorded_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_clip_performance_clip_id ON clip_performance (clip_id);

-- Campo de rating en generated_clips para fine-tuning dataset
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS user_rating SMALLINT;

-- Trigger para updated_at
CREATE OR REPLACE FUNCTION update_campaigns_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER campaigns_updated_at
    BEFORE UPDATE ON campaigns
    FOR EACH ROW EXECUTE FUNCTION update_campaigns_updated_at();
