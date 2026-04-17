-- Migration: Add batch_id to tasks table for P3.4 batch processing
-- Created: 2026-03-27

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS batch_id VARCHAR(36);

CREATE INDEX IF NOT EXISTS idx_tasks_batch_id
    ON tasks (batch_id)
    WHERE batch_id IS NOT NULL;
