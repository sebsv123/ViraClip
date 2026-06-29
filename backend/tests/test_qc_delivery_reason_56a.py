"""OUTPUT-QC-DELIVERY-REASON-COSMETIC-56A — delivery_decision_reason derived from the final
reconciled contract (same canonical materialization as 54D), never a stale provisional label."""
import sys
from pathlib import Path
# portable: resolve backend root from this file so it runs under any worktree/container path
_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/app/src"); sys.path.insert(0, "/app")  # compat (lower priority)
sys.path.insert(0, str(_BACKEND / "src")); sys.path.insert(0, str(_BACKEND))  # this backend wins

from src.services.task_service import _materialize_final_qc_state, ADVISORY_NOISE_STATES  # noqa: E402

FAIL = []
def ck(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c: FAIL.append(n)

# 1. Exact residual reproduction: provisional rejected_technical + advisory, final contract READY.
r1 = _materialize_final_qc_state(
    editorial_passed=True, technical_passed=True, delivery_decision="READY", final_publishable=True,
    provisional_qc_status="rejected_technical",
    provisional_qc_reasons=["final_qc_failed", "final_qc_severe"], delivery_hard_reject_reasons=[])
ck("1 READY -> reason='ready' (not rejected_technical)", r1["delivery_decision_reason"] == "ready")
ck("1 reason not an advisory/blocking token", r1["delivery_decision_reason"] not in ADVISORY_NOISE_STATES)
ck("1 qc_status=ready, advisory preserved separately",
   r1["qc_status"] == "ready" and set(r1["advisory_qc_reasons"]) == {"final_qc_failed", "final_qc_severe"})

# 2. Real technical failure -> reason keeps concrete technical reason / rejected_technical.
r2 = _materialize_final_qc_state(
    editorial_passed=True, technical_passed=False, delivery_decision="READY", final_publishable=True,
    provisional_qc_status="rejected_technical", provisional_qc_reasons=["audio_lufs_near_silence"],
    delivery_hard_reject_reasons=[])
ck("2 technical fail -> reason concrete technical", r2["delivery_decision_reason"] == "audio_lufs_near_silence" and r2["qc_status"] == "rejected_technical")

# 2b. technical fail with no concrete reason -> reason falls back to status, not empty/ready
r2b = _materialize_final_qc_state(
    editorial_passed=True, technical_passed=False, delivery_decision="READY", final_publishable=True,
    provisional_qc_status="rejected_technical", provisional_qc_reasons=[], delivery_hard_reject_reasons=[])
ck("2b technical fail no-reason -> rejected_technical", r2b["delivery_decision_reason"] == "rejected_technical")

# 3. Editorial rejection (technical ok) -> needs_review, NOT rejected_technical.
r3 = _materialize_final_qc_state(
    editorial_passed=False, technical_passed=True, delivery_decision="REVIEW", final_publishable=True,
    provisional_qc_status="needs_review", provisional_qc_reasons=["non_standalone_opening"],
    delivery_hard_reject_reasons=[])
ck("3 editorial -> reason=needs_review (not rejected_technical)",
   r3["delivery_decision_reason"] == "needs_review" and r3["qc_status"] != "rejected_technical")

# 4. Hard REJECT -> reason keeps concrete hard-reject reason.
r4 = _materialize_final_qc_state(
    editorial_passed=True, technical_passed=True, delivery_decision="REJECT", final_publishable=False,
    provisional_qc_status="rejected", provisional_qc_reasons=["backstage_detected"],
    delivery_hard_reject_reasons=["reason:backstage_detected"])
ck("4 REJECT -> reason concrete (backstage)", "backstage" in r4["delivery_decision_reason"])

# 5. Advisory-only legit READY -> reason='ready', advisory separate.
r5 = _materialize_final_qc_state(
    editorial_passed=True, technical_passed=True, delivery_decision="READY", final_publishable=True,
    provisional_qc_status="rejected_technical", provisional_qc_reasons=["final_qc_severe"],
    delivery_hard_reject_reasons=[])
ck("5 advisory-only READY -> reason=ready, advisory kept apart",
   r5["delivery_decision_reason"] == "ready" and "final_qc_severe" in r5["advisory_qc_reasons"])

# 6. Invariants table: reason must be consistent with decision; READY never carries reject/advisory.
import itertools
viol = []
for ed, te in itertools.product([True, False], repeat=2):
    for dd, fp, prov in (("READY", True, "rejected_technical"), ("REVIEW", True, "needs_review"),
                         ("REJECT", False, "rejected")):
        out = _materialize_final_qc_state(
            editorial_passed=ed, technical_passed=te, delivery_decision=dd, final_publishable=fp,
            provisional_qc_status=prov, provisional_qc_reasons=[], delivery_hard_reject_reasons=[])
        reason = out["delivery_decision_reason"]; qs = out["qc_status"]; rdy = out["ready"]
        if rdy and reason in ADVISORY_NOISE_STATES: viol.append(("ready+advisory_reason", ed, te, dd))
        if qs == "ready" and reason != "ready": viol.append(("ready_status_reason_mismatch", ed, te, dd, reason))
        if qs == "rejected_technical" and reason == "ready": viol.append(("rejtech+ready_reason", ed, te, dd))
ck("6 invariants: reason consistent with final decision/status", not viol)
if viol: print("  VIOLATIONS:", viol[:6])

print("RESULT:", "ALL GREEN" if not FAIL else f"FAILED {FAIL}")
sys.exit(1 if FAIL else 0)
