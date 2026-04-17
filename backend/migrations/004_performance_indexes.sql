-- Migration: Add performance indexes for scalability
-- Purpose: Optimize common queries for better performance at scale
-- Date: 2026-03-30

-- ============================================================================
-- TASKS TABLE INDEXES
-- ============================================================================

-- Index for filtering by user_id (most common query)
CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id);

-- Index for filtering by status (dashboard, monitoring)
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

-- Composite index for user's tasks by status (very common)
CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON tasks(user_id, status);

-- Index for recent tasks (ordered by created_at DESC)
CREATE INDEX IF NOT EXISTS idx_tasks_created_desc ON tasks(created_at DESC);

-- Composite index for user's recent tasks
CREATE INDEX IF NOT EXISTS idx_tasks_user_created ON tasks(user_id, created_at DESC);

-- Index for failed tasks monitoring
CREATE INDEX IF NOT EXISTS idx_tasks_failed ON tasks(status, error_code) WHERE status = 'failed';

-- Partial index for active tasks (queued or processing)
CREATE INDEX IF NOT EXISTS idx_tasks_active ON tasks(created_at DESC) 
WHERE status IN ('queued', 'processing');

-- ============================================================================
-- GENERATED_CLIPS TABLE INDEXES
-- ============================================================================

-- Index for finding clips by task_id (most common join)
CREATE INDEX IF NOT EXISTS idx_clips_task_id ON generated_clips(task_id);

-- Index for sorting clips by virality score
CREATE INDEX IF NOT EXISTS idx_clips_virality ON generated_clips(virality_score DESC NULLS LAST);

-- Composite index for task's clips by score
CREATE INDEX IF NOT EXISTS idx_clips_task_virality ON generated_clips(task_id, virality_score DESC);

-- Index for finding clips by filename (download/serve)
CREATE INDEX IF NOT EXISTS idx_clips_filename ON generated_clips(filename);

-- Index for clips duration filtering
CREATE INDEX IF NOT EXISTS idx_clips_duration ON generated_clips(duration);

-- ============================================================================
-- USERS TABLE INDEXES
-- ============================================================================

-- Index for email lookup (login, password reset)
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Index for active users
CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active) WHERE is_active = true;

-- Index for user creation date (analytics)
CREATE INDEX IF NOT EXISTS idx_users_created ON users(created_at DESC);

-- ============================================================================
-- QUERY OPTIMIZATION HINTS
-- ============================================================================

-- Analyze tables to update statistics for query planner
ANALYZE tasks;
ANALYZE generated_clips;
ANALYZE users;

-- Create comments for documentation
COMMENT ON INDEX idx_tasks_user_status IS 'Optimizes user task list queries with status filter';
COMMENT ON INDEX idx_tasks_active IS 'Partial index for monitoring active/in-progress tasks';
COMMENT ON INDEX idx_clips_task_virality IS 'Optimizes fetching top viral clips for a task';

-- ============================================================================
-- MATERIALIZED VIEW FOR ANALYTICS (Optional - for high-traffic scenarios)
-- ============================================================================

-- Materialized view for task statistics (refresh periodically)
CREATE MATERIALIZED VIEW IF NOT EXISTS task_stats_daily AS
SELECT 
    DATE(created_at) as date,
    COUNT(*) as total_tasks,
    COUNT(*) FILTER (WHERE status = 'completed') as completed,
    COUNT(*) FILTER (WHERE status = 'failed') as failed,
    AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) as avg_duration_seconds
FROM tasks
WHERE created_at > NOW() - INTERVAL '90 days'
GROUP BY DATE(created_at)
ORDER BY date DESC;

-- Index on materialized view
CREATE INDEX IF NOT EXISTS idx_task_stats_date ON task_stats_daily(date DESC);

-- Refresh command (run daily via cron or scheduled job):
-- REFRESH MATERIALIZED VIEW CONCURRENTLY task_stats_daily;

COMMENT ON MATERIALIZED VIEW task_stats_daily IS 
'Daily task statistics. Refresh with: REFRESH MATERIALIZED VIEW CONCURRENTLY task_stats_daily';
