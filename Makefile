.PHONY: up seed test demo-reset dev-api dev-web lint
up:
	docker compose up --build -d
seed:
	docker compose exec api python -m app.seed.load
demo-reset:
	docker compose exec api python -m app.seed.load --reset
test:
	cd apps/api && uv run pytest -q
lint:
	cd apps/api && uv run ruff check . && cd ../web && npm run lint
# no-docker local dev (SQLite + in-process memory/events)
dev-api:
	cd apps/api && DATABASE_URL=sqlite+aiosqlite:///./carebridge.db REDIS_URL= uv run uvicorn app.main:app --reload --port $${PORT:-8000}
dev-web:
	cd apps/web && npm run dev
