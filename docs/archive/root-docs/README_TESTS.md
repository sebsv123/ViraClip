# 🧪 Guía de Pruebas - ViraClip + ComfyUI

## Resumen de la Integración

✅ **ComfyUI instalado y configurado** para RTX 5070 8GB VRAM  
✅ **Pipeline integrado** en TaskService (Fase 10)  
✅ **4 features de IA** listas para usar:
   - 9:16 Reframe (VideoHelperSuite)
   - AI Thumbnails (SDXL-Turbo GGUF)
   - Auto Subtitles (Whisper)
   - B-Roll Transitions

---

## 🚀 Cómo Ejecutar las Pruebas

### Opción 1: Script Automático (Recomendado)

```bash
cd ~/proyectos/ViraClip
chmod +x run_tests.sh
./run_tests.sh
```

Este script hará:
1. Verificar/instalar dependencias (yt-dlp, ffmpeg)
2. Descargar el video de prueba de YouTube
3. Crear estructura de directorios
4. Verificar que ComfyUI está corriendo
5. Ejecutar las 4 pruebas del pipeline
6. Generar reporte final

### Opción 2: Paso a Paso Manual

#### Paso 1: Preparar entorno
```bash
export VIRA_ROOT=~/proyectos/ViraClip
mkdir -p $VIRA_ROOT/inputs/test_videos
mkdir -p $VIRA_ROOT/outputs/{test_channel,test_thumbnails,test_subtitles,test_comfy}
```

#### Paso 2: Descargar video de prueba
```bash
# Opción A: Desde YouTube
yt-dlp -f "best[height<=720]" \
  -o "$VIRA_ROOT/inputs/test_videos/seguro_3wgwaxIfUJQ.mp4" \
  "https://youtu.be/3wgwaxIfUJQ"

# Opción B: Crear video de prueba local (si yt-dlp falla)
ffmpeg -f lavfi -i testsrc=duration=300:size=1280x720:rate=30 \
  -f lavfi -i sine=frequency=1000:duration=300 \
  -pix_fmt yuv420p \
  $VIRA_ROOT/inputs/test_videos/seguro_test.mp4 -y
```

#### Paso 3: Verificar ComfyUI
```bash
# Verificar que está corriendo
curl http://localhost:8188/system_stats | head -10

# Si no responde, iniciarlo
cd $VIRA_ROOT && docker compose up -d comfyui
```

#### Paso 4: Ejecutar pruebas
```bash
cd $VIRA_ROOT
python3 test_pipeline_real.py
```

---

## 📊 Qué se Prueba

### Test 1: Pipeline Base (sin ComfyUI)
- Extrae 3-4 shorts de 15-25 segundos
- Usa Fases 1-9 del pipeline existente
- Output: `outputs/test_channel/`

### Test 2: ComfyUI Reframe + Thumbnail
- Aplica 9:16 reframe con VideoHelperSuite
- Genera thumbnail con SDXL-Turbo GGUF
- Output: `outputs/test_comfy/` y `outputs/test_thumbnails/`

### Test 3: ComfyUI Subtítulos
- Genera subtítulos SRT con Whisper
- Guarda video con subtítulos aplicados
- Output: `outputs/test_subtitles/`

### Test 4: Pipeline Completo
- Combina todas las features:
  - Reframe + Thumbnail + B-Roll + Subtítulos
- Optimizado para 8GB VRAM (chunk_size: 300)
- Output: múltiples directorios

---

## 🔧 Solución de Problemas

### Error: "No such container: viraclip-comfyui"
```bash
# Reiniciar ComfyUI
cd ~/proyectos/ViraClip
docker compose up -d comfyui
```

### Error: "OOM" / Out of Memory
```python
# En test_pipeline_real.py, reducir chunk_size:
comfyui_chunk_size=200  # Era 300
```

### Error: "Video not found"
```bash
# Crear video de prueba con ffmpeg
ffmpeg -f lavfi -i testsrc=duration=300:size=1280x720:rate=30 \
  -pix_fmt yuv420p ~/proyectos/ViraClip/inputs/test_videos/test.mp4 -y
```

### Error: "NVIDIA runtime not found"
```bash
# Configurar nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

---

## 📁 Estructura de Outputs

```
~/proyectos/ViraClip/outputs/
├── test_channel/
│   ├── short_test_base_01_c1.mp4
│   ├── short_test_base_01_c2.mp4
│   ├── short_test_base_01_c3.mp4
│   └── task_log_test_base_01.json
├── test_thumbnails/
│   ├── thumbnail_test_comfy_reframe_thumb_c1.png
│   └── full_test_comfy_full_c1.png
├── test_subtitles/
│   ├── subs_test_comfy_subtitles_c1.srt
│   └── short_test_comfy_subtitles_c1_with_srt.mp4
├── test_comfy/
│   ├── reframe_thumb_test_comfy_reframe_thumb_c1.mp4
│   ├── full_test_comfy_full_c1.mp4
│   └── task_log_*.json
└── test_report_final.json
```

---

## 🎯 Parámetros de Uso Real

### En código Python:
```python
from services.task_service import TaskService

await task_service.process_task(
    task_id="mi_task_123",
    url="https://youtu.be/3wgwaxIfUJQ",
    source_type="youtube",
    duration=25,
    min_rating=0.6,
    output_format="vertical",
    
    # Features ComfyUI (Fase 10)
    use_comfyui_reframe=True,
    use_comfyui_thumbnail=True,
    use_comfyui_subtitles=True,
    use_comfyui_broll=True,
    
    # Prompts y config
    thumbnail_prompt="face of insurance agent, bold text '¿Tienes seguro?',",
    comfyui_chunk_size=300,  # Para 8GB VRAM
)
```

---

## 📊 Estado Actual

| Componente | Estado |
|------------|--------|
| ComfyUI Docker | ✅ Corriendo |
| NVIDIA GPU | ✅ RTX 5070 detectada |
| Nodos VHS | ✅ Instalados |
| Nodos Whisper | ✅ Instalados |
| Nodos GGUF | ✅ Instalados |
| Modelo turbo-xl-Q4_0 | ✅ Listo (~3.5GB) |
| Integración TaskService | ✅ Fase 10 activa |
| Scripts de prueba | ✅ Creados |

---

## 🎉 Siguientes Pasos

1. Ejecutar `./run_tests.sh`
2. Verificar outputs en `~/proyectos/ViraClip/outputs/`
3. Revisar `test_report_final.json` para resultados
4. Si hay errores, consultar sección "Solución de Problemas"
5. Una vez validado, usar en producción con videos reales

---

**¿Listo para probar?** Ejecuta:
```bash
cd ~/proyectos/ViraClip && ./run_tests.sh
```
