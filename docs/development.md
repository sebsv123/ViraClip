# Local Development Guide

## Prerequisites

| Tool | Min version | Install |
|---|---|---|
| Docker + Compose | 24+ | [docs.docker.com](https://docs.docker.com/get-docker/) |
| Node.js | 20+ | [nodejs.org](https://nodejs.org/) |
| Python | 3.11+ | [python.org](https://www.python.org/) |
| `uv` | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Git | 2.40+ | system package manager |

Optional but recommended:
- **NVIDIA GPU + Container Toolkit** — 5-10× faster transcription and rendering
- **fish / zsh** — the scripts are POSIX-compatible but fish gives nicer UX

---

## Quick Start (Docker — recommended)

```bash
git clone https://github.com/sebsv123/ViraClip.git
cd ViraClip

# Copy and fill in your API keys
cp .env.example .env
$EDITOR .env  # add at minimum ASSEMBLY_AI_API_KEY + one LLM key

# Build and start everything
make build
make dev
```

Services available at:

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API + Swagger | http://localhost:8000/docs |
| Postgres | localhost:5432 |
| Redis | localhost:6379 |
| ComfyUI | http://localhost:8188 |

Watch logs: `make logs` · Backend only: `make logs-backend` · Worker only: `make logs-worker`

---

## Local Development (without Docker)

Useful when you want hot-reload on backend/frontend changes without rebuilding images.

### Backend

```bash
cd backend
uv sync --all-groups        # installs all deps into .venv

# Requires local Postgres + Redis (or start them via Docker)
docker compose up -d postgres redis

uv run uvicorn src.main:app --reload --port 8000
```

### Worker

```bash
cd backend
uv run arq src.workers.tasks.WorkerSettings
```

### Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:3000
```

---

## Pre-commit Hooks

We use `pre-commit` for automated checks on every commit:

```bash
pip install pre-commit
pre-commit install --hook-type pre-commit --hook-type commit-msg
```

Hooks run:
- **ruff** — Python linting + formatting
- **prettier** — JS/TS/JSON/YAML formatting  
- **detect-secrets** — prevents accidental secret commits
- **conventional-commits** — enforces commit message format

Run manually: `pre-commit run --all-files`

---

## Commit Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

Types:  feat | fix | chore | docs | refactor | test | ci | perf
Scopes: backend | frontend | worker | docker | pipeline | captions | broll | audio

Examples:
  feat(pipeline): add face autocrop service with MediaPipe tracking
  fix(captions): prevent triple subtitle overlay on re-render
  chore(docker): upgrade CUDA base image to 12.4
  docs(api): document segment scoring endpoint
```

---

## Running Tests

```bash
make test             # backend + frontend
make test-backend     # pytest (requires Postgres + Redis)
make test-frontend    # Vitest + React Testing Library + coverage
make test-e2e         # Playwright smoke flows
```

Backend tests run against a real Postgres/Redis — make sure they're up:
```bash
docker compose up -d postgres redis
make test-backend
```

---

## Linting

```bash
make lint             # ruff + ESLint
make fmt              # ruff format + prettier
make lint-backend     # Python only
make lint-frontend    # JS/TS only
```

---

## Database

```bash
make shell-db         # opens psql inside the postgres container
make migrate-status   # shows Alembic current revision

# Apply pending migrations
docker compose exec backend uv run alembic upgrade head

# Create a new migration
docker compose exec backend uv run alembic revision --autogenerate -m "add_clip_health_score"
```

---

## Project Structure

```
ViraClip/
├── backend/
│   ├── src/
│   │   ├── domains/      # Business domains (ai, audio, broll, captions, video…)
│   │   ├── services/     # Orchestration (coordinator.py is the main pipeline)
│   │   ├── workers/      # arq task definitions
│   │   ├── api/          # FastAPI routers
│   │   └── main.py
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── app/          # Next.js 15 App Router pages
│   │   ├── components/   # UI components
│   │   └── lib/          # API clients, hooks, utils
│   └── package.json
├── comfyui/              # ComfyUI workflows for generative B-roll
├── nginx/                # Reverse proxy config
├── rust-agent/           # High-perf task runner (optional)
├── scripts/              # Dev utilities
├── docs/                 # Documentation
├── docker-compose.yml
└── Makefile
```

---

## Useful Commands

```bash
make help             # full list of make targets
make shell-backend    # bash inside backend container
make shell-worker     # bash inside worker container
make clean            # nuclear option: removes volumes too

# Watch a specific task
docker compose logs -f worker | grep <task-id>

# Manually trigger a task via API
curl -X POST http://localhost:8000/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://youtu.be/..."}'
```

---

## Troubleshooting

See [`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) for common issues.

Most frequent:
- **Port conflicts** — check nothing else runs on 3000/8000/5432/6379
- **GPU not found** — ensure NVIDIA Container Toolkit is installed: `nvidia-smi` inside container should work
- **Build failures** — `make clean && make build` usually fixes stale layer issues
- **Worker not picking up tasks** — verify Redis is healthy: `docker compose ps redis`
