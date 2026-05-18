# 🎬 ViraClip

**Transform long videos into viral short clips — automatically.**

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)

ViraClip helps creators turn long-form videos—podcasts, interviews, webinars, and live streams—into short, high-impact vertical clips. It uses AI-powered transcription with Whisper, reasoning and editorial ranking with Groq LLM, and workflow orchestration with LangGraph to identify moments with viral potential. Each selected segment is enhanced with captions, B-roll, LUT color treatment, beat sync, and hook optimization before rendering. The output is a ready-to-publish set of clips for TikTok, Instagram Reels, and YouTube Shorts.

## ✨ Key Features

- AI viral segment detection and highlight scoring
- Word-level caption generation with ASS subtitle styling
- Beat-synced pacing and music alignment
- Automated B-roll enrichment with Pexels integration
- Face-aware auto-crop for vertical compositions
- LUT-based color grading presets
- Audio ducking and loudness normalization
- A/B clip variant generation for experimentation
- Health scoring for clip quality and publish readiness
- Analytics feedback loop for continuous optimization

## 🏗️ Architecture

ViraClip follows an orchestration-first pipeline in `coordinator.py`: preflight → transcript → viral gate → segment scoring → creative pipeline → parallel render → export. This flow is implemented as a LangGraph multi-agent pipeline, allowing each stage to specialize while keeping end-to-end execution deterministic, observable, and scalable.

## 🚀 Quick Start

```bash
git clone https://github.com/sebsv123/ViraClip.git
cd ViraClip
cp .env.example .env   # fill in your API keys
docker compose up --build
# Frontend: http://localhost:3000
# Backend API: http://localhost:8000
```

## ⚙️ Configuration

Use [`.env.example`](.env.example) as the canonical environment template, and follow [`API_KEYS_SETUP.md`](API_KEYS_SETUP.md) for complete API key setup (Groq, OpenAI, Pexels, ElevenLabs, and other integrations).

## 🗂️ Project Structure

```text
ViraClip/
├── backend/          # Python FastAPI + asyncio services
├── frontend/         # Next.js dashboard
├── comfyui/          # ComfyUI integration (optional visual AI)
├── nginx/            # Reverse proxy config
├── scripts/          # Utility scripts
├── transitions/      # FFmpeg transition presets
├── workflows/        # LangGraph workflow definitions
├── docs/             # Extended documentation
├── docker-compose.yml
└── .env.example
```

## 📚 Documentation

- [DEPLOY_GUIDE.md](DEPLOY_GUIDE.md)
- [DEVELOPMENT_SETUP.md](DEVELOPMENT_SETUP.md)
- [API_KEYS_SETUP.md](API_KEYS_SETUP.md)
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| AI/LLM | Groq, OpenAI, Anthropic |
| Transcription | OpenAI Whisper |
| Orchestration | LangGraph, asyncio |
| Video processing | FFmpeg 7.1 |
| Backend | Python 3.11, FastAPI |
| Frontend | Next.js 14, TypeScript |
| Database | PostgreSQL, Redis |
| Storage | AWS S3 / Cloudflare R2 |
| Container | Docker Compose |

## 🤝 Contributing

Contributions are welcome and appreciated. Please review [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow, coding standards, and pull request expectations before opening a PR.

## 📄 License

MIT
