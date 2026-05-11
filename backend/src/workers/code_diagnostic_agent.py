"""
Code Diagnostic Agent — watches worker logs in real-time, detects known error
patterns, applies automatic fixes, and queues unknown errors for review.

Usage:
    python -m src.workers.code_diagnostic_agent --watch
    python -m src.workers.code_diagnostic_agent --watch --log-file /var/log/worker.log
"""
import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DIAGNOSTIC] %(message)s",
)
logger = logging.getLogger("diagnostic")

# ── Config ──────────────────────────────────────────────────────────────────
REDIS_URL = os.getenv(
    "REDIS_URL",
    f"redis://{os.getenv('REDIS_HOST', 'redis')}:{os.getenv('REDIS_PORT', '6379')}",
)
REPO_ROOT = Path(os.getenv("REPO_ROOT", "/app"))
WORKER_CONTAINER = os.getenv("WATCHDOG_WORKER_CONTAINER", "viraclip-worker")


# ── Data classes ────────────────────────────────────────────────────────────
@dataclass
class Fix:
    """A known error pattern and its automatic fix."""
    pattern: re.Pattern
    description: str
    fix_file: str          # relative path from REPO_ROOT
    fix_search: str        # SEARCH block for replace_in_file
    fix_replace: str       # REPLACE block for replace_in_file
    count: int = 0


@dataclass
class DiagnosticResult:
    """Result of diagnosing a single log line."""
    matched: bool
    fix_applied: bool = False
    fix_name: str = ""
    error_type: str = ""
    context: dict = field(default_factory=dict)


# ── Known error patterns with automatic fixes ───────────────────────────────
KNOWN_FIXES: list[Fix] = [
    Fix(
        pattern=re.compile(r"async_generator.*context manager.*get_db"),
        description="get_db() used as async context manager — replace with AsyncSessionLocal()",
        fix_file="src/workers/tasks.py",
        fix_search="from ..database import get_db\n        async with get_db() as db:",
        fix_replace="from ..database import AsyncSessionLocal\n        async with AsyncSessionLocal() as db:",
    ),
    Fix(
        pattern=re.compile(r"column.*error_message.*does not exist"),
        description="error_message column does not exist — use error_code instead",
        fix_file="src/workers/tasks.py",
        fix_search="error_message = '",
        fix_replace="error_code = '",
    ),
    Fix(
        pattern=re.compile(r"ImportError: cannot import name '(\w+)' from '([\w.]+)'"),
        description="Missing import — log symbol and module for manual review",
        fix_file="",
        fix_search="",
        fix_replace="",
    ),
    Fix(
        pattern=re.compile(r"AttributeError: '(\w+)' object has no attribute '(\w+)'"),
        description="Missing attribute on object — log class and attribute",
        fix_file="",
        fix_search="",
        fix_replace="",
    ),
    Fix(
        pattern=re.compile(r"sqlalchemy.*not attached to a Session"),
        description="Detached SQLAlchemy instance — suggest db.refresh() or lazy load",
        fix_file="",
        fix_search="",
        fix_replace="",
    ),
    Fix(
        pattern=re.compile(r"422 Unprocessable Entity"),
        description="API validation error — extract endpoint and schema",
        fix_file="",
        fix_search="",
        fix_replace="",
    ),
    Fix(
        pattern=re.compile(r"arq\.worker.*ERROR"),
        description="ARQ worker error — extract function and traceback",
        fix_file="",
        fix_search="",
        fix_replace="",
    ),
]


# ── Agent ───────────────────────────────────────────────────────────────────
class CodeDiagnosticAgent:
    """Watches worker logs, diagnoses errors, applies fixes, queues unknowns."""

    def __init__(self, log_source: str = "docker", repo_root: Path = REPO_ROOT):
        self.log_source = log_source
        self.repo_root = repo_root
        self._redis: Any = None
        self._stats: dict[str, int] = {"lines_scanned": 0, "fixes_applied": 0, "unknowns_queued": 0}

    async def _get_redis(self) -> Any:
        if self._redis is None:
            import redis.asyncio as aioredis
            self._redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
        return self._redis

    async def watch(self) -> None:
        """Main loop — tail logs and diagnose each line.

        Reads from a shared log file (LOG_FILE env var), /proc/1/fd/1, or stdin.
        Does NOT use `docker logs` since this runs inside a container.
        """
        logger.info("Starting diagnostic watch")
        logger.info("Registered %d known fix patterns", len(KNOWN_FIXES))

        # Strategy 1: LOG_FILE env var (shared volume)
        log_path = os.getenv("LOG_FILE", "")
        if log_path:
            logger.info("Watching log file: %s", log_path)
            await self._watch_file(log_path)
            return

        # Strategy 2: /proc/1/fd/1 (stdout of PID 1 — the worker process)
        proc_stdout = Path("/proc/1/fd/1")
        if proc_stdout.exists():
            logger.info("Watching /proc/1/fd/1")
            await self._watch_file(str(proc_stdout))
            return

        # Strategy 3: stdin pipe
        logger.info("Watching stdin")
        await self._watch_stdin()

    async def _watch_file(self, path: str) -> None:
        """Tail a file by polling for new lines."""
        import time as _time
        try:
            with open(path, "r") as f:
                f.seek(0, 2)  # seek to end
                while not _shutdown.is_set():
                    line = f.readline()
                    if not line:
                        await asyncio.sleep(0.5)
                        continue
                    line = line.rstrip()
                    if not line:
                        continue
                    await self._process_line(line)
        except FileNotFoundError:
            logger.error("Log file not found: %s", path)
        except Exception as exc:
            logger.error("Error reading log file %s: %s", path, exc)

    async def _watch_stdin(self) -> None:
        """Read lines from stdin."""
        loop = asyncio.get_event_loop()
        while not _shutdown.is_set():
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                await asyncio.sleep(0.5)
                continue
            line = line.rstrip()
            if not line:
                continue
            await self._process_line(line)

    async def _process_line(self, line: str) -> None:
        """Process a single log line through diagnosis."""
        self._stats["lines_scanned"] += 1
        result = await self.diagnose(line)
        if result.matched:
            if result.fix_applied:
                self._stats["fixes_applied"] += 1
                logger.info("[FIX APPLIED] %s — %s", result.fix_name, result.context.get("file", ""))
            elif result.error_type == "unknown":
                self._stats["unknowns_queued"] += 1
                logger.info("[UNKNOWN] Queued for review: %s", line[:120])

        if self._stats["lines_scanned"] % 500 == 0:
            logger.info("[STATS] %s", json.dumps(self._stats))

    async def diagnose(self, log_line: str) -> DiagnosticResult:
        """Match a log line against known patterns and apply fix if possible."""
        for fix in KNOWN_FIXES:
            match = fix.pattern.search(log_line)
            if not match:
                continue

            fix.count += 1
            ctx: dict[str, Any] = {
                "pattern": fix.description,
                "line": log_line[:200],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # If fix has file content, apply it
            if fix.fix_file and fix.fix_search:
                success = await self._apply_fix(fix)
                return DiagnosticResult(
                    matched=True,
                    fix_applied=success,
                    fix_name=fix.description,
                    error_type="known",
                    context={"file": fix.fix_file, **ctx},
                )

            # Pattern without auto-fix — log details
            if "ImportError" in fix.description:
                ctx["symbol"] = match.group(1) if match.lastindex and match.lastindex >= 1 else "?"
                ctx["module"] = match.group(2) if match.lastindex and match.lastindex >= 2 else "?"
            elif "AttributeError" in fix.description:
                ctx["class"] = match.group(1) if match.lastindex and match.lastindex >= 1 else "?"
                ctx["attribute"] = match.group(2) if match.lastindex and match.lastindex >= 2 else "?"

            return DiagnosticResult(
                matched=True,
                fix_applied=False,
                fix_name=fix.description,
                error_type="logged",
                context=ctx,
            )

        # No pattern matched — queue as unknown
        if any(kw in log_line.lower() for kw in ("error", "exception", "traceback", "failed")):
            await self._queue_unknown(log_line)
            return DiagnosticResult(
                matched=True,
                fix_applied=False,
                error_type="unknown",
                context={"line": log_line[:300], "timestamp": datetime.now(timezone.utc).isoformat()},
            )

        return DiagnosticResult(matched=False)

    async def _apply_fix(self, fix: Fix) -> bool:
        """Apply a SEARCH/REPLACE fix to the source file."""
        file_path = self.repo_root / fix.fix_file
        if not file_path.exists():
            logger.warning("Fix file not found: %s", file_path)
            return False

        try:
            content = file_path.read_text(encoding="utf-8")
            if fix.fix_search not in content:
                logger.warning("Fix search pattern not found in %s", fix.fix_file)
                return False

            new_content = content.replace(fix.fix_search, fix.fix_replace)
            if new_content == content:
                return False

            file_path.write_text(new_content, encoding="utf-8")
            logger.info("✅ Fix applied to %s: %s", fix.fix_file, fix.description)
            return True
        except Exception as exc:
            logger.error("Failed to apply fix to %s: %s", fix.fix_file, exc)
            return False

    async def _queue_unknown(self, log_line: str) -> None:
        """Queue an unknown error in Redis for later review."""
        try:
            r = await self._get_redis()
            payload = json.dumps({
                "line": log_line[:500],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": self.log_source,
            })
            await r.lpush("diagnostic:unknown_errors", payload)
            await r.ltrim("diagnostic:unknown_errors", 0, 999)  # keep last 1000
        except Exception as exc:
            logger.debug("Failed to queue unknown error: %s", exc)


# ── CLI ─────────────────────────────────────────────────────────────────────
async def main() -> None:
    parser = argparse.ArgumentParser(description="Code Diagnostic Agent")
    parser.add_argument("--watch", action="store_true", help="Watch logs in real-time")
    parser.add_argument("--log-file", type=str, default="", help="Path to log file (instead of docker)")
    parser.add_argument("--one-shot", type=str, default="", help="Diagnose a single log line and exit")
    args = parser.parse_args()

    agent = CodeDiagnosticAgent(
        log_source="file" if args.log_file else "docker",
        repo_root=REPO_ROOT,
    )

    if args.one_shot:
        result = await agent.diagnose(args.one_shot)
        print(json.dumps({
            "matched": result.matched,
            "fix_applied": result.fix_applied,
            "fix_name": result.fix_name,
            "error_type": result.error_type,
            "context": result.context,
        }, indent=2))
        return

    if args.watch:
        await agent.watch()
        return

    parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
