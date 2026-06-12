-- Add context column to tasks table
ALTER TABLE "tasks" ADD COLUMN IF NOT EXISTS "context" JSONB;
