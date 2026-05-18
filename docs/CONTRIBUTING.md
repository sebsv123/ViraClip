# Contributing to ViraClip

Thank you for your interest in contributing! This document outlines our workflow.

## Quick Start

```bash
# 1. Fork & clone
git clone git@github.com:<your-user>/ViraClip.git
cd ViraClip

# 2. Configure environment
cp .env.example .env
# Edit .env with your API keys (see README for required keys)

# 3. Start the full stack
docker-compose up -d --build

# 4. Run pre-commit checks before pushing
pre-commit install
```

## Project Layout

```
backend/   FastAPI + arq worker. Code lives in src/{api,core,domains,workers,repositories,...}
frontend/  Next.js app. Code lives in src/{app,components,lib}
waitlist/  Standalone Next.js marketing site
comfyui/   ComfyUI custom build for AI broll generation
nginx/     Production reverse proxy config
```

Backend domains (`backend/src/domains/`): `ai`, `audio`, `autopilot`, `billing`, `broll`, `captions`, `detection`, `feedback`, `notifications`, `publishing`, `thumbnails`, `upscaling`, `validation`, `video`, `virality`.

Cross-cutting infrastructure lives in `backend/src/core/`.

## Branch Strategy

We use **trunk-based development** with short-lived feature branches.

- `main` is always deployable. Push directly only for hotfixes.
- Feature branches: `feat/<short-description>`, `fix/<short-description>`, `chore/<short-description>`, `docs/<short-description>`, `refactor/<short-description>`.
- Open a PR against `main`. Squash-merge after CI is green and at least one approving review.

## Commit Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

<optional body>
<optional footer>
```

**Types**: `feat`, `fix`, `chore`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`.

**Scopes** (recommended): `backend`, `frontend`, `waitlist`, `worker`, `comfyui`, `infra`, `deps`.

Examples:

```
feat(backend): add task list pagination
fix(frontend): correct overlay z-index on mobile
refactor(backend): split task_service into smaller modules
chore(deps): bump pydantic-ai to 1.2.0
```

Keep one logical change per commit. Short imperative subject (≤72 chars).

## Pull Request Checklist

Before opening a PR:

- [ ] Code is formatted (`pre-commit run --all-files` passes)
- [ ] Backend changes pass `cd backend && .venv/bin/pytest` (when tests exist)
- [ ] Frontend changes pass `cd frontend && npm run lint && npm run typecheck`
- [ ] No real secrets in code or commits — use `.env.example` as the template
- [ ] Linked issue and verification steps in the PR description
- [ ] Screenshots/GIFs for UI changes

CI must be green before merging. Branch protection requires at least one approving review on `main`.

## Code Style

### Python (backend)

- 4-space indentation, type hints where practical, `snake_case` for functions/modules
- Format with `ruff format` (Black-compatible)
- Lint with `ruff check`
- Imports sorted via `ruff` (replaces isort)

### TypeScript / React (frontend, waitlist)

- 2-space indentation, `PascalCase` for components, `camelCase` for variables/functions
- Format with Prettier; lint with the project ESLint config
- Use the `@/*` import alias when possible
- Next.js App Router conventions: `app/.../page.tsx`, `route.ts`

## Testing

The codebase is moving toward stronger test coverage. Until coverage is enforced, please:

- Add a smoke test for any new endpoint or UI route you introduce
- Place backend tests under `backend/tests/` (name `test_*.py`)
- Place frontend unit tests next to source (`*.test.ts[x]`) and E2E flows under `frontend/playwright/`

Manual verification is acceptable for small fixes — describe the steps in your PR.

## Security

- Never commit real API keys, tokens, or `.env` files
- Use `detect-secrets` (runs in pre-commit) to scan staged changes
- Required runtime keys are documented in `.env.example`
- Report vulnerabilities privately via a GitHub security advisory rather than a public issue

## Code of Conduct

Be respectful, focused, and constructive. Disagreements are fine; personal attacks and harassment are not.

---

Questions? Open a discussion or comment on a related issue.
