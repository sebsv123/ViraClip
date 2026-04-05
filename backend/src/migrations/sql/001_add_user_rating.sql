-- Migration 001: Add user_rating column to generated_clips
-- Feature C: per-clip user feedback (1-5 stars, nullable)
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS user_rating SMALLINT;
