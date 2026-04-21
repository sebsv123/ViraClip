# Agent Configuration — ViraClip

## Active Agents

### cascade (Primary)
- **Role**: Full-stack development assistant
- **Permissions**: Read all, modify services/, create tests
- **Restricted**: docker-compose.yml, coordinator.py, migrations, .env
- **Shell**: fish (`set -Ux`, not `export`)

## Context

- **Repository**: https://github.com/sebsv123/ViraClip
- **Branch**: version-basica
- **Stack**: FastAPI + Next.js + PostgreSQL + Redis + Docker

## Memory System

- **Working**: `.agent/memory/working/WORKSPACE.md`
- **Semantic**: `.agent/memory/semantic/DECISIONS.md`, `LESSONS.md`
- **Protocols**: `.agent/protocols/permissions.md`

## CLI Tools

Available in `.agent/tools/`:
- `agent-brain` — Query memory system
- `agent-context` — Load workspace state
- `agent-decide` — Record architectural decisions
