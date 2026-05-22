# ViraClip — Diagnóstico y Limpieza Estructural

## 1. Estado Actual (resumido)

- Monorepo con 3 apps activas: `backend/`, `frontend/`, `waitlist/` + `rust-agent/` + `nginx/`
- Backend migrado de monolito a dominios, pero arrastra ~20 scripts `.py` huérfanos en raíz
- 8 documentos BROLL_*.md de diagnóstico ya resueltos, nunca limpiados
- 3 directorios `archive/` con código muerto (backend, docs, tools) que ya no importa nadie
- `agente_seguros_ai/`: proyecto ajeno no relacionado, ocupa 3MB, tracked en git
- Archivos fantasma: `-c`, `-d`, `-H` (0 bytes), `Untitled.ipynb`, `docker-compose.yml.old`
- `backend/vendor/`: 7 forks de terceros no integrados en `requirements.txt`
- `backend/tests/`: ~170 tests, muchos phase_* legacy, sin suite ejecutable unificada

## 2. Problemas Detectados (ordenados por impacto)

| # | Impacto | Problema |
|---|---------|----------|
| P1 | ALTO | `agente_seguros_ai/` — proyecto externo dentro del repo, 3MB, 50+ archivos |
| P2 | ALTO | 20 scripts `.py` huérfanos en `backend/` raíz (process_*.py, test_*.py, viraclip_*.py) |
| P3 | MEDIO | 8 documentos BROLL_*.md de diagnóstico ya resueltos en `backend/` |
| P4 | MEDIO | `docker-compose.yml.old` — backup de una versión anterior |
| P5 | MEDIO | `docs/archive/` y `tools/archive/` — documentación y scripts obsoletos |
| P6 | BAJO | Archivos fantasma `-c`, `-d`, `-H` (0 bytes, creados accidentalmente) |
| P7 | BAJO | `Untitled.ipynb` — notebook Jupyter sin contenido relevante |
| P8 | BAJO | `backend/archive/` — 3 archivos Python legacy (broll_root.py, video_utils_legacy.py, video_utils_old.py) |
| P9 | BAJO | `backend/vendor/` — 7 forks no integrados, sin referencia en imports del proyecto |
| P10 | INFORMATIVO | `backend/tests/` — 170 tests, muchos phase_* legacy, pero no se tocan (tests) |
| P11 | INFORMATIVO | `backend/migrations/` y `backend/alembic/` coexisten — dos sistemas de migración |

## 3. Elementos a Conservar

- `backend/src/` — código activo del backend
- `backend/scripts/` — scripts de utilidad (se usan)
- `backend/tests/` — tests existentes (no se modifican)
- `backend/Dockerfile`, `backend/pyproject.toml`, `backend/requirements.txt`
- `frontend/`, `waitlist/`, `rust-agent/`, `nginx/` — apps activas
- `docker-compose.yml`, `init.sql`, `.env.example`, `Makefile`
- `docs/` — documentación activa (api-reference.md, architecture.md, etc.)
- `scripts/` — scripts operativos activos
- `assets/`, `transitions/`, `workflows/` — assets del proyecto
- `backend/fonts/`, `backend/music/`, `backend/comfy_workflows/`, `backend/assets/luts/` — recursos
- `backend/bin/start.sh` — script de entrada
- `backend/README.md`, `backend/REFACTORING_GUIDE.md` — docs útiles del backend
- `backend/AUDIT_REPORT.md`, `backend/PIPELINE_TRACE.md` — informes técnicos (se conservan)

## 4. Elementos a Eliminar

### 4.1 Proyecto externo
- `agente_seguros_ai/` — proyecto ajeno, no pertenece a ViraClip

### 4.2 Scripts huérfanos en backend/ raíz (no importados por src/, no referenciados en docker-compose)
- `backend/check_tasks.py` — script de depuración puntual
- `backend/check_users.py` — script de depuración puntual
- `backend/download_music.py` — one-off
- `backend/generate_clips_now.py` — one-off
- `backend/load_env.py` — utilidad no referenciada
- `backend/process_ai_standalone.py` — prototipo
- `backend/process_now.py` — prototipo
- `backend/process_real_videos.py` — prototipo
- `backend/process_simple.py` — prototipo
- `backend/process_videos_real.py` — prototipo
- `backend/process_with_logs.py` — prototipo
- `backend/run_test.py` — obsoleto (existe run_tests.py y pytest.ini)
- `backend/run_tests.py` — duplicado funcional de pytest
- `backend/temp_tiktok_font_urls.css` — archivo temporal
- `backend/test_e2e_youtube.py` — test puntual
- `backend/test_frankenstein.py` — test puntual
- `backend/test_llm_connection.py` — test puntual
- `backend/test_single_video.py` — test puntual
- `backend/trigger_live_test.py` — test puntual
- `backend/viraclip_ai_processor.py` — prototipo
- `backend/viraclip_ai_real.py` — prototipo
- `backend/viraclip_pipeline.py` — prototipo
- `backend/fix_clip_renderer.py` — script de reparación one-off
- `backend/fix_indent.py` — script de reparación one-off

### 4.3 Documentos de diagnóstico BROLL (ya resueltos)
- `backend/BROLL_DIAGNOSTIC.md`
- `backend/BROLL_OVERLAY_FIX.md`
- `backend/BROLL_GAP_ANALYSIS.md`
- `backend/BROLL_DOUBLE_SYSTEM_DIAGNOSIS.md`
- `backend/BROLL_FAKE_TIMESTAMPS_FIX.md`
- `backend/BROLL_ANTI_REPETITION_FIX.md`
- `backend/BROLL_CONSTANTS_CONSOLIDATION.md`
- `backend/BROLL_ACCEPTANCE_CRITERIA.md`
- `backend/BROLL_FAKE_TIMESTAMPS_DIAGNOSIS.md`
- `backend/BROLL_VALIDATION_REPORT.md`

### 4.4 Archivos huérfanos en raíz del proyecto
- `docker-compose.yml.old` — backup de versión anterior
- `.env.broll` — claves API duplicadas (ya están en .env.example)
- `Untitled.ipynb` — notebook vacío/sin contenido
- `-c`, `-d`, `-H` — archivos fantasma de 0 bytes

### 4.5 Archivos de reportes de ejecución
- `backend/processing_report_20260331_002327.json` — reporte de una ejecución
- `backend/test_report_20260331_000335.json` — reporte de tests

### 4.6 Archivos de migración duplicados/obsoletos
- `backend/v2_migration.sql` — migración ya aplicada (alembic gestiona migraciones)

### 4.7 Archivos de configuración obsoletos
- `backend/CONFIG_VIDEOFY.md` — doc de feature opt-in no usado

### 4.8 Archivos de documentación archivada
- `docs/archive/` — documentación antigua reemplazada por docs/ actual
- `tools/archive/` — scripts y herramientas obsoletas

### 4.9 Código legacy en backend/archive/
- `backend/archive/broll_root.py` — reemplazado por src/domains/broll/
- `backend/archive/video_utils_legacy.py` — reemplazado por src/domains/video/
- `backend/archive/video_utils_old.py` — reemplazado por src/domains/video/

### 4.10 Vendor forks no integrados
- `backend/vendor/` — 7 forks de terceros que no se importan desde src/

## 5. Plan Mínimo de Cambios (orden de ejecución)

1. **Eliminar archivos fantasma**: `-c`, `-d`, `-H`
2. **Eliminar `Untitled.ipynb`**
3. **Eliminar `docker-compose.yml.old`**
4. **Eliminar `.env.broll`** (claves duplicadas)
5. **Eliminar reportes JSON**: `processing_report_*.json`, `test_report_*.json`
6. **Eliminar `backend/v2_migration.sql`**
7. **Eliminar `backend/CONFIG_VIDEOFY.md`**
8. **Eliminar `backend/temp_tiktok_font_urls.css`**
9. **Eliminar 25 scripts huérfanos de `backend/` raíz**
10. **Eliminar 10 documentos BROLL_*.md**
11. **Eliminar `backend/archive/`** (3 archivos legacy)
12. **Eliminar `docs/archive/`** (14 documentos obsoletos)
13. **Eliminar `tools/archive/`** (45 scripts obsoletos)
14. **Eliminar `backend/vendor/`** (7 forks no integrados)
15. **Eliminar `agente_seguros_ai/`** (proyecto externo)

## 6. Riesgos de Cada Cambio

| Cambio | Riesgo | Mitigación |
|--------|--------|------------|
| 1-8 (archivos huérfanos) | NINGUNO | No referenciados por ningún código activo |
| 9 (scripts backend/) | BAJO | Verificar que ningún Dockerfile o docker-compose los referencia |
| 10 (BROLL_*.md) | NINGUNO | Solo documentación de diagnóstico |
| 11 (backend/archive/) | NINGUNO | Código legacy no importado por src/ |
| 12 (docs/archive/) | NINGUNO | Docs reemplazados por docs/ actuales |
| 13 (tools/archive/) | NINGUNO | Scripts obsoletos, reemplazados por scripts/ |
| 14 (backend/vendor/) | MEDIO | Verificar que ningún import en src/ apunte a vendor/ |
| 15 (agente_seguros_ai/) | BAJO | Proyecto externo, no relacionado. Confirmar que no hay dependencias |

## 7. Verificación Final Esperada

- `git status` muestra solo los archivos eliminados (no cambios en código activo)
- `docker-compose build` no se rompe (ningún Dockerfile referencia archivos eliminados)
- `cd backend && python -c "from src.main import app"` importa sin errores
- `cd frontend && npm run lint` pasa sin errores nuevos
- El repo queda ~5-10% más ligero y sin artefactos muertos
