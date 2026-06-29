"""OUTPUT-OBJECTS-3D-53C — self-expanding 3D library tests."""
import copy
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/src")

from services.vpi_object_3d_recipe_service import (  # noqa: E402
    RECIPES, ALLOWED_COMPONENTS, extract_concepts, select_concept, resolve_concept_to_asset,
    is_generic_concept, register_asset, validate_render, load_catalog, recipe_for_concept,
)
from services.vpi_object_3d_compositor import resolve_cached_object_3d  # noqa: E402

FAIL = []
def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAIL.append(name)

REC = RECIPES["medical_reimbursement_3d"]
ROOT = Path("/app/assets/objects_3d/rendered")

def good_variant_renders():
    vr = {}
    for v in ("reveal_left", "reveal_right"):
        key = f"medical_reimbursement_3d__{v}__720x720__30fps__51f__vpi-3d-v1"
        p = ROOT / (key + ".webm")
        vr[v] = {"cache_key": key, "render_path": str(p), "frame_count": 51, "fps": 30,
                 "duration_s": 1.7, "validation": validate_render(p)}
    return vr

TXT = ("hablemos del reembolso en las polizas de salud. el reembolso es para todo el mundo. "
       "con las polizas de reembolso pasa mucho. una poliza con reembolso. libertad para elegir "
       "especialistas. que tipo de tranquilidad esta buscando.")

# 1. reembolso sin asset -> genera y registra (fresh empty catalog)
cands = extract_concepts(TXT)
sel = select_concept(cands)
check("1a concept selected = reembolso", sel is not None and sel.concept == "reembolso médico")
rec = recipe_for_concept(sel.concept)
check("1b recipe found", rec is not None and rec.asset_id == "medical_reimbursement_3d")
fresh = {"version": 1, "assets": {}}
res = register_asset(fresh, rec, variant_renders=good_variant_renders(),
                     created_from_task="t-test", run_new_count=0)
check("1c registers into empty catalog", res["registered"] is True and "medical_reimbursement_3d" in fresh["assets"])
check("1d registered asset is approved+pixel+alpha", fresh["assets"]["medical_reimbursement_3d"]["approved"]
      and fresh["assets"]["medical_reimbursement_3d"]["pixel_verified"]
      and fresh["assets"]["medical_reimbursement_3d"]["alpha_verified"])

# 2. reembolso posterior -> reutiliza (already present, no second mint)
res2 = register_asset(fresh, rec, variant_renders=good_variant_renders(), created_from_task="t2", run_new_count=0)
check("2 second register -> already_present (reuse)", res2["registered"] is False and res2["reason"] == "already_present")
check("2b resolves to same asset", resolve_concept_to_asset("reembolso", fresh) == "medical_reimbursement_3d")

# 3. gastos medicos -> mismo asset (alias reuse)
check("3 gastos medicos alias -> same asset", resolve_concept_to_asset("gastos medicos", fresh) == "medical_reimbursement_3d")
check("3b poliza con reembolso -> same asset", resolve_concept_to_asset("poliza con reembolso", fresh) == "medical_reimbursement_3d")

# 4. tranquilidad -> no genera
check("4 tranquilidad generic", is_generic_concept("tranquilidad") is True)
check("4b tranquilidad not selected", all(c.concept != "tranquilidad" or c.generic for c in cands))
check("4c tranquilidad resolves to nothing", resolve_concept_to_asset("tranquilidad", fresh) is None)

# 5. concepto ambiguo / abstracto (libertad) -> no genera
check("5 libertad generic/abstract -> no mint", is_generic_concept("libertad de elección") is True
      and recipe_for_concept("libertad de elección") is None)
empty_sel = select_concept([c for c in extract_concepts("hoy hablamos de libertad y tranquilidad sin mas")])
check("5b only-abstract transcript -> no concrete concept", empty_sel is None)

# 6. render inválido -> no registra
bad_vr = good_variant_renders()
bad_vr["reveal_left"]["validation"] = {"ok": False, "alpha_verified": True, "frame_count": 0, "reason": "no_frames"}
check("6 invalid render -> refused", register_asset({"assets": {}}, rec, variant_renders=bad_vr, created_from_task="t", run_new_count=0)["registered"] is False)

# 7. alpha inválido -> no registra
bad_a = good_variant_renders()
bad_a["reveal_right"]["validation"] = {"ok": False, "alpha_verified": False, "frame_count": 51, "reason": "no_alpha"}
check("7 invalid alpha -> refused", register_asset({"assets": {}}, rec, variant_renders=bad_a, created_from_task="t", run_new_count=0)["registered"] is False)

# 8. timeout/missing -> fallback (compositor returns ok False, no crash)
from services.vpi_object_3d_compositor import composite_object_3d
miss = composite_object_3d("/nope.mp4", "/tmp/x.mp4", asset_id="medical_reimbursement_3d",
                           variant="reveal_right", placement="upper_right", window_start_s=1.0, window_end_s=2.0)
check("8 missing master -> ok False fallback", miss.get("ok") is False)

# growth control: max 1 new asset per task
check("G max-1-new-per-task", register_asset({"assets": {}}, rec, variant_renders=good_variant_renders(),
      created_from_task="t", run_new_count=1)["reason"] == "max_new_assets_per_task_reached")
# component whitelist
check("G components whitelisted", all(c in ALLOWED_COMPONENTS for c in REC.components))
# real catalog has the asset + cache resolves (51 frames)
real = load_catalog()
check("R real catalog has asset", "medical_reimbursement_3d" in (real.get("assets") or {}))
c = resolve_cached_object_3d("medical_reimbursement_3d", "reveal_left")
check("R cache resolves 51f asset", c is not None and c.frame_count == 51 and c.alpha_verified)

# 9/10 sibling + 53/53B suites green
_TDIR = Path(__file__).resolve().parent
SUITES = {
    "9 SELECTION-52B": "test_selection_52b.py", "9 VISUAL-COVERAGE-52C": "test_visual_coverage_52c.py",
    "9 HOOK-RHYTHM-52D": "test_hook_rhythm_52d.py", "9 DELIVERY-GATE-52E": "test_delivery_gate_52e.py",
    "10 OBJECTS-3D-53": "test_objects_3d_53.py", "10 OBJECTS-3D-53B": "test_objects_3d_53b.py",
}
for label, fn in SUITES.items():
    p = _TDIR / fn
    if not p.exists():
        print("SKIP", label); continue
    r = subprocess.run(["/app/.venv/bin/python", str(p)], capture_output=True, text=True, timeout=400)
    check(f"{label} green", r.returncode == 0)
    if r.returncode != 0:
        print(r.stdout[-500:], r.stderr[-200:])

print()
if FAIL:
    print("RESULT: FAIL ->", FAIL); sys.exit(1)
print("RESULT: ALL GREEN")
