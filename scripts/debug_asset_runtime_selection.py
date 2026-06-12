#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _candidate in (ROOT / "backend" / "src", ROOT / "src"):
    _path = str(_candidate)
    if _candidate.exists() and _path not in sys.path:
        sys.path.insert(0, _path)
        break

from services.vpi_asset_library_service import build_asset_index, select_verified_bgm_candidate  # noqa: E402
from services.vpi_broll_intent import build_broll_editorial_decision, match_broll_asset  # noqa: E402
from services.vpi_sfx_service import build_sfx_retention_decision, match_sfx_asset  # noqa: E402
from services.caption_service import plan_caption_overlay_pack  # noqa: E402
from services.vpi_motion_overlay_service import select_motion_overlay_candidate  # noqa: E402


def _pick_font(index: dict) -> str:
    fonts = list((index.get("verified") or {}).get("fonts") or [])
    if not fonts:
        return ""
    preferred = next((f for f in fonts if "caption_primary" in list(f.get("tags") or [])), fonts[0])
    return str(preferred.get("path") or "")


def _pick_icon(plan: dict) -> str:
    icon = dict(plan.get("caption_icon") or {})
    return str(icon.get("asset") or "") if icon.get("applied") else ""


def main() -> int:
    index = build_asset_index()
    verified_overlays = list((index.get("verified") or {}).get("motion_overlay") or [])
    generated_overlay_assets = []
    for item in verified_overlays:
        path_txt = str(item.get("path") or "")
        path_norm = path_txt.replace("\\", "/")
        if "/assets/overlays/generated_icons/" in path_norm or "assets/overlays/generated_icons/" in path_norm:
            concept_txt = str(item.get("concept") or "").strip()
            if not concept_txt:
                parts = path_norm.split("/assets/overlays/generated_icons/")
                if len(parts) == 2 and "/" in parts[1]:
                    concept_txt = parts[1].split("/", 1)[0].strip()
            if concept_txt:
                item = dict(item)
                item["concept"] = concept_txt
                generated_overlay_assets.append(item)
    segments = [
        {
            "text": "esto mucha gente no lo sabe sobre el seguro de salud",
            "editorial_type": "salud",
            "hook_intent": "risk_warning",
            "composition_mode": "warning_tension",
        },
        {
            "text": "si eres autónomo y mañana no puedes trabajar",
            "editorial_type": "autonomos",
            "hook_intent": "autonomous_business_stakes",
            "composition_mode": "business_punch",
        },
        {
            "text": "la tranquilidad para ti y los tuyos",
            "editorial_type": "decesos",
            "hook_intent": "emotional_closure",
            "composition_mode": "emotional_soft",
        },
    ]

    selected_broll = ""
    selected_sfx = ""
    selected_bgm = ""
    selected_bgm_manifest_verified = False
    selected_icon = ""
    selected_font = _pick_font(index)
    selected_motion_overlay = ""
    selected_motion_overlay_manifest_verified = False

    for seg in segments:
        if not selected_broll:
            decision = build_broll_editorial_decision(
                segment_text=seg["text"],
                hook_intent=seg["hook_intent"],
                topic=seg["editorial_type"],
                private_premium_status="PRIVATE_PREMIUM_READY",
                composition_decision={"mode": seg["composition_mode"]},
                first3_visual_contract={"status": "pass"},
                visual_profile="",
            )
            match = match_broll_asset(
                broll_intent=str(decision.get("broll_intent") or ""),
                topic=seg["editorial_type"],
                segment_text=seg["text"],
            )
            if match.get("matched"):
                selected_broll = str(match.get("asset") or "")

        if not selected_sfx:
            sfx_decision = build_sfx_retention_decision(
                hook_intent=seg["hook_intent"],
                visual_profile="",
                composition_mode=seg["composition_mode"],
                broll_editorial_decision={},
                segment_text=seg["text"],
                private_premium_status="PRIVATE_PREMIUM_READY",
                first3_visual_contract={"status": "pass"},
            )
            sfx_match = match_sfx_asset(
                sfx_family=str(sfx_decision.get("sfx_family") or ""),
                hook_intent=seg["hook_intent"],
                task_id="debug_asset_runtime_selection",
            )
            if sfx_match.get("matched"):
                selected_sfx = str(sfx_match.get("asset") or "")

        if not selected_icon:
            caption_plan = plan_caption_overlay_pack(
                "salud especialistas tranquilidad",
                hook_intent="neutral_explanation",
                editorial_type="salud",
                words=[{"word": "salud", "start": 0.0, "end": 0.3}, {"word": "tranquilidad", "start": 0.3, "end": 0.6}],
                subtitle_already_strong=True,
                enable_lower_third=True,
                composition_decision={"mode": "minimal_safe"},
            )
            selected_icon = _pick_icon(caption_plan)

        if not selected_bgm:
            bgm_match = select_verified_bgm_candidate(
                editorial_type=seg["editorial_type"],
                hook_intent=seg["hook_intent"],
                segment_text=seg["text"],
                index=index,
            )
            if bgm_match.get("matched") and bgm_match.get("path"):
                selected_bgm = str(bgm_match.get("path") or "")
                selected_bgm_manifest_verified = bool(bgm_match.get("manifest_verified"))

        if not selected_motion_overlay:
            overlay = select_motion_overlay_candidate(
                text=seg["text"],
                topics=[seg["editorial_type"], seg["hook_intent"]],
                tags=[],
                editorial_signal={"composition_mode": seg["composition_mode"], "layer_overload": False},
                asset_index=index,
            )
            if overlay and overlay.get("motion_overlay_asset_path"):
                selected_motion_overlay = str(overlay.get("motion_overlay_asset_path") or "")
                selected_motion_overlay_manifest_verified = bool(overlay.get("motion_overlay_manifest_verified"))

    ok = all([selected_broll, selected_sfx, selected_bgm, selected_icon, selected_font, selected_bgm_manifest_verified])
    required_concepts = ["checkmark", "shield", "warning", "chat_bubble", "euro"]
    generated_concepts_available = sorted(
        {
            str(item.get("concept") or "").strip()
            for item in generated_overlay_assets
            if str(item.get("concept") or "").strip()
        }
    )
    generated_concepts_ok = all(concept in generated_concepts_available for concept in required_concepts)
    generated_selectable = {}
    for concept in required_concepts:
        concept_assets = [
            item for item in generated_overlay_assets
            if str(item.get("concept") or "").strip() == concept
        ]
        generated_selectable[concept] = bool(concept_assets)

    generated_selectable_ok = all(generated_selectable.values())
    semantic_fixtures = [
        ("No todos los seguros cubren lo mismo", {"warning"}),
        ("familia protegida si pasa algo serio", {"shield", "heart"}),
        ("póliza correcta y documentación en orden", {"document_check"}),
        ("precio descuento condiciones", {"euro"}),
        ("escríbenos por WhatsApp", {"chat_bubble", "phone"}),
    ]
    semantic_checks = []
    semantic_ok = True
    for text, expected in semantic_fixtures:
        res = select_motion_overlay_candidate(
            text=text,
            topics=["generated_icon", "motion_overlay"],
            tags=["beta_clean_semantic"],
            editorial_signal={"composition_mode": "balanced", "layer_overload": False},
            asset_index=index,
        )
        selected_concept = str((res or {}).get("overlay_concept") or "")
        hit = bool(res and selected_concept in expected and str((res or {}).get("motion_overlay_asset_id") or "").startswith("generated_icon_"))
        semantic_checks.append((text, selected_concept, hit))
        semantic_ok = semantic_ok and hit

    ok = bool(ok and generated_concepts_ok and generated_selectable_ok and semantic_ok)
    print(f"ASSET_RUNTIME_SELECTION={'PASS' if ok else 'FAIL'}")
    print(f"selected_broll={selected_broll or 'none'}")
    print(f"selected_sfx={selected_sfx or 'none'}")
    print(f"selected_bgm={selected_bgm or 'none'}")
    print(f"selected_bgm_manifest_verified={'true' if selected_bgm_manifest_verified else 'false'}")
    print(f"selected_icon={selected_icon or 'none'}")
    print(f"selected_font={selected_font or 'none'}")
    print(f"selected_motion_overlay={selected_motion_overlay or 'none'}")
    print(
        "selected_motion_overlay_manifest_verified="
        f"{'true' if selected_motion_overlay_manifest_verified else 'false'}"
    )
    print(f"generated_icon_motion_overlay_assets={len(generated_overlay_assets)}")
    print(f"generated_icon_required_concepts_available={'true' if generated_concepts_ok else 'false'}")
    for concept in required_concepts:
        print(
            f"generated_icon_selectable_{concept}="
            f"{'true' if generated_selectable.get(concept) else 'false'}"
        )
    print(f"generated_icon_semantic_selector={'true' if semantic_ok else 'false'}")
    for idx, (_text, selected_concept, hit) in enumerate(semantic_checks, start=1):
        print(
            f"generated_icon_semantic_case_{idx}="
            f"{'true' if hit else 'false'} concept={selected_concept or 'none'}"
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
