"""
CodePatcher — applies fixes to source files and tracks pending rebuilds.

Each patch is saved to /app/src/patches/patch_{timestamp}.json for traceability.
Pending rebuilds are tracked in Redis under "self_healing:rebuild_needed".

Safety:
  - Only patches files in whitelisted directories (domains/video/, domains/ai/, services/, ai.py)
  - Blocks critical files (database.py, models.py, tasks.py, config.py, migrations/)
  - Validates syntax with py_compile before writing
  - Creates backup before applying patch
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .error_diagnostician import ErrorDiagnosis

logger = logging.getLogger("code_patcher")

REPO_ROOT = Path(os.getenv("REPO_ROOT", "/app"))
PATCHES_DIR = REPO_ROOT / "src" / "patches"
REDIS_URL = os.getenv("REDIS_URL", f"redis://{os.getenv('REDIS_HOST', 'redis')}:{os.getenv('REDIS_PORT', '6379')}")


class CodePatcher:
    """Applies fixes to source files and tracks pending rebuilds."""

    # ── Whitelist: only auto-patch these directories ────────────────────────
    ALLOWED_PREFIXES = (
        "domains/video/",
        "domains/ai/",
        "services/",
        "ai.py",
    )
    BLOCKED_FILES = (
        "database.py",
        "models.py",
        "tasks.py",
        "config.py",
        "self_healing_agent.py",
        "code_patcher.py",
        "error_diagnostician.py",
    )
    BLOCKED_DIRS = ("migrations/",)

    @classmethod
    def _is_allowed(cls, file_path: str) -> bool:
        """Check if a file is safe to auto-patch."""
        for blocked in cls.BLOCKED_FILES:
            if file_path.endswith(blocked):
                return False
        for blocked_dir in cls.BLOCKED_DIRS:
            if blocked_dir in file_path:
                return False
        for prefix in cls.ALLOWED_PREFIXES:
            if file_path.startswith(prefix) or file_path == prefix:
                return True
        return False

    @staticmethod
    async def _get_redis():
        import redis.asyncio as aioredis
        return await aioredis.from_url(REDIS_URL, decode_responses=True)

    @classmethod
    async def apply_fix(cls, diagnosis: ErrorDiagnosis) -> bool:
        """Apply a code fix based on diagnosis. Returns True if patch was applied."""
        if not diagnosis.fix_code or not diagnosis.file_path:
            logger.warning("No fix code or file path in diagnosis")
            return False

        # ── Whitelist check ────────────────────────────────────────────────
        if not cls._is_allowed(diagnosis.file_path):
            logger.warning(
                "[CODE-PATCHER] ⚠️ Fix blocked — critical file: %s. "
                "Task needs human review.",
                diagnosis.file_path,
            )
            return False

        file_path = REPO_ROOT / diagnosis.file_path
        if not file_path.exists():
            logger.warning("File not found: %s", file_path)
            return False

        # Parse fix_code: extract BEFORE and AFTER sections
        before, after = cls._parse_fix_code(diagnosis.fix_code)
        if not before or not after:
            logger.warning("Could not parse fix_code for %s", diagnosis.error_type)
            return False

        # Read file
        content = file_path.read_text(encoding="utf-8")
        if before not in content:
            logger.warning("Search pattern not found in %s", file_path)
            return False

        # Apply patch
        new_content = content.replace(before, after)
        if new_content == content:
            return False

        # ── Syntax validation ──────────────────────────────────────────────
        import py_compile
        import tempfile
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False)
            tmp.write(new_content.encode("utf-8"))
            tmp.close()
            py_compile.compile(tmp.name, doraise=True)
            Path(tmp.name).unlink(missing_ok=True)
        except py_compile.PyCompileError as _syn_e:
            Path(tmp.name).unlink(missing_ok=True)
            logger.error("[CODE-PATCHER] ❌ Patch invalid — syntax error: %s", _syn_e)
            return False

        # ── Backup original ────────────────────────────────────────────────
        backup_name = f"backup_{Path(diagnosis.file_path).name}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.py"
        backup_path = PATCHES_DIR / backup_name
        PATCHES_DIR.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(content, encoding="utf-8")
        logger.info("[CODE-PATCHER] Backup saved: %s", backup_path)

        # Save patch record before writing
        await cls._save_patch_record(diagnosis, before, after)

        # Write file
        file_path.write_text(new_content, encoding="utf-8")
        logger.info(
            "[CODE-PATCHER] Fixed %s in %s:%s — %s",
            diagnosis.error_type,
            diagnosis.file_path,
            diagnosis.line_number or "?",
            diagnosis.fix_description,
        )

        # Mark rebuild needed
        await cls._mark_rebuild_needed(diagnosis.file_path)

        return True

    @classmethod
    async def _save_patch_record(cls, diagnosis: ErrorDiagnosis, before: str, after: str) -> None:
        """Save patch to /app/src/patches/patch_{timestamp}.json for traceability."""
        PATCHES_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        patch = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error_type": diagnosis.error_type,
            "file_path": diagnosis.file_path,
            "line_number": diagnosis.line_number,
            "description": diagnosis.fix_description,
            "before": before,
            "after": after,
        }
        patch_file = PATCHES_DIR / f"patch_{timestamp}.json"
        patch_file.write_text(json.dumps(patch, indent=2), encoding="utf-8")
        logger.debug("Patch record saved: %s", patch_file)

    @classmethod
    async def _mark_rebuild_needed(cls, file_path: str) -> None:
        """Mark in Redis that a rebuild is needed after code patching."""
        try:
            r = await cls._get_redis()
            raw = await r.get("self_healing:rebuild_needed")
            files = json.loads(raw) if raw else []
            if file_path not in files:
                files.append(file_path)
            await r.set("self_healing:rebuild_needed", json.dumps(files))
            await r.expire("self_healing:rebuild_needed", 86400)
            await r.aclose()
            logger.info("[CODE-PATCHER] Rebuild needed — patched files: %s", files)
        except Exception as exc:
            logger.debug("Failed to mark rebuild: %s", exc)

    @classmethod
    async def get_pending_patches(cls) -> list[dict]:
        """Return list of patches applied but pending rebuild."""
        patches = []
        if PATCHES_DIR.exists():
            for f in sorted(PATCHES_DIR.glob("patch_*.json")):
                try:
                    patches.append(json.loads(f.read_text()))
                except Exception:
                    pass
        return patches

    @classmethod
    async def get_rebuild_needed_files(cls) -> list[str]:
        """Return list of files that were patched and need rebuild."""
        try:
            r = await cls._get_redis()
            raw = await r.get("self_healing:rebuild_needed")
            await r.aclose()
            return json.loads(raw) if raw else []
        except Exception:
            return []

    @classmethod
    async def clear_rebuild_flag(cls) -> None:
        """Clear the rebuild needed flag (called after successful rebuild)."""
        try:
            r = await cls._get_redis()
            await r.delete("self_healing:rebuild_needed")
            await r.aclose()
        except Exception:
            pass

    @staticmethod
    def _parse_fix_code(fix_code: str) -> tuple[Optional[str], Optional[str]]:
        """Extract BEFORE and AFTER sections from fix_code string."""
        lines = fix_code.split("\n")
        before_lines = []
        after_lines = []
        in_before = False
        in_after = False

        for line in lines:
            stripped = line.strip()
            if stripped == "# BEFORE:":
                in_before = True
                in_after = False
                continue
            if stripped == "# AFTER:":
                in_before = False
                in_after = True
                continue
            if in_before:
                before_lines.append(line)
            if in_after:
                after_lines.append(line)

        before = "\n".join(before_lines).strip() if before_lines else None
        after = "\n".join(after_lines).strip() if after_lines else None
        return before, after
