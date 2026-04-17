"""
Startup Utilities

Ensures required directories and resources exist before application starts.
This prevents FileNotFoundError on first run or in standalone mode.
"""

import os
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def ensure_required_directories() -> None:
    """
    FIX: Create all required directories if they don't exist.
    Prevents errors on first startup or in standalone mode.
    """
    # Get base paths from environment or use defaults
    temp_dir = os.getenv("TEMP_DIR", "/app/temp/uploads")
    overlay_cache_dir = os.getenv("OVERLAY_CACHE_DIR", "/app/storage/overlay_cache")
    dataset_dir = os.getenv("DATASET_DIR", "/app/datasets")
    audio_library_path = os.getenv("AUDIO_LIBRARY_PATH", "/app/assets/sounds")
    
    # Define all required directories
    required_dirs: List[Path] = [
        # Temp directories for processing
        Path(temp_dir),
        Path(temp_dir) / "clips",
        Path(temp_dir) / "downloads",
        
        # Storage directories
        Path(overlay_cache_dir),
        Path("/app/storage/ingested"),  # Video ingestion
        
        # Data directories
        Path(dataset_dir),
        Path("/app/data"),
        Path("/app/data/reasoning_traces"),  # Structured reasoning
        Path("/app/data/creator_profiles"),  # Creator templates
        
        # Asset directories
        Path(audio_library_path),
        Path(audio_library_path) / "bgm",  # Background music
        Path(audio_library_path) / "sfx",  # Sound effects
        Path("/app/fonts"),
        Path("/app/transitions"),
        
        # Model cache directories
        Path("/app/models"),
        Path("/app/models/whisper"),
        Path("/app/models/t2v"),
        Path("/app/models/tts"),
        Path("/app/models/esrgan"),
        Path("/app/models/rvc"),
        Path("/app/models/lora"),
        Path("/app/models/lora_cache"),
    ]
    
    created = []
    already_existed = []
    failed = []
    
    for directory in required_dirs:
        try:
            if directory.exists():
                already_existed.append(directory)
            else:
                directory.mkdir(parents=True, exist_ok=True)
                created.append(directory)
                logger.debug(f"Created directory: {directory}")
        except Exception as e:
            failed.append((directory, str(e)))
            logger.warning(f"Failed to create directory {directory}: {e}")
    
    # Log summary
    if created:
        logger.info(f"✅ Created {len(created)} directories on startup")
    if already_existed:
        logger.debug(f"✓ {len(already_existed)} directories already exist")
    if failed:
        logger.warning(f"⚠️  Failed to create {len(failed)} directories:")
        for dir_path, error in failed:
            logger.warning(f"  - {dir_path}: {error}")


def validate_critical_paths() -> bool:
    """
    FIX: Validate that critical paths are accessible.
    Returns True if all critical paths are OK, False otherwise.
    """
    temp_dir = Path(os.getenv("TEMP_DIR", "/app/temp/uploads"))
    
    critical_paths = [
        temp_dir,
    ]
    
    all_ok = True
    for path in critical_paths:
        if not path.exists():
            logger.error(f"❌ Critical path does not exist: {path}")
            all_ok = False
        elif not os.access(path, os.W_OK):
            logger.error(f"❌ Critical path is not writable: {path}")
            all_ok = False
        else:
            logger.debug(f"✓ Critical path OK: {path}")
    
    return all_ok


def initialize_application() -> None:
    """
    FIX: Main initialization function.
    Call this from main_refactored.py on startup.
    """
    logger.info("🚀 Initializing ViraClip application...")
    
    # Step 1: Ensure directories exist
    ensure_required_directories()
    
    # Step 2: Validate critical paths
    if not validate_critical_paths():
        logger.warning("⚠️  Some critical paths are not accessible - may cause errors")
    
    logger.info("✅ Application initialization complete")
