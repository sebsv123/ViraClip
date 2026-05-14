-- ============================================================================
-- Cleanup stuck tasks that are in infinite loop
-- Task IDs: 89d18603-7047-4503-a169-f11029221cc1
--           886bf921-c6da-401d-8c58-e13db50d396a
-- ============================================================================
-- These tasks are stuck in an infinite loop because:
-- 1. They are in the Redis queue (arq sorted set)
-- 2. The worker picks them up, tries to process, fails with "status is not queued"
-- 3. The self-healing agent picks them up, marks SELF_HEALING_EXHAUSTED
-- 4. But they stay in Redis queue, so the cycle repeats
--
-- This script marks them as permanently failed in PostgreSQL.
-- Run the companion cleanup_stuck_tasks.sh to also clean Redis.
-- ============================================================================

BEGIN;

-- Mark task 1 as permanently failed
UPDATE tasks
SET status = 'failed',
    error_code = 'SELF_HEALING_EXHAUSTED',
    state_reason = 'self_healing_exhausted',
    error_message = 'Task manually cleaned up — was stuck in infinite loop (self-healing + Redis queue)',
    updated_at = NOW()
WHERE id = '89d18603-7047-4503-a169-f11029221cc1'
  AND status IN ('failed', 'queued', 'processing');

-- Mark task 2 as permanently failed
UPDATE tasks
SET status = 'failed',
    error_code = 'SELF_HEALING_EXHAUSTED',
    state_reason = 'self_healing_exhausted',
    error_message = 'Task manually cleaned up — was stuck in infinite loop (self-healing + Redis queue)',
    updated_at = NOW()
WHERE id = '886bf921-c6da-401d-8c58-e13db50d396a'
  AND status IN ('failed', 'queued', 'processing');

COMMIT;

-- Verify
SELECT id, status, error_code, state_reason, updated_at
FROM tasks
WHERE id IN ('89d18603-7047-4503-a169-f11029221cc1', '886bf921-c6da-401d-8c58-e13db50d396a');
