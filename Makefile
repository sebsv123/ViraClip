BACKEND_TEST_ENV = DATABASE_URL=$${TEST_DATABASE_URL:-$${DATABASE_URL:-postgresql+asyncpg://viraclip:viraclip_password@127.0.0.1:5432/viraclip}} REDIS_HOST=$${REDIS_HOST:-127.0.0.1} REDIS_PORT=$${REDIS_PORT:-6379}
FRONTEND_TEST_ENV = DATABASE_URL=$${TEST_DATABASE_URL:-$${DATABASE_URL:-postgresql://viraclip:viraclip_password@127.0.0.1:5432/viraclip}} BACKEND_AUTH_SECRET=$${BACKEND_AUTH_SECRET:-viraclip_test_secret} BETTER_AUTH_SECRET=$${BETTER_AUTH_SECRET:-viraclip_better_auth_test_secret} NEXT_PUBLIC_SELF_HOST=true

.PHONY: test test-backend test-frontend test-e2e test-ci status logs-worker logs-backend worker-restart flush-queue task-status test-task

test: test-backend test-frontend

test-backend:
	cd backend && uv sync --all-groups
	cd backend && $(BACKEND_TEST_ENV) .venv/bin/pytest

test-frontend:
	cd frontend && npm install
	cd frontend && $(FRONTEND_TEST_ENV) npm run test:coverage

test-e2e:
	cd frontend && npm install
	cd frontend && $(FRONTEND_TEST_ENV) npx playwright install --with-deps
	cd frontend && $(FRONTEND_TEST_ENV) npm run test:e2e

test-ci: test-backend test-frontend test-e2e

# ─────────────────────────────────────────────────────────────────────────────
# Development targets
# ─────────────────────────────────────────────────────────────────────────────

status:
	@./dev-status.sh

logs-worker:
	@docker logs viraclip-worker -f --tail 100

logs-backend:
	@docker logs viraclip-backend -f --tail 100

worker-restart:
	@docker restart viraclip-worker
	@echo "✓ Worker reiniciado"

flush-queue:
	@echo "⚠ Esto eliminará TODOS los jobs pendientes en arq:queue"
	@read -p "¿Continuar? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	@docker exec viraclip-redis redis-cli DEL arq:queue
	@docker exec viraclip-redis redis-cli KEYS 'arq:retry:*' | xargs -r docker exec viraclip-redis redis-cli DEL
	@echo "✓ Queue limpiada"

task-status:
ifndef TASK_ID
	@echo "Uso: make task-status TASK_ID=<uuid>"
	@exit 1
endif
	@echo "=== Task Status en PostgreSQL ==="
	@docker exec viraclip-postgres psql -U viraclip -d viraclip -c "
		SELECT id, status, progress, current_stage, error_message, created_at, updated_at
		FROM tasks WHERE id = '$(TASK_ID)';
	" 2>/dev/null || echo "  (error consultando PostgreSQL)"
	@echo ""
	@echo "=== Job Status en Redis (arq) ==="
	@docker exec viraclip-redis redis-cli KEYS "arq:*:$(TASK_ID)*" 2>/dev/null | head -5 || echo "  (no encontrado en Redis)"

test-task:
ifndef URL
	@echo "Uso: make test-task URL=<youtube_url>"
	@exit 1
endif
	@echo "🎬 Creando task de prueba..."
	@$(eval TASK_RESPONSE := $(shell curl -s -X POST http://localhost:8000/tasks \
		-H "Content-Type: application/json" \
		-d '{"url":"$(URL)","num_clips":1,"add_subtitles":true}'))
	@$(eval TASK_ID := $(shell echo '$(TASK_RESPONSE)' | python3 -c "import sys,json; print(json.load(sys.stdin).get('task_id',''))" 2>/dev/null || echo ""))
	@if [ -z "$(TASK_ID)" ]; then \
		echo "❌ Error creando task: $(TASK_RESPONSE)"; \
		exit 1; \
	fi
	@echo "✓ Task creado: $(TASK_ID)"
	@echo ""
	@echo "⏳ Polling hasta completion..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do \
		STATUS=$$(curl -s http://localhost:8000/tasks/$(TASK_ID) | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "error"); \
		PROGRESS=$$(curl -s http://localhost:8000/tasks/$(TASK_ID) | python3 -c "import sys,json; print(json.load(sys.stdin).get('progress',0))" 2>/dev/null || echo "0"); \
		STAGE=$$(curl -s http://localhost:8000/tasks/$(TASK_ID) | python3 -c "import sys,json; print(json.load(sys.stdin).get('current_stage',''))" 2>/dev/null || echo ""); \
		echo "  [$$i] Status: $$STATUS, Progress: $$PROGRESS%, Stage: $$STAGE"; \
		if [ "$$STATUS" = "completed" ] || [ "$$STATUS" = "error" ]; then \
			echo ""; \
			echo "=== Resultado Final ==="; \
			curl -s http://localhost:8000/tasks/$(TASK_ID) | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8000/tasks/$(TASK_ID); \
			break; \
		fi; \
		sleep 10; \
	done
