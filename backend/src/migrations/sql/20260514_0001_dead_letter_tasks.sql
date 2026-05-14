-- Dead-letter tasks table
-- Stores tasks that have exhausted all retry/healing attempts and are permanently dead.
-- This prevents them from being re-enqueued by any mechanism.
-- Admin can view and manually retry them via the /admin/dead-letter endpoint.

CREATE TABLE IF NOT EXISTS dead_letter_tasks (
    id              UUID PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    original_status VARCHAR(50) NOT NULL DEFAULT 'dead',
    error_code      VARCHAR(100) NOT NULL,
    error_message   TEXT,
    source          VARCHAR(50) NOT NULL DEFAULT 'watchdog',  -- 'watchdog' or 'self_healing'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retried_at      TIMESTAMPTZ,
    retried_by      VARCHAR(100),
    UNIQUE(task_id)
);

CREATE INDEX IF NOT EXISTS idx_dead_letter_tasks_created_at
    ON dead_letter_tasks (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_dead_letter_tasks_error_code
    ON dead_letter_tasks (error_code);

CREATE INDEX IF NOT EXISTS idx_dead_letter_tasks_retried
    ON dead_letter_tasks (retried_at)
    WHERE retried_at IS NULL;
