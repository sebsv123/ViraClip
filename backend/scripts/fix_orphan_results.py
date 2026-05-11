"""
Fix orphan ARQ results — tasks stuck in "queued"/"processing" that already
have a result in Redis but the DB callback never executed.

Supports --dry-run flag to simulate without writing changes.

Usage:
    cd /home/_sebastian/CascadeProjects/ViraClip/backend
    .venv/bin/python scripts/fix_orphan_results.py
    .venv/bin/python scripts/fix_orphan_results.py --dry-run
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone

import asyncpg

# ── Config ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://viraclip:viraclip_password@localhost:5432/viraclip",
)
REDIS_URL = os.getenv(
    "REDIS_URL",
    os.getenv("REDIS_HOST", "redis://localhost:6379"),
)

if DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("fix_orphan")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Fix orphan ARQ results")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without writing changes")
    args = parser.parse_args()
    dry_run = args.dry_run

    if dry_run:
        logger.info("🔷 DRY RUN mode — no changes will be written")

    # ── Connect to Redis ───────────────────────────────────────────────────
    try:
        import redis.asyncio as aioredis
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        await r.ping()
        logger.info("✅ Connected to Redis at %s", REDIS_URL)
    except Exception as exc:
        logger.error("❌ Redis connection failed: %s", exc)
        sys.exit(1)

    # ── Connect to PostgreSQL ──────────────────────────────────────────────
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        logger.info("✅ Connected to PostgreSQL")
    except Exception as exc:
        logger.error("❌ PostgreSQL connection failed: %s", exc)
        sys.exit(1)

    # ── Scan all arq:result:* keys ─────────────────────────────────────────
    cursor = 0
    result_keys: list[str] = []
    while True:
        cursor, keys = await r.scan(cursor=cursor, match="arq:result:*", count=500)
        result_keys.extend(keys)
        if cursor == 0:
            break

    logger.info("🔍 Found %d arq:result:* keys in Redis", len(result_keys))

    fixed = 0
    skipped = 0
    errors = 0
    details: list[str] = []

    for key in result_keys:
        try:
            raw = await r.get(key)
            if not raw:
                continue

            result_data = json.loads(raw)
            job_id = key.split("arq:result:", 1)[-1]

            # ── Find task by job_id ────────────────────────────────────────
            # job_id may be the task.id directly, or stored in metadata JSONB
            row = await conn.fetchrow(
                "SELECT id, status, error_message, metadata FROM tasks WHERE id = $1",
                job_id,
            )

            # If not found by id, try searching in metadata->>'job_id'
            if not row:
                row = await conn.fetchrow(
                    "SELECT id, status, error_message FROM tasks WHERE metadata->>'job_id' = $1",
                    job_id,
                )

            if not row:
                details.append(f"  ⏭️  No task found for job {job_id[:12]}")
                skipped += 1
                continue

            task_id = row["id"]
            status = row["status"]

            if status not in ("queued", "processing"):
                details.append(f"  ⏭️  Task {str(task_id)[:12]} status={status}")
                skipped += 1
                continue

            # ── Determine error message ────────────────────────────────────
            success = result_data.get("success", False)
            redis_error = result_data.get("error") or result_data.get("result")

            if success:
                error_msg = "Task processed by ARQ but DB callback was lost (E_RESULT_ORPHAN)"
                error_code = "E_RESULT_ORPHAN"
            else:
                error_msg = str(redis_error or "Unknown ARQ error (E_RESULT_ORPHAN)")
                error_code = "E_RESULT_ORPHAN"

            # ── Update task ────────────────────────────────────────────────
            now = datetime.now(timezone.utc)
            if dry_run:
                details.append(
                    f"  🔷 WOULD FIX task {str(task_id)[:12]} (was {status}) → failed | {error_msg[:80]}"
                )
            else:
                await conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'failed',
                        error_message = $1,
                        error_code = $2,
                        updated_at = $3
                    WHERE id = $4
                    """,
                    error_msg[:500],
                    error_code,
                    now,
                    task_id,
                )
                details.append(
                    f"  ✅ Fixed task {str(task_id)[:12]} (was {status}) → failed | {error_msg[:80]}"
                )
            fixed += 1

        except Exception as exc:
            logger.warning("  ❌ Error processing key %s: %s", key, exc)
            errors += 1

    # ── Cleanup ────────────────────────────────────────────────────────────
    await r.aclose()
    await conn.close()

    logger.info("=" * 50)
    for d in details:
        logger.info(d)
    logger.info("=" * 50)
    logger.info("📊 Summary: fixed=%d  skipped=%d  errors=%d  dry_run=%s", fixed, skipped, errors, dry_run)
    logger.info("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
