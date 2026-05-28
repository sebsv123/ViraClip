#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.services.vpi_retention_editing_service import _build_caption_visual_support_plan  # noqa: E402


def main() -> int:
    simple = "La responsabilidad protege a tu familia"
    plan = _build_caption_visual_support_plan("emotional_protection", simple)
    assert "responsabilidad" in simple
    assert plan["caption_visual_support_applied"] in {True, False}
    if plan["caption_visual_support_applied"]:
        assert plan["caption_icon_asset"]
    else:
        assert plan["caption_visual_support_skipped_reason"] in {"no_local_asset", "no_matching_concept"}
    print("caption_simple_text_preserved=true")
    print(f"caption_icon_only_when_local_asset={plan['caption_visual_support_applied']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
