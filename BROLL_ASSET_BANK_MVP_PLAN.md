# Plan Operativo MVP — Local B-roll Asset Bank VPI

## 1. Primera tanda MVP: 15 assets, 5 categorías, 3 por categoría

Se priorizan las 5 categorías con mayor impacto narrativo para contenido de seguros.
Se descartan `healthy_lifestyle` y `financial_planning` en MVP — se añadirán en beta.

### Tabla de assets sugeridos

| # | Categoría | Archivo | Descripción visual | Prioridad | Dónde conseguir |
|---|---|---|---|---|---|
| 1 | family_protection | `fp_calor_01.mp4` | Plano medio de familia sentada en sofá, luz natural de ventana, tonos cálidos | 🔴 Alta | Pexels "family sitting couch warm" o grabar con móvil |
| 2 | family_protection | `fp_reunion_02.mp4` | Padres e hijos alrededor de mesa de comedor, conversación tranquila | 🔴 Alta | Coverr "family dinner" o Pexels |
| 3 | family_protection | `fp_abrazos_03.mp4` | Abrazo de padres a hijos, plano medio, luz suave | 🔴 Alta | Pexels "family hug" |
| 4 | emotional_reassurance | `er_calma_01.mp4` | Persona sentada en sillón leyendo, luz natural entrando por ventana | 🔴 Alta | Coverr "person reading window" |
| 5 | emotional_reassurance | `er_te_02.mp4` | Primer plano de manos sosteniendo taza de té/café, vapor, fondo desenfocado | 🔴 Alta | Pexels "coffee cup hands" |
| 6 | emotional_reassurance | `er_ventana_03.mp4` | Ventana con cortinas moviéndose suavemente, luz de atardecer | 🟡 Media | Pexels "window curtains breeze" |
| 7 | risk_warning | `rw_reflexion_01.mp4` | Persona mirando por ventana, de espaldas, luz tenue, tonos azulados | 🔴 Alta | Pexels "person looking window" |
| 8 | risk_warning | `rw_documentos_02.mp4` | Documentos y papeles sobre escritorio de madera, iluminación suave | 🔴 Alta | Pexels "documents on desk" |
| 9 | risk_warning | `rw_manos_03.mp4` | Primer plano de manos entrelazadas sobre mesa, tonos neutros | 🟡 Media | Pexels "hands together table" |
| 10 | documents_admin | `da_firma_01.mp4` | Mano firmando un documento con pluma, plano detalle | 🔴 Alta | Pexels "signing document" |
| 11 | documents_admin | `da_sello_02.mp4` | Sello de goma estampando papel, plano detalle | 🟡 Media | Pexels "rubber stamp" |
| 12 | documents_admin | `da_carpeta_03.mp4` | Carpeta de cartón abriéndose, documentos en su interior | 🟡 Media | Coverr "folder opening" |
| 13 | advisor_meeting | `am_reunion_01.mp4` | Dos personas sentadas frente a frente en oficina, conversando | 🔴 Alta | Pexels "office meeting two people" |
| 14 | advisor_meeting | `am_apreton_02.mp4` | Apretón de manos, plano medio, fondo de oficina desenfocado | 🟡 Media | Pexels "handshake office" |
| 15 | advisor_meeting | `am_asesoria_03.mp4` | Asesor señalando documento en mesa, cliente asintiendo | 🟡 Media | Pexels "advisor pointing document" |

### Prioridades
- **🔴 Alta** (7 assets): Imprescindibles para que el planner tenga opciones reales
- **🟡 Media** (8 assets): Segundo lote, dan variedad sin ser críticos

---

## 2. Checklist de ingestión

Cada asset debe pasar estos controles antes de copiarlo al banco:

```
□ Formato: .mp4 (H.264)
□ Duración: 3-7 segundos
□ Resolución: ≥ 720p (1280×720 mínimo)
□ Orientación: vertical 9:16 (1080×1920 ideal, 720×1280 mínimo)
□ Sin logos, marcas de agua ni texto incrustado
□ Sin movimiento brusco (cámara estable o lenta)
□ Sin personas reconocibles sin permiso explícito
□ Sin música con copyright
□ Peso: < 10MB (ideal < 5MB)
□ Nombre de archivo sigue la convention: {cat}_{subestilo}_NN.mp4
```

---

## 3. Procedimiento de ingestión

### Paso 1: Descargar/obtener el asset
Obtener de Pexels, Coverr o grabación propia.
No usar APIs automáticas — descarga manual.

### Paso 2: Verificar con ffprobe
```bash
# Verificar duración, resolución, codec
ffprobe -v error -show_entries format=duration:stream=codec_name,width,height \
  -of default=noprint_wrappers=1 /ruta/al/asset.mp4

# Ejemplo de salida esperada:
# duration=5.040000
# codec_name=h264
# width=1080
# height=1920
```

### Paso 3: Convertir si es necesario
```bash
# Si no está en vertical 9:16 o el codec no es H.264:
ffmpeg -i input.mp4 -vf "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920" \
  -c:v libx264 -preset fast -crf 23 -an -y /app/assets/broll/{categoria}/{archivo}.mp4
```

### Paso 4: Copiar a la carpeta correcta
```bash
cp /ruta/al/asset.mp4 /app/assets/broll/{categoria}/{archivo}.mp4
```

### Paso 5: Validar que LocalBrollAssetBank lo detecta
```bash
docker compose exec worker sh -lc '.venv/bin/python -c "
from src.services.local_broll_asset_bank import find_asset, list_assets
assets = list_assets(\"{categoria}\")
print(f\"Assets en {categoria}: {len(assets)}\")
for a in assets:
    print(f\"  {a.name}\")
"'
```

### Paso 6: Test find_asset
```bash
docker compose exec worker sh -lc '.venv/bin/python -c "
from src.services.local_broll_asset_bank import find_asset
a = find_asset(\"{categoria}\")
print(f\"find_asset devuelve: {a.name if a else 'None'}\")
"'
```

---

## 4. Comandos de validación rápidos

### Listar todos los assets del banco
```bash
find /app/assets/broll -type f \( -name "*.mp4" -o -name "*.mov" -o -name "*.webm" -o -name "*.mkv" \) | sort
```

### Verificar duración y resolución de todos los assets
```bash
for f in $(find /app/assets/broll -name "*.mp4"); do
  dur=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$f" 2>/dev/null)
  res=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$f" 2>/dev/null)
  echo "$(basename $f): ${dur}s, ${res}"
done
```

### Test completo del Asset Bank
```bash
docker compose exec worker sh -lc '.venv/bin/python -c "
from src.services.local_broll_asset_bank import find_asset, list_assets
categorias = ['family_protection','emotional_reassurance','risk_warning','documents_admin','advisor_meeting']
for cat in categorias:
    assets = list_assets(cat)
    a = find_asset(cat)
    print(f'{cat}: {len(assets)} assets, find_asset={\"OK\" if a else \"NONE\"}')"'
```

---

## 5. Próximos pasos: de MVP a 70 assets

| Fase | Assets nuevos | Total | Acción |
|---|---|---|---|
| **MVP** (ahora) | 15 | 15 | Descargar 15 assets de Pexels/Coverr + ingerir |
| **Beta ampliación** | +15 | 30 | Añadir 3 más por categoría existente |
| **Beta categorías** | +20 | 50 | Añadir healthy_lifestyle + financial_planning (10 c/u) |
| **Producción** | +20 | 70 | Completar las 7 categorías a 10 assets c/u |

### Orden recomendado de descarga
1. Pexels (gratuito, HD, sin atribución obligatoria)
2. Coverr (CC0, vídeos cinematográficos)
3. Grabación propia con móvil (mejor control de identidad VPI)
4. Pixabay (gratuito, calidad variable)

### Mantenimiento semanal
- Revisar `.usage_history.json` para ver qué assets se usan más
- Si un asset tiene > 10 usos, considerar rotarlo manualmente
- Añadir 1-2 assets nuevos por semana para mantener frescura visual
