# Local B-roll Asset Bank — Guía de Construcción VPI v1

## 1. Cantidad de assets por fase

| Fase | Assets por categoría | Total | Frecuencia de publicación |
|---|---|---|---|
| **MVP** (lanzar) | 3–5 | ~28 | 1 clip/día → 3-5 días sin repetir |
| **Beta cómoda** (2 semanas) | 8–12 | ~70 | 1-2 clips/día → 1-2 semanas sin repetir |
| **Producción diaria** (estable) | 15–20 | ~120 | 2 clips/día → 1 mes sin repetir |

Con 3 assets por categoría y rotación inteligente, un clip diario se ve fresco ~3 semanas.

---

## 2. Matriz cue_type → momento del discurso → visual

| cue_type | El speaker dice… | Visual recomendado |
|---|---|---|
| **family_protection** | "tu familia", "los tuyos", "tus seres queridos", "proteger a los que más quieres" | Familia reunida en sala, padres con hijos, abuelos con nietos, hogar acogedor |
| **emotional_reassurance** | "calma", "tranquilidad", "paz", "descanso", "sin preocupaciones" | Persona relajada en sofá, ventana con luz natural, paisaje sereno, taza de café |
| **risk_warning** | "si mañana te pasa algo", "imprevisto", "accidente", "enfermedad", "golpe duro" | Documentos sobre mesa, calendario con fechas marcadas, manos entrelazadas, mirada seria |
| **documents_admin** | "póliza", "contrato", "firma", "papeles", "burocracia", "trámites" | Manos firmando, sellos, carpetas, documentos sobre escritorio, pluma estilográfica |
| **advisor_meeting** | "tu asesor", "tu agente", "vamos a verlo juntos", "te explico", "reunión" | Dos personas conversando en oficina, apretón de manos, pantalla compartida, café de reunión |
| **healthy_lifestyle** | "vida saludable", "ejercicio", "bienestar", "cuidarse", "prevención" | Persona caminando al aire libre, frutas, agua, estiramientos, luz natural |
| **financial_planning** | "ahorro", "inversión", "futuro", "jubilación", "patrimonio", "planificar" | Gráficos, calculadora, alcancía, manos contando billetes, edificio financiero |

---

## 3. Guía por categoría

### family_protection
- **Intención**: Calor familiar, protección, hogar
- **Planos**: Plano medio de familia reunida, detalle de manos entrelazadas, plano general de hogar
- **Tono**: Cálido, luminoso, tonos tierra y dorados
- **Duración ideal**: 4-7s
- **Naming**: `fp_calor_01.mp4`, `fp_reunion_02.mp4`, `fp_abrazos_03.mp4`
- **Evitar**: Familias de stock falsas, sonrisas forzadas, escenas de playa/diversión

### emotional_reassurance
- **Intención**: Serenidad, confianza, paz mental
- **Planos**: Plano detalle de manos sosteniendo taza, persona mirando por ventana, luz suave
- **Tono**: Pastel, desaturado suave, bokeh
- **Duración ideal**: 3-6s
- **Naming**: `er_calma_01.mp4`, `er_respiro_02.mp4`, `er_luz_03.mp4`
- **Evitar**: Gente riendo a carcajadas, escenas de fiesta, colores saturados

### risk_warning
- **Intención**: Seriedad, reflexión, urgencia suave
- **Planos**: Primer plano de ojos, manos entrelazadas, documentos sobre mesa, luz tenue
- **Tono**: Contraste medio, azulados, textura de papel
- **Duración ideal**: 3-5s
- **Naming**: `rw_reflexion_01.mp4`, `rw_documentos_02.mp4`, `rw_mirada_03.mp4`
- **Evitar**: Escenas catastróficas, ambulancias, hospitales, lágrimas

### documents_admin
- **Intención**: Orden, profesionalismo, gestión
- **Planos**: Manos escribiendo, sello estampando, carpeta abriéndose, pluma sobre papel
- **Tono**: Limpio, iluminación de oficina, blanco/gris/azul claro
- **Duración ideal**: 3-5s
- **Naming**: `da_firma_01.mp4`, `da_sello_02.mp4`, `da_carpeta_03.mp4`
- **Evitar**: Escritorios desordenados, papeles arrugados, oficinas vacías

### advisor_meeting
- **Intención**: Cercanía profesional, confianza, asesoría
- **Planos**: Plano medio de dos personas conversando, apretón de manos, café en mesa
- **Tono**: Cálido profesional, tonos madera, luz natural de ventana
- **Duración ideal**: 4-7s
- **Naming**: `am_reunion_01.mp4`, `am_apreton_02.mp4`, `am_asesoria_03.mp4`
- **Evitar**: Ejecutivos en traje mirando laptop, salas de juntas frías

### healthy_lifestyle
- **Intención**: Vitalidad, prevención, bienestar
- **Planos**: Persona caminando en parque, manos con fruta, vaso de agua, luz de mañana
- **Tono**: Fresco, verde/azul, luminoso
- **Duración ideal**: 3-6s
- **Naming**: `hl_paseo_01.mp4`, `hl_fruta_02.mp4`, `hl_agua_03.mp4`
- **Evitar**: Gimnasios, pesas, sudor, escenas extremas de ejercicio

### financial_planning
- **Intención**: Seguridad financiera, crecimiento, orden
- **Planos**: Calculadora, manos contando billetes, gráfico en tablet, alcancía, edificio
- **Tono**: Profesional, azul corporativo, iluminación limpia
- **Duración ideal**: 3-5s
- **Naming**: `fp_ahorro_01.mp4`, `fp_grafico_02.mp4`, `fp_alcancia_03.mp4`
- **Evitar**: Fajos de billetes, lujo ostentoso, gráficos de cripto

---

## 4. Reglas editoriales

### Cuándo usar B-roll
- El transcript contiene una frase de las listadas en la matriz
- La duración del clip es ≥ 15s
- Hay al menos 2s de silencio o pausa natural donde insertar
- La inserción no interrumpe una palabra (usar word timestamps)

### Cuándo NO usar B-roll
- El clip dura < 12s
- El speaker está dando un dato concreto (número, fecha, nombre)
- El tono es muy personal/emocional íntimo (dejar que la cámara hable)
- Ya hay 3 overlays en el mismo clip
- El B-roll cubriría más del 40% de la duración total del clip

### Duración máxima por inserción
- **Mínimo**: 1.5s (apenas un destello visual)
- **Recomendado**: 2.5–4s
- **Máximo**: 6s (empieza a sentirse como video aparte)

### Proporción máxima de B-roll por clip
- Clip de 15s → máximo 6s de B-roll (40%)
- Clip de 30s → máximo 10s de B-roll (33%)
- Clip de 60s → máximo 18s de B-roll (30%)

### Cómo evitar repetición visual
- El Asset Bank v2 ya rotación por scoring
- Tener ≥ 3 assets por categoría
- Si un asset se ha usado en los últimos 3 clips, penalizarlo
- Variar planos: no usar dos planos detalle seguidos
- Variar duración: no insertar siempre a los 3s

### Cómo mantener identidad VPI
- **Colores**: Tonos cálidos (naranja, dorado, crema) + azul corporativo
- **Textura**: Ligeramente desaturado, contraste suave
- **Movimiento**: Cámara lenta o estable, sin zoom brusco
- **Tipografía**: Nunca texto en los B-rolls (el texto va en subtítulos)
- **Formato**: Siempre vertical 9:16, 1080×1920

---

## 5. Checklist para seleccionar assets

- [ ] ¿El video está en vertical 9:16? (si no, se puede recortar)
- [ ] ¿La resolución es ≥ 720p?
- [ ] ¿La duración está entre 3-7s?
- [ ] ¿No tiene texto superpuesto?
- [ ] ¿No tiene marcas de agua?
- [ ] ¿El tono visual es coherente con VPI?
- [ ] ¿No hay personas reconocibles sin permiso?
- [ ] ¿El archivo pesa < 5MB?
- [ ] ¿El nombre sigue la convention?
- [ ] ¿Está en la carpeta correcta?

---

## 6. Naming convention

```
{categoria}_{subestilo}_{numero}.mp4

Categorías:
  fp  = family_protection
  er  = emotional_reassurance
  rw  = risk_warning
  da  = documents_admin
  am  = advisor_meeting
  hl  = healthy_lifestyle
  fn  = financial_planning

Subestilos:
  calor, reunion, abrazos, hogar, juegos, cena
  calma, respiro, luz, ventana, lectura, te
  reflexion, documentos, mirada, manos, seriedad
  firma, sello, carpeta, pluma, papel, sello
  asesoria, reunion, apreton, cafe, oficina, dialogo
  paseo, fruta, agua, naturaleza, sol, estiramientos
  ahorro, grafico, alcancia, billetes, calculadora, edificio

Ejemplos:
  fp_calor_01.mp4
  fp_reunion_02.mp4
  er_calma_01.mp4
  rw_reflexion_01.mp4
  da_firma_01.mp4
  am_asesoria_01.mp4
  hl_paseo_01.mp4
  fn_ahorro_01.mp4
```

---

## 7. Estructura final sugerida (70 assets)

```
/app/assets/broll/
├── family_protection/          (10 assets)
│   ├── fp_calor_01.mp4        Familia en sala viendo fotos
│   ├── fp_reunion_02.mp4      Padres e hijos en mesa
│   ├── fp_abrazos_03.mp4      Abrazo familiar
│   ├── fp_hogar_04.mp4        Exterior de casa acogedora
│   ├── fp_juegos_05.mp4       Niños jugando en jardín
│   ├── fp_cena_06.mp4         Familia cenando
│   ├── fp_lectura_07.mp4      Madre leyendo a hijos
│   ├── fp_jardin_08.mp4       Familia en jardín
│   ├── fp_cocina_09.mp4       Cocina familiar
│   └── fp_atardecer_10.mp4    Familia al atardecer
│
├── emotional_reassurance/      (10 assets)
│   ├── er_calma_01.mp4        Persona en sofá con luz natural
│   ├── er_respiro_02.mp4      Ventana con cortinas al viento
│   ├── er_luz_03.mp4          Rayo de luz en habitación
│   ├── er_te_04.mp4           Manos sosteniendo taza de té
│   ├── er_lectura_05.mp4      Persona leyendo en sillón
│   ├── er_vela_06.mp4         Vela encendida
│   ├── er_lluvia_07.mp4       Lluvia en ventana
│   ├── er_hamaca_08.mp4       Hamaca meciéndose
│   ├── er_libro_09.mp4        Páginas de libro pasando
│   └── er_amanecer_10.mp4     Amanecer sobre campo
│
├── risk_warning/               (10 assets)
│   ├── rw_reflexion_01.mp4    Persona mirando por ventana
│   ├── rw_documentos_02.mp4   Documentos sobre mesa
│   ├── rw_mirada_03.mp4       Primer plano de ojos serios
│   ├── rw_manos_04.mp4        Manos entrelazadas
│   ├── rw_calendario_05.mp4   Calendario con fechas marcadas
│   ├── rw_reloj_06.mp4        Reloj de pared
│   ├── rw_carta_07.mp4        Sobre de carta abriéndose
│   ├── rw_llaves_08.mp4       Llaves en mano
│   ├── rw_puerta_09.mp4       Puerta cerrándose suavemente
│   └── rw_sombra_10.mp4       Sombra en pared
│
├── documents_admin/            (10 assets)
│   ├── da_firma_01.mp4        Mano firmando documento
│   ├── da_sello_02.mp4        Sello estampando papel
│   ├── da_carpeta_03.mp4      Carpeta abriéndose
│   ├── da_pluma_04.mp4        Pluma sobre papel
│   ├── da_papel_05.mp4        Hoja de papel siendo leída
│   ├── da_impresora_06.mp4    Impresora imprimiendo
│   ├── da_archivo_07.mp4      Archivo ordenado
│   ├── da_lupa_08.mp4         Lupa sobre documento
│   ├── da_grapa_09.mp4        Grapadora sobre papel
│   └── da_sobre_10.mp4        Sobre lacrado
│
├── advisor_meeting/            (10 assets)
│   ├── am_reunion_01.mp4      Dos personas conversando
│   ├── am_apreton_02.mp4      Apretón de manos
│   ├── am_asesoria_03.mp4     Asesor señalando documento
│   ├── am_cafe_04.mp4         Tazas de café en mesa
│   ├── am_oficina_05.mp4      Oficina con luz natural
│   ├── am_dialogo_06.mp4      Primer plano de diálogo
│   ├── am_sonrisa_07.mp4      Sonrisa de confianza
│   ├── am_pizarra_08.mp4      Pizarra con anotaciones
│   ├── am_tablet_09.mp4       Tablet siendo usada
│   └── am_saludo_10.mp4       Saludo en recepción
│
├── healthy_lifestyle/          (10 assets)
│   ├── hl_paseo_01.mp4        Persona caminando en parque
│   ├── hl_fruta_02.mp4        Manos con fruta fresca
│   ├── hl_agua_03.mp4         Vaso de agua
│   ├── hl_naturaleza_04.mp4   Árboles con luz de sol
│   ├── hl_sol_05.mp4          Amanecer en montaña
│   ├── hl_estiramientos_06.mp4 Persona estirándose
│   ├── hl_bici_07.mp4         Bicicleta en camino rural
│   ├── hl_ensalada_08.mp4     Ensalada siendo preparada
│   ├── hl_meditacion_09.mp4   Persona meditando
│   └── hl_sonrisa_10.mp4      Sonrisa genuina al aire libre
│
└── financial_planning/         (10 assets)
    ├── fn_ahorro_01.mp4       Alcancía siendo llenada
    ├── fn_grafico_02.mp4      Gráfico en tablet
    ├── fn_alcancia_03.mp4     Mano poniendo moneda en alcancía
    ├── fn_billetes_04.mp4     Manos contando billetes
    ├── fn_calculadora_05.mp4  Calculadora y papel
    ├── fn_edificio_06.mp4     Edificio corporativo
    ├── fn_monedas_07.mp4      Pila de monedas creciendo
    ├── fn_libreta_08.mp4      Libreta de ahorros
    ├── fn_grafico_09.mp4      Gráfico de crecimiento
    └── fn_futuro_10.mp4       Horizonte de ciudad al atardecer
```

---

## Resumen

| Concepto | Valor |
|---|---|
| Assets mínimos MVP | 3 por categoría (21 total) |
| Assets beta cómoda | 10 por categoría (70 total) |
| Assets producción | 15-20 por categoría (120+ total) |
| Duración ideal por asset | 3-7s |
| Formato | 9:16 vertical, 1080×1920 |
| Rotación | Automática vía scoring (uses + recencia + jitter) |
| Sin repetición | ≥ 3 assets por categoría garantiza variedad |
| Identidad VPI | Tonos cálidos, contraste suave, cámara lenta |
