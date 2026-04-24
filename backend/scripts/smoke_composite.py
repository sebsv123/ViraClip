"""Smoke test end-to-end del pipeline composite: SAM2 + LTX + FFmpeg."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from src.services.person_segmentation import person_segmentation_service
from src.services.composite_engine import composite_engine
from src.services.comfyui.orchestrator import comfyui_orchestrator


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

    task_id = "smoke_comp_001"

    print("[1/3] SAM2 mask...")
    mask = await person_segmentation_service.extract_person(str(clip), task_id=task_id)
    if not mask:
        print("[FAIL] SAM2 no devolvió máscara")
        return 3
    print(f"      -> {mask}")

    print("[2/3] LTX background...")
    bg_prompt = (
        "abstract cinematic gradient background, soft bokeh, "
        "warm sunset tones, shallow depth of field, 9:16 vertical"
    )
    bg = await comfyui_orchestrator.generate_broll_with_ltx(
        prompt=bg_prompt,
        task_id=task_id,
        duration_seconds=3.0,
        width=512,
        height=864,
    )
    print(f"      -> {bg}")

    print("[3/3] FFmpeg composite...")
    out = await composite_engine.composite(
        original_clip=str(clip),
        mask_clip=mask,
        background_clip=bg,
        task_id=task_id,
    )
    if not out:
        print("[FAIL] composite devolvió None")
        return 4

    size = Path(out).stat().st_size if Path(out).exists() else 0
    print(f"[OK] composite: {out} ({size} bytes)")
    return 0 if size > 0 else 5


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
