#!/bin/bash
# Rebuild Watcher — polls Redis for rebuild_needed flag and triggers docker compose rebuild.
# Run on the HOST (not inside container):
#   chmod +x backend/src/services/rebuild_watcher.sh
#   nohup bash backend/src/services/rebuild_watcher.sh > /tmp/rebuild_watcher.log 2>&1 &
#   echo $! > /tmp/rebuild_watcher.pid

REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
PROJECT_DIR="/home/_sebastian/CascadeProjects/ViraClip"
POLL_INTERVAL=15

echo "[REBUILD-WATCHER] Starting (poll every ${POLL_INTERVAL}s, Redis=${REDIS_HOST}:${REDIS_PORT})"

while true; do
  FLAG=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" get self_healing:rebuild_needed 2>/dev/null)
  if [ -n "$FLAG" ] && [ "$FLAG" != "0" ]; then
    echo "[REBUILD-WATCHER] $(date) — Rebuild triggered by self-healing agent"
    echo "[REBUILD-WATCHER] Patched files: $FLAG"

    # Clear flag immediately to prevent double rebuilds
    redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" del self_healing:rebuild_needed > /dev/null 2>&1

    cd "$PROJECT_DIR" || { echo "[REBUILD-WATCHER] ERROR: project dir not found"; sleep $POLL_INTERVAL; continue; }

    echo "[REBUILD-WATCHER] Building worker..."
    docker compose build worker --no-cache 2>&1 | tail -5
    echo "[REBUILD-WATCHER] Building backend..."
    docker compose build backend --no-cache 2>&1 | tail -5

    echo "[REBUILD-WATCHER] Restarting services..."
    docker compose up -d worker backend 2>&1

    echo "[REBUILD-WATCHER] $(date) — Rebuild complete"
  fi
  sleep $POLL_INTERVAL
done
