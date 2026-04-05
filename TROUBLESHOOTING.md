# ViraClip Troubleshooting Guide

Esta guía cubre los problemas más comunes y sus soluciones. **Ejecuta primero el script de diagnóstico** para identificar el problema.

---

## 🔍 Diagnóstico Rápido

### Ejecutar Script de Diagnóstico

```bash
# Verificar todo el sistema
python check_system.py

# Solo verificar Docker y contenedores
python check_system.py --docker-only
```

**Salida esperada:**
- ✅ Verde = Todo OK
- ❌ Rojo = Problema detectado (ver detalles)
- ⚠️ Amarillo = Advertencia (sistema funcional con limitaciones)

---

## 📋 Tabla de Síntomas → Causa → Solución

| **Síntoma** | **Causa Probable** | **Solución** |
|-------------|-------------------|--------------|
| **"No Clips Generated"** al 100% | LLM no responde / API key inválida | 1. Ejecuta `docker-compose exec worker python test_llm_connection.py`<br>2. Verifica `GOOGLE_API_KEY` en `.env`<br>3. Revisa logs: `docker-compose logs -f worker \| grep LLM` |
| Task se queda al 0% sin avanzar | Worker no arrancó / Redis no conecta | `docker-compose restart worker && docker-compose logs -f worker` |
| `ASSEMBLY_AI_API_KEY` error | Falta API key de AssemblyAI | 1. Obtén key en [AssemblyAI](https://www.assemblyai.com/)<br>2. Añade a `.env`: `ASSEMBLY_AI_API_KEY=xxx`<br>3. Reinicia: `docker-compose restart backend worker` |
| Worker crash con OOM (Out of Memory) | Video muy largo o 4K | 1. Limita duración: `MAX_VIDEO_DURATION=3600` (1h)<br>2. Usa `processing_mode=fast`<br>3. Aumenta memoria Docker a 8GB+ |
| `ERROR: connection to server failed` | PostgreSQL no iniciado | `docker-compose up -d postgres && docker-compose logs postgres` |
| Frontend no carga (localhost:3000) | Puerto en uso / contenedor no arrancó | 1. Verifica puerto: `netstat -ano \| findstr :3000`<br>2. Reinicia: `docker-compose restart frontend` |
| Whisper transcription muy lenta | Usando GPU cuando no hay / CPU lento | Ver sección **AMD / Sin GPU NVIDIA** abajo ⬇️ |
| `ModuleNotFoundError: No module named 'pydantic_ai'` | Dependencias no instaladas en worker | `docker-compose build --no-cache worker && docker-compose up -d` |
| Ollama no responde | Modelo no descargado / contenedor parado | `docker-compose exec ollama ollama pull llama3.2` |
| Redis `NOAUTH Authentication required` | Contraseña incorrecta en .env | Verifica `REDIS_PASSWORD` coincide con `docker-compose.yml` |
| `FileNotFoundError: video_path` | Video borrado durante procesamiento | Logs añadidos - ver `docker-compose logs worker` para causa raíz |
| Task completed but 0 clips | LLM retornó 0 segmentos | 1. Verifica transcripción: logs muestran `[AI ANALYSIS]`<br>2. Prueba video más largo (>2min)<br>3. Cambia LLM: `LLM=google:gemini-1.5-flash` |

---

## 🖥️ AMD / Sin GPU NVIDIA

ViraClip puede ejecutarse **sin GPU NVIDIA** en sistemas AMD o solo CPU. Configuración recomendada:

### Paso 1: Configurar Variables de Entorno

Edita tu archivo `.env`:

```bash
# Whisper en CPU (más lento pero funciona)
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8

# LLM: Usa Google Gemini (API cloud) en lugar de Ollama local
LLM=google:gemini-1.5-flash
GOOGLE_API_KEY=tu_clave_aqui

# O usa Ollama en CPU (muy lento)
LLM=ollama:llama3.2
OLLAMA_BASE_URL=http://ollama:11434

# Deshabilitar análisis de visión (requiere GPU)
VISION_ANALYSIS_ENABLED=false

# Limitar concurrencia de renders (evita saturar CPU)
RENDER_CONCURRENCY=2
```

### Paso 2: Modificar `docker-compose.yml`

**Elimina todas las referencias a GPU NVIDIA:**

```yaml
# ❌ ELIMINAR estas líneas del servicio ollama:
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
```

### Paso 3: Reiniciar Servicios

```bash
docker-compose down
docker-compose up -d --build
```

### Rendimiento Esperado (CPU AMD / Intel)

| **Operación** | **GPU NVIDIA** | **CPU** | **Notas** |
|--------------|---------------|---------|-----------|
| Transcripción Whisper (10 min video) | 30-60s | 5-15 min | Usar `WHISPER_MODEL_SIZE=tiny` para más velocidad |
| Render 1 clip (30s) | 10-20s | 60-120s | Usa `RENDER_CONCURRENCY=1` si se congela |
| Análisis LLM | ~5s | ~5s | Igual (cloud API) |

---

## 🔧 Comandos de Diagnóstico

### Ver Logs de Contenedores

```bash
# Todos los logs en tiempo real
docker-compose logs -f

# Solo un servicio específico
docker-compose logs -f worker
docker-compose logs -f backend
docker-compose logs -f postgres
docker-compose logs -f redis
docker-compose logs -f ollama

# Últimas 100 líneas
docker-compose logs --tail=100 worker

# Filtrar por palabra clave
docker-compose logs worker | grep -i "error"
docker-compose logs worker | grep -i "llm"
docker-compose logs worker | grep -i "clip"

# Guardar logs a archivo (debugging profundo)
docker-compose logs worker > worker_logs.txt
```

### Verificar Estado de Servicios

```bash
# Ver qué contenedores están corriendo
docker-compose ps

# Ver uso de recursos (CPU, RAM)
docker stats

# Entrar a un contenedor (debugging interactivo)
docker-compose exec worker bash
docker-compose exec backend bash
docker-compose exec postgres psql -U viraclip
```

### Verificar Conectividad de Servicios

```bash
# Redis
docker-compose exec redis redis-cli ping
# Esperado: PONG

# PostgreSQL
docker-compose exec postgres pg_isready -U viraclip
# Esperado: accepting connections

# Backend health
curl http://localhost:8000/api/health
# Esperado: {"status":"ok"}

# Ollama (si lo usas)
docker-compose exec ollama ollama list
# Esperado: lista de modelos
```

### Limpiar y Reiniciar Sistema

```bash
# Reinicio suave (mantiene datos)
docker-compose restart

# Reinicio completo (reconstruye contenedores)
docker-compose down
docker-compose up -d --build

# Limpiar TODO (⚠️ BORRA DATOS - solo para reset completo)
docker-compose down -v
docker system prune -a --volumes
docker-compose up -d --build
```

---

## 🐛 Debugging Avanzado: "No Clips Generated"

Este es el error más común. **Nuevos logs añadidos** para facilitar el diagnóstico.

### Paso 1: Verificar LLM

```bash
# Ejecutar test del LLM
docker-compose exec worker python test_llm_connection.py
```

**Salidas posibles:**

✅ **Éxito:**
```
LLM Model: google:gemini-1.5-flash
Google API Key: ✅ SET
✅ SUCCESS! LLM responded with 1 segment(s)
```

❌ **Error de API Key:**
```
❌ ERROR: LLM call failed!
Exception: AuthenticationError: Invalid API key
```
**Solución:** Verifica `GOOGLE_API_KEY` en `.env`

❌ **Error de modelo no soportado:**
```
❌ ERROR: Model 'google-gla:gemini-2.0-flash' not found
```
**Solución:** Cambia en `.env`: `LLM=google:gemini-1.5-flash`

### Paso 2: Ver Logs del Worker

```bash
docker-compose logs -f worker | grep -E "\[AI ANALYSIS\]|\[LLM CALL\]|CRITICAL|segments"
```

**Busca estos mensajes:**

✅ **Flujo normal:**
```
[LLM CALL] Initializing agent with model: google:gemini-1.5-flash
[LLM CALL] ✅ LLM responded successfully
[AI ANALYSIS] ✅ Complete: 5 segments found
[TASK xxx] ✅ 5 segments ready to render
```

❌ **LLM retorna 0 segmentos:**
```
[LLM CALL] ⚠️ WARNING: LLM returned 0 segments!
[AI ANALYSIS] ❌ CRITICAL: LLM returned 0 segments!
[TASK xxx] ❌❌❌ CRITICAL: segments_to_render is EMPTY!
```
**Causas:**
- Transcripción muy corta (< 1 minuto)
- LLM no pudo parsear el transcript
- API key con cuota agotada

**Solución:**
1. Prueba con video más largo (>3 minutos)
2. Verifica cuota en [Google AI Studio](https://aistudio.google.com/)
3. Cambia a otro LLM: `LLM=openai:gpt-4o-mini` + `OPENAI_API_KEY`

### Paso 3: Verificar Transcripción

```bash
docker-compose logs worker | grep -i "transcript"
```

Debe mostrar:
```
Transcript generated: 15234 characters
[AI ANALYSIS] Starting transcript analysis (duration=182.5s, transcript_length=15234 chars)
```

Si muestra `0 characters` o falla:
- Verifica `ASSEMBLY_AI_API_KEY` en `.env`
- Revisa logs: `docker-compose logs worker | grep -i "assembly"`

---

## 📊 Interpretación del Script de Diagnóstico

### Salida Ejemplo

```
✅ PASS | Docker daemon running (v24.0.7)
✅ PASS | docker-compose available (v2.23.0)
✅ PASS | All containers running (5 services)
✅ PASS | Redis responding to PING
✅ PASS | PostgreSQL accepting connections
❌ FAIL | Ollama has models loaded
       No models found. Run: docker-compose exec ollama ollama pull llama3.2
✅ PASS | Workers active (3 worker(s))
✅ PASS | Backend health endpoint (status: healthy)
❌ FAIL | Critical environment variables set
       Missing or empty: ASSEMBLY_AI_API_KEY

📊 Health Check Summary
⚠️  Most checks passed (7/9 - 77%)
ViraClip may work but some features might be limited.
```

**Interpretación:**
- **100%**: Todo OK, sistema listo
- **70-99%**: Funcional con limitaciones (ej: Ollama opcional si usas Google Gemini)
- **<70%**: Sistema no funcional, corregir errores críticos

---

## 🆘 Problemas No Resueltos

Si ninguna solución funciona:

### 1. Capturar Logs Completos

```bash
# Procesar un video corto (2-3 minutos)
# Mientras procesa, captura logs:
docker-compose logs -f worker > debug_worker.log

# Cuando termine (100%), detén con Ctrl+C
# Adjunta debug_worker.log al issue de GitHub
```

### 2. Verificar Configuración

```bash
# Exportar configuración del sistema
python check_system.py > system_check.txt
docker-compose config > docker_config.yml
```

### 3. Abrir Issue en GitHub

Incluye:
- `system_check.txt`
- `debug_worker.log`
- Tu archivo `.env` (⚠️ **OCULTA API KEYS**)
- Sistema operativo y versión Docker

---

## 📚 Recursos Adicionales

- **Documentación oficial**: `README.md`
- **Test LLM**: `backend/test_llm_connection.py`
- **Diagnóstico sistema**: `check_system.py`
- **Configuración ejemplo**: `.env.example`

---

## 🔄 Changelog de Fixes

| **Versión** | **Fix** | **Archivos** |
|------------|---------|--------------|
| 2024-04-02 | Logging detallado "No Clips Generated" | `ai.py`, `video_service.py`, `task_service.py` |
| 2024-04-02 | Script diagnóstico sistema | `check_system.py` |
| 2024-04-02 | Test conexión LLM | `backend/test_llm_connection.py` |
| 2024-04-02 | Guía troubleshooting completa | `TROUBLESHOOTING.md` |

---

**¿Aún tienes problemas?** Revisa los logs con los comandos de arriba y compara con los ejemplos de esta guía.
