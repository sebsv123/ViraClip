# ViraClip Documentation

Canonical documentation hub for ViraClip. If you only have time for one file, read the [project README](../README.md) first; this folder goes deeper.

## Recommended reading paths

**For operators (running the stack):**

1. [Setup](./setup.md) — Docker-first install + first-run checklist.
2. [Configuration](./configuration.md) — every environment variable, organised by feature.
3. [Troubleshooting](./troubleshooting.md) — startup failures, stuck tasks, auth/font/billing/YouTube issues.

**For developers (writing code):**

1. [Development](./development.md) — repo layout, per-app commands, common workflows.
2. [Architecture](./architecture.md) — frontend/backend/worker/Redis/Postgres flow, video pipeline, DB model.
3. [API Reference](./api-reference.md) — frontend proxy routes, backend endpoints, auth and streaming notes.

**For product and support:**

1. [App Guide](./app-guide.md) — main screens, routes, user workflows, hosted vs self-host differences.
2. [Troubleshooting](./troubleshooting.md).

## Documentation map

| Doc | What is in it |
|---|---|
| [`setup.md`](./setup.md) | Docker install, local dev commands, production-minded setup notes |
| [`configuration.md`](./configuration.md) | API keys, processing modes, auth, monetisation, analytics, YouTube auth |
| [`app-guide.md`](./app-guide.md) | Screens, routes, core workflows, admin features |
| [`architecture.md`](./architecture.md) | Components, queues, SSE progress, DB model |
| [`api-reference.md`](./api-reference.md) | Endpoints (frontend proxy + backend), auth, streaming |
| [`development.md`](./development.md) | Where to modify major features, how to add domains/services |
| [`troubleshooting.md`](./troubleshooting.md) | Common failures and fixes |
| [`archive/`](./archive/) | Historical docs preserved for reference (not maintained) |

## Related root-level docs

These live outside `docs/` because they are project-wide rather than user-facing:

- [`README.md`](../README.md) — project overview, quick start, badges
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — branch strategy, commit conventions, PR checklist
- [`AGENTS.md`](../AGENTS.md) — repository conventions for AI/human contributors
- [`SECURITY.md`](../SECURITY.md) — responsible disclosure
- [`CHANGELOG.md`](../CHANGELOG.md) — release notes
- [`DEPLOY_GUIDE.md`](../DEPLOY_GUIDE.md) — deployment recipes
- [`API_KEYS_SETUP.md`](../API_KEYS_SETUP.md) — how to obtain provider keys
- [`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) — root-level troubleshooting (overlaps with the docs version; will be merged in a future cleanup)

## What ViraClip is

ViraClip is an open-source, GPU-accelerated AI video clipping platform. It ingests a long video (YouTube URL or upload), transcribes it with `faster-whisper`, picks the most viral segments with an LLM, and renders ready-to-publish vertical short-form clips with subtitles, B-roll, music, and platform-specific export presets.

The repository contains three apps:

- `frontend/` — main Next.js 15 app (creator dashboard, billing, admin)
- `waitlist/` — standalone Next.js marketing/waitlist app
- `backend/` — FastAPI API + `arq` worker, organised by domain under `backend/src/domains/` with cross-cutting infrastructure under `backend/src/core/`

Plus optional services: ComfyUI for generative B-roll, Ollama for local LLMs, and an nginx reverse-proxy reference config.

## Contributing to the docs

Docs follow the same flow as code: open a PR with a `docs(scope): summary` commit. See [`CONTRIBUTING.md`](../CONTRIBUTING.md). Old material that is no longer accurate should be moved to [`archive/`](./archive/) rather than deleted, so that history stays inspectable.
