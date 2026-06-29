"""OUTPUT-DURATION-RECONCILIATION-54A — narrow tests for physical-duration persistence.

The persisted (`generated_clips.duration`) / API duration must be the physical master
duration (ffprobe), never the editorial selection window. Reproduces the evidence case:
selection 27.34 s vs physical 11.51 s -> persisted 11.51 s.
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/src")

from src.services.task_service import (  # noqa: E402
    _reconciled_physical_duration,
    _build_clip_technical_qc,
)

FAIL = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAIL.append(name)


# 1) selection 27.34 vs physical 11.51 -> persisted 11.51 (physical wins)
ci = {"duration": 27.34, "technical_qc": {"meta": {"duration": 11.51}}}
d, src = _reconciled_physical_duration(ci)
check("1 physical 11.51 chosen over editorial 27.34",
      abs(d - 11.51) < 0.05 and src == "technical_qc_physical_probe")

# 2) editorial selection duration is NOT lost/overwritten on clip_info
check("2 editorial selection preserved on clip_info (not mutated)", ci["duration"] == 27.34)

# 3) a reconciled physical value is not overwritten by editorial/contract before persistence
#    (technical_qc physical probe has top precedence)
ci3 = {"duration": 27.34, "physical_duration_s": 11.49, "technical_qc": {"meta": {"duration": 11.51}}}
d3, src3 = _reconciled_physical_duration(ci3)
check("3 technical_qc physical wins over editorial+contract",
      abs(d3 - 11.51) < 0.05 and src3 == "technical_qc_physical_probe")

# 3b) final-contract physical used when no technical_qc probe present
ci3b = {"duration": 27.34, "final_mp4_contract": {"physical_duration_s": 11.51}}
d3b, src3b = _reconciled_physical_duration(ci3b)
check("3b final-contract physical used (no technical_qc)",
      abs(d3b - 11.51) < 0.05 and src3b == "final_contract_physical_duration")

# 4) tolerance: real probe 11.509591 within 0.05 of expected 11.51
ci4 = {"duration": 27.34, "technical_qc": {"meta": {"duration": 11.509591}}}
d4, _ = _reconciled_physical_duration(ci4)
check("4 tolerance <= 0.05", abs(d4 - 11.51) <= 0.05)

# 5) fallback when ffprobe yields no valid duration: editorial fallback WITH provenance,
#    never invents 0 when an editorial value exists
ci5 = {"duration": 27.34, "technical_qc": {"meta": {"duration": 0.0}}, "final_mp4_contract": {}}
d5, src5 = _reconciled_physical_duration(ci5)
check("5 editorial fallback reported when no physical probe",
      abs(d5 - 27.34) < 0.05 and src5 == "editorial_selection_fallback")

# 5b) nothing available -> 0.0 but provenance is explicit (honest absence, not silent)
d5b, src5b = _reconciled_physical_duration({})
check("5b empty -> 0.0 with explicit provenance", d5b == 0.0 and src5b == "editorial_selection_fallback")

# 5c) invalid types do not crash the persistence boundary
d5c, _ = _reconciled_physical_duration({"duration": "x", "technical_qc": {"meta": {"duration": "y"}}})
check("5c invalid types safe (no crash, 0.0)", d5c == 0.0)

# 6) INTEGRATED: real served master of the evidence task. No E2E rerun; just the public
#    persistence-path reconciliation over the existing physical file.
MASTER = Path("/app/outputs/generated/a94fdb22-1372-4209-af64-c40d9db29c0f/clip_01.mp4")
if MASTER.exists():
    tq = _build_clip_technical_qc(path=MASTER, clip_info={"duration": 27.34}, min_duration_s=8.0)
    ci6 = {"duration": 27.34, "technical_qc": tq}
    d6, src6 = _reconciled_physical_duration(ci6)
    check("6 integrated real master physical ~11.51",
          abs(d6 - 11.51) < 0.05 and src6 == "technical_qc_physical_probe")
    check("6b technical_qc.meta.duration is physical ~11.51",
          abs(float(tq["meta"]["duration"]) - 11.51) < 0.05)
    check("6c editorial 27.34 still present after reconciliation", ci6["duration"] == 27.34)
else:
    print("SKIP 6 integrated (evidence master not present in container)")

print("RESULT:", "ALL GREEN" if not FAIL else f"FAILED {FAIL}")
sys.exit(1 if FAIL else 0)
