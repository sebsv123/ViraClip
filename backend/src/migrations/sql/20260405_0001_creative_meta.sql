-- Phase 9: persist creative pipeline metadata per clip
ALTER TABLE generated_clips
    ADD COLUMN IF NOT EXISTS creative_meta_json TEXT;
