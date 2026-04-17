-- Add multilingual support to tasks and clips
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS target_language VARCHAR(10) DEFAULT 'eng';
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS translated_text TEXT;
