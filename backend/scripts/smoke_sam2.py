"""Smoke test aislado: invoca PersonSegmentationService sobre un clip real."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from src.services.person_segmentation import person_segmentation_service


async def main() -> int:
    clip = Path(
        os.getenv(
            "SMOKE_CLIP",
            "/app/temp/uploads/broll/clips/ff74a714-5430-41fc-9e9e-1ae7507459c1/"
            "sub_jc_clip_2_viral_53_0035-0135.mp4",
        )
    )
    if not clip.exists():
        print(f"[FAIL] clip inexistente: {clip}")
        return 2
    print(f"[*] Ejecutando SAM2 sobre {clip}")
    result = await person_segmentation_service.extract_person(
        str(clip), task_id="smoke_sam2_001"
    )
    if not result:
        print("[FAIL] extract_person devolvió None")
        return 3
    p = Path(result)
    size = p.stat().st_size if p.exists() else 0
    print(f"[OK] máscara: {result} ({size} bytes)")
    return 0 if size > 0 else 4


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
