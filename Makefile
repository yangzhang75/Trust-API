.DEFAULT_GOAL := help
.PHONY: help install run up down test lint fmt migrate openapi

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install the package with dev dependencies
	pip install -e ".[dev]"

run: ## Run the API locally with autoreload
	uvicorn trust_api.main:app --reload --host 0.0.0.0 --port 8000

up: ## Build and start all services (api + postgres + redis)
	docker compose up --build

down: ## Stop services and remove volumes
	docker compose down -v

test: ## Run tests with coverage
	pytest --cov=trust_api --cov-report=term-missing

lint: ## Lint with ruff and check formatting with black
	ruff check src tests scripts migrations
	black --check src tests scripts migrations

fmt: ## Auto-format with black and apply ruff fixes
	ruff check --fix src tests scripts migrations
	black src tests scripts migrations

migrate: ## Apply database migrations to head
	alembic upgrade head

openapi: ## Export the OpenAPI schema to docs/openapi.json
	python scripts/export_openapi.py
