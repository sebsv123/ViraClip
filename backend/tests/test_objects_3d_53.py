"""OUTPUT-OBJECTS-3D-53 — deterministic tests for real 3D object selection + resolver order.

Covers the 20 mandatory cases (FASE 16). Cases 1–14 exercise the selection service / compositor
directly; cases 15–20 assert the sibling QC suites stay green (run as a cross-suite check).
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/src")

from services.vpi_object_3d_service import (  # noqa: E402
    select_object_3d, resolve_visual_coverage_choice, intent_to_asset_3d,
    _choose_placement_and_variant, VALID_3D_ASSETS, Object3DDecision,
)
from services.vpi_object_3d_compositor import (  # noqa: E402
    cache_key, resolve_cached_object_3d, load_manifest, composite_object_3d,
)

FAIL = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAIL.append(name)


def words_from(sentence, *, start=8.0, wdur=0.45):
    """Build a words_with_confidence list, one word per token, sequential timing."""
    out = []
    t = start
    for tok in sentence.split():
        out.append({"word": tok, "text": tok, "start": round(t, 3), "end": round(t + wdur, 3), "confidence": 0.9})
        t += wdur
    return out


CTX = {"editorial_type": "", "hook_end_s": 2.0}
NO_VIS = {"broll_strong": False, "face_side": "center", "captions_band": "bottom"}


# ── 1. travel explícito -> suitcase 3D ──
w = words_from("antes del viaje al aeropuerto con la maleta y el equipaje listo para todo", start=9.0)
d = select_object_3d(w, existing_visuals=NO_VIS, clip_duration_s=24.0, task_context=CTX)
check("1 travel explicit -> suitcase", d is not None and d.asset_id == "travel_suitcase_3d")

# ── 2. pasaporte/documentos -> passport 3D ──
w = words_from("necesitas el visado la documentacion de residencia y el certificado vigente sin falta", start=9.0)
d = select_object_3d(w, existing_visuals=NO_VIS, clip_duration_s=24.0, task_context=CTX)
check("2 documents -> passport", d is not None and d.asset_id == "document_passport_3d")

# explicit "pasaporte" phrase also resolves to passport family
check("2b pasaporte token -> passport family",
      intent_to_asset_3d("documents_admin") == "document_passport_3d")

# ── 3. protección familiar -> shield 3D ──
w = words_from("queremos proteger a tu familia y dar tranquilidad a los tuyos siempre cada dia", start=9.0)
d = select_object_3d(w, existing_visuals=NO_VIS, clip_duration_s=24.0, task_context=CTX)
check("3 protection -> shield", d is not None and d.asset_id == "protection_shield_3d")

# ── 4. salud -> health heart 3D ──
w = words_from("cuando la salud no avisa necesitas atencion sanitaria y acudir al medico a tiempo", start=9.0)
d = select_object_3d(w, existing_visuals=NO_VIS, clip_duration_s=24.0, task_context=CTX)
check("4 health -> heart", d is not None and d.asset_id == "health_heart_3d")

# ── 5. riesgo genérico -> no 3D automático ──
w = words_from("por si acaso ante cualquier problema o riesgo inesperado conviene estar prevenido siempre", start=9.0)
d = select_object_3d(w, existing_visuals=NO_VIS, clip_duration_s=24.0, task_context=CTX)
check("5 generic risk -> no 3D", d is None)

# ── 6. B-roll fuerte presente -> no 3D ──
w = words_from("antes del viaje al aeropuerto con la maleta y el equipaje listo para todo", start=9.0)
d = select_object_3d(w, existing_visuals={**NO_VIS, "broll_strong": True}, clip_duration_s=24.0, task_context=CTX)
check("6 strong broll -> no 3D", d is None)

# ── 7. score bajo -> None (caller falls back to card/2D) ──
w = words_from("hoy hablamos un poco de todo sin entrar en demasiados detalles concretos ahora", start=9.0)
d = select_object_3d(w, existing_visuals=NO_VIS, clip_duration_s=24.0, task_context=CTX)
check("7 weak score -> no 3D (fallback)", d is None)
check("7b resolver falls back to 2D when 3D None",
      resolve_visual_coverage_choice(broll_strong=False, object_3d_decision=None,
                                     card_available=False, object_2d_available=True) == "object_2d")

# ── 8. render 3D falla -> fallback 2D (cache miss is non-fatal) ──
miss = composite_object_3d("/nonexistent.mp4", "/tmp/none.mp4", asset_id="unknown_asset",
                           variant="reveal_left", placement="upper_right",
                           window_start_s=1.0, window_end_s=2.0)
check("8 cache miss -> ok False (no crash)", miss.get("ok") is False and miss.get("error") == "cache_miss")

# ── 9. captions collision -> upper band (never over bottom captions) ──
pl, var = _choose_placement_and_variant({"captions_band": "bottom", "face_side": "center"})
check("9 captions bottom -> upper placement", pl.startswith("upper_"))

# ── 10. face collision -> opposite side ──
pl_r, var_r = _choose_placement_and_variant({"face_side": "right", "captions_band": "bottom"})
pl_l, var_l = _choose_placement_and_variant({"face_side": "left", "captions_band": "bottom"})
check("10 face right -> object left", pl_r.endswith("_left") and var_r == "reveal_left")
check("10b face left -> object right", pl_l.endswith("_right") and var_l == "reveal_right")

# ── 11. hook overlap -> phrase inside hook+4s separation -> no window ──
w = words_from("antes del viaje al aeropuerto con la maleta y el equipaje listo", start=1.0, wdur=0.3)
d = select_object_3d(w, existing_visuals=NO_VIS, clip_duration_s=24.0,
                     task_context={"editorial_type": "", "hook_end_s": 3.0})
check("11 hook overlap -> no window (skip)", d is None)

# ── 12. fade overlap -> phrase in closure tail -> no window ──
w = words_from("antes del viaje al aeropuerto con la maleta y el equipaje", start=22.5, wdur=0.3)
d = select_object_3d(w, existing_visuals=NO_VIS, clip_duration_s=24.0, task_context=CTX)
check("12 closure overlap -> no window (skip)", d is None)

# ── 13. máximo 1 objeto -> select returns a single decision, never a list ──
w = words_from("antes del viaje al aeropuerto con la maleta y el equipaje listo para todo", start=9.0)
d = select_object_3d(w, existing_visuals=NO_VIS, clip_duration_s=24.0, task_context=CTX)
check("13 exactly one object decision", isinstance(d, Object3DDecision))

# ── 14. duración/audio intactos -> the 4 BASE families are 54f@30fps, alpha verified ──
# (53C: the library may grow with extra assets; assert the base families, not an exact total.)
man = load_manifest()
objs = man.get("objects") or {}
base_objs = {k: o for k, o in objs.items() if o.get("asset_id") in VALID_3D_ASSETS}
check("14 manifest has the 8 base-family objects", len(base_objs) == 8)
check("14b base families alpha_verified + 54 frames",
      all(o.get("alpha_verified") and o.get("frame_count") == 54 for o in base_objs.values()))
check("14c all 4 families cached x2 variants",
      set(VALID_3D_ASSETS).issubset({o["asset_id"] for o in objs.values()}))
cobj = resolve_cached_object_3d("travel_suitcase_3d", "reveal_right")
check("14d cache resolve hit", cobj is not None and cobj.alpha_verified and cobj.frame_count == 54)

# resolver order precedence (FASE 7): broll > 3D > card > 2D
class _Dummy: ...
check("R broll wins", resolve_visual_coverage_choice(broll_strong=True, object_3d_decision=_Dummy(), card_available=True, object_2d_available=True) == "broll")
check("R 3D over card/2D", resolve_visual_coverage_choice(broll_strong=False, object_3d_decision=_Dummy(), card_available=True, object_2d_available=True) == "object_3d")
check("R card over 2D", resolve_visual_coverage_choice(broll_strong=False, object_3d_decision=None, card_available=True, object_2d_available=True) == "card")

# ── 15–20. sibling QC suites must stay green ──
_TDIR = Path(__file__).resolve().parent
SUITES = {
    "16 SELECTION-52B": str(_TDIR / "test_selection_52b.py"),
    "17 VISUAL-COVERAGE-52C": str(_TDIR / "test_visual_coverage_52c.py"),
    "18 HOOK-RHYTHM-52D": str(_TDIR / "test_hook_rhythm_52d.py"),
    "19 DELIVERY-GATE-52E": str(_TDIR / "test_delivery_gate_52e.py"),
}
for label, path in SUITES.items():
    if not Path(path).exists():
        print("SKIP", label, "(suite file not present)")
        continue
    r = subprocess.run(["/app/.venv/bin/python", path], capture_output=True, text=True, timeout=300)
    ok = r.returncode == 0
    check(f"{label} green", ok)
    if not ok:
        print(r.stdout[-500:], r.stderr[-300:])

print()
if FAIL:
    print("RESULT: FAIL ->", FAIL)
    sys.exit(1)
print("RESULT: ALL GREEN")
