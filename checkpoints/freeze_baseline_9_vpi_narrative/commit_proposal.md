# Propuesta de commit seguro — v0.3.0-vpi-narrative-baseline (NO ejecutado)

## Por qué este alcance
La baseline validada es el working tree COMPLETO de código (el worker monta
backend/src tal cual). Commitear solo los 6 ficheros de los bloques 8/8B/9
produciría un estado roto: 20 módulos core (vpi_disfluency_editor,
vpi_editorial_fluency_service, vpi_timeline_plan, vpi_ass_caption_service…)
son UNTRACKED y los importa el runtime. El corte seguro es:
código+config+manifests SÍ · media/outputs/checkpoints pesados NO.

## git add sugerido (en este orden, SIN -A)
# 1) Tracked modificados (86) — incluye toda la lista obligatoria del bloque:
git add -u

# 2) Módulos runtime nuevos (untracked, imprescindibles):
git add backend/src/services/vpi_3d_object_registry.py backend/src/services/vpi_animated_asset_registry.py \
  backend/src/services/vpi_ass_caption_service.py backend/src/services/vpi_complete_idea_gate.py \
  backend/src/services/vpi_disfluency_editor.py backend/src/services/vpi_dynamic_overlay_text_service.py \
  backend/src/services/vpi_editly_exporter.py backend/src/services/vpi_editorial_fluency_service.py \
  backend/src/services/vpi_face_safe_layout.py backend/src/services/vpi_fast_fail_rescue.py \
  backend/src/services/vpi_gpu_runtime.py backend/src/services/vpi_lottie_asset_registry.py \
  backend/src/services/vpi_metadata_normalization.py backend/src/services/vpi_motion_grammar.py \
  backend/src/services/vpi_motion_overlay_service.py backend/src/services/vpi_overlay_renderer_adapter.py \
  backend/src/services/vpi_remotion_scene_plan.py backend/src/services/vpi_task_source_contract.py \
  backend/src/services/vpi_timeline_plan.py backend/src/services/vpi_visual_priority_guard.py

# 3) Config y migraciones (untracked, runtime las lee):
git add configs backend/alembic

# 4) Registries/manifests de assets (solo JSON, nada de media):
git add assets/vpi_3d_asset_sources.json assets/vpi_3d_asset_sources.schema.json \
  assets/vpi_3d_object_registry.json assets/vpi_animated_asset_registry.json

# 5) Frontend nuevo (error/loading pages, prisma migrations, scripts):
git add frontend/prisma/migrations frontend/scripts \
  "frontend/src/app/error.tsx" "frontend/src/app/global-error.tsx" "frontend/src/app/loading.tsx" \
  "frontend/src/app/dashboard/error.tsx" "frontend/src/app/dashboard/loading.tsx" \
  "frontend/src/app/sign-in/error.tsx" "frontend/src/app/sign-in/loading.tsx" \
  "frontend/src/app/tasks/[id]/error.tsx" "frontend/src/app/tasks/[id]/loading.tsx"

# 6) Documentación de checkpoints (solo texto; sin frames/traces/mp4):
git add checkpoints/freeze_baseline_9_vpi_narrative \
  checkpoints/validation_3videos_stress/VALIDATION_3VIDEOS_STRESS_SUMMARY.md \
  checkpoints/output_cuts_8_apply_disfluency_cuts/{OUTPUT_CUTS_8_SUMMARY.md,diagnosis.md,files_changed.txt,test_output_cuts.py,test_results.txt} \
  checkpoints/output_cuts_8b_false_positive_guard/{OUTPUT_CUTS_8B_SUMMARY.md,diagnosis.md,test_false_positive_guard.py,test_results.txt} \
  checkpoints/output_narrative_9_closure_planner/{OUTPUT_NARRATIVE_9_SUMMARY.md,diagnosis.md,test_narrative_9.py,test_results.txt} \
  checkpoints/output_narrative_9_closure_planner/resmoke_videos_2_3/RESMOKE_VIDEOS_2_3_SUMMARY.md

## Validación ANTES del commit (sugerida, no ejecutada)
git add -n -u                                  # dry-run, revisar lista
git diff --check                               # whitespace/conflictos en tracked
git diff --cached --check                      # idem en staged
git status --short | grep "^A\|^M" | head -50  # revisar staging final
# compile de todos los .py candidatos dentro del venv del worker:
docker exec viraclip-worker /app/.venv/bin/python3 -m compileall -q /app/src/services && echo PY_OK
# regresiones rápidas ya conocidas:
PYTHONDONTWRITEBYTECODE=1 python3 checkpoints/output_cuts_8_apply_disfluency_cuts/test_output_cuts.py
PYTHONDONTWRITEBYTECODE=1 python3 checkpoints/output_cuts_8b_false_positive_guard/test_false_positive_guard.py
docker exec -i viraclip-worker /app/.venv/bin/python3 - < checkpoints/output_narrative_9_closure_planner/test_narrative_9.py
# opcional (lento): cd frontend && npx tsc --noEmit

## Commit y tag (después de validar)
git commit -m "v0.3.0-vpi-narrative-baseline"
git tag v0.3.0-vpi-narrative-baseline

## Notas de riesgo
1. NO usar `git add -A`: arrastraría outputs/ (3GB), checkpoints/ (395MB),
   assets/broll (640MB), overlays_staging (229MB) y frontend/~ (1.7GB).
2. `frontend/~/` es un directorio basura accidental de 1.7GB en el repo —
   revisar su contenido y borrarlo a mano (no lo toco en este bloque).
3. outputs/ NO está en .gitignore — recomendar añadir outputs/, checkpoints/
   (o subcarpetas pesadas), assets/broll/, assets/overlays_staging/ y
   "frontend/~/" a .gitignore en un commit posterior.
4. assets/fonts (21MB) queda fuera; si el build del contenedor los necesita
   desde el repo, decidir aparte (hoy backend/fonts ya está montado).
5. Los 163 scripts untracked (debug/regression) son texto válido para un
   commit aparte "tooling", no mezclarlos con la baseline.
6. reports/editorial_eval/preflight_latest.* son generados pero ya tracked:
   entran con `git add -u` (riesgo bajo, son texto pequeño).
