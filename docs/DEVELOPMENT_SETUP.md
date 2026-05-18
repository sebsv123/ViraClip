# ViraClip Development Setup Guide

Complete guide to set up ViraClip for development on any machine.

---

## Prerequisites

### Required Software

1. **Docker Desktop** (Windows/Mac) or Docker Engine (Linux)
   - Download: https://www.docker.com/products/docker-desktop/
   - Minimum: 8GB RAM, 50GB disk space

2. **Git**
   - Download: https://git-scm.com/downloads

3. **Node.js 20+** (for local frontend development)
   - Download: https://nodejs.org/

4. **Bun** (faster alternative to npm)
   - Install: `npm install -g bun`
   - Or: https://bun.sh/

---

## Quick Start (5 minutes)

### 1. Clone Repository

```bash
git clone https://github.com/sebsv123/ViraClip.git
cd ViraClip
```

### 2. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env and add your API keys (optional but recommended)
# Minimum required: none (works offline)
# Recommended: PEXELS_API_KEY, UNSPLASH_ACCESS_KEY, GROQ_API_KEY
```

### 3. Start Services

```bash
# Start all services with Docker
docker-compose up -d

# Wait 30-60 seconds for services to initialize
docker-compose logs -f backend
```

### 4. Access ViraClip

- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:8000/docs
- **Ollama:** http://localhost:11434

---

## Detailed Setup

### Step 1: Environment Configuration

#### Required Services

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

#### Minimum Configuration (Works Offline)

ViraClip works without any external API keys:

```env
# Database
DATABASE_URL=postgresql://viraclip:viraclip@postgres:5432/viraclip

# Redis
REDIS_URL=redis://redis:6379

# Local LLM (no API key needed)
LLM=ollama:phi3:mini
OLLAMA_BASE_URL=http://ollama:11434

# Whisper (local, no API key)
WHISPER_MODEL_SIZE=small
WHISPER_DEVICE=cpu
```

#### Recommended API Keys (95% Quality)

For production-level quality, add these free API keys:

```env
# Stock Media (Free forever)
PEXELS_API_KEY=your_key_here
UNSPLASH_ACCESS_KEY=your_key_here

# AI Inference (14,000 requests/day free)
GROQ_API_KEY=your_key_here

# Google AI (for Gemini LLM + Imagen 3 images)
GOOGLE_API_KEY=your_key_here
```

**Get Free API Keys:**
- Pexels: https://www.pexels.com/api/
- Unsplash: https://unsplash.com/developers
- Groq: https://console.groq.com/
- Google AI: https://makersuite.google.com/app/apikey

#### Optional API Keys (Enhanced Features)

```env
# Enhanced transcription (60 hours/month free)
ASSEMBLY_AI_API_KEY=your_key_here

# Additional LLM options
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here

# AI Image Generation (Multi-Provider System)
# Google Imagen 3 (1000 images/month free - uses GOOGLE_API_KEY above)
USE_GOOGLE_IMAGEN=true

# Pixabay (200,000+ stock + 100 requests/min free)
PIXABAY_API_KEY=your_key_here

# Replicate (Flux.1, SDXL - ~$0.003/image)
REPLICATE_API_TOKEN=your_token_here

# Stability AI (SDXL - ~$0.002/image)
STABILITY_API_KEY=your_key_here

# Provider fallback order
IMAGE_GEN_PROVIDERS=pexels,google_imagen,replicate,stability,dalle
```

**Enhanced Image Generation Keys:**
- Pixabay: https://pixabay.com/api/docs/
- Replicate: https://replicate.com/account/api-tokens
- Stability AI: https://platform.stability.ai/account/keys

### Step 2: Start Docker Services

#### First-Time Setup

```bash
# Pull all images and start services
docker-compose up -d

# Check service status
docker-compose ps

# View logs
docker-compose logs -f backend worker
```

#### Service Initialization

Services take 30-60 seconds to start:

1. **Postgres** (5s) - Database
2. **Redis** (5s) - Cache and job queue
3. **Ollama** (20s) - Pulls phi3:mini model (2GB)
4. **Backend** (10s) - FastAPI server
5. **Workers** (10s) - 3 parallel processing workers
6. **Frontend** (30s) - Next.js app
7. **Rust Agent** (5s) - Performance service

#### Verify Services

```bash
# All services should show "healthy" or "Up"
docker-compose ps

# Test backend health
curl http://localhost:8000/health/db

# Test frontend
curl http://localhost:3000
```

### Step 3: Initialize Database

Database migrations run automatically on first start. To manually migrate:

```bash
cd frontend
bun install
bunx prisma migrate deploy
bunx prisma generate
```

### Step 4: Expand Audio Library (Recommended)

ViraClip includes 17 audio files by default. **NEW:** Auto-expand to 100+ professional tracks:

```bash
# Download 50 BGM + 50 SFX from Pixabay and Mixkit
docker exec viraclip-backend .venv/bin/python /app/scripts/expand_audio_library_v2.py
```

This downloads:
- **50 BGM tracks:** Viral hype, cinematic, lo-fi, corporate, emotional
- **50 SFX files:** Transitions, impacts, UI sounds, ambient

**Requirements:**
- Optional `PIXABAY_API_KEY` (100 requests/min free)
- Mixkit downloads work without API key

**Manual Downloads:**
```bash
# Pixabay only
docker exec viraclip-backend .venv/bin/python /app/scripts/download_pixabay_audio.py

# Mixkit only  
docker exec viraclip-backend .venv/bin/python /app/scripts/download_mixkit_audio.py
```

---

## Development Workflow

### Frontend Development

```bash
cd frontend

# Install dependencies
bun install

# Start dev server (with hot reload)
bun run dev

# Open http://localhost:3000
```

### Backend Development

```bash
cd backend

# Create virtual environment
uv sync

# Run backend locally (alternative to Docker)
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### Run Workers Locally

```bash
cd backend
source .venv/bin/activate

# Start worker
arq src.workers.tasks.WorkerSettings
```

### Database Management

```bash
cd frontend

# Create new migration
bunx prisma migrate dev --name your_migration_name

# View database in browser
bunx prisma studio

# Reset database (CAUTION: deletes all data)
bunx prisma migrate reset
```

---

## Testing

### Run All Tests

```bash
# Backend tests (2048 tests)
docker exec viraclip-backend .venv/bin/python -m pytest

# Specific test file
docker exec viraclip-backend .venv/bin/python -m pytest tests/test_coordinator.py

# With coverage
docker exec viraclip-backend .venv/bin/python -m pytest --cov=src --cov-report=html
```

### Smoke Test

```bash
docker exec viraclip-backend .venv/bin/python /app/scripts/smoke_test.py
```

### Verify Production Config

```bash
docker exec viraclip-backend .venv/bin/python /app/scripts/verify_production.py
```

### Full Synchronization Check

```bash
docker exec viraclip-backend .venv/bin/python /app/scripts/verify_full_sync.py
```

---

## Common Issues

### Port Already in Use

If ports 3000, 8000, or 5432 are busy:

```bash
# Stop conflicting services
docker-compose down

# Or change ports in docker-compose.yml
```

### Services Won't Start

```bash
# Clean restart
docker-compose down
docker-compose up -d --build --force-recreate

# Check logs
docker-compose logs backend
```

### Database Connection Error

```bash
# Restart Postgres
docker-compose restart postgres

# Check connection
docker exec viraclip-backend psql $DATABASE_URL -c "SELECT 1"
```

### Ollama Model Not Loading

```bash
# Pull model manually
docker exec viraclip-ollama ollama pull phi3:mini

# Check status
docker exec viraclip-ollama ollama list
```

### Frontend Build Errors

```bash
cd frontend

# Clear cache and reinstall
rm -rf node_modules .next bun.lockb
bun install
bun run build
```

---

## Project Structure

```
ViraClip/
├── backend/              # FastAPI backend
│   ├── src/
│   │   ├── api/         # API routes (126 files)
│   │   ├── services/    # Business logic (153 services)
│   │   ├── workers/     # Background jobs
│   │   └── main.py      # App entry point
│   ├── scripts/         # Utility scripts (35 files)
│   ├── tests/           # Test suite (2048 tests)
│   ├── pyproject.toml   # Python dependencies
│   └── Dockerfile
├── frontend/            # Next.js frontend
│   ├── src/
│   │   ├── app/        # App router pages
│   │   ├── components/ # React components
│   │   └── lib/        # Utilities
│   ├── prisma/         # Database schema
│   ├── package.json    # Node dependencies
│   └── Dockerfile
├── waitlist/           # Marketing site
├── docker-compose.yml  # Service orchestration
├── .env.example        # Environment template
└── start.sh           # Quick start script
```

---

## Key Technologies

### Backend Stack
- **FastAPI** - Modern Python web framework
- **Faster-Whisper** - Local speech-to-text
- **MoviePy** - Video processing
- **FFmpeg** - Media encoding
- **MediaPipe** - Face tracking
- **Librosa** - Audio analysis
- **PySceneDetect** - Scene detection
- **Torch** - Deep learning
- **Redis** - Job queue
- **PostgreSQL** - Database

### Frontend Stack
- **Next.js 15** - React framework
- **Prisma** - Database ORM
- **Better-Auth** - Authentication
- **shadcn/ui** - UI components
- **TailwindCSS** - Styling
- **Lucide** - Icons

### Infrastructure
- **Docker** - Containerization
- **Ollama** - Local LLM (phi3:mini)
- **Rust Agent** - Performance service
- **uv** - Fast Python package manager
- **Bun** - Fast JavaScript runtime

---

## Environment Variables Reference

### Core Configuration

```env
# Database
DATABASE_URL=postgresql://user:password@host:port/database

# Redis
REDIS_URL=redis://host:port

# LLM Provider (choose one)
LLM=ollama:phi3:mini          # Local (no API key)
LLM=groq:llama-3.3-70b        # Fast (Groq API key)
LLM=openai:gpt-4o             # OpenAI (API key)

# Whisper Transcription
WHISPER_MODEL_SIZE=small      # tiny, small, medium, large-v3
WHISPER_DEVICE=cpu            # cpu or cuda
```

### Viral Features (All Enabled by Default)

```env
# Contextual Overlays
CONTEXTUAL_OVERLAYS_ENABLED=true
OVERLAY_FREQUENCY=adaptive
MAX_OVERLAYS_PER_CLIP=8

# Speed Control
SPEED_CONTROL_ENABLED=true

# Scene Detection
SCENE_DETECTION_ENABLED=true

# Audio Ducking
AUDIO_DUCKING_ENABLED=true
```

### Enhanced Features (New!)

#### Multi-Provider Image Generation

Eliminates single-source dependency with 9-provider fallback chain:

```env
# Enable multi-provider image generation
USE_GOOGLE_IMAGEN=true
IMAGE_GEN_PROVIDERS=pexels,google_imagen,replicate,stability,dalle

# API Keys (optional, falls back to free providers)
PIXABAY_API_KEY=your_key          # 100 req/min free
GOOGLE_API_KEY=your_key           # 1000 imgs/month free
REPLICATE_API_TOKEN=your_token    # ~$0.003/img
STABILITY_API_KEY=your_key        # ~$0.002/img
```

**Test Providers:**
```bash
docker exec viraclip-backend .venv/bin/python /app/scripts/test_image_providers.py
```

#### Structured Reasoning System

Transparent Chain-of-Thought reasoning for AI decisions:

```env
# Reasoning mode (monolithic=default, structured=5-step COT)
REASONING_MODE=structured

# Log each reasoning step (verbose debugging)
REASONING_STEPS_LOGGING=true

# Save reasoning traces for review
SAVE_REASONING_TRACES=true
REASONING_TRACE_DIR=/app/data/reasoning_traces
```

**Demo Reasoning:**
```bash
docker exec viraclip-backend .venv/bin/python /app/scripts/demo_reasoning.py
```

Benefits:
- ✅ Transparent AI decisions (see each step)
- ✅ Debuggable reasoning traces
- ✅ Auditable logs saved to JSON
- ✅ No additional cost (uses existing LLM)

#### Expanded Audio Library

100+ professional tracks organized by category:

```env
# Auto-download on first run
AUTO_DOWNLOAD_AUDIO=true
AUDIO_SOURCES=pixabay,mixkit
TARGET_BGM_COUNT=50
TARGET_SFX_COUNT=50
```

### API Keys (Optional)

```env
# Stock Media
PEXELS_API_KEY=your_key
UNSPLASH_ACCESS_KEY=your_key

# AI Inference
GROQ_API_KEY=your_key
OPENAI_API_KEY=your_key
ANTHROPIC_API_KEY=your_key
GOOGLE_API_KEY=your_key

# Transcription
ASSEMBLY_AI_API_KEY=your_key
```

---

## Git Workflow

### Daily Development

```bash
# Pull latest changes
git pull origin version-basica

# Create feature branch
git checkout -b feature/your-feature

# Make changes, then commit
git add .
git commit -m "feat: your feature description"

# Push to GitHub
git push origin feature/your-feature
```

### Sync with Remote

```bash
# Fetch all branches
git fetch origin

# Merge latest changes
git merge origin/version-basica

# Or rebase
git rebase origin/version-basica
```

---

## Performance Tips

### Faster Startup

```bash
# Skip frontend build in development
docker-compose up -d postgres redis ollama backend worker

# Run frontend locally
cd frontend && bun run dev
```

### Parallel Processing

ViraClip uses 3 parallel workers by default. To scale:

```bash
# In docker-compose.yml, add more workers
docker-compose up -d --scale worker=5
```

### GPU Acceleration

If you have an NVIDIA GPU:

```bash
# Start GPU worker
docker-compose --profile gpu up -d gpu_worker

# Use GPU for faster processing
```

---

## Support

### Documentation
- **API Docs:** http://localhost:8000/docs
- **Production Guide:** `PRODUCTION_READINESS.md`
- **API Keys Setup:** `API_KEYS_SETUP.md`
- **Offline Mode:** `OFFLINE_MODE.md`

### Verification Scripts
- `scripts/verify_production.py` - Check config
- `scripts/verify_full_sync.py` - Full system check
- `scripts/smoke_test.py` - End-to-end test

### Community
- **GitHub:** https://github.com/sebsv123/ViraClip
- **Issues:** https://github.com/sebsv123/ViraClip/issues

---

## Next Steps

1. ✅ Clone repository
2. ✅ Configure `.env`
3. ✅ Start Docker services
4. ✅ Access http://localhost:3000
5. 🎬 Create your first viral clip!

**Happy developing! 🚀**
