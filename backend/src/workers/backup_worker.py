"""
Daily PostgreSQL backup with gzip compression and S3/R2 upload.
"""
import asyncio
import gzip
import logging
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

BACKUP_DIR = Path(os.getenv("BACKUP_LOCAL_DIR", "/tmp/viraclip_backups"))
BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "7"))
DATABASE_URL = os.getenv("DATABASE_URL", "")


async def backup_postgresql() -> dict:
    """Generate compressed pg_dump and upload to storage."""
    if not DATABASE_URL:
        logger.error("[Backup] DATABASE_URL not configured")
        return {"success": False, "error": "DATABASE_URL not configured"}

    start = datetime.utcnow()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = start.strftime("%Y%m%d_%H%M%S")
    dump_path = BACKUP_DIR / f"viraclip_{timestamp}.sql"
    gz_path = BACKUP_DIR / f"viraclip_{timestamp}.sql.gz"

    try:
        parsed = urlparse(DATABASE_URL)
        pg_env = {**os.environ, "PGPASSWORD": parsed.password or ""}
        pg_host = parsed.hostname or "localhost"
        pg_port = str(parsed.port or 5432)
        pg_user = parsed.username or "postgres"
        pg_db = parsed.path.lstrip("/") or "viraclip"
    except Exception as exc:
        logger.error("[Backup] Failed to parse DATABASE_URL: %s", exc)
        return {"success": False, "error": str(exc)}

    cmd = [
        "pg_dump", "-h", pg_host, "-p", pg_port,
        "-U", pg_user, "-d", pg_db,
        "--no-password", "--format=plain", "--file", str(dump_path),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, env=pg_env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        if proc.returncode != 0:
            logger.error("[Backup] pg_dump failed: %s", stderr.decode()[-500:])
            return {"success": False, "error": stderr.decode()[-200:]}
    except asyncio.TimeoutError:
        logger.error("[Backup] pg_dump timed out after 300s")
        return {"success": False, "error": "timeout"}

    # Compress
    with open(dump_path, "rb") as f_in:
        with gzip.open(gz_path, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
    dump_path.unlink(missing_ok=True)

    size_mb = gz_path.stat().st_size / 1024 / 1024
    logger.info("[Backup] Generated: %s (%.1fMB)", gz_path.name, size_mb)

    upload_ok = await _upload_backup(gz_path)
    await _cleanup_old_backups()

    duration = (datetime.utcnow() - start).total_seconds()
    return {
        "success": upload_ok,
        "filename": gz_path.name,
        "size_mb": round(size_mb, 2),
        "duration_s": round(duration, 1),
        "uploaded": upload_ok,
    }


async def _upload_backup(gz_path: Path) -> bool:
    """Upload backup to configured storage (S3/R2/local)."""
    storage = os.getenv("BACKUP_STORAGE", "local")
    if storage == "local":
        logger.info("[Backup] Storage=local, file kept at %s", gz_path)
        return True
    if storage in ("s3", "r2"):
        try:
            import boto3
            from botocore.config import Config
            s3 = boto3.client(
                "s3",
                endpoint_url=os.getenv("BACKUP_S3_ENDPOINT"),
                aws_access_key_id=os.getenv("BACKUP_S3_KEY"),
                aws_secret_access_key=os.getenv("BACKUP_S3_SECRET"),
                config=Config(signature_version="s3v4"),
            )
            bucket = os.getenv("BACKUP_S3_BUCKET", "viraclip-backups")
            key = f"backups/{gz_path.name}"
            await asyncio.to_thread(s3.upload_file, str(gz_path), bucket, key)
            logger.info("[Backup] Uploaded to s3://%s/%s", bucket, key)
            gz_path.unlink(missing_ok=True)
            return True
        except Exception as exc:
            logger.error("[Backup] S3 upload failed: %s", exc)
            return False
    logger.warning("[Backup] Unknown storage: %s", storage)
    return False


async def _cleanup_old_backups() -> None:
    """Remove local backups older than retention days."""
    cutoff = datetime.utcnow() - timedelta(days=BACKUP_RETENTION_DAYS)
    for f in BACKUP_DIR.glob("viraclip_*.sql.gz"):
        try:
            mtime = datetime.utcfromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                f.unlink()
                logger.info("[Backup] Removed old backup: %s", f.name)
        except Exception as exc:
            logger.warning("[Backup] Failed to remove %s: %s", f.name, exc)
