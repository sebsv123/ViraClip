# VPI Asset Intake Checklist

> Checklist por asset para garantizar que cada recurso cumple los requisitos de la librería premium local.
> Cada asset debe pasar todos los pasos antes de añadirse al manifest.

---

## Checklist (por asset)

- [ ] **1. Archivo descargado localmente**
  - El archivo físico existe en la ruta correcta dentro de `assets/`.

- [ ] **2. Nombre normalizado**
  - Sigue la naming convention (ver más abajo).

- [ ] **3. Ruta correcta**
  - El archivo está en el subdirectorio correspondiente a su tipo e intent/familia.

- [ ] **4. Source name**
  - Nombre de la fuente (ej: `pexels`, `pixabay`, `mixkit`, `lucide`, `tabler`).

- [ ] **5. Source URL**
  - URL directa del asset en la fuente original.

- [ ] **6. License name**
  - Nombre exacto de la licencia (ej: `Pexels License`, `Pixabay Content License`, `MIT`).

- [ ] **7. Commercial use OK**
  - `commercial_use_ok: true` — verificado contra la licencia.

- [ ] **8. Attribution required**
  - `attribution_required: true/false` según la licencia.

- [ ] **9. Tags editoriales**
  - Mínimo 1 tag del intent/familia correspondiente.

- [ ] **10. Topics**
  - Lista de temas relevantes (ej: `["decesos", "vida", "familia"]`).

- [ ] **11. Sensitive tone**
  - `safe`, `mild`, o `sensitive` según el contenido.

- [ ] **12. Avoid for**
  - Lista de intents/familias para los que NO debe usarse este asset.

- [ ] **13. Duración**
  - `duration_hint` en segundos (para b-roll, SFX, BGM).

- [ ] **14. Resolución o formato**
  - Resolución mínima 1080p para video. Formato para iconos (SVG) y fuentes (TTF/OTF).

- [ ] **15. Revisión visual/sonora humana**
  - Una persona ha verificado que el asset se ve/oye bien y es apropiado.

- [ ] **16. Sin logos/marcas**
  - No hay logos, marcas registradas, ni watermarks visibles.

- [ ] **17. Sin datos personales**
  - No hay información personal legible (DNI, direcciones, etc.).

- [ ] **18. Sin contenido dramático/agresivo para decesos**
  - Especialmente importante para `family_relief` y `emotional_support`.

- [ ] **19. Añadido al manifest**
  - Entrada completa en `assets/vpi_asset_manifest.json` con todos los campos.

- [ ] **20. Preflight ejecutado**
  - `python scripts/debug_asset_library_pack.py` pasa sin errores.
  - `python scripts/vpi_editorial_preflight.py --strict` muestra `ASSET_LIBRARY_STATUS=PARTIAL` o `READY`.

---

## Naming Convention

### B-roll

```
assets/broll/<intent>/<intent>_<source>_<###>.mp4
```

Ejemplos:
```
assets/broll/family_relief/family_relief_pexels_001.mp4
assets/broll/health_access/health_access_pixabay_002.mp4
assets/broll/office_work/office_work_mixkit_003.mp4
```

### SFX

```
assets/sounds/sfx/<family>/<family>_<source>_<###>.mp3
```

Ejemplos:
```
assets/sounds/sfx/dark_riser/dark_riser_mixkit_001.mp3
assets/sounds/sfx/magic_whoosh/magic_whoosh_pixabay_002.mp3
assets/sounds/sfx/deep_boom/deep_boom_mixkit_003.mp3
```

### BGM

```
assets/sounds/bgm/<mood>/<mood>_<source>_<###>.mp3
```

Ejemplos:
```
assets/sounds/bgm/warm_trust/warm_trust_pixabay_001.mp3
assets/sounds/bgm/clean_corporate/clean_corporate_mixkit_002.mp3
```

### Icons

```
assets/icons/<concept>/<concept>_<set>_<###>.svg
```

Ejemplos:
```
assets/icons/family/family_lucide_001.svg
assets/icons/health/health_tabler_002.svg
assets/icons/shield/shield_lucide_003.svg
```

### Motion Overlay

```
assets/overlays/<concept>/<concept>_<source>_<###>.webm
```

Ejemplos:
```
assets/overlays/shield/shield_swishy_001.webm
assets/overlays/heart/heart_swishy_002.mov
assets/overlays/warning/warning_swishy_003.mp4
assets/overlays/hook_card/hook_card_swishy_001.mp4
assets/overlays/review_card/review_card_swishy_001.mp4
assets/overlays/whatsapp_card/whatsapp_card_swishy_001.mp4
assets/overlays/coverage_card/coverage_card_swishy_001.mp4
assets/overlays/promo_badge/promo_badge_swishy_001.mp4
assets/overlays/agent_card/agent_card_swishy_001.mp4
assets/overlays/limited_time/limited_time_swishy_001.mp4
```

### Fonts

```
assets/fonts/<family>/<file>.ttf
```

Ejemplos:
```
assets/fonts/Manrope/Manrope-VariableFont_wght.ttf
assets/fonts/Inter/Inter-VariableFont_opsz_wght.ttf
assets/fonts/DM_Sans/DMSans-VariableFont_opsz_wght.ttf
```

---

## Metadata required por asset en manifest

```json
{
  "id": "<intent/family>_<source>_<###>",
  "type": "broll|sfx|bgm|icons|fonts|motion_overlay",
  "path": "assets/<type>/<subdir>/<filename>.<ext>",
  "source": "<source_name>",
  "source_url": "<url>",
  "license_name": "<license>",
  "commercial_use_ok": true,
  "attribution_required": false,
  "tags": ["<tag1>", "<tag2>"],
  "topics": ["<topic1>", "<topic2>"],
  "sensitive_tone": "safe|mild|sensitive",
  "avoid_for": ["<intent/family>"],
  "duration_hint": <seconds>
}
```

## Motion Overlay Generic Policy

- Priorizar assets genéricos reutilizables (cards/containers), no copies hiperpersonalizadas.
- `text_replaceable=true` para containers (`notification_card`, `toggle_card`, `timeline_card`, `folder_gallery`, `stat_card`, `price_badge`).
- `text_replaceable=false|optional` para `location_popup`, `keyword_spin`, `typewriter_text`, `glow_text`.
- `overlay_content_mode` recomendado:
  - `generic_container`
  - `claim_container`
  - `cta_container`
  - `fixed_text`
  - `category_word`

## Swishy source note

`source=swishy_export` requiere revisión manual de términos/licencia.  
No asumir open-source ni uso comercial automático.

## Dynamic Overlay Text (runtime note)

- Los overlays genéricos pueden recibir texto contextual en runtime.
- No registrar variantes manuales por frase si el concepto puede reutilizarse.
- Mantener separación honesta:
  - `selected` (elegido)
  - `rendered` (texto generado)
  - `applied` (composición final real)
- Si `needs_claim_review=true`, evitar marcar texto como seguro sin validación de claim.

---

## QC thresholds record

| Categoría | Mínimo READY | Actual | Estado |
|-----------|-------------|--------|--------|
| B-roll | 10 | | |
| SFX | 10 | | |
| BGM | 3 | | |
| Icons | 10 | | |
| Fonts | 1 | | |

> Rellenar "Actual" después de cada tanda de intake y ejecutar preflight.
