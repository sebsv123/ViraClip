"""OUTPUT-FINAL-QC-STATE-MATERIALIZATION-54D.

Single canonical materialization of the public qc state from the FINAL reconciled delivery
decision. Fixes the QC-54C contradiction: a publishable clip (delivery READY, final_publishable=
true, editorial+technical pass) persisted with a stale advisory qc_status=rejected_technical.
"""
import itertools
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/src")

from src.services.task_service import (  # noqa: E402
    _materialize_final_qc_state,
    classify_final_delivery_decision,
    ADVISORY_NOISE_STATES,
)

FAIL = []


def ck(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAIL.append(name)


# 1. Exact 54C reproduction: provisional stale rejected_technical + advisory blocking, but the
#    FINAL reconciled delivery is READY with editorial+technical pass.
r1 = _materialize_final_qc_state(
    editorial_passed=True, technical_passed=True, delivery_decision="READY", final_publishable=True,
    provisional_qc_status="rejected_technical",
    provisional_qc_reasons=["final_qc_failed", "final_qc_severe"],
    delivery_hard_reject_reasons=[])
ck("1 54C repro -> ready", r1["qc_status"] == "ready")
ck("1 no stale blocking in qc_reasons", not (set(r1["qc_reasons"]) & ADVISORY_NOISE_STATES) and r1["qc_reasons"] == [])
ck("1 do_not_upload false / ready true", r1["do_not_upload"] is False and r1["ready"] is True)
ck("1 advisory preserved separately", set(r1["advisory_qc_reasons"]) == {"final_qc_failed", "final_qc_severe"})

# 2. Authentic technical failure -> rejected_technical, never ready/READY.
r2 = _materialize_final_qc_state(
    editorial_passed=True, technical_passed=False, delivery_decision="READY", final_publishable=True,
    provisional_qc_status="rejected_technical", provisional_qc_reasons=["audio_lufs_near_silence"],
    delivery_hard_reject_reasons=[])
ck("2 real technical fail -> rejected_technical", r2["qc_status"] == "rejected_technical")
ck("2 technical fail not ready, do_not_upload", r2["ready"] is False and r2["do_not_upload"] is True)
ck("2 concrete technical reason kept", "audio_lufs_near_silence" in r2["qc_reasons"])

# 3. Physical corruption surfaced as technical failure.
r3 = _materialize_final_qc_state(
    editorial_passed=True, technical_passed=False, delivery_decision="REVIEW", final_publishable=False,
    provisional_qc_status="rejected_technical", provisional_qc_reasons=["corrupted_output"],
    delivery_hard_reject_reasons=[])
ck("3 corruption -> rejected_technical, not ready", r3["qc_status"] == "rejected_technical" and r3["ready"] is False)

# 4. Editorial rejection (technical ok) -> needs_review, NOT rejected_technical.
r4 = _materialize_final_qc_state(
    editorial_passed=False, technical_passed=True, delivery_decision="REVIEW", final_publishable=True,
    provisional_qc_status="needs_review", provisional_qc_reasons=["non_standalone_opening"],
    delivery_hard_reject_reasons=[])
ck("4 editorial fail -> needs_review (not rejected_technical)",
   r4["qc_status"] == "needs_review" and r4["qc_status"] != "rejected_technical")
ck("4 editorial reason kept, do_not_upload false", "non_standalone_opening" in r4["qc_reasons"] and r4["do_not_upload"] is False)

# 5. Legitimate advisory: advisory present, blocking degraded, final publishable READY.
r5 = _materialize_final_qc_state(
    editorial_passed=True, technical_passed=True, delivery_decision="READY", final_publishable=True,
    provisional_qc_status="rejected_technical", provisional_qc_reasons=["final_qc_severe"],
    delivery_hard_reject_reasons=[])
ck("5 advisory-only -> publishable, advisory kept out of blocking",
   r5["qc_status"] == "ready" and "final_qc_severe" not in r5["qc_reasons"] and "final_qc_severe" in r5["advisory_qc_reasons"])

# 6. Blocking NOT degraded: a real hard delivery REJECT preserved.
r6 = _materialize_final_qc_state(
    editorial_passed=True, technical_passed=True, delivery_decision="REJECT", final_publishable=False,
    provisional_qc_status="rejected", provisional_qc_reasons=["backstage_detected"],
    delivery_hard_reject_reasons=["reason:backstage_detected"])
ck("6 hard REJECT preserved", r6["qc_status"] in ("rejected",) and r6["ready"] is False and r6["do_not_upload"] is True)
ck("6 hard reject reason kept", any("backstage" in str(x) for x in r6["qc_reasons"]))

# 7. Coherence table over combinations — assert global invariants.
statuses = ["ready", "needs_review", "rejected_technical", "rejected"]
viol = []
for ed, te, fp in itertools.product([True, False], repeat=3):
    for prov in statuses:
        # derive the delivery decision the way the live code does (from provisional qc_status)
        dd = classify_final_delivery_decision(prov, [])["delivery_decision"]
        out = _materialize_final_qc_state(
            editorial_passed=ed, technical_passed=te, delivery_decision=dd, final_publishable=(dd != "REJECT"),
            provisional_qc_status=prov, provisional_qc_reasons=[], delivery_hard_reject_reasons=[])
        ready_out, status_out, dnu = out["ready"], out["qc_status"], out["do_not_upload"]
        # Invariants:
        if ready_out and status_out in ("rejected_technical", "rejected"):
            viol.append(("ready+reject", ed, te, prov, status_out))
        if ready_out and dnu:
            viol.append(("ready+do_not_upload", ed, te, prov))
        if (not te) and ready_out:
            viol.append(("technical_false+ready", ed, prov))
        if status_out == "ready" and (not te or not ed):
            viol.append(("ready_without_gates", ed, te, prov))
ck("7 coherence invariants hold (no contradictory final state)", not viol)
if viol:
    print("  VIOLATIONS:", viol[:8])

# 8. READY+publishable+gates can never end rejected_technical (the exact 54C guarantee).
ck("8 READY+publishable+gates never rejected_technical",
   _materialize_final_qc_state(editorial_passed=True, technical_passed=True, delivery_decision="READY",
                               final_publishable=True, provisional_qc_status="rejected_technical",
                               provisional_qc_reasons=["final_qc_failed"],
                               delivery_hard_reject_reasons=[])["qc_status"] != "rejected_technical")

print("RESULT:", "ALL GREEN" if not FAIL else f"FAILED {FAIL}")
sys.exit(1 if FAIL else 0)
