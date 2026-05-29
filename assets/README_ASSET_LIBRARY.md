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
