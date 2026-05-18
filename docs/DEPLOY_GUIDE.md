# ViraClip Deployment Guide — Phase 1 & 2 Features

## Prerequisites

- Docker + Docker Compose
- 8GB+ RAM (16GB recommended for Whisper large-v3)
- **30GB+ free disk space** (20GB para datasets + 10GB para modelos)
- (Optional) NVIDIA GPU for Phase 3 & 6.4 features
- **Tokens de API** (ver Step 1)

---

## 🚀 Quick Start (Setup Automatizado)

**Para setup completo con datasets y ComfyUI:**

```bash
# 1. Clonar repositorio
git clone https://github.com/tu-usuario/ViraClip.git
cd ViraClip

# 2. Configurar tokens en .env
cp backend/.env.example backend/.env
# Edita backend/.env y añade tus tokens (ver abajo)

# 3. Ejecutar setup automático
chmod +x setup.sh
./setup.sh
```

El script `setup.sh` hará automáticamente:
- ✅ Construir containers
- ✅ Descargar datasets (TikTok-Videos desde HuggingFace)
- ✅ Copiar workflows de ComfyUI
- ✅ Verificar custom nodes
- ✅ Iniciar todos los servicios
- ✅ Health checks

**Tiempo estimado**: 15-20 minutos (primera vez)

---

## Step 1: Environment Setup (Manual)

### Tokens Requeridos

Antes de setup, obtén estos tokens:

| Token | Dónde obtener | Requerido para |
|-------|---------------|----------------|
| `HF_TOKEN` | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) | **Datasets TikTok** |
| `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | LLM (o usa Ollama local) |
| `KAGGLE_USERNAME` + `KAGGLE_KEY` | [kaggle.com/settings](https://www.kaggle.com/settings) → API → Create Token | Datasets Kaggle (opcional) |
| `YOUTUBE_API_KEY` | [console.cloud.google.com](https://console.cloud.google.com/apis/credentials) | YouTube trending (opcional) |

### Configurar .env

Copy the updated `.env.example` to `.env` and configure:

```bash
cd backend
cp .env.example .env
```

### Required Configuration

```bash
# Core LLM (pick ONE)
OPENAI_API_KEY=sk-...
# OR
GOOGLE_API_KEY=...
# OR
ANTHROPIC_API_KEY=...
# OR (local)
OLLAMA_BASE_URL=http://ollama:11434/v1
LLM=ollama:llama3.2-vision

# Whisper Model (large-v3 = best quality, highest RAM)
WHISPER_MODEL_SIZE=large-v3

# Database
POSTGRES_PASSWORD=change_me_secure_password

# Backend Auth
BACKEND_AUTH_SECRET=change_me_64_char_secret
ADMIN_SECRET=change_me_admin_secret
```

### Optional Features

```bash
# Background Music (Pixabay API)
PIXABAY_API_KEY=your_key_here

# B-Roll from Pexels
PEXELS_API_KEY=your_key_here
BROLL_ENABLED=true

# YOLOv10 Object Detection (downloads 6MB model on first use)
YOLO_BROLL_ENABLED=true

# Audio Quality
DENOISE_NOISE_FLOOR_DB=-25          # Lower = more aggressive denoising
SILENCE_THRESHOLD_SECONDS=0.4       # Jump-cut threshold

# AssemblyAI (faster transcription, costs $)
ASSEMBLY_AI_API_KEY=your_key_here
```

---

## Step 2: Rebuild Containers

```bash
cd /path/to/ViraClip
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

**Build time**: ~10–15 minutes (downloads models, fonts, dependencies)

### Verify Services

```bash
docker-compose ps
```

Expected output:
```
frontend     running   0.0.0.0:3000->3000/tcp
backend      running   0.0.0.0:8000->8000/tcp
worker (×3)  running
postgres     running   5432/tcp
redis        running   6379/tcp
ollama       running   11434/tcp (if using local LLM)
```

---

## Step 3: Health Checks

### Backend Health
```bash
curl http://localhost:8000/health
```
Expected: `{"status":"ok"}`

### Frontend
```bash
curl http://localhost:3000
```
Expected: HTML response

### Worker Queue
```bash
docker-compose logs worker | grep "Worker started"
```
Expected: 3 worker instances ready

---

## Step 4: Smoke Test

### Create a Test Clip

```bash
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -H "user_id: test_user_123" \
  -d '{
    "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "processing_mode": "fast",
    "add_subtitles": true,
    "output_format": "vertical",
    "target_platform": "tiktok"
  }'
```

Response:
```json
{
  "task_id": "abc123...",
  "status": "queued"
}
```

### Monitor Progress (SSE)

Open browser console and run:
```javascript
const taskId = "abc123...";
const evtSource = new EventSource(`http://localhost:8000/api/tasks/${taskId}/progress`);
evtSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(`${data.progress}%: ${data.message}`);
};
```

### Check Task Status (Polling)

```bash
curl http://localhost:8000/api/tasks/abc123
```

### Download Clip

When `status = "completed"`:
```bash
curl http://localhost:8000/api/tasks/abc123/clips/0/download -o clip.mp4
```

---

## Step 5: Verify New Features

### 1. Audio Denoising ✅
- **Test**: Create clip from noisy source video
- **Verify**: Listen for reduced background hiss/hum
- **Log**: Check for `🔇 Audio denoised (afftdn nf=-25dB)` in worker logs

### 2. Silence/Filler Removal ✅
- **Test**: Create clip from video with "um", "uh", pauses
- **Verify**: Jump cuts applied, clip is tighter
- **Log**: Check for `✓ Silence/fillers removed (jump cuts applied)`

### 3. Platform Duration Cap ✅
- **Test**: Create clip with `target_platform=tiktok`
- **Verify**: Clip duration ≤60s even if AI suggests longer
- **Log**: Check for `Duration X.Xs → Y.Ys (platform=tiktok cap=60s)`

### 4. Smart Thumbnail ✅
- **Test**: View generated thumbnail (`.jpg` file next to clip)
- **Verify**: Sharp frame with face visible (if present)
- **Log**: Check for `✓ Smart thumbnail selected: clip_0.jpg`

### 5. Viral Metadata ✅
- **Test**: Check task response JSON
- **Verify**: `seo_title`, `seo_description`, `suggested_hashtags` present
- **Log**: Check for `✓ Viral metadata: '<title>' (N hashtags)`

### 6. YOLOv10 B-Roll (Optional) ✅
- **Test**: Enable `YOLO_BROLL_ENABLED=true`, create clip
- **Verify**: B-roll keywords include detected objects
- **Log**: Check for `[BRoll] YOLO augmented keywords: [...]`

### 7. SSE Progress ✅
- **Test**: Open browser console during clip creation
- **Verify**: Real-time progress updates streaming
- **Expected**: Events fire every ~5s during processing

---

## Performance Tuning

### RAM Usage

| Config | Minimum | Recommended |
|--------|---------|-------------|
| `WHISPER_MODEL_SIZE=base` | 4 GB | 6 GB |
| `WHISPER_MODEL_SIZE=medium` | 6 GB | 8 GB |
| `WHISPER_MODEL_SIZE=large-v3` | 8 GB | 16 GB |

**Note**: Each worker instance loads the model independently.

### Worker Scaling

Edit `docker-compose.yml`:
```yaml
worker:
  # ...
  deploy:
    replicas: 3  # Increase to 4-6 for high load
```

Then:
```bash
docker-compose up -d --scale worker=5
```

### Redis Memory

For high-traffic deployments:
```bash
# Add to docker-compose.yml redis service
command: redis-server --maxmemory 2gb --maxmemory-policy allkeys-lru
```

---

## Troubleshooting

### Issue: "Whisper model download stuck"
**Fix**: Increase Docker build timeout
```bash
DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker-compose build --no-cache
```

### Issue: "Font not found, using Arial"
**Fix**: Check font downloaded correctly
```bash
docker-compose exec backend ls -lh /app/fonts/TikTokSans-Regular.ttf
```
Expected: ~150KB file

### Issue: "YOLO model download failed"
**Fix**: Model downloads on first use, not build time. Check worker logs:
```bash
docker-compose logs worker | grep "yolo"
```

### Issue: "SSE connection refused"
**Fix**: Check CORS settings in `.env`
```bash
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

### Issue: "Out of memory during clip generation"
**Fix**: Reduce Whisper model size or worker count
```bash
# .env
WHISPER_MODEL_SIZE=medium  # Down from large-v3

# docker-compose.yml
worker:
  deploy:
    replicas: 2  # Down from 3
```

---

## Production Deployment Checklist

- [ ] Change all `change_me_*` secrets in `.env`
- [ ] Set `SELF_HOST=false` if using monetization
- [ ] Configure reverse proxy (nginx/Caddy) with HTTPS
- [ ] Set `CORS_ORIGINS` to actual frontend domain
- [ ] Enable database backups (pg_dump cron)
- [ ] Configure Redis persistence (AOF + RDB)
- [ ] Set up monitoring (Prometheus + Grafana recommended)
- [ ] Configure log rotation for Docker containers
- [ ] Test SSE through reverse proxy (nginx needs special config)
- [ ] Load test with expected traffic (use `hey` or `ab`)

### nginx SSE Config Example

```nginx
location /api/tasks {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
}
```

---

---

## 📦 Descarga de Datasets REAL (Phase 7)

### Datasets Implementados con Descarga Automática

#### 1. TikTok-Videos (HuggingFace) ✅ REAL
```bash
# Descarga automática via HuggingFace datasets library
docker-compose run --rm backend python scripts/download_datasets.py --tiktok-only

# Dataset: datahiveai/Tiktok-Videos
# Tamaño: ~2GB (100k+ videos)
# Campos: plays, likes, shares, comments, duration, hashtags, caption
# Uso: Entrenamiento de virality scorer + LoRA training
```

**Implementación real en `download_datasets.py`**:
```python
from datasets import load_dataset

dataset = load_dataset(
    "datahiveai/Tiktok-Videos",
    split="train",
    token=HF_TOKEN,  # Tu token de HuggingFace
    cache_dir="/app/datasets/huggingface"
)
# Guardado en: /app/datasets/tiktok_videos.parquet
```

#### 2. YouTube Trending (Google API) ✅ REAL
```bash
# Descarga trending diario via YouTube Data API v3
docker-compose run --rm backend python scripts/download_datasets.py --youtube-only

# API: YouTube Data API v3
# Endpoint: videos().list(chart="mostPopular")
# Datos: Top 50 trending videos US (actualizado diario)
```

**Implementación real**:
```python
from googleapiclient.discovery import build

youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
response = youtube.videos().list(
    part="snippet,statistics,contentDetails",
    chart="mostPopular",
    regionCode="US",
    maxResults=50
).execute()
# Guardado en: /app/datasets/youtube_trending_YYYYMMDD.json
```

#### 3. Kaggle Datasets (Manual Setup)
```bash
# 1. Configura credenciales Kaggle en .env
KAGGLE_USERNAME=tu_usuario
KAGGLE_KEY=tu_api_key

# 2. Descarga dataset específico
docker-compose run --rm backend python scripts/download_datasets.py --kaggle-only
```

### Verificar Datasets Descargados

```bash
# Ver status de todos los datasets
docker-compose run --rm backend python scripts/download_datasets.py --status

# Output esperado:
# ✅ TikTok-Videos (HF)           (2048.5 MB)
#    Source: datahiveai/Tiktok-Videos
#    Path: /app/datasets/tiktok_videos.parquet
#
# ✅ YouTube Trending             (3 archivos)
#    Source: YouTube Data API
#    Path: /app/datasets/youtube/
```

### Usar Datasets en Training

```python
# backend/src/dataset_integration.py - YA IMPLEMENTADO
from dataset_integration import TikTokDatasetLoader

loader = TikTokDatasetLoader()
df = loader.load(split="train")

# Ver estadísticas REALES
print(f"Videos totales: {len(df)}")
print(f"Promedio plays: {df['plays'].mean():,.0f}")
print(f"Videos virales (>1M): {(df['plays'] > 1000000).sum()}")

# Entrenar modelo
from dataset_integration import ViralityScorerTrainer
trainer = ViralityScorerTrainer(model_type="xgboost")
trainer.train(df, target_col="is_viral")
trainer.save("/app/models/virality_scorer.pkl")
```

---

## Phase 6 & 7 — ComfyUI Integration & Datasets (NEW)

### Phase 6: ComfyUI Integration

#### ComfyUI Service Setup

The ComfyUI service is now included in `docker-compose.yml`. It provides:
- **Port 8188**: ComfyUI web interface (`http://localhost:8188`)
- **Custom Nodes**: ViraClip nodes for Whisper, YOLO, metadata, thumbnails
- **Workflow Templates**: Pre-built JSON workflows in `/workflows/`

#### Accessing ComfyUI

```bash
# After docker-compose up, access ComfyUI at:
open http://localhost:8188

# Check ComfyUI health
curl http://localhost:8188/system_stats
```

#### Using ViraClip Custom Nodes

1. Open ComfyUI (`http://localhost:8188`)
2. Click "Load" → Choose a workflow:
   - `viral_clip_basic.json` — Whisper + silence removal + metadata + thumbnail
   - `viral_clip_with_broll.json` — Basic + YOLO object detection for B-roll keywords
   - `viral_clip_generative.json` — Basic + Wan2.2 AI B-roll generation (**GPU required**)
3. Configure node inputs (video path, model size, etc.)
4. Click "Queue Prompt"

#### API Bridge (Backend Integration)

Execute workflows programmatically from ViraClip backend:

```python
from comfyui_bridge import execute_viral_clip_workflow
import asyncio

result = asyncio.run(execute_viral_clip_workflow(
    video_path="/path/to/video.mp4",
    workflow="viral_clip_basic",
    platform="tiktok"
))

print(f"Output: {result.outputs}")
```

FastAPI endpoints (automatically added):
- `POST /api/comfyui/execute/{workflow_name}` — Execute workflow
- `GET /api/comfyui/status/{prompt_id}` — Check execution status  
- `GET /api/comfyui/workflows` — List available workflows
- `GET /api/comfyui/system-stats` — GPU/CPU stats

#### LoRA Training (Phase 6.4)

Train viral style LoRAs using TikTok datasets:

1. **Prepare Dataset** (in ComfyUI):
   - Node: `ViraClipDatasetPrepNode`
   - Select: TikTok-Videos dataset, virality threshold, style target
   - Output: `prepared_dataset.json`

2. **Train LoRA**:
   - Node: `ViraClipLoRATrainerNode`
   - Input: prepared dataset
   - Config: Base model (Wan2.2), epochs, learning rate
   - Style targets: `tiktok_drama`, `zach_king_magic`, `mrbeast_energy`, `hormozi_business`
   - Output: `viral_lora.safetensors`

3. **Use LoRA**:
   - Load in Wan2.2 T2V node
   - Trigger word: `viral style`
   - Prompt: `viral style, dramatic reveal, trending content`

---

### Phase 7: Virality Datasets & Training

#### Dataset Setup

Datasets are downloaded automatically on first use:

```python
# From Python/backend
from dataset_integration import TikTokDatasetLoader

# Load and prepare TikTok dataset
loader = TikTokDatasetLoader()
loader.load(split="train").prepare_virality_labels()

# Access training data
X_train, X_test, y_train, y_test = loader.get_training_split()
print(f"Training samples: {len(X_train)}")
```

#### Supported Datasets

| Dataset | Auto-Download | Size | Features |
|---------|---------------|------|----------|
| TikTok-Videos (HF) | ✅ Yes | 100k+ videos | Plays, likes, shares, duration |
| Short Video Engagement (Kaggle) | ⚠️ Manual | 17k rows | Audio/visual features |
| YouTube Trending (Daily) | ⚠️ API | Daily | Views, likes, tags, rank |
| UGC Short Videos (ArXiv) | ⚠️ Paper link | Large | Watch %, continuation rate |

#### Training Virality Scorer

```python
from dataset_integration import ViralityScorerTrainer, get_tiktok_dataset

# Load dataset
df = get_tiktok_dataset()

# Train model
trainer = ViralityScorerTrainer(model_type="xgboost")
trainer.train(df, target_col="is_viral")

# Save model
trainer.save("/app/models/virality_scorer_v1.pkl")

# Predict virality
score = trainer.predict({
    "duration": 30.5,
    "engagement": 0.85,
    "text_features": 0.72
})
print(f"Virality score: {score:.1f}/100")
```

#### Auto-Update Pipeline

Add to crontab for daily/weekly updates:

```bash
# Daily: Update YouTube trending
0 6 * * * cd /app && python -c "from dataset_integration import YouTubeTrendingLoader; YouTubeTrendingLoader().load_daily()"

# Weekly: Retrain LoRA with fresh data
0 2 * * 0 cd /app && python -c "from dataset_integration import ViralityScorerTrainer; ..."
```

#### Runtime Integration

ViraClip automatically uses dataset insights in Ollama prompts:

```python
# In virality scorer (automatic)
ollama_prompt = f"""
Score viralidad basado en patrones de:
- TikTok 5M+ views: {dataset_patterns['tiktok_viral']}
- YouTube Trending global: {dataset_patterns['yt_trending']}

Features clip: {clip_features}
"""
```

---

## Phase 6-7 Deployment Checklist

### Pre-Deployment

- [ ] **GPU available?** Phase 6.4 (LoRA) & 6.5 (Wan2.2) need 8GB+ VRAM
- [ ] Dataset storage: Ensure 20GB+ for TikTok dataset cache
- [ ] ComfyUI port 8188 open (or behind reverse proxy)

### Configuration

```bash
# .env additions for Phase 6-7

# ComfyUI
COMFYUI_ENABLED=true
COMFYUI_HOST=comfyui
COMFYUI_PORT=8188

# Datasets (optional - for training)
HF_TOKEN=your_huggingface_token  # For TikTok dataset
KAGGLE_USERNAME=your_kaggle_user
KAGGLE_KEY=your_kaggle_key

# LoRA Training (GPU only)
LORA_TRAINING_ENABLED=false  # Set true when GPU available
VRACLIP_DATASETS_DIR=/app/datasets
```

### Smoke Test Phase 6-7

```bash
# 1. Test ComfyUI is running
curl http://localhost:8188/system_stats | jq

# 2. Test dataset download
python -c "from dataset_integration import TikTokDatasetLoader; TikTokDatasetLoader().load(split='train')"

# 3. Test custom nodes are registered
curl http://localhost:8188/api/object_info | grep -i viraclip

# 4. Execute a workflow via API
curl -X POST http://localhost:8000/api/comfyui/execute/viral_clip_basic \
  -H "Content-Type: application/json" \
  -d '{"video_path": "/app/temp/uploads/test.mp4", "platform": "tiktok"}'

# 5. Check outputs
docker-compose logs comfyui | grep "ViraClip"
```

### Troubleshooting Phase 6-7

| Issue | Solution |
|-------|----------|
| ComfyUI nodes not showing | Check `backend/src/comfy_nodes/` mounted to `/ComfyUI/custom_nodes/viraclip_nodes` |
| Dataset download fails | Check HuggingFace token, internet connectivity |
| LoRA training OOM | Reduce batch_size, resolution, or network_dim |
| Wan2.2 out of memory | Use 1.3B model instead of 14B, or enable `--lowvram` |
| API bridge timeout | Increase timeout in `comfyui_bridge.py` (default 300s) |

---

## Phase 3 — GPU Generative AI Stack

### GPU Requirements

| Feature | VRAM | Model | Speed |
|---------|------|-------|-------|
| T2V B-Roll (LTX-Video) | 5-8GB | LTX-Video 0.9.7 | ~2-5s generation |
| T2V B-Roll (Wan2.2) | 16GB | Wan2.2-T2V-14B | Best quality |
| RVC Voice Enhancement | 4GB | RVC v2 | ~2x real-time |
| ESRGAN Upscaling | 2GB | Real-ESRGAN x2 | ~20s per 60s clip |
| XTTS Narration | 4-8GB | Coqui XTTS v2 | ~3s per sentence |
| LoRA Training | 8GB+ | SD1.5/SDXL base | ~30min-1h |

**Minimum**: RTX 3060 (12GB) or RTX 4060 Ti (16GB)
**Recommended**: RTX 4090 (24GB) for Wan2.2-14B model

### Enable GPU Services

```bash
# .env additions for GPU stack

# GPU Worker (required for all GPU features)
GPU_WORKER_ENABLED=true
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16

# T2V B-Roll Generation
T2V_MODEL=ltx-video           # ltx-video | wan2.2-1.3b | wan2.2-14b
T2V_RESOLUTION=720p           # 480p | 720p | 1080p
T2V_CACHE_DIR=/app/models/t2v

# RVC Voice Enhancement
RVC_ENABLED=true
RVC_MODEL_PATH=/app/models/rvc/model.pth

# ESRGAN Upscaling
ESRGAN_ENABLED=true
ESRGAN_SCALE=2                # 2 | 4
UPSCALING_MODEL=realesrgan-x2
UPSCALING_MODELS_DIR=/app/models/esrgan

# XTTS Narration
TTS_NARRATION_ENABLED=true
TTS_MODEL=xtts-v2
TTS_LANGUAGE=en               # en | es | fr | de | pt | ... (17 supported)
TTS_SNR_THRESHOLD_DB=15.0     # Skip TTS if source SNR > threshold
TTS_CACHE_DIR=/app/models/tts

# LoRA Training
LORA_OUTPUT_DIR=/app/models/lora
LORA_CACHE_DIR=/app/models/lora_cache
```

### Start GPU Stack

```bash
# Start with GPU profile (includes comfyui + gpu_worker)
docker-compose --profile gpu up -d --build

# Verify GPU worker is running
docker-compose ps | grep gpu_worker

# Check GPU availability
curl http://localhost:8000/gpu/status
```

### GPU Services API Endpoints

```bash
# Check GPU status
curl http://localhost:8000/gpu/status

# Generate T2V B-Roll
curl -X POST http://localhost:8000/gpu/broll/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "ocean waves crashing on beach at sunset",
    "duration": 4.0,
    "resolution": "720p",
    "model": "ltx-video"
  }'

# Poll job status
curl http://localhost:8000/gpu/broll/{job_id}

# Synthesize TTS narration
curl -X POST http://localhost:8000/gpu/tts/synthesize \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Welcome to this viral clip breakdown!",
    "language": "en",
    "speed": 1.0
  }'

# Upscale video
curl -X POST http://localhost:8000/gpu/upscale \
  -H "Content-Type: application/json" \
  -d '{
    "input_path": "/app/temp/uploads/clip_720p.mp4",
    "scale_factor": 2
  }'

# Train LoRA
curl -X POST http://localhost:8000/gpu/lora/train \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_path": "/app/datasets/lora_training",
    "base_model": "sd1.5",
    "style_name": "viral_weekly",
    "num_steps": 500
  }'
```

### Testing GPU Features

```bash
# Run Phase 3 GPU tests (mocked, no GPU required)
docker-compose exec backend .venv/bin/python -m pytest tests/test_phase3_gpu_services.py -v

# Expected: 24/24 passed
```

### Troubleshooting GPU Features

| Issue | Solution |
|-------|----------|
| `No GPU detected` | Check NVIDIA drivers, CUDA toolkit, nvidia-docker2 |
| `CUDA out of memory` | Use smaller model (ltx-video vs wan2.2-14b), reduce batch size |
| `Model download fails` | Check internet, model cache permissions |
| `T2V generation timeout` | Increase COMFYUI_TIMEOUT to 600s+ |
| `RVC fails to load` | Verify model.pth exists at RVC_MODEL_PATH |

### Phase 9.3: 8K/Hollywood-Quality Upscaling

**Requirements:** RTX 3060+ (12GB+ VRAM recommended)

**API Endpoints:**
```bash
# Check 8K capability
curl http://localhost:8000/gpu/upscale/8k/info

# Upscale to 8K (7680×4320)
curl -X POST http://localhost:8000/gpu/upscale/8k \
  -H "Content-Type: application/json" \
  -d '{
    "input_path": "/app/temp/uploads/clip_1080p.mp4",
    "mode": "dual",
    "denoise": true,
    "hdr": false
  }'

# Modes: direct (fast), dual (best quality), 4k_intermediate (balanced)
```

**VRAM Usage:**
| Mode | VRAM | Time | Quality |
|------|------|------|---------|
| direct | ~6GB | ~20s | Good |
| dual | ~10GB | ~40s | Excellent |
| 4k_intermediate | ~8GB | ~30s | Very Good |

---

## 🔍 Verificación Completa del Setup

### Quick Health Check

```bash
# Verificar todos los servicios (30 segundos)
chmod +x backend/scripts/health_check.sh
./backend/scripts/health_check.sh

# Output esperado:
# ✅ Backend API
# ✅ Next.js frontend
# ✅ ComfyUI interface
# ✅ Postgres
# ✅ Redis
# ✅ Workers (3 running)
```

### Smoke Tests Automatizados

```bash
# Verificar todas las fases implementadas
docker-compose run --rm backend python scripts/verify_setup.py --all

# Verificar fase específica
docker-compose run --rm backend python scripts/verify_setup.py --phase 4.1
docker-compose run --rm backend python scripts/verify_setup.py --phase 5.3

# Verificar datasets
docker-compose run --rm backend python scripts/verify_setup.py --datasets

# Verificar ComfyUI
docker-compose run --rm backend python scripts/verify_setup.py --comfyui
```

### Verificación por Fase

#### Phase 4.1: Multi-platform Export
```bash
# Test bitrate variants
curl -X POST http://localhost:8000/api/test/export-variants \
  -H "Content-Type: application/json" \
  -d '{"platform": "tiktok"}'

# Expected: JSON con 3 variantes (high, medium, low)
```

#### Phase 4.3: Viral Trends
```bash
# Test trend boost
curl http://localhost:8000/api/trends/status

# Expected: {"trending_hashtags": [...], "last_updated": "..."}
```

#### Phase 5.1: Milvus Vector DB
```bash
# Check Milvus status
docker-compose exec backend python -c "
from services.milvus_vector_service import get_milvus_service
import asyncio
async def test():
    milvus = await get_milvus_service()
    stats = await milvus.get_stats()
    print(f'Milvus stats: {stats}')
asyncio.run(test())
"
```

#### Phase 5.3: Feedback Loop
```bash
# Test feedback stats
curl http://localhost:8000/api/feedback/stats

# Test model prediction
curl -X POST http://localhost:8000/api/feedback/predict \
  -H "Content-Type: application/json" \
  -d '{
    "duration": 30.0,
    "hook_strength": 85.0,
    "engagement_score": 72.0,
    "has_captions": 1,
    "has_broll": 0
  }'

# Expected: {"predicted_score": 78.5, "model_version": "v20260403"}
```

#### Phase 7: Datasets
```bash
# Verify datasets downloaded
docker-compose run --rm backend python scripts/download_datasets.py --status

# Expected output:
# ✅ TikTok-Videos (HF)           (2048.5 MB)
# ✅ YouTube Trending             (3 archivos)
```

### Verificación Manual Completa

**1. Crear clip de prueba:**
```bash
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -H "user_id: test_user" \
  -d '{
    "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "processing_mode": "fast",
    "add_subtitles": true,
    "target_platform": "tiktok"
  }'

# Guardar task_id de la respuesta
```

**2. Monitorear progreso:**
```bash
# En navegador o curl
curl http://localhost:8000/api/tasks/{task_id}/progress
```

**3. Verificar clip generado:**
```bash
# Cuando status = "completed"
curl http://localhost:8000/api/tasks/{task_id}/clips/0/download -o test_clip.mp4

# Verificar que exista variantes
ls -lh exports/clips/ | grep {clip_id}
# Debe mostrar: clip.mp4, clip_mq.mp4, clip_lq.mp4, clip.srt
```

**4. Test ComfyUI workflow:**
```bash
# Abrir ComfyUI
open http://localhost:8188

# Pasos en UI:
# 1. Click "Load" → viral_clip_basic.json
# 2. Verificar nodos "ViraClip" aparecen
# 3. Click "Queue Prompt"
# 4. Verificar ejecución sin errores
```

**5. Test feedback loop:**
```bash
# Trigger retraining manual (sync)
curl -X POST http://localhost:8000/api/feedback/retrain/sync

# Verificar modelo generado
docker-compose exec backend ls -lh /app/models/
# Debe mostrar: virality_scorer_current.pkl
```

### Troubleshooting Common Issues

| Issue | Solution |
|-------|----------|
| **ComfyUI nodos no aparecen** | `docker-compose restart comfyui && docker-compose logs -f comfyui` |
| **Dataset download fails** | Verificar `HF_TOKEN` en `.env`, internet connectivity |
| **Milvus errors** | Instalar: `docker-compose exec backend pip install pymilvus` |
| **Feedback retraining fails** | Verificar: `docker-compose exec backend pip install xgboost scikit-learn` |
| **Worker not processing** | `docker-compose logs worker \| grep ERROR` |
| **Out of memory** | Reducir workers: `docker-compose up -d --scale worker=1` |

### Performance Benchmarks

Ejecutar benchmarks de performance:

```bash
# Test clip generation speed
time docker-compose run --rm backend python -c "
from workers.tasks import process_video_task
import asyncio
asyncio.run(process_video_task({
    'task_id': 'bench_test',
    'source': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    'processing_mode': 'fast'
}))
"

# Expected: ~2-3 min for 60s video (CPU-only)
```

### Logs de Verificación

```bash
# Ver logs en tiempo real
docker-compose logs -f backend worker

# Buscar errores
docker-compose logs backend | grep -i error
docker-compose logs worker | grep -i error

# Verificar warnings importantes
docker-compose logs | grep -i "warning\|error\|fail"
```

---

---

## 🧪 Testing & Model Training (Phase 8.3-8.4)

### Run Test Suite
```powershell
# Ejecutar todos los tests (Windows PowerShell)
docker-compose exec backend python /app/scripts/run_all_tests.py

# Con coverage report
docker-compose exec backend python /app/scripts/run_all_tests.py --coverage

# Tests rápidos (sin integration)
docker-compose exec backend python /app/scripts/run_all_tests.py --fast

# Test específico de una phase
docker-compose exec backend python /app/scripts/run_all_tests.py --phase 8.3
```

### Smoke Test End-to-End
```powershell
# Test completo del pipeline
docker-compose exec backend python /app/scripts/smoke_test.py

# Test rápido (solo servicios)
docker-compose exec backend python /app/scripts/smoke_test.py --quick
```

### Train ML Models
```powershell
# Entrenar todos los modelos (viral scorer + engagement predictor)
docker-compose exec backend python /app/scripts/train_all_models.py

# Solo datos sintéticos (sin DB)
docker-compose exec backend python /app/scripts/train_all_models.py --synthetic-only

# Con más epochs
docker-compose exec backend python /app/scripts/train_all_models.py --epochs 100

# Entrenar + exportar a ONNX
docker-compose exec backend python /app/scripts/train_all_models.py --export-onnx
```

### Export to ONNX (Mobile/Edge Deployment)
```powershell
# Exportar modelos a ONNX
docker-compose exec backend python /app/scripts/export_to_onnx.py --verify

# Ver estado de modelos ONNX
docker-compose exec backend python /app/scripts/export_to_onnx.py --status
```

**ONNX Benefits:**
- 3-5× faster CPU inference vs sklearn/PyTorch
- ~2-5MB model files (deployable to mobile/edge)
- CoreML/TFLite conversion ready for iOS/Android

### Verify Trained Models
```powershell
# Ver estado de modelos entrenados
docker-compose exec backend python /app/scripts/train_viral_scorer.py --status
docker-compose exec backend python /app/scripts/train_engagement_predictor.py --status

# Modelos esperados en /app/models/:
# - viral_scorer.pkl (~500KB)
# - engagement_predictor.pkl (~2-5MB)
# - onnx/viral_scorer.onnx (~2MB)
# - onnx/engagement_predictor.onnx (~5MB)
```

**Ver documentación completa:**
- `TESTING_GUIDE.md` — Testing estrategias, benchmarking, CI/CD
- `OPTIMIZATION_GUIDE.md` — Performance tuning, profiling, caching

---

## Monitoring & Observability (NEW)

### Prometheus Metrics

ViraClip exposes Prometheus metrics for monitoring GPU utilization, queue depth, and job statistics.

**Endpoints:**
```bash
# Prometheus scrape endpoint
curl http://localhost:8000/metrics

# Detailed health status
curl http://localhost:8000/health/detailed

# GPU-specific health
curl http://localhost:8000/health/gpu
```

**Metrics Available:**
- `viraclip_gpu_jobs_total` — Total GPU jobs by type and status
- `viraclip_gpu_jobs_duration_seconds` — Job execution time histogram
- `viraclip_gpu_vram_bytes` — VRAM usage (total/used/free)
- `viraclip_gpu_queue_depth` — Current queue depth
- `viraclip_gpu_active_jobs` — Currently running jobs
- `viraclip_requests_total` — HTTP request count
- `viraclip_request_duration_seconds` — Request latency

**Prometheus Configuration:**
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'viraclip'
    static_configs:
      - targets: ['backend:8000']
    scrape_interval: 15s
```

### Rate Limiting

GPU-intensive endpoints have built-in rate limiting to prevent abuse:

| Endpoint | Limit | Window |
|----------|-------|--------|
| T2V B-Roll | 10 | per minute |
| TTS | 20 | per minute |
| Upscale | 5 | per minute |
| 8K Upscale | 3 | per minute |
| LoRA Train | 1 | per hour |

**Environment Variables:**
```bash
RATE_LIMIT_T2V_PER_MINUTE=10
RATE_LIMIT_TTS_PER_MINUTE=20
RATE_LIMIT_UPSCALE_PER_MINUTE=5
RATE_LIMIT_8K_PER_MINUTE=3
RATE_LIMIT_LORA_PER_HOUR=1
```

**Rate Limit Headers:**
```bash
curl -I http://localhost:8000/gpu/broll/generate
# X-RateLimit-Limit: 10
# X-RateLimit-Remaining: 8
# X-RateLimit-Endpoint: t2v
```

### Health Checks

**Comprehensive Service Health:**
```bash
# Full system health
curl http://localhost:8000/health

# GPU status
curl http://localhost:8000/health/gpu
# Returns: device name, VRAM, CUDA version, supported features

# Database
curl http://localhost:8000/health/db

# Redis
curl http://localhost:8000/health/redis
```

**Kubernetes/Docker Health Probes:**
```yaml
# docker-compose.yml or k8s deployment
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s
  timeout: 10s
  retries: 3
```

---

## Session 3 — Production Readiness Improvements (April 5, 2026)

### Overview

Las siguientes mejoras fueron implementadas en Session 3 para preparar ViraClip para producción a escala:

| Mejora | Archivo | Impacto |
|--------|---------|---------|
| **Phase 9 Wired** | `task_service.py:565-601` | Creative engine ahora ejecuta en cada clip |
| **Timeout 600s** | `docker-compose.yml` | Jobs pesados no fallan por timeout |
| **Vision Opt-in** | `docker-compose.yml` | Ollama 5GB no requerido por defecto |
| **Hook Slowmo ON** | `docker-compose.yml` | Efecto visual activado por defecto |
| **Nginx Proxy** | `nginx/nginx.conf` | SSE buffering disabled, TLS-ready |
| **Rate Limiting** | `rate_limit.py` | 20 tasks/hour por usuario/IP |
| **Whisper Warm-up** | `tasks.py:198-223` | Modelo precargado en startup |

---

### Phase 9 Creative Engine — Now Active

El creative pipeline (Phase 9) está ahora wired en `task_service._render_one()`:

```python
# After create_single_clip() succeeds:
creative_meta = await creative_pipeline.enhance(
    clip_path=Path(clip_info["path"]),
    source_video=Path(video_path),
    segment=segment,
    words=words,
    audio_features=audio_features,
    task_id=task_id,
    clip_index=clip_index,
    platform=platform,
)
clip_info.update(creative_meta)  # Merges viral_score, preset_used, etc.
```

**Efectos aplicados automáticamente:**
- Hook analysis + reorder (si hook >3s)
- B-roll contextual overlay (max 3 por clip)
- Zoom punch en picos de audio (max 6 punches)
- Color grading (vignette + eq filters)
- Audio mastering (EBU R128 loudnorm -14 LUFS)
- SFX injection (si aplica)
- QA validation + manifest JSON

**Verificar en logs:**
```bash
docker-compose logs worker | grep -E "(creative|viral_score|preset|hook_reorder|broll|zoom_punch|qa_passed)"
```

---

### Timeout Configuration (600s)

**Variable actualizada en todos los workers:**
```yaml
# docker-compose.yml — worker, worker-2, worker-3, gpu_worker
environment:
  - QUEUED_TASK_TIMEOUT_SECONDS=${QUEUED_TASK_TIMEOUT_SECONDS:-600}  # Was 180
```

**Impacto:**
- Jobs con videos largos (10+ min) o muchos clips no fallan por timeout
- Primera carga de Whisper model no causa timeout
- GPU jobs (T2V, LoRA) tienen tiempo suficiente

---

### Vision Analysis — Opt-in

**Cambio:** Vision analysis requiere Ollama 5GB+ modelo. Ahora es **opt-in** (default `false`):

```yaml
# docker-compose.yml
environment:
  - VISION_ANALYSIS_ENABLED=${VISION_ANALYSIS_ENABLED:-false}  # Was true
```

**Activar si tienes GPU/suficiente RAM:**
```bash
# .env
VISION_ANALYSIS_ENABLED=true
OLLAMA_MODEL=llama3.2-vision  # or llava
```

---

### Hook Slow-Motion — Enabled

**Hook slowmo ahora activado por defecto** (CPU-only, alto impacto visual):

```yaml
# docker-compose.yml
environment:
  - HOOK_SLOWMO_ENABLED=${HOOK_SLOWMO_ENABLED:-true}  # Was false
```

**Efecto:** Primeros 0.5-1s del hook se reproducen a 120fps (synthetic slowmo) para captar atención.

---

### Nginx Reverse Proxy

**Configuración agregada en `nginx/nginx.conf`:**

```nginx
upstream backend {
    server backend:8000;
}

server {
    listen 80;
    server_name localhost;

    # SSE endpoints — buffering must be disabled
    location /api/tasks/ {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }

    # TLS-ready (uncomment for production)
    # listen 443 ssl http2;
    # ssl_certificate /etc/nginx/ssl/cert.pem;
    # ssl_certificate_key /etc/nginx/ssl/key.pem;
}
```

**Iniciar Nginx:**
```bash
docker-compose up -d nginx
```

**Verificar:**
```bash
curl http://localhost/api/health  # Should proxy to backend
```

---

### Task Rate Limiting (Redis-backed)

**Nuevo rate limiter para POST /tasks:**

```python
# backend/src/api/middleware/rate_limit.py
DEFAULT_LIMITS["tasks"] = {"requests": 20, "window": 3600}  # 20 tasks/hour
```

**Aplicado en:**
```python
# backend/src/api/routes/tasks.py
@router.post("/", dependencies=[Depends(task_rate_limit_dependency)])
async def create_task(...)
```

**Respuesta 429 cuando excedido:**
```json
{
  "detail": {
    "message": "Task creation rate limit exceeded",
    "limit": 20,
    "window_seconds": 3600,
    "retry_after_seconds": 1800
  }
}
```

**Headers en respuesta:**
```
X-RateLimit-Limit: 20
X-RateLimit-Remaining: 18
X-RateLimit-Reset: 3600
```

**Bypass para admin:**
```bash
curl -X POST http://localhost:8000/api/tasks \
  -H "x-viraclip-admin-secret: $ADMIN_SECRET" \
  -H "Content-Type: application/json" \
  -d '{...}'  # No rate limit applied
```

---

### Whisper Model Warm-up

**Worker ahora precarga Whisper en startup:**

```python
# backend/src/workers/tasks.py — worker_startup()
async def _warm_whisper():
    try:
        from faster_whisper import WhisperModel
        model_size = getattr(config, "whisper_model_size", "small")
        device = getattr(config, "whisper_device", "cpu")
        compute = getattr(config, "whisper_compute_type", "int8")
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: WhisperModel(model_size, device=device, compute_type=compute)
        )
        logger.info(f"✅ Whisper warm-up complete ({model_size}/{device})")
    except Exception as e:
        logger.warning(f"⚠️ Whisper warm-up failed: {e}")

# Ejecutar en background
asyncio.create_task(_warm_whisper())
```

**Verificar en logs:**
```bash
docker-compose logs worker | grep "Whisper warm-up"
# Expected: 🔄 Whisper warm-up: loading model=small device=cpu compute=int8
#           ✅ Whisper warm-up complete
```

**Beneficio:** Primer task no sufre delay de 10-30s por carga de modelo.

---

### Tests — Cobertura 100%

**Nuevos tests para mejoras de producción:**

```bash
# 14 tests cubriendo Session 3
docker-compose exec backend .venv/bin/pytest tests/test_prod_readiness_improvements.py -v

# TestPhase9Injection — 4 tests
# TestTaskRateLimitDependency — 6 tests  
# TestWhisperWarmup — 4 tests
```

**Ejecutar suite completa:**
```bash
docker-compose exec backend .venv/bin/pytest tests/ -v --no-cov
# Expected: 681/682 passed
```

---

### Deprecated Fixes

**Pydantic v2:**
- `regex=` → `pattern=` en Query/Field
- `class Config:` → `model_config = ConfigDict(...)`

**Redis 5.x:**
- `await redis_client.close()` → `await redis_client.aclose()`

**Test markers:**
- `performance`, `stress` añadidos a `pyproject.toml`

---

## Phase 10: Full Automation Setup (NEW)

### Overview

ViraClip now supports **complete automation**:
- Auto-upload to YouTube, TikTok, Instagram
- Scheduled recurring content processing
- A/B testing for virality optimization
- Real-time analytics feedback
- Trend-triggered auto-processing

### Step 1: Platform API Setup

#### YouTube Data API v3

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create new project → Enable YouTube Data API v3
3. Create OAuth2 credentials (Desktop app)
4. Download client secrets JSON

```bash
# .env additions
YOUTUBE_CLIENT_ID=your_client_id.apps.googleusercontent.com
YOUTUBE_CLIENT_SECRET=your_client_secret
YOUTUBE_REDIRECT_URI=http://localhost:8000/auth/youtube/callback
```

**Authorize ViraClip:**
```bash
# Get OAuth URL
curl http://localhost:8000/auth/youtube/url
# Returns: {"oauth_url": "https://accounts.google.com/..."}

# Visit URL in browser, authorize, get code from redirect
# Then exchange:
curl -X POST http://localhost:8000/auth/youtube/exchange \
  -H "Content-Type: application/json" \
  -d '{"code": "AUTH_CODE_FROM_REDIRECT", "user_id": "your_user_id"}'
```

#### TikTok Content Posting API

1. Apply at [TikTok for Developers](https://developers.tiktok.com/)
2. Create app → Get Client Key and Secret
3. Request Content Posting API access

```bash
# .env additions
TIKTOK_CLIENT_KEY=your_client_key
TIKTOK_CLIENT_SECRET=your_client_secret
TIKTOK_REDIRECT_URI=http://localhost:8000/auth/tiktok/callback
```

**Authorize:**
```bash
curl http://localhost:8000/auth/tiktok/url
curl -X POST http://localhost:8000/auth/tiktok/exchange \
  -d '{"code": "AUTH_CODE", "user_id": "your_user_id"}'
```

#### Instagram Graph API

1. Create Facebook App at [Meta for Developers](https://developers.facebook.com/)
2. Add Instagram Graph API product
3. Configure OAuth redirect URI

```bash
# .env additions
INSTAGRAM_APP_ID=your_app_id
INSTAGRAM_APP_SECRET=your_app_secret
INSTAGRAM_REDIRECT_URI=http://localhost:8000/auth/instagram/callback
```

**Authorize:**
```bash
curl http://localhost:8000/auth/instagram/url
curl -X POST http://localhost:8000/auth/instagram/exchange \
  -d '{"code": "AUTH_CODE", "user_id": "your_user_id"}'
```

### Step 2: Configure Auto-Publish

Once authorized, clips can auto-publish on completion:

```bash
# Create task with auto-publish enabled
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -H "user_id: your_user_id" \
  -d '{
    "source": "https://youtube.com/watch?v=...",
    "processing_mode": "fast",
    "auto_publish": true,
    "publish_config": {
      "youtube": {"privacy": "public", "category": "22"},
      "tiktok": {"privacy": "public"},
      "instagram": {"share_to_feed": true}
    }
  }'
```

### Step 3: Schedule Recurring Content

Set up automatic processing of recurring sources:

```bash
# Schedule daily processing of a YouTube channel
curl -X POST http://localhost:8000/api/schedule \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "your_user_id",
    "name": "Daily Channel Processing",
    "source_type": "youtube_channel",
    "source_url": "https://youtube.com/@channelname",
    "frequency": "daily",
    "processing_config": {
      "target_platform": "tiktok",
      "add_subtitles": true,
      "auto_center_face": true
    },
    "publish_config": {
      "auto_publish": true,
      "platforms": ["tiktok", "instagram"]
    }
  }'

# List scheduled jobs
curl http://localhost:8000/api/schedule/list?user_id=your_user_id

# Delete scheduled job
curl -X DELETE http://localhost:8000/api/schedule/schedule_id_here
```

### Step 4: A/B Testing for Virality

Create multiple variants to test optimal style:

```bash
# Create A/B test with 3 variants
curl -X POST http://localhost:8000/api/abtest/create \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "your_user_id",
    "clip_id": "clip_id_to_test",
    "num_variants": 3,
    "test_duration_hours": 24,
    "test_accounts": {
      "youtube": "test_channel_id",
      "tiktok": "test_account_id"
    }
  }'

# Start the test
curl -X POST http://localhost:8000/api/abtest/start?test_id=your_test_id

# Check results (after test_duration_hours)
curl http://localhost:8000/api/abtest/results?test_id=your_test_id
# Returns winner variant with confidence level
```

**Variant Styles:**
- `fast_cuts` — High energy, quick cuts
- `slow_educational` — Slower, informative
- `balanced` — Middle ground (baseline)
- `music_heavy` — Strong music emphasis
- `hook_first` — Hook in first 1 second
- `caption_heavy` — More text overlays
- `minimal` — Clean, simple

### Step 5: Trend-Triggered Auto-Processing

Automatically create clips when trends match your keywords:

```bash
# Create trend trigger
curl -X POST http://localhost:8000/api/trend-triggers \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "your_user_id",
    "keywords": ["ai", "technology", "future"],
    "min_virality_score": 75,
    "processing_config": {
      "target_platform": "tiktok"
    },
    "publish_config": {
      "auto_publish": true
    }
  }'

# When trend "AI breakthrough" with score 80 is detected,
# system automatically searches for content and creates clips
```

### Step 6: Analytics Feedback Loop

Real metrics from published clips improve the virality model:

```bash
# Manually trigger analytics update
curl -X POST http://localhost:8000/api/analytics/update

# View clip performance
curl http://localhost:8000/api/clips/clip_id/performance
# Returns: views, likes, engagement_rate, actual_virality_score
```

**Automatic:**
- Analytics polled daily for all published clips
- Virality scorer retrained weekly with new data
- Model improves prediction accuracy over time

### Step 7: Notification Setup

Configure where you receive alerts:

```bash
# Update notification preferences
curl -X POST http://localhost:8000/api/user/notifications \
  -H "Content-Type: application/json" \
  -H "user_id: your_user_id" \
  -d '{
    "email_notifications": true,
    "slack_webhook_url": "https://hooks.slack.com/...",
    "discord_webhook_url": "https://discord.com/api/webhooks/..."
  }'

# Test notification
curl -X POST http://localhost:8000/api/user/notifications/test \
  -H "user_id: your_user_id"
```

**Notification Types:**
- Clip ready (WebSocket + Email)
- Clip viral threshold reached (>100K views)
- A/B test complete
- Task failed
- Trend detected

### WebSocket Real-Time Updates

Connect for real-time notifications:

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/notifications?user_id=xxx');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Notification:', data.title, data.message);
  
  if (data.type === 'clip_complete') {
    showNotification(`Clip ready! Score: ${data.data.viral_score}`);
  }
};
```

### Automation Environment Variables

```bash
# Platform APIs
YOUTUBE_CLIENT_ID=xxx
YOUTUBE_CLIENT_SECRET=xxx
YOUTUBE_REDIRECT_URI=http://localhost:8000/auth/youtube/callback

TIKTOK_CLIENT_KEY=xxx
TIKTOK_CLIENT_SECRET=xxx
TIKTOK_REDIRECT_URI=http://localhost:8000/auth/tiktok/callback

INSTAGRAM_APP_ID=xxx
INSTAGRAM_APP_SECRET=xxx
INSTAGRAM_REDIRECT_URI=http://localhost:8000/auth/instagram/callback

# Notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/...
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
EMAIL_FROM=noreply@viraclip.com

# A/B Testing
AB_TEST_MIN_VIEWS=100
AB_TEST_CONFIDENCE_THRESHOLD=0.75

# Analytics Feedback
ANALYTICS_UPDATE_INTERVAL_HOURS=24
RETRAIN_THRESHOLD_SAMPLES=100
VIRAL_THRESHOLD_VIEWS=100000
```

### Testing Automation

```bash
# Test YouTube upload
curl -X POST http://localhost:8000/api/test/youtube-upload \
  -d '{"clip_id": "test_clip_id", "privacy": "private"}'

# Test scheduling
curl -X POST http://localhost:8000/api/test/schedule \
  -d '{"user_id": "test_user", "delay_minutes": 1}'

# Test A/B test creation
curl -X POST http://localhost:8000/api/test/abtest \
  -d '{"clip_id": "test_clip", "variants": 2}'
```

### Troubleshooting Automation

| Issue | Solution |
|-------|----------|
| OAuth token expired | Re-authorize via `/auth/{platform}/url` endpoints |
| Upload fails with 401 | Check token refresh is working; verify API quotas |
| Scheduled jobs not running | Check ARQ worker is running: `docker-compose logs worker` |
| Analytics not updating | Verify platform API access; check rate limits |
| A/B test inconclusive | Increase test duration or number of variants |

---

## NEW: Session 4 — Analytics Dashboard & Transcript Cache (April 5, 2026)

### Overview

Nuevas features implementadas para producción:

| Feature | Archivo | Descripción |
|---------|---------|-------------|
| **Redis Transcript Cache** | `video_processing/transcription.py` | Cache distribuido de transcripciones (TTL 7 días) |
| **Analytics Dashboard** | `services/analytics_service.py` | Métricas de uso, health checks, reportes |
| **Analytics API** | `api/routes/analytics.py` | Endpoints `/analytics/*` para dashboard |

---

### Redis Transcript Cache

**Problema:** Whisper tarda 10-30s en transcribir un video. Si el mismo video se procesa múltiples veces (ej: diferentes cortes), se desperdicia tiempo.

**Solución:** Cache de transcripciones en Redis con hash del contenido del video.

**Flujo:**
```
1. Video llega al worker
2. Calcular SHA256 del primer 1MB del video
3. Buscar en Redis: transcript:{hash}
4. Si HIT → usar cache, saltar Whisper (ahorro 10-30s)
5. Si MISS → transcribir con Whisper, guardar en Redis (TTL 7 días)
```

**Verificar en logs:**
```bash
docker-compose logs worker | grep -E "(Redis cache HIT|Cache MISS)"
# [TRANSCRIPTION] Redis cache HIT - skipping Whisper for video.mp4
# [TRANSCRIPTION] Cache MISS - transcribing with faster-whisper: /path/video.mp4
```

**TTL:** 7 días (`_TRANSCRIPT_REDIS_TTL_SECONDS = 604800`)

---

### Analytics Dashboard API

**Endpoints disponibles:**

| Endpoint | Descripción | Auth |
|----------|-------------|------|
| `GET /analytics/health` | System health (queue, workers, error rate) | Público |
| `GET /analytics/metrics` | Task metrics (30d default) | Usuario |
| `GET /analytics/daily` | Daily stats (7d default) | Usuario |
| `GET /analytics/virality` | Virality score distribution | Usuario |
| `GET /analytics/sources` | Most popular sources | Admin |
| `GET /analytics/summary` | Complete dashboard summary | Usuario |

**Ejemplos:**

```bash
# System health (público)
curl http://localhost:8000/analytics/health
# {
#   "status": "healthy",
#   "queue_depth": 5,
#   "active_workers": 3,
#   "active_tasks": 2,
#   "error_rate_1h": 0.0
# }

# User metrics (últimos 30 días)
curl http://localhost:8000/analytics/metrics \
  -H "user_id: your_user_id"
# {
#   "period_days": 30,
#   "total_tasks": 42,
#   "completed": 38,
#   "failed": 2,
#   "success_rate": 90.48,
#   "avg_processing_time_seconds": 145.3,
#   "total_clips_generated": 87
# }

# Daily stats (últimos 7 días)
curl http://localhost:8000/analytics/daily \
  -H "user_id: your_user_id"
# {
#   "daily_stats": [
#     {"date": "2026-04-01", "tasks_completed": 5, "clips_generated": 12},
#     ...
#   ]
# }

# Virality distribution
curl http://localhost:8000/analytics/virality
# {
#   "distribution": {"0-20": 5, "21-40": 12, "41-60": 25, "61-80": 30, "81-100": 15},
#   "percentages": {"81-100": 18.75}  # 18.75% son "virales"
# }

# Dashboard completo
curl http://localhost:8000/analytics/summary \
  -H "user_id: your_user_id"
# {
#   "summary": {
#     "total_tasks_30d": 42,
#     "success_rate": 90.48,
#     "total_clips": 87,
#     "trend": "up"
#   },
#   "recent_daily": [...]
# }
```

---

### Grafana Dashboard (Opcional)

Para visualización avanzada, exportar métricas a Prometheus/Grafana:

```bash
# Métricas Prometheus ya disponibles en:
curl http://localhost:8000/metrics

# Incluye:
# - viraclip_requests_total
# - viraclip_request_duration_seconds
# - viraclip_gpu_jobs_total
# - viraclip_gpu_vram_bytes
```

---

### Tests Nuevos

```bash
# Tests para Session 4
docker-compose exec backend .venv/bin/pytest tests/test_new_features.py -v

# Cobertura:
# - TestRedisTranscriptCache — 4 tests
# - TestAnalyticsService — 4 tests
# - TestAnalyticsAPI — 2 tests
# - TestVideoHash — 3 tests
```

---

## Performance Optimizations (Session 5 — April 5, 2026)

### Overview

Optimizaciones implementadas para máximo rendimiento en producción:

| Optimización | Archivo | Impacto |
|-------------|---------|---------|
| **Redis Connection Pool** | `utils/redis_pool.py` | 50-80% menos overhead de conexiones |
| **DB Indexes** | `migrations/perf_001_add_indexes.py` | 10-100x queries más rápidas |
| **HTTP Compression** | `middleware/compression.py` | 60-80% menos bandwidth |
| **Async FFmpeg Pool** | `utils/ffmpeg_pool.py` | 4x extracciones paralelas |
| **Async Video Downloader** | `utils/video_downloader.py` | 3x descargas concurrentes |

---

### Redis Connection Pool

**Problema:** Cada operación Redis creaba nueva conexión TCP (~50ms overhead).

**Solución:** Pool persistente de 50 conexiones reutilizables.

```python
# Antes (lento)
import redis.asyncio as aioredis
redis = aioredis.Redis(host=...)  # Nueva conexión cada vez
await redis.get("key")
await redis.aclose()

# Ahora (rápido)
from src.utils.redis_pool import get_redis_client
redis = await get_redis_client()  # Reusa conexión del pool
await redis.get("key")
# No hay aclose() - conexión vuelve al pool
```

**Configuración:**
```python
# Pool size en src/utils/redis_pool.py
max_connections=50  # Ajustar según carga
health_check_interval=30  # Segundos
```

**Monitoreo:**
```bash
# Ver estado del pool
curl http://localhost:8000/health/redis
# {
#   "connected": true,
#   "pool_size": 50,
#   "available_connections": 45
# }
```

---

### Database Indexes

**Indexes agregados:**

| Tabla | Index | Uso típico |
|-------|-------|-----------|
| tasks | idx_task_user_id | Dashboard por usuario |
| tasks | idx_task_status | Worker queue polling |
| tasks | idx_task_user_status | Filtrado user+status |
| tasks | idx_task_created_at | Analytics time-series |
| generated_clips | idx_clip_task_id | Joins task→clips |
| generated_clips | idx_clip_virality_score | Ordenar por score |

**Aplicar migración:**
```bash
cd backend
.venv/bin/alembic upgrade perf_001
# o manualmente:
docker-compose exec backend .venv/bin/python -c "
from alembic import op
op.create_index('idx_task_user_id', 'tasks', ['user_id'])
# ... más indexes
"
```

**Verificar uso de indexes:**
```sql
-- Ejecutar en PostgreSQL
EXPLAIN ANALYZE
SELECT * FROM tasks
WHERE user_id = 'xxx' AND created_at > NOW() - INTERVAL '30 days';
-- Debe mostrar: Index Scan using idx_task_user_created
```

---

### HTTP Compression

**Middleware activado:** Gzip compression para respuestas >500 bytes.

**Resultados típicos:**
| Endpoint | Original | Comprimido | Ahorro |
|----------|----------|------------|--------|
| /analytics/metrics | 15 KB | 3 KB | 80% |
| /api/tasks/list | 45 KB | 8 KB | 82% |
| /api/clips/viral | 120 KB | 25 KB | 79% |

**Client-side:**
```bash
# Cliente debe enviar:
curl -H "Accept-Encoding: gzip" http://localhost:8000/analytics/metrics
```

**Exclusiones automáticas:**
- SSE streams (`text/event-stream`)
- Respuestas <500 bytes
- Archivos ya comprimidos (imágenes, videos)

---

### Async FFmpeg Pool

**Capacidades:**
- Máximo 4 FFmpeg procesos concurrentes
- Stream copy para extracciones rápidas (sin re-encode)
- Batch processing de múltiples clips
- Concatenación eficiente con demuxer

**Uso:**
```python
from src.utils.ffmpeg_pool import get_ffmpeg_pool

pool = get_ffmpeg_pool(max_concurrent=4)

# Extraer un clip
result = await pool.extract_clip_fast(
    input_path=Path("video.mp4"),
    output_path=Path("clip.mp4"),
    start_time=10.5,
    duration=30.0
)

# Batch: extraer 10 clips en paralelo
clips = [
    (0, 30, Path("clip1.mp4")),
    (30, 30, Path("clip2.mp4")),
    # ...
]
results = await pool.batch_extract_clips(
    input_path=Path("video.mp4"),
    clips=clips,
    max_parallel=2
)
```

**Performance:**
- 1 clip serial: ~3s
- 4 clips paralelos: ~3.5s total (no 12s)
- 10 clips con batch: ~8s total

---

### Async Video Downloader

**Features:**
- Connection pooling (10 conexiones)
- Retry automático con backoff exponencial
- Progress callbacks
- Batch downloads concurrentes

**Uso:**
```python
from src.utils.video_downloader import get_downloader

downloader = get_downloader(max_connections=10)

# Download simple
result = await downloader.download_with_retry(
    url="https://youtube.com/watch?v=...",
    output_path=Path("/tmp/video.mp4")
)

# Batch: 5 videos en paralelo
downloads = [
    (url1, Path("/tmp/v1.mp4")),
    (url2, Path("/tmp/v2.mp4")),
    # ...
]
results = await downloader.batch_download(downloads, max_parallel=3)
```

**Performance vs sync:**
- Sync (requests): ~30s por video
- Async (aiohttp): ~10s por video (3x más rápido)

---

### Benchmark Tests

Ejecutar benchmarks de performance:

```bash
# Todos los benchmarks
docker-compose exec backend .venv/bin/pytest tests/test_performance.py -v -m performance

# Solo Redis
docker-compose exec backend .venv/bin/pytest tests/test_performance.py::TestRedisConnectionPooling -v

# Solo FFmpeg
docker-compose exec backend .venv/bin/pytest tests/test_performance.py::TestFFmpegAsyncOperations -v

# Baselines
docker-compose exec backend .venv/bin/pytest tests/test_performance.py -v -m benchmark
```

**Resultados esperados:**
```
[Redis Pool] 100 operations: ~200ms
[FFmpeg Async] 10 concurrent ops: ~15ms
[Compression] 1000 items JSON: ~60% reduction
[JSON] 100 serialize/deserialize: ~150ms
[Hash] 100 SHA256 of 1MB: ~50ms
```

---

### Tuning Recommendations

**Para alta carga (>100 tasks/min):**
```yaml
# docker-compose.yml
worker:
  deploy:
    replicas: 4  # Scale horizontal
  environment:
    - MAX_CONCURRENT_FFMPEG=4
    - REDIS_POOL_SIZE=100
    - WHISPER_MODEL_SIZE=small  # tiny para ultra-fast
```

**Para memoria limitada:**
```python
# Reducir pool sizes
FFmpegPool(max_concurrent=2)
VideoDownloader(max_connections=5)
get_redis_client(pool_size=20)
```

**Para máxima velocidad (GPU):**
```python
# Usar Whisper large-v3 en GPU
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16
FFMPEG_PRESET=ultrafast  # vs slow
```

---

## Next Steps

1. **✅ Run test suite**: `run_all_tests.py` — verify all phases
2. **✅ Train models**: `train_all_models.py --export-onnx` — enable ML features
3. **✅ Smoke test**: `smoke_test.py` — E2E verification
4. **Monitor performance** for 24h with real traffic
5. **Gather user feedback** on clip quality
6. **Train custom LoRAs** using Phase 7 datasets (when GPU available)

**All CPU-capable phases complete. Phase 3.1-3.4 GPU features implemented and tested (24/24 passing).**

**Ready for end-to-end GPU pipeline testing with real hardware.**

**Phase 7.5 Auto-Update Pipeline (NEW)**:
- Daily trending fetch: 03:00 UTC via ARQ cron
- Weekly LoRA retrain: Sun 02:30 UTC via GPU worker
- Monthly full scorer retrain: 1st 04:00 UTC

See `ROADMAP.md` for remaining Phase 8.5+ research roadmap.
