-- Phase 10/11: per-task feature flags for timeline + vision AI opt-in
ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS enable_timeline       BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS enable_vision_ai      BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS enable_timeline_render BOOLEAN NOT NULL DEFAULT false;
