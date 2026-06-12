# VPI Asset Library

> Librería premium local de assets para ViraClip VPI editorial pipeline.
> Assets verificados con manifest, licencias y metadata editorial.

---

## Estructura de carpetas esperada

```
assets/
├── broll/                          # B-roll footage (MP4/MOV/WEBM)
│   ├── family_relief/
│   ├── emotional_support/
│   ├── health_access/
│   ├── medical_care/
│   ├── autonomous_work_stability/
│   ├── office_work/
│   ├── practical_explanation/
│   ├── paperwork_support/
│   ├── risk_warning_context/
│   ├── calm_lifestyle/
│   └── family_home/
├── sounds/
│   ├── sfx/                        # Sound effects (WAV/MP3)
│   │   ├── dark_riser/
│   │   ├── tension_riser/
│   │   ├── high_riser/
│   │   ├── magic_whoosh/
│   │   ├── deep_boom/
│   │   ├── soft_chime/
│   │   ├── click_soft/
│   │   └── ambient_soft/
│   └── bgm/                        # Background music (WAV/MP3)
│       ├── warm_trust/
│       ├── clean_corporate/
│       ├── soft_health/
│       ├── subtle_tension/
│       ├── emotional_family/
│       └── modern_explainer/
├── icons/                          # Icon SVGs
│   ├── family/
│   ├── health/
│   ├── shield/
│   ├── heart/
│   ├── warning/
│   ├── briefcase/
│   ├── document/
│   ├── euro/
│   ├── calendar/
│   ├── phone/
│   ├── support/
│   ├── checklist/
│   ├── hospital/
│   ├── user/
│   └── home/
├── overlays/                       # Motion overlay objects normalizados (WEBM/MP4)
│   ├── shield/
│   ├── heart/
│   ├── warning/
│   ├── document/
│   ├── checklist/
│   ├── euro/
│   ├── health/
│   ├── calendar/
│   ├── phone/
│   ├── cta/
│   ├── message_bubble/
│   ├── price_badge/
│   ├── coverage_card/
│   ├── review_card/
│   ├── agent_card/
│   ├── limited_time/
│   ├── hook_card/
│   ├── whatsapp_card/
│   ├── promo_badge/
│   ├── notification_card/          # Swishy v1 — notification/micro overlay
│   ├── glow_text/                  # Swishy v1 — strong card, hook reveal
│   ├── time_passage/               # Swishy v1 — urgency/plazo micro overlay
│   ├── finance_chart/              # Swishy v1 — strong card, claim review required
│   ├── stat_card/                  # Swishy v1 — strong card, claim review required
│   ├── timeline_card/              # Swishy v1 — strong card, step-by-step
│   ├── toggle_card/                # Swishy v1 — strong card, comparison
│   ├── folder_gallery/             # Swishy v1 — micro overlay, documents
│   ├── typewriter_text/            # Swishy v1 — micro overlay, quotes
│   ├── location_popup/             # Swishy v1 — micro overlay, office location
│   └── keyword_spin/               # Swishy v1 — micro overlay, emphasis
├── overlays_staging/               # Staging para GIFs sin normalizar
│   └── swishy_gif/                 # GIFs exportados desde Swishy (raw, no registrar)
│       ├── notification_card/
│       ├── glow_text/
│       ├── time_passage/
│       ├── finance_chart/
│       ├── stat_card/
│       ├── timeline_card/
│       ├── toggle_card/
│       ├── folder_gallery/
│       ├── typewriter_text/
│       ├── location_popup/
│       ├── keyword_spin/
│       ├── _discarded/             # GIFs descartados tras revisión
│       └── _needs_review/          # GIFs pendientes de revisión visual

├── fonts/                          # Font files (TTF/OTF)
│   ├── Manrope/
│   ├── Inter/
│   └── DM_Sans/
├── vpi_asset_manifest.json         # Manifest activo (registro de assets verificados)
├── vpi_asset_manifest.template.json # Template para nuevos manifests
└── README_ASSET_LIBRARY.md         # Este archivo
```

---

## Cómo añadir assets

### 1. Descargar el asset

Descargar manualmente desde las fuentes aprobadas (ver `docs/vpi_asset_source_plan.md`).

### 2. Colocar en la ruta correcta

Seguir la naming convention:

| Tipo | Patrón |
|------|--------|
| B-roll | `assets/broll/<intent>/<intent>_<source>_<###>.mp4` |
| SFX | `assets/sounds/sfx/<family>/<family>_<source>_<###>.mp3` |
| BGM | `assets/sounds/bgm/<mood>/<mood>_<source>_<###>.mp3` |
| Icons | `assets/icons/<concept>/<concept>_<set>_<###>.svg` |
| Motion Overlay (standard) | `assets/overlays/<concept>/<concept>_<source>_<###>.webm` |
| Motion Overlay (Swishy v1) | `assets/overlays/<swishy_family>/<swishy_family>_swishy_<###>.webm` |
| Fonts | `assets/fonts/<family>/<file>.ttf` |


### 3. Registrar en el manifest

Añadir entrada en `assets/vpi_asset_manifest.json`:

```json
{
  "id": "family_relief_pexels_001",
  "type": "broll",
  "path": "assets/broll/family_relief/family_relief_pexels_001.mp4",
  "source": "pexels",
  "source_url": "https://www.pexels.com/video/...",
  "license_name": "Pexels License",
  "commercial_use_ok": true,
  "attribution_required": false,
  "tags": ["family_relief", "emotional_support", "warm_family"],
  "topics": ["decesos", "vida", "familia"],
  "sensitive_tone": "safe",
  "avoid_for": ["risk_warning_aggressive"],
  "duration_hint": 5.0
}
```

### 4. Ejecutar validación

```bash
python scripts/debug_asset_library_pack.py
python scripts/vpi_editorial_preflight.py --strict
```

---

## Estados de asset

| Estado | Significado |
|--------|-------------|
| `verified` | Asset en manifest con todos los campos válidos, archivo existe, licencia OK |
| `unverified_local` | Archivo encontrado en disco pero NO registrado en manifest |
| `invalid` | Asset en manifest pero falla validación (licencia, ruta, archivo faltante) |
| `attribution_required` | Asset válido pero requiere atribución en descripción del video |
| `commercial_use_ok` | Asset con licencia que permite uso comercial |

---

## ASSET_LIBRARY_STATUS

El QC report genera uno de estos estados:

| Status | Significado | ¿Bloquea preflight? |
|--------|-------------|---------------------|
| `EMPTY` | No hay assets verificados en ninguna categoría | ❌ No |
| `PARTIAL` | Algunas categorías tienen assets, pero no se alcanzan los thresholds READY | ❌ No |
| `READY` | Todas las categorías cumplen los thresholds mínimos | ❌ No |
| `INVALID` | Hay assets en manifest con errores de validación | ✅ Sí |

### Criterios READY

| Categoría | Mínimo |
|-----------|--------|
| B-roll | >= 10 |
| SFX | >= 10 |
| Icons | >= 10 |
| BGM | >= 3 |
| Fonts | >= 1 |

---

## Real overlay smoke render

Fixture smoke para validar el camino completo de composición final de overlay sin tocar manifest ni usar assets de producción.

- Basado en fixtures locales (video input corto + overlay fixture + texto dinámico PNG).
- No registra assets y no modifica `assets/vpi_asset_manifest.json`.
- No depende de Docker, CUDA ni NVENC.
- Verifica `ffprobe`, duración esperada y flags finales de overlay.
- Escribe outputs y reportes en `exports/smoke_overlay/`.

Comandos:

```bash
python scripts/run_real_overlay_smoke_render.py
python scripts/debug_real_overlay_smoke_render.py
```

El debug imprime `REAL_OVERLAY_SMOKE_RENDER=PASS/FAIL` y el preflight publica `REAL_OVERLAY_SMOKE_RENDER=true/false`.

---

## Review overlay smoke render

Smoke de inspección visual para overlays locales pendientes de revisión de licencia/comercial.

- Solo modo review/debug: requiere `--allow-review-assets` explícito.
- No registra manifest y no cambia `commercial_use_ok`.
- No equivale a `manifest_verified` ni a `production_verified`.
- No habilita uso en producción.
- Genera output local para revisión visual manual.

Comandos:

```bash
python scripts/run_review_overlay_smoke_render.py --allow-review-assets
python scripts/debug_review_overlay_smoke_render.py
```

El reporte marca explícitamente `REVIEW_ASSET_NOT_PRODUCTION`.

---

## Animated icon synthesizer (SVG local)

Generación local de animated icons candidatos desde SVGs ya presentes en `assets/icons` (sin descargas externas).

- Solo staging/review: outputs en `assets/overlays_staging/generated_icons/`.
- No registra manifest y no altera estado de producción.
- Cada output queda con `license_status=manual_review_required`.
- `commercial_use_ok` permanece en `unknown`.
- Incluye thumbs y contact sheet para inspección visual.

Comandos:

```bash
python scripts/generate_animated_icons_from_svg.py
python scripts/debug_animated_icon_synthesizer.py
```

Reportes:

- `assets/overlays_staging/_download_reports/generated_animated_icon_report.json`
- `docs/animated_icon_synthesizer_review.md`

---

## Generated icon registration

Cuando la revisión legal esté aprobada, los generated icons seleccionados pueden registrarse en manifest como `motion_overlay` con source `local_svg_synthesizer`.

- Ruta registrada: `assets/overlays/generated_icons/<family>/<family>_<variant>.mp4`
- License notice file: `assets/overlays/generated_icons/LICENSE_LUCIDE_FEATHER.txt`
- Validación recomendada:

```bash
python scripts/debug_generated_icon_manifest_registration.py
python scripts/debug_asset_runtime_selection.py
python scripts/vpi_editorial_preflight.py --strict
```

---

## Registered generated icon smoke render

Smoke render real usando únicamente assets `generated_icon_*` ya registrados en manifest.

- Selecciona candidato registrado por `concept` desde `assets/vpi_asset_manifest.json`.
- Requiere `manifest_verified=true`, `commercial_use_ok=true`, `source=local_svg_synthesizer` y `license_file` existente.
- No usa assets de review ni flags `--allow-review-assets`.
- Valida output final con `ffprobe` y flags de aplicación real.
- Escribe outputs en `exports/smoke_registered_generated_icon/` con fallback seguro a `/tmp/viraclip_registered_generated_icon_smoke/`.

Comandos:

```bash
python scripts/run_registered_generated_icon_smoke_render.py --concept warning
python scripts/debug_registered_generated_icon_smoke_render.py
```

---

## Production overlay smoke render

Smoke de producción controlado usando `generated_icon_*` registrados y verificados en manifest.

- Selección semántica por `scenario` (`warning`, `protection`, `health`, `documents`, `price`, `contact`).
- El reporte incluye telemetría del selector (`selector_selected_asset_id`, `selector_selected_concept`, `selector_matched_keywords`, `selector_score`) y fallback.
- Usa solo assets con `manifest_verified=true`, `commercial_use_ok=true`, `source=local_svg_synthesizer`.
- Excluye assets review/unverified y no usa Mixkit candidatos.
- Aplica overlay real con `apply_overlay_card_to_video` y valida output con `ffprobe`.
- No publica, no usa CUDA/NVENC, no toca runtime productivo.
- Output en `exports/smoke_production_overlay/` con fallback a `/tmp/viraclip_production_overlay_smoke/`.

Comandos:

```bash
python scripts/run_production_overlay_smoke_render.py --scenario warning
python scripts/debug_production_overlay_smoke_render.py
```

---

## Real Beta Clean overlay test

Prueba controlada tipo Beta Clean con clip corto local y selección semántica de overlays registrados.

- Usa solo `generated_icon_*` registrados/verificados desde manifest.
- No usa assets review/unverified ni candidatos Mixkit.
- No usa CUDA/NVENC ni publica output.
- Intenta selector semántico real y aplica fallback explícito por escenario si hace falta.
- El reporte deja trazabilidad de `selection_fallback_used` y del scoring del selector.
- Valida composición final real con `ffprobe` y flags honestos (`motion_overlay_selected`, `motion_overlay_applied`, `final_output_uses_motion_overlay`).
- Outputs en `exports/beta_clean_overlay_test/` con fallback a `/tmp/viraclip_beta_clean_overlay_test/`.

Comandos:

```bash
python scripts/run_real_beta_clean_overlay_test.py --scenario warning
python scripts/debug_real_beta_clean_overlay_test.py
```

---

## Real user video overlay test

Smoke controlado para laboratorio Beta Clean sobre un vídeo local real.

- Acepta `--input-video` local (o `--generate-fixture` para prueba rápida).
- No modifica el input original.
- Usa solo `generated_icon_*` registrados/verificados del manifest.
- Bloquea assets review/unverified y no usa Mixkit review assets.
- No publica, no frontend, no CUDA/NVENC.
- Valida output con `ffprobe` y flags de overlay aplicadas de forma honesta.
- Salida en `exports/real_user_overlay_test/` con fallback a `/tmp/viraclip_real_user_overlay_test/`.

Comandos:

```bash
python scripts/run_real_user_video_overlay_test.py --generate-fixture --scenario warning
python scripts/debug_real_user_video_overlay_test.py
```

---

---

## Swishy GIF workflow

> Flujo de trabajo para normalizar GIFs exportados desde Swishy antes de registrarlos en el manifest.
> En el enfoque actual, prioriza objetos genéricos reutilizables (no textos hiperpersonalizados).

### 1. Exportar GIF desde Swishy

Exportar el overlay como GIF animado desde Swishy.

### 2. Guardar en staging

```
assets/overlays_staging/swishy_gif/<swishy_family>_swishy_<###>.gif
```

### 3. Normalizar con `normalize_motion_overlay_gif.py`

```bash
# GIF → MP4 (recomendado para cards completas sin transparencia)
python scripts/normalize_motion_overlay_gif.py \
  --input assets/overlays_staging/swishy_gif/notification_card_swishy_001.gif \
  --concept notification_card \
  --output-format mp4 \
  --source swishy_export

# GIF → WebM (recomendado para overlays con transparencia)
python scripts/normalize_motion_overlay_gif.py \
  --input assets/overlays_staging/swishy_gif/keyword_spin_swishy_001.gif \
  --concept keyword_spin \
  --output-format webm \
  --source swishy_export

# Dry-run (verificar sin escribir)
python scripts/normalize_motion_overlay_gif.py \
  --input assets/overlays_staging/swishy_gif/toggle_card_swishy_001.gif \
  --concept toggle_card \
  --output-format mp4 \
  --dry-run
```

### 4. Revisar visualmente

Verificar que el output se ve correcto antes de registrar.

### 5. Registrar con `vpi_asset_intake.py`

El script imprime un comando sugerido. Revisar licencia antes de ejecutar:

```bash
python scripts/vpi_asset_intake.py add \
  --type motion_overlay \
  --path assets/overlays/notification_card/notification_card_swishy_001.mp4 \
  --id notification_card_swishy_001 \
  --source swishy_export \
  --license-name "Swishy Export / Manual Review" \
  --commercial-use-ok false \
  --attribution-required false \
  --review-required true \
  --tags notification_card motion_overlay swishy \
  --topics manual_review \
  --sensitive-tone safe \
  --duration-hint 1.2
```

**Importante:**
- `commercial-use-ok false` por defecto hasta revisión legal.
- `review-required true` — no saltar revisión manual.
- Preferir MP4 para cards completas (glow_text, finance_chart, stat_card, timeline_card, toggle_card).
- Preferir WebM para overlays con transparencia (notification_card, time_passage, folder_gallery, typewriter_text, location_popup, keyword_spin).

### Ejemplos

| GIF origen | Output | Formato | Razón |
|------------|--------|---------|-------|
| `notification_card_swishy_001.gif` | `notification_card_swishy_001.mp4` | MP4 | Card completa, sin transparencia crítica |
| `keyword_spin_swishy_001.gif` | `keyword_spin_swishy_001.webm` | WebM | Overlay con posible transparencia |
| `toggle_card_swishy_001.gif` | `toggle_card_swishy_001.mp4` | MP4 | Card completa |

---

## Comandos de validación

```bash
# Validar solo la librería de assets
python scripts/debug_asset_library_pack.py

# Preflight completo (incluye asset library)
python scripts/vpi_editorial_preflight.py --strict

# Ver sintaxis Python de los archivos clave
PYTHONPYCACHEPREFIX=/tmp/viraclip_pycache_check python -m py_compile \
  backend/src/services/vpi_asset_library_service.py \
  scripts/debug_asset_library_pack.py \
  scripts/vpi_editorial_preflight.py
```

---

## Register assets with `vpi_asset_intake.py`

```bash
# Add B-roll entry to active manifest
python scripts/vpi_asset_intake.py add \
  --type broll \
  --path assets/broll/family_relief/family_relief_pexels_001.mp4 \
  --id family_relief_001 \
  --source pexels \
  --source-url "" \
  --license-name "Pexels License" \
  --commercial-use-ok true \
  --attribution-required false \
  --tags family_relief emotional_support warm_family \
  --topics decesos vida familia \
  --sensitive-tone safe \
  --duration-hint 2.0

# Add SFX entry
python scripts/vpi_asset_intake.py add \
  --type sfx \
  --path assets/sounds/sfx/soft_chime/soft_chime_mixkit_001.mp3 \
  --id soft_chime_001 \
  --source mixkit \
  --source-url "" \
  --license-name "Mixkit Free License" \
  --commercial-use-ok true \
  --attribution-required false \
  --tags soft_chime

# Add Motion Overlay entry (manual export only)
python scripts/vpi_asset_intake.py add \
  --type motion_overlay \
  --path assets/overlays/shield/shield_swishy_001.webm \
  --id shield_swishy_001 \
  --source swishy_export \
  --source-url "" \
  --license-name "Swishy Export / Manual Review" \
  --commercial-use-ok true \
  --attribution-required false \
  --review-required true \
  --tags shield protection motion_overlay \
  --topics vida decesos proteccion \
  --sensitive-tone safe

# Add Swishy Motion Overlay entry (v1 template family)
python scripts/vpi_asset_intake.py add \
  --type motion_overlay \
  --path assets/overlays/notification_card/notification_card_swishy_001.webm \
  --id notification_card_swishy_001 \
  --source swishy_export \
  --source-url "" \
  --license-name "Swishy Export / Manual Review" \
  --commercial-use-ok false \
  --attribution-required false \
  --review-required true \
  --tags notification_card motion_overlay swishy_v1 \
  --topics contacto whatsapp alerta \
  --sensitive-tone safe

# Add Swishy strong card with claim review (finance_chart)
python scripts/vpi_asset_intake.py add \
  --type motion_overlay \
  --path assets/overlays/finance_chart/finance_chart_swishy_001.webm \
  --id finance_chart_swishy_001 \
  --source swishy_export \
  --source-url "" \
  --license-name "Swishy Export / Manual Review" \
  --commercial-use-ok false \
  --attribution-required false \
  --review-required true \
  --tags finance_chart motion_overlay swishy_v1 claim_review \
  --topics ahorro precio finanzas \
  --sensitive-tone safe

# Validate intake manifest

python scripts/vpi_asset_intake.py validate

# List assets (optional filters)
python scripts/vpi_asset_intake.py list
python scripts/vpi_asset_intake.py list --type broll --status verified

# Suggest missing categories for READY
python scripts/vpi_asset_intake.py suggest
```

For `swishy_export`, do not assume open-source/commercial permission by default. Register explicit license metadata and keep `commercial_use_ok=false` when legal certainty is missing.

## Overlay Content Modes (Documentation)

Conceptual metadata for motion overlays:

- `overlay_content_mode=generic_container`: card genérica para texto runtime futuro.
- `overlay_content_mode=claim_container`: card para datos/promos con revisión de claims.
- `overlay_content_mode=cta_container`: card de contacto/CTA.
- `overlay_content_mode=fixed_text`: texto ya final dentro del asset.
- `overlay_content_mode=category_word`: palabra de categoría (ej. SALUD/VIDA).

`text_replaceable=true` recomendado para:
- `notification_card`, `toggle_card`, `timeline_card`, `folder_gallery`, `stat_card`, `price_badge`.

`text_replaceable=false|optional`:
- `location_popup`, `keyword_spin`, `typewriter_text`, `glow_text`.

## Dynamic Overlay Text

ViraClip puede generar un `overlay text plan` contextual sobre containers genéricos.

- `selected`: overlay elegido por semántica.
- `rendered`: texto dinámico generado como recurso visual (si aplica).
- `applied`: overlay+texto realmente compuestos en el output final.

Estos estados son independientes.  
`selected=true` no implica `rendered=true`, y `rendered=true` no implica `applied=true`.

Reglas:
- no duplicar captions principales.
- no claims fuertes sin validación (`claim_verified`).
- `needs_claim_review=true` para promos/estadísticas sensibles.
- evitar sobrecarga visual en `minimal_safe` o `layer_overload`.

### Dynamic overlay text rendering

- ViraClip puede renderizar PNGs transparentes de texto contextual para overlays genéricos.
- Este render de texto **no implica** composición final sobre el video.
- Estados separados:
  - `planned` (plan generado),
  - `rendered` (PNG generado),
  - `applied` (composición final en video).
- Claims sensibles mantienen gate de revisión.
- Cache local por defecto:
  - `exports/dynamic_overlay_text/`

### Dynamic overlay card composer

- ViraClip puede componer un preview local de card combinando:
  - un `motion_overlay` genérico, y
  - un PNG de texto dinámico (`dynamic_overlay_text_asset`).
- Este output es solo evidencia/preview offline.
- **No** implica aplicación en clip final:
  - `dynamic_overlay_card_composed` puede ser `true`,
  - mientras `motion_overlay_applied=false` y `final_output_uses_motion_overlay=false`.
- Cache local por defecto:
  - `exports/dynamic_overlay_cards/`

### Final overlay video composition

- La aplicación final del overlay en el clip solo cuenta cuando FFmpeg genera output legible.
- Estados separados y obligatorios:
  - `selected` (candidato semántico),
  - `composed` (preview card offline),
  - `applied` (overlay realmente insertado en clip final),
  - `final_output_uses_motion_overlay` (solo `true` si `applied=true`).
- En producción, el asset debe estar `manifest_verified=true`.
- Si falla la aplicación final, se conserva el clip original (`fallback preserved`), sin romper pipeline.
- Cache local por defecto:
  - `exports/final_overlay_composed/`

## Future Pack Note

`Dynamic Overlay Text Pack v1` (futuro):
- usar overlays genéricos y superponer texto semántico en runtime con fuentes locales.
- reducir necesidad de exportar múltiples variantes personalizadas en Swishy.
- no implementado en esta fase.

---

## Fuentes aprobadas

| Fuente | Tipos | Licencia | Commercial Use |
|--------|-------|----------|----------------|
| Pexels | B-roll | Pexels License | ✅ |
| Pixabay | B-roll, SFX, BGM | Pixabay Content License | ✅ |
| Mixkit | B-roll, SFX, BGM | Mixkit Free License | ✅ |
| Coverr | B-roll | Coverr License | ✅ |
| Freesound (CC0) | SFX | CC0 1.0 | ✅ |
| Freesound (CC-BY) | SFX | CC BY 4.0 | ✅ (con atribución) |
| Lucide | Icons | ISC | ✅ |
| Tabler | Icons | MIT | ✅ |
| Heroicons | Icons | MIT | ✅ |
| Google Fonts | Fonts | OFL | ✅ |

Ver `docs/vpi_asset_source_plan.md` para plan detallado por categoría.
Ver `docs/vpi_asset_intake_checklist.md` para checklist de incorporación.
