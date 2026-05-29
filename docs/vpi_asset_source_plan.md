# VPI Asset Source Plan v1

> Plan operativo para llenar manualmente la librería premium local de ViraClip.
> Assets seguros, metadata compatible con `assets/vpi_asset_manifest.template.json`.
> Sin descargas automáticas, sin APIs, sin commits.

---

## A) B-roll

### Objetivos

| Nivel | Cantidad |
|-------|----------|
| Mínimo READY | 10 assets verificados |
| Premium recomendado | 60 assets |

### Distribución por intent

| Intento | Clips | Descripción | Evitar |
|---------|-------|-------------|--------|
| `family_relief` / `emotional_support` | 12 | Familia tranquila, hogar, conversación, abrazo sobrio, apoyo, calma | Cementerios, ataúdes, llanto explícito, dramatismo barato |
| `health_access` / `medical_care` | 12 | Consulta médica, sala de espera limpia, doctores hablando, manos, tecnología médica sobria | Quirófanos agresivos, sangre, urgencias dramáticas |
| `autonomous_work_stability` / `office_work` | 12 | Autónomos, oficina pequeña, portátil, llamadas, negocio local, agenda, trabajo concentrado | Corporativo falso de multinacional si no encaja |
| `practical_explanation` / `paperwork_support` | 10 | Documentos, firma, tablet, calendario, planificación, familia revisando papeles | Mostrar datos personales legibles |
| `risk_warning_context` | 8 | Lluvia suave, calle, casa, silencio, reflexión, imprevisto abstracto | Miedo explícito |
| `calm_lifestyle` / `family_home` | 6 | Vida cotidiana, tranquilidad, paseo, hogar, rutina | — |

### Fuentes recomendadas

| Fuente | Licencia | Commercial Use | Attribution |
|--------|----------|----------------|-------------|
| [Pexels](https://www.pexels.com) | Pexels License | ✅ Sí | ❌ No requerida |
| [Pixabay](https://pixabay.com) | Pixabay Content License | ✅ Sí | ❌ No requerida |
| [Mixkit](https://mixkit.co) | Mixkit Free License | ✅ Sí | ❌ No requerida |
| [Coverr](https://coverr.co) | Coverr License | ✅ Sí | ❌ No requerida |

### Notas de selección

- Descargar solo clips **sin logos ni marcas visibles**.
- Preferir planos **genéricos, limpios, vertical-friendly** (9:16 o recortables a vertical).
- Duración ideal: **4–12 segundos**.
- Resolución mínima: **1080p** (1920×1080 o 1080×1920).
- Evitar caras demasiado protagonistas si pueden distraer del mensaje.
- Registrar `source_url` y `license_name` por cada asset en el manifest.

---

## B) SFX

### Objetivos

| Nivel | Cantidad |
|-------|----------|
| Mínimo READY | 10 SFX verificados |
| Premium recomendado | 40 SFX |

### Distribución por familia

| Familia | Cantidad | Descripción |
|---------|----------|-------------|
| `dark_riser` | 6 | Riser grave y lento para transiciones serias |
| `tension_riser` | 6 | Riser de tensión media para momentos de advertencia |
| `high_riser` | 4 | Riser agudo para énfasis positivo |
| `magic_whoosh` | 8 | Whoosh limpio para transiciones y cambios de plano |
| `deep_boom` | 8 | Boom grave para golpes de énfasis |
| `soft_chime` | 6 | Campanilla suave para puntos de atención |
| `click_soft` | 4 | Click sutil para microtransiciones |
| `ambient_soft` | 4 | Ambiente suave de fondo para silencios |

### Fuentes recomendadas

| Fuente | Licencia | Commercial Use | Attribution |
|--------|----------|----------------|-------------|
| [Mixkit](https://mixkit.co/free-sound-effects) | Mixkit Free License | ✅ Sí | ❌ No requerida |
| [Pixabay](https://pixabay.com/sound-effects) | Pixabay Content License | ✅ Sí | ❌ No requerida |
| [Freesound](https://freesound.org) | CC0 / CC-BY | ✅ Sí (CC0) / ✅ Sí (CC-BY) | ⚠️ CC-BY requiere `attribution_required=true` |

### Notas de selección

- Evitar SFX **agresivos o de videojuego**.
- Volumen percibido **moderado** (no saturar).
- Preferir **WAV o MP3** limpios, sin ruido de fondo.
- Registrar `duration_hint` y `sfx_family` en el manifest.
- Crear **5–10 variaciones** para booms, whooshes y risers.

---

## C) BGM

### Objetivos

| Nivel | Cantidad |
|-------|----------|
| Mínimo READY | 3 pistas |
| Premium recomendado | 8–12 pistas |

### Tipos / Moods

| Mood | Descripción |
|------|-------------|
| `warm_trust` | Cálido, acogedor, para temas de familia y apoyo |
| `clean_corporate` | Corporativo limpio, para explicaciones y documentos |
| `soft_health` | Suave, profesional, para contexto médico |
| `subtle_tension` | Tensión sutil, para advertencias y riesgos |
| `emotional_family` | Emotivo pero contenido, para momentos de impacto |
| `modern_explainer` | Moderno, rítmico, para contenido educativo |

### Fuentes recomendadas

| Fuente | Licencia | Commercial Use | Attribution |
|--------|----------|----------------|-------------|
| [Pixabay Music](https://pixabay.com/music) | Pixabay Content License | ✅ Sí | ❌ No requerida |
| [Mixkit Music](https://mixkit.co/free-stock-music) | Mixkit Free License | ✅ Sí | ❌ No requerida |
| YouTube Audio Library | Varía | ⚠️ Verificar por pista | ⚠️ Verificar por pista |

### Notas de selección

- Evitar música **muy protagonista** que compita con la voz.
- Loops de **30–60 segundos** ideales.
- **Sin voces** (instrumental).
- Registrar `attribution_required` por pista.

---

## D) Icons

### Objetivos

| Nivel | Cantidad |
|-------|----------|
| Mínimo READY | 10 iconos |
| Premium recomendado | 40–60 iconos |

### Conceptos

| Concepto | Descripción |
|----------|-------------|
| `family` | Familia, hogar, padres e hijos |
| `health` | Salud, médico, hospital |
| `shield` | Protección, seguro, escudo |
| `heart` | Corazón, cuidado, apoyo emocional |
| `warning` | Advertencia, precaución, riesgo |
| `briefcase` | Trabajo, autónomo, oficina |
| `document` | Papeles, firma, contrato |
| `euro` | Dinero, ahorro, planificación financiera |
| `calendar` | Calendario, planificación, fechas |
| `phone` | Teléfono, contacto, llamada |
| `support` | Soporte, ayuda, asistencia |
| `checklist` | Lista, verificación, trámites |
| `hospital` | Hospital, clínica, atención médica |
| `user` | Usuario, persona, perfil |
| `home` | Casa, hogar, vivienda |

### Fuentes recomendadas

| Fuente | Licencia | Commercial Use | Attribution |
|--------|----------|----------------|-------------|
| [Lucide](https://lucide.dev) | ISC | ✅ Sí | ❌ No requerida |
| [Tabler Icons](https://tabler-icons.io) | MIT | ✅ Sí | ❌ No requerida |
| [Heroicons](https://heroicons.com) | MIT | ✅ Sí | ❌ No requerida |

### Notas de selección

- Formato **SVG**.
- Estilo **consistente**: stroke lineal, mismo peso de trazo.
- No mezclar familias visuales si no es necesario.
- Guardar licencia del pack (ISC / MIT).

---

## E) Fonts

### Objetivos

| Nivel | Cantidad |
|-------|----------|
| Mínimo READY | 1 fuente |
| Premium recomendado | 2–3 familias |

### Familias recomendadas

| Fuente | Peso | Roles |
|--------|------|-------|
| [Manrope](https://fonts.google.com/specimen/Manrope) | Variable / 200–800 | `caption_primary`, `caption_emphasis`, `lower_third` |
| [Inter](https://fonts.google.com/specimen/Inter) | Variable / 100–900 | `caption_primary`, `lower_third` |
| [DM Sans](https://fonts.google.com/specimen/DM+Sans) | 400, 500, 700 | `caption_emphasis`, `brand_title` |
| [Source Sans 3](https://fonts.google.com/specimen/Source+Sans+3) | Variable / 200–900 | `caption_primary`, `lower_third` |
| [IBM Plex Sans](https://fonts.google.com/specimen/IBM+Plex+Sans) | 400, 500, 600, 700 | `caption_primary`, `caption_emphasis` |
| [Montserrat](https://fonts.google.com/specimen/Montserrat) | Variable / 100–900 | `brand_title`, `lower_third` |

### Roles

| Role | Uso |
|------|-----|
| `caption_primary` | Texto principal de subtítulos |
| `caption_emphasis` | Palabras destacadas en karaoke/highlight |
| `lower_third` | Texto de tercio inferior (nombres, títulos) |
| `brand_title` | Título de marca / intro |

### Notas de selección

- Descargar desde **Google Fonts** o **GitHub oficial**.
- Guardar archivo **OFL/LICENSE** junto a la fuente.
- No copiar ni compartir fuentes fuera del repo privado.
- No incluir archivos de fuente en este plan — solo registrar origen.

---

## Resumen de cantidades objetivo

| Categoría | Mínimo READY | Premium |
|-----------|-------------|---------|
| B-roll | 10 | 60 |
| SFX | 10 | 40 |
| BGM | 3 | 8–12 |
| Icons | 10 | 40–60 |
| Fonts | 1 | 2–3 familias |

**Total mínimo para READY: 34 assets.**
**Total premium recomendado: ~150–175 assets.**

---

## Estructura de directorios esperada

```
assets/
├── broll/
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
│   ├── sfx/
│   │   ├── dark_riser/
│   │   ├── tension_riser/
│   │   ├── high_riser/
│   │   ├── magic_whoosh/
│   │   ├── deep_boom/
│   │   ├── soft_chime/
│   │   ├── click_soft/
│   │   └── ambient_soft/
│   └── bgm/
│       ├── warm_trust/
│       ├── clean_corporate/
│       ├── soft_health/
│       ├── subtle_tension/
│       ├── emotional_family/
│       └── modern_explainer/
├── icons/
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
├── fonts/
│   ├── Manrope/
│   ├── Inter/
│   └── DM_Sans/
├── vpi_asset_manifest.template.json
└── README_ASSET_LIBRARY.md
```
