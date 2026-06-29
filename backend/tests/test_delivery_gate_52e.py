"""OUTPUT-DELIVERY-GATE-52E — deterministic tests for the final delivery decision."""
import sys
sys.path.insert(0, "/app")
from src.services.task_service import (
    classify_final_delivery_decision as decide,
    HARD_REJECT_QC_STATUSES,
    HARD_REJECT_REASON_TOKENS,
    ADVISORY_NOISE_STATES,
    _BACKSTAGE_HARD_DELIVERY_PHRASES,
    _normalize_text_hard,
    _build_publishable_qc,
)

FAIL = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond: FAIL.append(name)

# ── concrete hard-reject reasons -> REJECT (irreversible) ──
# 1. backstage_detected -> REJECT, excluded, not publishable
d = decide("ready", ["backstage_detected"])
check("1 backstage_detected -> REJECT", d["delivery_decision"] == "REJECT")
check("1 excluded_from_frontend", d["excluded_from_frontend"] is True)
check("1 final_publishable false", d["final_publishable"] is False)

# 2. backstage_phrase_detected -> REJECT
check("2 backstage_phrase_detected -> REJECT", decide("needs_review", ["backstage_phrase_detected"])["delivery_decision"] == "REJECT")

# 3. disfluency_hard_fail -> REJECT
check("3 disfluency_hard_fail -> REJECT", decide("ready", ["disfluency_hard_fail"])["delivery_decision"] == "REJECT")

# 4. rejected_incomplete_final_idea (52A) -> REJECT
check("4 rejected_incomplete_final_idea -> REJECT", decide("needs_review", ["rejected_incomplete_final_idea"])["delivery_decision"] == "REJECT")

# 5. duplicate / cross-task / render / physical / media / recovery / corrupted -> REJECT
for r in ("duplicate_rejected", "rejected_cross_task_duplicate", "render_safety_failed",
          "physical_contract_failed", "missing_media_binding", "recovery_raw",
          "corrupted_output", "editorial_integrity_failed", "non_standalone_opening"):
    check(f"5 [{r}] -> REJECT", decide("needs_review", [r])["delivery_decision"] == "REJECT")

# ── advisory noise MUST NOT reject (the whole point of 52E) ──
# 6. rejected_technical ALONE -> NOT REJECT (it is on the good 20572881/116fe6db clips too)
d = decide("rejected_technical", ["final_qc_failed", "final_qc_severe"])
check("6 rejected_technical alone -> NOT REJECT", d["delivery_decision"] != "REJECT")
check("6 rejected_technical advisory recognised", "rejected_technical" in ADVISORY_NOISE_STATES)

# 7. final_qc_severe ALONE -> NOT REJECT (noise on 62% of clips)
check("7 final_qc_severe alone -> NOT REJECT", decide("needs_review", ["final_qc_severe"])["delivery_decision"] != "REJECT")

# 8. REVIEW advisory, no hard reason -> REVIEW (still deliverable)
d = decide("needs_review", ["weak_first_second"])
check("8 needs_review -> REVIEW deliverable", d["delivery_decision"] == "REVIEW" and d["excluded_from_frontend"] is False and d["final_publishable"] is True)

# 9. ready / publishable clean -> READY
check("9 ready -> READY", decide("ready", [])["delivery_decision"] == "READY")
check("9 publishable -> READY", decide("publishable", [])["delivery_decision"] == "READY")
# even with the advisory rejected_technical label, a clip with no concrete hard reason is deliverable
check("9 rejected_technical+no_hard_reason -> deliverable", decide("rejected_technical", [])["delivery_decision"] in ("READY", "REVIEW"))

# 10. REJECT irreversible invariant
d = decide("ready", ["backstage_detected"])
check("10 REJECT invariant", d["excluded_from_frontend"] is True and d["final_publishable"] is False)

# ── backstage-phrase separator: Case A reject, Case B/C keep ──
def has_backstage(text):
    n = _normalize_text_hard(text)
    return any(p in n for p in _BACKSTAGE_HARD_DELIVERY_PHRASES)

A = "La salud no siempre avisa. Tiene una costumbre rebelde. No siempre. No. Es que estoy leyendo el titulo."
B = "La poliza de asistencia en viaje se inicia desde el momento que sales hasta que regresas con la fecha del pasaje."
C = "Hablar de un seguro de vida no trae nada malo. Hablar de proteger a tu familia tampoco."
check("11 Case A (690c9c9c) backstage detected", has_backstage(A) is True)
check("12 Case B (20572881) NOT backstage", has_backstage(B) is False)
check("13 Case C (116fe6db) NOT backstage", has_backstage(C) is False)
# end-to-end: Case A reason flows to REJECT
check("14 Case A -> REJECT via backstage_phrase", decide("rejected_technical", ["backstage_phrase_detected"])["delivery_decision"] == "REJECT")

# ── 54A rescue gate: a valid MP4 cannot rescue a clip that starts mid-thought ──
bad_opening_qc = _build_publishable_qc(
    {"text": "organiza, por qué espera de su cobertura o qué tipo de tranquilidad está buscando, porque elegir bien tiene sentido para ti.", "starts_cleanly": False},
    {
        "text": "organiza, por qué espera de su cobertura o qué tipo de tranquilidad está buscando, porque elegir bien tiene sentido para ti.",
        "duration": 14.8,
        "path": "/tmp/nonexistent-but-contract-says-ok.mp4",
        "final_mp4_contract": {
            "render_success": True,
            "final_publishable": True,
            "has_captions": True,
            "has_bgm": True,
            "has_motion_or_vfx": True,
        },
        "hook_plan": {"hook_first3_score": 7},
        "music": {"music_applied": True, "final_output_uses_bgm": True},
        "speaker_focus": {"speaker_focus_enhanced": True},
    },
    vpi_productive_minimum=True,
)
check("15 starts mid-thought flagged", bad_opening_qc["non_standalone_opening"] is True)
check("16 starts mid-thought strict reason", "non_standalone_opening" in bad_opening_qc["strict_publishable_reasons"])
check("17 starts mid-thought -> hard REJECT", decide("rejected_technical", bad_opening_qc["strict_publishable_reasons"])["delivery_decision"] == "REJECT")

good_advisory_qc = _build_publishable_qc(
    {"text": "Esto cambia la forma de elegir una cobertura medica porque te obliga a pensar primero en tus necesidades reales."},
    {
        "text": "Esto cambia la forma de elegir una cobertura medica porque te obliga a pensar primero en tus necesidades reales.",
        "duration": 14.8,
        "path": "/tmp/nonexistent-but-contract-says-ok.mp4",
        "final_mp4_contract": {
            "render_success": True,
            "final_publishable": True,
            "has_captions": True,
            "has_bgm": True,
            "has_motion_or_vfx": True,
        },
        "hook_plan": {"hook_first3_score": 7},
        "music": {"music_applied": True, "final_output_uses_bgm": True},
        "speaker_focus": {"speaker_focus_enhanced": True},
    },
    vpi_productive_minimum=True,
)
check("18 valid advisory opening not flagged", good_advisory_qc["non_standalone_opening"] is False)
check("19 rejected_technical advisory remains deliverable", decide("rejected_technical", ["final_qc_failed"])["delivery_decision"] != "REJECT")

print()
if FAIL:
    print("RESULT: FAIL ->", FAIL); sys.exit(1)
print("RESULT: ALL GREEN")
