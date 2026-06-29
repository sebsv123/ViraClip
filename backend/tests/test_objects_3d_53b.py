"""OUTPUT-OBJECTS-3D-53B — gate calibration tests (two-tier literal/inferred evidence policy)."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/src")

from services.vpi_object_3d_service import (  # noqa: E402
    select_object_3d, classify_evidence_tier, LITERAL_FLOOR, MIN_SEMANTIC_SCORE_3D, GATE_VERSION,
)

FAIL = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAIL.append(name)

def W(sentence, start=9.0, wd=0.45):
    out, t = [], start
    for tok in sentence.split():
        out.append({"word": tok, "text": tok, "start": round(t, 3), "end": round(t + 0.4, 3)})
        t += wd
    return out

NV = {"broll_strong": False, "face_side": "center", "captions_band": "bottom"}
CTX = {"editorial_type": "", "hook_end_s": 2.0}

def sel(sentence):
    return select_object_3d(W(sentence), existing_visuals=NV, clip_duration_s=26.0, task_context=CTX)

# ── 1–4: literal phrases ACCEPT via LITERAL_STRONG ──
d = sel("antes de viajar al extranjero para una estancia larga lejos de aqui")
check("1 literal travel accept", d is not None and d.asset_id == "travel_suitcase_3d" and d.evidence_tier == "LITERAL_STRONG")

d = sel("tienes que presentar el pasaporte al llegar a tu destino de viaje")
check("2 literal passport accept", d is not None and d.asset_id == "document_passport_3d" and d.evidence_tier == "LITERAL_STRONG")

d = sel("lo importante es proteger a tu familia y a los tuyos cada dia")
check("3 literal family protection accept", d is not None and d.asset_id == "protection_shield_3d" and d.evidence_tier == "LITERAL_STRONG")

d = sel("vas a necesitar atencion sanitaria y acudir al medico sin demora alguna")
check("4 literal health accept", d is not None and d.asset_id == "health_heart_3d" and d.evidence_tier == "LITERAL_STRONG")

# ── 5–6: generic risk / care REJECT ──
check("5 generic risk reject", sel("si ocurre cualquier problema conviene estar prevenido por si acaso siempre") is None)
check("6 generic care reject", sel("lo importante es estar tranquilo y cuidarse un poco mas cada dia hoy") is None)

# ── 7: strong=True but NOT literal (tranquilidad) -> reject / reclassified to INFERRED ──
d = sel("que tipo de tranquilidad esta buscando para su cobertura personal el cliente hoy")
check("7 strong-but-not-literal reject (d1ec4a6f phrase)", d is None)

# ── 8: literal strong with raw 0.5 (single literal token) + real max -> accept via LITERAL tier ──
d = sel("hoy quiero hablarte de tu viaje y de nada mas en concreto ahora")
check("8 single-literal-0.5 accept (scale fix)", d is not None and d.evidence_tier == "LITERAL_STRONG" and abs(d.raw_score - 0.5) < 1e-6)

# ── 9: inferred intent keeps the high gate (single non-literal strong 0.5 < 0.82) ──
ti = classify_evidence_tier("protection_shield_3d", [{"matched_phrase": "tranquilidad", "matched_norm": "tranquilidad", "evidence_strength": "strong"}])
check("9 tranquilidad -> INFERRED tier", ti["tier"] == "INFERRED" and ti["literal_match"] is False)
check("9b inferred high gate held", MIN_SEMANTIC_SCORE_3D == 0.82)

# ── 10: B-roll present -> no 3D ──
check("10 strong broll -> no 3D",
      select_object_3d(W("antes de viajar al extranjero para una estancia larga lejos"),
                       existing_visuals={**NV, "broll_strong": True}, clip_duration_s=26.0, task_context=CTX) is None)

# ── tier classifier directly ──
check("T literal travel tier", classify_evidence_tier("travel_suitcase_3d", [{"matched_norm": "al extranjero", "evidence_strength": "strong"}])["tier"] == "LITERAL_STRONG")
check("T non-literal excluded", classify_evidence_tier("protection_shield_3d", [{"matched_norm": "respaldo", "evidence_strength": "strong"}])["tier"] == "INFERRED")
check("T floor=0.5", abs(LITERAL_FLOOR - 0.5) < 1e-9)
check("T gate version", GATE_VERSION == "3d-gate-53b-v1")

# ── provenance fields present on an accepted decision ──
d = sel("antes de viajar al extranjero para una estancia larga lejos de aqui")
check("P provenance fields", d is not None and d.gate_version == GATE_VERSION and d.literal_match is True and d.gate_reason.startswith("literal_strong:"))

# ── 11–12: sibling + 53 suites green ──
_TDIR = Path(__file__).resolve().parent
SUITES = {
    "11 SELECTION-52B": str(_TDIR / "test_selection_52b.py"),
    "11 VISUAL-COVERAGE-52C": str(_TDIR / "test_visual_coverage_52c.py"),
    "11 HOOK-RHYTHM-52D": str(_TDIR / "test_hook_rhythm_52d.py"),
    "11 DELIVERY-GATE-52E": str(_TDIR / "test_delivery_gate_52e.py"),
    "12 OBJECTS-3D-53": str(_TDIR / "test_objects_3d_53.py"),
}
for label, path in SUITES.items():
    if not Path(path).exists():
        print("SKIP", label); continue
    r = subprocess.run(["/app/.venv/bin/python", path], capture_output=True, text=True, timeout=400)
    check(f"{label} green", r.returncode == 0)
    if r.returncode != 0:
        print(r.stdout[-600:], r.stderr[-300:])

print()
if FAIL:
    print("RESULT: FAIL ->", FAIL); sys.exit(1)
print("RESULT: ALL GREEN")
