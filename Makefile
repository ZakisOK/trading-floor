.PHONY: dev test lint format run migrate seed backtest bootstrap docker-up docker-down docker-logs

dev:
	docker compose up -d && uvicorn src.api.main:app --reload --port 8000

test:
	pytest tests/ -v --asyncio-mode=auto

lint:
	ruff check src/ tests/ && mypy src/

format:
	ruff format src/ tests/

run:
	uvicorn src.api.main:app --port 8000

migrate:
	alembic upgrade head

seed:
	python scripts/seed_db.py

bootstrap:
	python scripts/bootstrap_streams.py

backtest:
	python scripts/run_backtest.py

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f
