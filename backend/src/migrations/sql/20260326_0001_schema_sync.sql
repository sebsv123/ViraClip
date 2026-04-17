-- Migration: Sync DB schema with application code
-- Adds missing columns that exist in repositories but not in init.sql
-- Safe to run multiple times (uses IF NOT EXISTS / DO NOTHING patterns)

-- sources: add url_secondary for multi-angle support
ALTER TABLE sources ADD COLUMN IF NOT EXISTS url_secondary VARCHAR(1000);

-- tasks: add clip generation options
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS target_language VARCHAR(10) DEFAULT 'eng';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS auto_center_face BOOLEAN DEFAULT false;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS eye_contact_correction BOOLEAN DEFAULT false;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS split_screen BOOLEAN DEFAULT false;

-- generated_clips: add translation and multi-angle metadata
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS translated_text TEXT;
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS multi_angle_metadata TEXT;
