<div align="center">

# 🎬 ViraClip

### Turn any long video into viral short clips — fully automated, fully self-hostable.

Drop a YouTube URL (or upload a file). Get back TikTok-ready vertical clips with AI-scored hooks, word-level subtitles, B-roll, beat-synced music, and platform export presets. Zero manual editing.

[![Tests](https://github.com/sebsv123/ViraClip/actions/workflows/tests.yml/badge.svg)](https://github.com/sebsv123/ViraClip/actions/workflows/tests.yml)
[![Lint](https://github.com/sebsv123/ViraClip/actions/workflows/lint.yml/badge.svg)](https://github.com/sebsv123/ViraClip/actions/workflows/lint.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Next.js](https://img.shields.io/badge/Next.js-15-000000?logo=next.js&logoColor=white)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

[Quick Start](#-quick-start) · [Features](#-features) · [Architecture](#-architecture) · [Configuration](#%EF%B8%8F-configuration) · [Contributing](CONTRIBUTING.md) · [Docs](docs/)

</div>

---

## 🤔 Why ViraClip?

Most AI clipping tools are black boxes — you upload, they charge, you get clips. ViraClip is different:

- **Open source & self-hostable** — your videos never leave your infrastructure
- **Full pipeline control** — every stage (transcription → scoring → rendering → export) is inspectable and overridable
- **GPU-accelerated end-to-end** — Whisper, ComfyUI B-roll generation, and FFmpeg all run on your hardware
- **Multi-provider LLM** — swap between Gemini, GPT-4o, Claude, or a local Ollama model with one env variable

---

## 🚀 Quick Start

```bash
git clone https://github.com/sebsv123/ViraClip.git
cd ViraClip
cp .env.example .env   # add ASSEMBLY_AI_API_KEY + one LLM key
docker compose up -d --build
```

| Service          | URL                          |
|------------------|------------------------------|
| Frontend         | http://localhost:3000        |
| API docs         | http://localhost:8000/docs   |
| Postgres         | localhost:5432               |
| Redis            | localhost:6379               |

> **GPU acceleration:** requires NVIDIA Container Toolkit. CPU-only mode works but is ~5–10× slower for transcription and rendering.

The first `build` pulls heavy ML images (CUDA, Whisper, ComfyUI). Subsequent `up -d` starts in seconds.

---

## ✨ Features

### AI Pipeline
| Stage | What happens |
|---|---|
| **Ingest** | `yt-dlp` downloads from YouTube / upload any file |
| **Transcribe** | `faster-whisper` (GPU) produces word-level timestamps |
| **Score** | LLM ranks every segment by virality, hook strength, and emotional arc |
| **Edit** | Cuts, pacing, impact zoom, hook slo-mo applied automatically |
| **B-roll** | Pulled from Pexels, generated via ComfyUI (LTXV), Stability AI, or Replicate |
| **Subtitles** | ASS-rendered TikTok / CapCut / Hormozi word-pop presets |
| **Audio** | Denoising → voice enhancement → beat-synced BGM → EBU R128 loudness |
| **Export** | TikTok 9:16, Reels 4:5, Shorts — ready to publish |

### Platform
- ⚡ **Async rendering** — `arq` + Redis worker queue, multiple clips in parallel
- 💾 **Smart caching** — Redis + disk cache for transcripts and AI analysis
- 📊 **Observability** — Prometheus metrics, structured JSON logging
- 🔐 **Auth** — `better-auth` with email/password + Google OAuth
- 💳 **Billing (optional)** — Stripe subscriptions + Resend lifecycle emails
- 🏠 **Self-host or hosted** — same codebase, toggled via `SELF_HOST` env var

---

## 🧱 Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  Next.js 15 │────►│  FastAPI + SSE   │────►│   arq Worker     │
│  (frontend) │     │  (REST API)      │     │  (clip renderer) │
└─────────────┘     └──────────────────┘     └──────────────────┘
       │                     │                        │
       │              ┌──────┴───────┐                │
       └─────────────►│  PostgreSQL  │◄───────────────┘
                      │    Redis     │
                      └──────────────┘
                             ▲
                    ┌────────┴────────┐
                    │   ComfyUI       │  (GPU B-roll generation)
                    │   Ollama        │  (local LLM, optional)
                    │   Rust Agent    │  (high-perf task runner)
                    └─────────────────┘
```

Backend is organized by **business domain** — not a flat `services/` dump:

```
backend/src/domains/
├── ai/          # LLMs, vision, editorial scoring
├── audio/       # BGM, SFX, voice, beat sync
├── broll/       # generative + stock B-roll
├── captions/    # subtitles + translation
├── detection/   # CV, face, scene detection
├── video/       # core clip rendering pipeline
├── virality/    # scoring, hooks, ML models
└── ...          # billing, publishing, upscaling, thumbnails
```

Full diagram: [`docs/architecture.md`](docs/architecture.md)

---

## ⚙️ Configuration

Everything is driven by environment variables. Annotated template: [`.env.example`](.env.example).

**Minimum to get started:**

```env
# Transcription
ASSEMBLY_AI_API_KEY=your_key

# Pick one LLM provider
LLM=google-gla:gemini-2.0-flash
GOOGLE_API_KEY=your_key

# Or OpenAI
# LLM=openai:gpt-4o
# OPENAI_API_KEY=your_key

# Or fully local (no API costs)
# LLM=ollama:qwen2.5:7b
# OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
```

| Section             | Doc                                                  |
|---------------------|------------------------------------------------------|
| All config keys     | [`docs/configuration.md`](docs/configuration.md)    |
| Getting API keys    | [`API_KEYS_SETUP.md`](API_KEYS_SETUP.md)             |
| Production deploy   | [`DEPLOY_GUIDE.md`](DEPLOY_GUIDE.md)                 |
| Troubleshooting     | [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)           |

---

## 🧪 Testing

> Tests are being rebuilt after the recent backend domain refactor. Current baseline: smoke-test via `docker compose up -d` + submit a task end-to-end. Contributions to test coverage are very welcome — see [`good first issue`](https://github.com/sebsv123/ViraClip/issues?q=is%3Aopen+label%3A%22good+first+issue%22).

```bash
make test            # backend + frontend unit tests
make test-backend    # pytest (requires Postgres + Redis)
make test-frontend   # Vitest + React Testing Library
make test-e2e        # Playwright smoke flows
```

---

## 🛠️ Local Development

**Prerequisites:** Docker, Node 20+, Python 3.11+, [`uv`](https://github.com/astral-sh/uv)

```bash
# Frontend (live reload)
cd frontend && npm install && npm run dev

# Backend (live reload)
cd backend && uv sync && .venv/bin/uvicorn src.main:app --reload --port 8000

# Worker
cd backend && .venv/bin/arq src.workers.tasks.WorkerSettings
```

Pre-commit hooks (`ruff`, `prettier`, `detect-secrets`, conventional commits) are pre-configured:

```bash
pip install pre-commit && pre-commit install --hook-type pre-commit --hook-type commit-msg
```

Full guide: [`CONTRIBUTING.md`](CONTRIBUTING.md) · [`docs/development.md`](docs/development.md)

---

## 📚 Documentation

| Doc | Contents |
|-----|----------|
| [`docs/architecture.md`](docs/architecture.md) | System architecture deep-dive |
| [`docs/configuration.md`](docs/configuration.md) | All config keys reference |
| [`DEPLOY_GUIDE.md`](DEPLOY_GUIDE.md) | Production deployment (57KB guide) |
| [`API_KEYS_SETUP.md`](API_KEYS_SETUP.md) | Getting every API key |
| [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) | Common issues + fixes |
| [`AGENTS.md`](AGENTS.md) | Repo conventions for AI/human contributors |
| [`CHANGELOG.md`](CHANGELOG.md) | Release notes |

---

## 🤝 Contributing

PRs are welcome. Good first issues are labeled [`good first issue`](https://github.com/sebsv123/ViraClip/issues?q=is%3Aopen+label%3A%22good+first+issue%22).

We follow [Conventional Commits](https://www.conventionalcommits.org/) and the [Contributor Covenant](.github/CODE_OF_CONDUCT.md).

---

## 🛡️ Security

Found a vulnerability? **Do not open a public issue.** See [`SECURITY.md`](SECURITY.md) for our responsible disclosure process.

---

## 📝 License

Released under [AGPL-3.0](LICENSE). If you offer ViraClip as a network service (modified or not), you must release your source under the same license.

For commercial licensing without AGPL obligations: open a [GitHub Discussion](https://github.com/sebsv123/ViraClip/discussions).

---

## 🙏 Built on top of

- [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) — GPU-accelerated transcription
- [`ComfyUI`](https://github.com/comfyanonymous/ComfyUI) — generative B-roll (LTXV)
- [`pydantic-ai`](https://github.com/pydantic/pydantic-ai) — LLM orchestration
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) — robust video ingestion
- [AssemblyAI](https://www.assemblyai.com/) — transcription API
- [Pexels](https://www.pexels.com/) — free stock B-roll

---

<div align="center">

**Built for creators who ship.**

[Website](https://www.viraclip.com) · [Issues](https://github.com/sebsv123/ViraClip/issues) · [Discussions](https://github.com/sebsv123/ViraClip/discussions)

⭐ If ViraClip saves you editing time, a star helps others find it.

</div>
