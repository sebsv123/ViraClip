<div align="center">

# 🎬 ViraClip

**AI-powered video clipping for content creators**

Turn long-form videos into viral short clips for TikTok, Reels, and Shorts — automatically.

[![Tests](https://github.com/sebsv123/ViraClip/actions/workflows/tests.yml/badge.svg)](https://github.com/sebsv123/ViraClip/actions/workflows/tests.yml)
[![Lint](https://github.com/sebsv123/ViraClip/actions/workflows/lint.yml/badge.svg)](https://github.com/sebsv123/ViraClip/actions/workflows/lint.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Next.js](https://img.shields.io/badge/Next.js-15-000000?logo=next.js&logoColor=white)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

[Quick start](#-quick-start) · [Features](#-features) · [Architecture](#-architecture) · [Configuration](#%EF%B8%8F-configuration) · [Contributing](CONTRIBUTING.md) · [Docs](docs/)

</div>

---

## ✨ What is ViraClip?

ViraClip ingests a long video (YouTube URL or upload), transcribes it, scores the most viral moments with AI, and renders ready-to-publish vertical short-form clips with subtitles, B-roll, captions, and platform-specific export presets.

It is **open-source**, **self-hostable**, and **GPU-accelerated** end-to-end.

```
URL  ─►  Download  ─►  Whisper transcript  ─►  AI virality scoring
          │
          └─►  Per-clip pipeline:
                 Subtitles  →  B-roll  →  Beat-sync BGM  →  Polish  →  Export
```

## 🚀 Quick start

```bash
git clone https://github.com/sebsv123/ViraClip.git
cd ViraClip
cp .env.example .env       # add at least ASSEMBLY_AI_API_KEY + one LLM provider key
docker compose up -d --build
```

Then open:

| Service          | URL                                         |
|------------------|---------------------------------------------|
| Frontend         | <http://localhost:3000>                     |
| Backend API docs | <http://localhost:8000/docs>                |
| Postgres         | `localhost:5432` (`viraclip` / env-driven)  |
| Redis            | `localhost:6379`                            |

The first build pulls heavy ML images (CUDA, Whisper, ComfyUI). After that, `docker compose up -d` is fast.

> **Need GPU acceleration?** Make sure NVIDIA Container Toolkit is installed. CPU-only mode also works but transcription/clip rendering will be ~5–10× slower.

## 🎯 Features

### Pipeline
- 🎬 **AI clip selection** — LLM ranks segments by virality and hook strength
- 📝 **Word-level transcription** — `faster-whisper` with GPU acceleration
- 🪄 **Multi-style subtitles** — ASS-rendered TikTok/CapCut/Hormozi presets
- 🎞️ **B-roll generation** — Pexels, ComfyUI (LTXV), Stability AI, Replicate
- 🎵 **Beat-synced BGM** — automatic BPM matching + sidechain ducking
- 🔊 **Audio polish** — denoising, voice enhancement, EBU R128 loudness
- 🎨 **Visual polish** — LUT grading, vignette, cut-zoom, hook slo-mo
- 📱 **Platform exports** — TikTok / Reels / Shorts presets out of the box

### Platform
- 🚦 **Async worker queue** — `arq` + Redis for concurrent rendering
- 💾 **Smart caching** — Redis + disk-tier cache for transcripts and AI analysis
- 📊 **Observability** — Prometheus-friendly metrics, structured logging
- 🔐 **Auth** — `better-auth` with email/password + Google OAuth
- 💳 **Billing (optional)** — Stripe subscriptions with Resend lifecycle emails
- 🔄 **Self-host or hosted** — same codebase, toggled via `SELF_HOST` env var

## 🧱 Architecture

```
┌──────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  Next.js 15  │───►│   FastAPI API    │───►│   arq worker    │
│  (frontend)  │    │  (REST + SSE)    │    │  (clip render)  │
└──────────────┘    └──────────────────┘    └─────────────────┘
       │                     │                       │
       │              ┌──────┴──────┐                │
       └─────────────►│  Postgres   │◄───────────────┘
                      │   Redis     │
                      └─────────────┘
                             ▲
                             │
                      ┌──────┴──────┐
                      │  ComfyUI    │  (optional, GPU)
                      │  Ollama     │  (optional, local LLM)
                      └─────────────┘
```

Backend code is organised by **business domain** instead of one big `services/` folder:

```
backend/src/
├── api/                  # HTTP routes
├── core/                 # cache, metrics, error handling, observability
├── domains/
│   ├── ai/               # LLMs, vision, editorial brain
│   ├── audio/            # music, SFX, voice, beat sync
│   ├── autopilot/        # task orchestration
│   ├── billing/
│   ├── broll/            # generative + stock B-roll
│   ├── captions/         # subtitles + translation
│   ├── detection/        # CV / face / scene
│   ├── feedback/         # learning loops
│   ├── notifications/
│   ├── publishing/       # social distribution
│   ├── thumbnails/
│   ├── upscaling/
│   ├── validation/       # QA & health
│   ├── video/            # clip rendering pipeline
│   └── virality/         # scoring, hooks, ML
├── repositories/         # DB access
├── workers/              # arq worker entrypoints
└── agents/               # agent pipelines
```

See [`docs/architecture.md`](docs/architecture.md) for the full diagram.

## ⚙️ Configuration

ViraClip is configured via environment variables. A complete annotated template is in [`.env.example`](.env.example). The minimum required:

```env
# Transcription
ASSEMBLY_AI_API_KEY=...

# One of the following LLM providers
LLM=google-gla:gemini-2.0-flash
GOOGLE_API_KEY=...

# Or:
# LLM=openai:gpt-4o
# OPENAI_API_KEY=...

# Or fully local:
# LLM=ollama:qwen2.5:7b
# OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
```

| Section            | Doc                                                              |
|--------------------|------------------------------------------------------------------|
| All config keys    | [`docs/configuration.md`](docs/configuration.md)                 |
| Getting API keys   | [`API_KEYS_SETUP.md`](API_KEYS_SETUP.md)                         |
| Production deploy  | [`DEPLOY_GUIDE.md`](DEPLOY_GUIDE.md)                             |
| Troubleshooting    | [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)                       |

## 🧪 Testing

> **Status (current):** lint runs in CI; the test suite is being rebuilt after the recent backend domain refactor. Smoke testing via `docker compose up -d` + creating a task end-to-end is the current verification baseline. Contributions to test coverage are very welcome.

When tests are present:

```bash
make test            # backend + frontend unit tests
make test-backend    # pytest with Postgres + Redis service containers
make test-frontend   # Vitest + React Testing Library
make test-e2e        # Playwright smoke flows
make test-ci         # full CI matrix
```

Local runs expect Postgres and Redis. Easiest path: `docker compose up -d postgres redis`, then `make test`.

## 🛠️ Local development

Pre-requisites: Docker, Node 20+, Python 3.11+, [`uv`](https://github.com/astral-sh/uv).

```bash
# Frontend live reload
cd frontend && npm install && npm run dev

# Backend live reload (in another shell)
cd backend && uv sync && .venv/bin/uvicorn src.main:app --reload --port 8000

# Worker
cd backend && .venv/bin/arq src.workers.tasks.WorkerSettings
```

Coding style and PR workflow are described in [`CONTRIBUTING.md`](CONTRIBUTING.md). Pre-commit hooks (`ruff`, `prettier`, `detect-secrets`, conventional commits) are pre-configured — install with:

```bash
pip install pre-commit && pre-commit install --hook-type pre-commit --hook-type commit-msg
```

## 📚 Documentation

- 🏗️ [`docs/architecture.md`](docs/architecture.md) — system architecture
- 🔧 [`docs/configuration.md`](docs/configuration.md) — config reference
- 🚀 [`docs/setup.md`](docs/setup.md) — deployment setup
- 📖 [`docs/api-reference.md`](docs/api-reference.md) — REST API
- 🧑‍💻 [`docs/development.md`](docs/development.md) — developer guide
- 🆘 [`docs/troubleshooting.md`](docs/troubleshooting.md) — common issues
- 📋 [`AGENTS.md`](AGENTS.md) — repository conventions for AI/human contributors
- 🔒 [`SECURITY.md`](SECURITY.md) — security policy
- 📓 [`CHANGELOG.md`](CHANGELOG.md) — release notes

## 🤝 Contributing

Pull requests are welcome! Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`docs/development.md`](docs/development.md) before starting. Good first issues are tagged [`good first issue`](https://github.com/sebsv123/ViraClip/issues?q=is%3Aopen+label%3A%22good+first+issue%22).

We follow [Conventional Commits](https://www.conventionalcommits.org/) and the [Contributor Covenant](.github/CODE_OF_CONDUCT.md).

## 🛡️ Security

Found a vulnerability? Please **do not** open a public issue. See [`SECURITY.md`](SECURITY.md) for our responsible disclosure process.

## 📝 License

ViraClip is released under the [AGPL-3.0](LICENSE) license. If you offer ViraClip — modified or not — as a network service, you must release your source under the same license.

For commercial licensing without AGPL obligations, please open a [GitHub discussion](https://github.com/sebsv123/ViraClip/discussions).

## 🙏 Acknowledgments

ViraClip stands on the shoulders of giants:

- [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) — GPU-accelerated transcription
- [`pydantic-ai`](https://github.com/pydantic/pydantic-ai) — LLM orchestration
- [`ComfyUI`](https://github.com/comfyanonymous/ComfyUI) — generative B-roll
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) — robust YouTube ingestion
- [Pexels](https://www.pexels.com/) — free stock B-roll
- [AssemblyAI](https://www.assemblyai.com/) — transcription API

…and the SupoClip project, which inspired the original architecture.

---

<div align="center">

**Made for content creators who ship.**

[Website](https://www.viraclip.com) · [Issues](https://github.com/sebsv123/ViraClip/issues) · [Discussions](https://github.com/sebsv123/ViraClip/discussions)

</div>
