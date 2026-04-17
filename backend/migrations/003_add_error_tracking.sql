-- Migration: Add error tracking columns to tasks table
-- Purpose: Store error codes and messages for better debugging and metrics
-- Date: 2026-03-30

-- Add error tracking columns
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS error_code VARCHAR(10);
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS error_message TEXT;

-- Add index for efficient error queries
CREATE INDEX IF NOT EXISTS idx_tasks_error_code ON tasks(error_code) WHERE error_code IS NOT NULL;

-- Add comment for documentation
COMMENT ON COLUMN tasks.error_code IS 'Error code from ViraClip exception system (E1xxx-E9xxx)';
COMMENT ON COLUMN tasks.error_message IS 'Human-readable error message';
