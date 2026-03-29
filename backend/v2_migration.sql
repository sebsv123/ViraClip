-- ViraClip V2 Migration Script
-- Adds support for Multi-Angle Intelligence and AI Image Generation

-- 1. Update sources table for dual-input
ALTER TABLE sources ADD COLUMN IF NOT EXISTS url_secondary VARCHAR(1000);

-- 2. Update tasks table for MAI metadata
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS secondary_source_id VARCHAR(36) REFERENCES sources(id) ON DELETE SET NULL;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS audio_sync_offset FLOAT DEFAULT 0.0;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS image_gen_enabled BOOLEAN DEFAULT false;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS image_gen_config JSONB;

-- 3. Update generated_clips for multi-angle flags
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS multi_angle_metadata JSONB;

-- 4. Create AI Assets table
CREATE TABLE IF NOT EXISTS ai_assets (
    id VARCHAR(36) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    task_id VARCHAR(36) NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    prompt TEXT NOT NULL,
    provider VARCHAR(50) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    asset_type VARCHAR(20) DEFAULT 'image', -- 'image', 'sticker', 'broll'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexing for performance
CREATE INDEX IF NOT EXISTS idx_ai_assets_task_id ON ai_assets(task_id);
