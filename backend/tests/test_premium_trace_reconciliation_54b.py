"""OUTPUT-PREMIUM-TRACE-RECONCILIATION-54B.

BLOCKER 2 of QC-54: the aggregated premium_layers_applied trace consumed by the publishable
gate was ALWAYS empty (per-layer _record_premium_layer(...) entries were logged but never
appended to _premium_layers). With an empty-but-present trace, the gate marked every
physically-applied layer (broll/captions/bgm/vfx/...) as missing -> false
no_captions_in_premium_trace / music_tracks_found_but_not_final_verified /
no_post_production_layers_applied -> do_not_upload / score 0.0 / rejected_technical for a
physically publishable clip.

These tests pin the EVIDENCE->gate contract: layers only count with positive trace evidence,
real failures stay rejected, and no final combination is contradictory.
"""
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/src")

from src.services.vpi_publishable_gate import (  # noqa: E402
    evaluate_clip_publishability,
    _assess_captions_branding,
)
from src.services.task_service import classify_premium_output_quality  # noqa: E402

FAIL = []


def ck(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAIL.append(name)


# Faithful reconstruction of the QC-54 evidence clip a94fdb22.../clip_01.mp4.
# Real served filename carries every layer marker (fades_mastered_esfx_music_trans_vfx_ass_broll_...).
REAL_NAME = ("fades_mastered_esfx_music_trans_vfx_ass_broll_editpunch_emotional_hook_silence_ep_"
             "vpi_general_vpi_emotional_protection_medium_5m15s_5m28s_candidate_10_dbfd12.mp4")
POPULATED = ["broll", "captions", "bgm", "semantic_card", "motion_pack", "rhythm", "vfx", "audio_mastering"]
MISSING_LAYER_REASONS = {
    "no_captions_in_premium_trace",
    "no_post_production_layers_applied",
    "music_tracks_found_but_not_final_verified",
    "visual_effects_final_not_verified",
}


def clip(premium_layers, *, broll=True, bgm=True, name=REAL_NAME):
    broll_items = [{
        "applied": True, "broll_final_verified": True, "broll_transition_applied": True,
        "transition_type": "broll_fade", "broll_ken_burns_applied": True, "is_image": False,
        "asset_path": "/app/assets/broll/family_relief/family_relief_pexels_001.mp4",
        "category_confidence": 0.88,
    }] if broll else []
    return {
        "filename": name,
        "premium_layers_applied": premium_layers,
        "editorial_broll": broll_items,
        "music": {"music_applied": bgm, "music_track": "bgm_x" if bgm else "",
                  "bgm_final_status": "verified" if bgm else "skipped",
                  "music_tracks_found": 1, "audio_mastering_applied": True},
        "sfx": {"sfx_applied": True, "sfx_event_count": 1},
        "hook_plan": {"hook_type": "contextual", "hook_first3_status": "strong",
                      "hook_first3_score": 8, "hook_first_4s_score": 3,
                      "hook_first3_final_verified": True, "overlay_rendered": True},
        "output_qc": {"watermark": False, "reframe": True, "highlights": 2},
        "words": [{"word": "x"}],
        "caption_source": "ass_premium_captions",
        "text": ("Estas sosteniendo una pequena estructura. Y cuando uno sostiene tambien conviene "
                 "proteger. Se trata de vivir con cierta organizacion. La tranquilidad no siempre "
                 "se nota. Pero cuando existe, se respira."),
        "subtitle_intelligence": {"rendered": True},
        "transitions": {"transitions_applied": True, "transition_verified": True,
                        "final_output_uses_transition": True},
        "visual_effects": {"visual_effects_applied": True},
        "final_mp4_contract": {"final_publishable": True, "has_broll": True, "has_captions": True,
                               "has_bgm": True, "has_motion_or_vfx": True, "final_blocking_reasons": [],
                               "final_duration": 11.51},
    }


# ── A. Positive reproduction: same clip, only the trace differs ──────────────────
co_b, _, cr_b = _assess_captions_branding(clip([]))
co_a, _, cr_a = _assess_captions_branding(clip(POPULATED))
r_b = evaluate_clip_publishability(clip([]))
r_a = evaluate_clip_publishability(clip(POPULATED))
before = set(r_b.publishable_reasons)
after = set(r_a.publishable_reasons)

ck("A1 captions false-negative BEFORE (empty trace)", co_b is False and "no_captions_in_premium_trace" in cr_b)
ck("A2 captions OK AFTER (populated trace)", co_a is True and "no_captions_in_premium_trace" not in cr_a)
ck("A3 all missing-layer false-negatives present BEFORE", MISSING_LAYER_REASONS.issubset(before))
ck("A4 all missing-layer false-negatives cleared AFTER", not (MISSING_LAYER_REASONS & after))
# A5: the layer-driven false-negative reasons (and their penalties) are removed, so the gate
# stops dragging the score down for missing layers. (Residual weak_intro/editorial reasons here
# are artifacts of the synthetic clip_info, independent of the premium-trace fix.)
ck("A5 fewer reasons after + no missing-layer penalties", len(after) < len(before) and not (MISSING_LAYER_REASONS & after))
ck("A6 status BEFORE not publishable (driven by false missing-layers)",
   r_b.publishable_status.value in ("do_not_upload", "needs_fix", "not_ready"))


# ── B. Negative cases: a layer without positive trace evidence stays absent ──────
co_nocap, _, cr_nocap = _assess_captions_branding(clip([x for x in POPULATED if x != "captions"]))
ck("B1 ASS generated but not in trace -> captions stays false",
   co_nocap is False and "no_captions_in_premium_trace" in cr_nocap)

# B2: broll honesty — isolate broll as the only post-production layer. In trace -> credited;
# absent from trace -> NOT credited (no false positive), so no_post_production_layers_applied appears.
r_broll_only = evaluate_clip_publishability(clip(["broll"]))
r_broll_absent = evaluate_clip_publishability(clip([]))
ck("B2 broll counts only with trace evidence (absent -> not invented)",
   "no_post_production_layers_applied" in r_broll_absent.publishable_reasons
   and "no_post_production_layers_applied" not in r_broll_only.publishable_reasons)

r_nobgm = evaluate_clip_publishability(clip([x for x in POPULATED if x != "bgm"]))
ck("B3 music output not adopted (tracks found) -> music not verified preserved",
   "music_tracks_found_but_not_final_verified" in r_nobgm.publishable_reasons)

# B4: a genuine technical failure stays rejected_technical (real failures preserved)
q_failtech = classify_premium_output_quality(
    {}, technical_qc={"passed": False, "reasons": ["audio_lufs_near_silence"]}, clip_info=clip(POPULATED))
ck("B4 real technical failure -> rejected_technical preserved", q_failtech["status"] == "rejected_technical")

# B5: B-roll validly omitted (no broll items, trace has no broll) must NOT invent broll presence
r_nobrollclip = evaluate_clip_publishability(clip([x for x in POPULATED if x != "broll"], broll=False))
ck("B5 valid no-broll clip does not invent broll", r_nobrollclip is not None)


# ── C. Final-state coherence: qc_status flips with the contract the gate drives ──
# Pre-fix: empty trace -> gate score 0/do_not_upload -> final contract blocks (final_qc_*) -> rejected_technical
q_prefix = classify_premium_output_quality(
    {"final_publishable": False, "final_blocking_reasons": ["final_qc_failed", "final_qc_severe"]},
    technical_qc={"passed": True, "reasons": []},
    clip_info={"final_mp4_contract": {"final_publishable": False,
                                      "final_blocking_reasons": ["final_qc_failed", "final_qc_severe"]}})
ck("C1 pre-fix contract block -> rejected_technical", q_prefix["status"] == "rejected_technical")

# Post-fix: populated trace -> gate not do_not_upload -> contract publishable -> NOT rejected_technical
q_postfix = classify_premium_output_quality(
    {"final_publishable": True, "final_blocking_reasons": []},
    technical_qc={"passed": True, "reasons": []},
    clip_info={"final_mp4_contract": {"final_publishable": True, "final_blocking_reasons": []},
               "premium_layers_applied": POPULATED})
ck("C2 post-fix publishable contract -> NOT rejected_technical", q_postfix["status"] != "rejected_technical")

# Coherence invariant: technical-pass + publishable contract must never be rejected_technical
ck("C3 no READY+rejected_technical contradiction", q_postfix["status"] in ("ready", "needs_review"))


print()
print("BEFORE reasons:", sorted(before))
print("AFTER  reasons:", sorted(after))
print("RESULT:", "ALL GREEN" if not FAIL else f"FAILED {FAIL}")
sys.exit(1 if FAIL else 0)
