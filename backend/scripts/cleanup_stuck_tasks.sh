#!/bin/bash
# ============================================================================
# Cleanup stuck tasks — PostgreSQL + Redis
# Task IDs: 89d18603-7047-4503-a169-f11029221cc1
#           886bf921-c6da-401d-8c58-e13db50d396a
# ============================================================================
# This script:
# 1. Marks the tasks as permanently failed in PostgreSQL
# 2. Removes them from the Redis arq job queue
# 3. Cleans up any dead letter queue entries
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── Load environment ─────────────────────────────────────────────────────────
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# ── Configuration ───────────────────────────────────────────────────────────
DB_URL="${DATABASE_URL:-postgresql://viraclip:viraclip_password@postgres:5432/viraclip}"
# Strip asyncpg prefix if present
DB_URL="${DB_URL/postgresql+asyncpg:\/\//postgresql:\/\/}"

REDIS_HOST="${REDIS_HOST:-redis}"
REDIS_PORT="${REDIS_PORT:-6379}"

TASK_1="89d18603-7047-4503-a169-f11029221cc1"
TASK_2="886bf921-c6da-401d-8c58-e13db50d396a"

echo "============================================"
echo " Cleanup stuck tasks"
echo "============================================"
echo "DB URL:    $DB_URL"
echo "Redis:     ${REDIS_HOST}:${REDIS_PORT}"
echo "Task 1:    $TASK_1"
echo "Task 2:    $TASK_2"
echo ""

# ── Step 1: PostgreSQL cleanup ──────────────────────────────────────────────
echo "▶ Step 1: Updating PostgreSQL..."
psql "$DB_URL" <<SQL
BEGIN;

UPDATE tasks
SET status = 'failed',
    error_code = 'SELF_HEALING_EXHAUSTED',
    state_reason = 'self_healing_exhausted',
    error_message = 'Task manually cleaned up — was stuck in infinite loop (self-healing + Redis queue)',
    updated_at = NOW()
WHERE id = '$TASK_1'
  AND status IN ('failed', 'queued', 'processing');

UPDATE tasks
SET status = 'failed',
    error_code = 'SELF_HEALING_EXHAUSTED',
    state_reason = 'self_healing_exhausted',
    error_message = 'Task manually cleaned up — was stuck in infinite loop (self-healing + Redis queue)',
    updated_at = NOW()
WHERE id = '$TASK_2'
  AND status IN ('failed', 'queued', 'processing');

COMMIT;

SELECT id, status, error_code, state_reason, updated_at
FROM tasks
WHERE id IN ('$TASK_1', '$TASK_2');
SQL

echo "✅ PostgreSQL updated"
echo ""

# ── Step 2: Redis cleanup ───────────────────────────────────────────────────
echo "▶ Step 2: Cleaning up Redis..."

QUEUE_KEY="arq:queue:viraclip_cpu_tasks"

for TASK_ID in "$TASK_1" "$TASK_2"; do
    echo "  Cleaning task $TASK_ID ..."

    # Remove from arq job queue (sorted set)
    REMOVED=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" zrem "$QUEUE_KEY" "$TASK_ID")
    if [ "$REMOVED" = "1" ]; then
        echo "    ✓ Removed from queue $QUEUE_KEY"
    else
        echo "    - Not found in queue $QUEUE_KEY"
    fi

    # Remove arq job key
    DEL_JOB=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" del "arq:job:${TASK_ID}")
    if [ "$DEL_JOB" != "0" ]; then
        echo "    ✓ Removed arq:job:${TASK_ID}"
    else
        echo "    - No arq:job key found"
    fi

    # Remove from dead letter set
    SREM_DL=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" srem "tasks:dead_letter" "$TASK_ID")
    if [ "$SREM_DL" = "1" ]; then
        echo "    ✓ Removed from tasks:dead_letter set"
    else
        echo "    - Not in tasks:dead_letter set"
    fi

    # Remove dead letter payload
    DEL_DL=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" del "dead_letter:${TASK_ID}")
    if [ "$DEL_DL" != "0" ]; then
        echo "    ✓ Removed dead_letter:${TASK_ID}"
    else
        echo "    - No dead_letter key found"
    fi

    # Remove any task source cache
    DEL_SRC=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" del "task_source:${TASK_ID}")
    if [ "$DEL_SRC" != "0" ]; then
        echo "    ✓ Removed task_source:${TASK_ID}"
    fi

    # Remove any cancel flag
    DEL_CANCEL=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" del "task_cancel:${TASK_ID}")
    if [ "$DEL_CANCEL" != "0" ]; then
        echo "    ✓ Removed task_cancel:${TASK_ID}"
    fi

    echo ""
done

echo "✅ Redis cleaned up"
echo ""

# ── Step 3: Verify ──────────────────────────────────────────────────────────
echo "▶ Step 3: Verification..."
echo ""
echo "--- PostgreSQL ---"
psql "$DB_URL" -c "
SELECT id, status, error_code, state_reason, updated_at
FROM tasks
WHERE id IN ('$TASK_1', '$TASK_2');
"

echo ""
echo "--- Redis queue ---"
for TASK_ID in "$TASK_1" "$TASK_2"; do
    IN_QUEUE=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" zrank "$QUEUE_KEY" "$TASK_ID")
    if [ "$IN_QUEUE" = "" ]; then
        echo "  Task $TASK_ID: NOT in Redis queue ✓"
    else
        echo "  ⚠ Task $TASK_ID: STILL in Redis queue at rank $IN_QUEUE"
    fi
done

echo ""
echo "============================================"
echo " Cleanup complete!"
echo "============================================"
