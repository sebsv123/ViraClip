# Changelog

All notable changes to ViraClip are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Until a `1.0.0` tag is cut, expect breaking changes between minor versions.

## [Unreleased]

### Added
- Domain-driven backend layout: `backend/src/domains/` (16 domains) + `backend/src/core/` for cross-cutting infrastructure.
- Submodule split for the video pipeline:
  - `_helpers.py`, `_subtitles.py`, `_transcript.py`, `_clips_batch.py`, `_clip_renderer.py`, `_clip_polish.py`, `_clips_transitions.py`, `_pipeline.py`.
- Mixin split for `TaskService`: `_processor_mixin.py`, `_queries_mixin.py`, `_editor_mixin.py`.
- Repo hygiene: `CONTRIBUTING.md`, `CODEOWNERS`, `.editorconfig`, `.pre-commit-config.yaml`, GitHub PR/issue templates.
- CI/CD: `lint.yml` and `tests.yml` workflows with path filtering, plus a Dependabot configuration covering pip / npm / GitHub Actions / Docker.
- `SECURITY.md` describing the responsible disclosure process.
- `CHANGELOG.md` (this file).
- `.github/CODE_OF_CONDUCT.md` (Contributor Covenant 2.1).
- `.github/FUNDING.yml` for sponsorship metadata.

### Changed
- `VideoService` is now a thin facade (≈60 lines) over the new video submodules; public API preserved.
- `TaskService` is now a thin facade (≈240 lines) inheriting from focused mixins; public API preserved.
- `README.md` rewritten: badges, accurate state, architecture diagram, honest test status.
- `AGENTS.md` updated to reflect the new domain layout.
- The legacy `backend/src/services/` directory has been removed; ComfyUI orchestration lives under `domains/broll/comfyui/`.

### Removed
- Outdated references to the deleted `version-basica` branch.
- Inflated test-suite claims from the README; the real testing baseline is described honestly.

## [0.1.0] - 2026-04-16

Initial public snapshot. Covers the MVP feature set:

- AI-driven clip selection from YouTube URLs and uploads.
- GPU-accelerated transcription (`faster-whisper`).
- Word-level ASS subtitle rendering with multiple presets.
- B-roll generation pipeline (Pexels, ComfyUI/LTXV, Stability AI, Replicate).
- Beat-synced background music with sidechain ducking.
- Cut-zoom, hook slo-mo, LUT grading, vignette, hook visual overlays.
- Async worker queue (`arq`) with Redis-backed cache.
- Stripe + Resend hosted-billing flow (opt-in via `SELF_HOST=false`).
- Next.js 15 frontend with Better Auth (email/password + Google OAuth).
- Docker-based local stack: frontend, backend, worker, ComfyUI, Postgres, Redis, nginx.

[Unreleased]: https://github.com/sebsv123/ViraClip/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/sebsv123/ViraClip/releases/tag/v0.1.0
