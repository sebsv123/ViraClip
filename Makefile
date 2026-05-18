# ==============================================================================
# ViraClip — Developer Makefile
# ==============================================================================
# Usage: make <target>
# Run `make help` for a full list of available targets.

# ── Environment defaults ──────────────────────────────────────────────────────
BACKEND_TEST_ENV = \
	DATABASE_URL=$${TEST_DATABASE_URL:-$${DATABASE_URL:-postgresql+asyncpg://viraclip:viraclip_password@127.0.0.1:5432/viraclip}} \
	REDIS_HOST=$${REDIS_HOST:-127.0.0.1} \
	REDIS_PORT=$${REDIS_PORT:-6379}

FRONTEND_TEST_ENV = \
	DATABASE_URL=$${TEST_DATABASE_URL:-$${DATABASE_URL:-postgresql://viraclip:viraclip_password@127.0.0.1:5432/viraclip}} \
	BACKEND_AUTH_SECRET=$${BACKEND_AUTH_SECRET:-viraclip_test_secret} \
	BETTER_AUTH_SECRET=$${BETTER_AUTH_SECRET:-viraclip_better_auth_test_secret} \
	NEXT_PUBLIC_SELF_HOST=true

.DEFAULT_GOAL := help

.PHONY: help dev up down build logs restart clean \
        test test-backend test-frontend test-e2e test-ci \
        lint lint-backend lint-frontend fmt fmt-backend fmt-frontend \
        shell-backend shell-worker shell-db migrate-status \
        labels

# ── Help ──────────────────────────────────────────────────────────────────────
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*##"}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Docker ────────────────────────────────────────────────────────────────────
dev: ## Start all services in development mode (with override)
	docker compose -f docker-compose.yml -f docker-compose.override.yml up -d

up: ## Start all services (production mode)
	docker compose up -d

build: ## Rebuild all images
	docker compose build

down: ## Stop all services
	docker compose down

logs: ## Tail logs for all services
	docker compose logs -f

logs-backend: ## Tail backend logs only
	docker compose logs -f backend

logs-worker: ## Tail worker logs only
	docker compose logs -f worker

restart: ## Restart all services
	docker compose restart

clean: ## Remove containers, volumes and orphans
	docker compose down -v --remove-orphans

# ── Testing ───────────────────────────────────────────────────────────────────
test: test-backend test-frontend ## Run all tests (backend + frontend)

test-backend: ## Run backend pytest suite
	cd backend && uv sync --all-groups
	cd backend && $(BACKEND_TEST_ENV) .venv/bin/pytest -v --tb=short

test-frontend: ## Run frontend Vitest suite with coverage
	cd frontend && npm install
	cd frontend && $(FRONTEND_TEST_ENV) npm run test:coverage

test-e2e: ## Run Playwright end-to-end tests
	cd frontend && npm install
	cd frontend && $(FRONTEND_TEST_ENV) npx playwright install --with-deps
	cd frontend && $(FRONTEND_TEST_ENV) npm run test:e2e

test-ci: test-backend test-frontend test-e2e ## Run full CI test suite

# ── Linting & Formatting ──────────────────────────────────────────────────────
lint: lint-backend lint-frontend ## Lint all code

lint-backend: ## Run ruff linter on backend
	cd backend && uv run ruff check .

fmt-backend: ## Format backend code with ruff
	cd backend && uv run ruff format .

lint-frontend: ## Run ESLint on frontend
	cd frontend && npm run lint

fmt-frontend: ## Format frontend code with prettier
	cd frontend && npm run format

fmt: fmt-backend fmt-frontend ## Format all code

# ── Shells & DB ───────────────────────────────────────────────────────────────
shell-backend: ## Open a shell inside the backend container
	docker compose exec backend bash

shell-worker: ## Open a shell inside the worker container
	docker compose exec worker bash

shell-db: ## Open psql inside the postgres container
	docker compose exec postgres psql -U viraclip -d viraclip

migrate-status: ## Show Alembic migration status
	docker compose exec backend uv run alembic current

# ── Labels ────────────────────────────────────────────────────────────────────
labels: ## Create GitHub repo labels (requires GITHUB_TOKEN env var)
	@echo "Creating labels..."
	@for row in \
		'backend:0075ca:Changes to backend Python code' \
		'frontend:f9d0c4:Changes to Next.js frontend' \
		'docker:e4e669:Docker / infrastructure changes' \
		'ci:6e5494:CI/CD workflows' \
		'documentation:0052cc:Documentation updates' \
		'dependencies:cfd3d7:Dependency bumps' \
		'comfyui:d93f0b:ComfyUI pipeline changes' \
		'scripts:bfd4f2:Dev scripts and tooling' \
		'pipeline:e11d48:Core video pipeline changes' \
		'good first issue:7057ff:Good for newcomers' \
		'bug:d73a4a:Something is not working' \
		'enhancement:a2eeef:New feature or request'; do \
			NAME=$$(echo $$row | cut -d: -f1); \
			COLOR=$$(echo $$row | cut -d: -f2); \
			DESC=$$(echo $$row | cut -d: -f3-); \
			curl -s -X POST \
				-H "Authorization: token $${GITHUB_TOKEN}" \
				-H "Accept: application/vnd.github.v3+json" \
				https://api.github.com/repos/sebsv123/ViraClip/labels \
				-d "{\"name\":\"$$NAME\",\"color\":\"$$COLOR\",\"description\":\"$$DESC\"}" \
				> /dev/null && echo "  ✓ $$NAME"; \
		done
