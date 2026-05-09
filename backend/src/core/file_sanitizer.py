"""
Filename sanitization and safe upload path generation.
Prevents path traversal and dangerous characters.
"""
import os
import re
from pathlib import Path

MAX_FILENAME_LENGTH = 200
_SAFE_PATTERN = re.compile(r"[^a-zA-Z0-9_.\-]")

_ALLOWED_EXTENSIONS = {
    "mp4", "mov", "avi", "mkv", "webm",
    "mp3", "wav", "m4a", "aac",
}


def sanitize_filename(filename: str) -> str:
    """Elimina path traversal y caracteres peligrosos."""
    if not filename:
        return "upload"

    name = os.path.basename(filename)
    name = name.replace("..", "").replace("/", "").replace("\\", "")
    name = _SAFE_PATTERN.sub("_", name)

    stem, _, ext = name.rpartition(".")
    if ext.lower() not in _ALLOWED_EXTENSIONS:
        ext = "mp4"

    max_stem = MAX_FILENAME_LENGTH - len(ext) - 1
    stem = stem[:max_stem] if stem else "upload"

    return f"{stem}.{ext}"


def safe_upload_path(base_dir: Path, filename: str, task_id: str) -> Path:
    """Retorna un path seguro dentro de base_dir/{task_id}/."""
    safe_name = sanitize_filename(filename)
    upload_dir = base_dir / str(task_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    full_path = upload_dir / safe_name

    try:
        full_path.resolve().relative_to(base_dir.resolve())
    except ValueError:
        raise ValueError(f"Path traversal detected: {filename}")

    return full_path
