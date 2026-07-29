.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE      := docker compose
COMPOSE_PROD := docker compose -f docker-compose.yml -f docker-compose.prod.yml
BACKEND      := $(COMPOSE) exec -T backend
FRONTEND     := $(COMPOSE) exec -T frontend

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Setup -------------------------------------------------------------------

.PHONY: init
init: ## First-time setup: create .env and build images
	@test -f .env || (cp .env.example .env && \
		SECRET=$$(openssl rand -base64 48 | tr -d '\n') && \
		sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=$$SECRET|" .env && rm -f .env.bak && \
		echo "Created .env with a generated SECRET_KEY")
	$(COMPOSE) build
	@echo "Run 'make up' to start the stack."

# --- Lifecycle ---------------------------------------------------------------

.PHONY: up
up: ## Start the full stack
	$(COMPOSE) up -d
	@echo "API      http://localhost:8000/docs"
	@echo "Frontend http://localhost:3000"

.PHONY: down
down: ## Stop the stack
	$(COMPOSE) down

.PHONY: restart
restart: down up ## Restart the stack

.PHONY: clean
clean: ## Stop the stack and delete all volumes (destroys local data)
	$(COMPOSE) down -v --remove-orphans

.PHONY: logs
logs: ## Tail logs (make logs S=backend)
	$(COMPOSE) logs -f $(S)

.PHONY: ps
ps: ## Show service status
	$(COMPOSE) ps

.PHONY: build
build: ## Rebuild images
	$(COMPOSE) build --pull

# --- Database ----------------------------------------------------------------

.PHONY: migrate
migrate: ## Apply migrations
	$(BACKEND) alembic upgrade head

.PHONY: migration
migration: ## Autogenerate a migration (make migration M="add tokens")
	@test -n "$(M)" || (echo "Usage: make migration M=\"description\"" && exit 1)
	$(BACKEND) alembic revision --autogenerate -m "$(M)"

.PHONY: downgrade
downgrade: ## Roll back one migration
	$(BACKEND) alembic downgrade -1

.PHONY: migration-check
migration-check: ## Fail if a model has drifted from the migrations
	$(BACKEND) alembic check

.PHONY: seed
seed: ## Create a local admin user
	$(BACKEND) python -m scripts.seed

.PHONY: psql
psql: ## Open a psql shell
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-memescope} -d $${POSTGRES_DB:-memescope}

.PHONY: redis-cli
redis-cli: ## Open a redis shell
	$(COMPOSE) exec redis redis-cli

# --- Quality -----------------------------------------------------------------

.PHONY: test
test: test-backend test-frontend ## Run all tests

.PHONY: test-backend
test-backend: ## Run backend tests
	$(BACKEND) pytest

.PHONY: test-unit
test-unit: ## Run backend unit tests only
	$(BACKEND) pytest -m unit

.PHONY: test-frontend
test-frontend: ## Run frontend tests
	$(FRONTEND) npm run test

.PHONY: lint
lint: ## Lint both services
	$(BACKEND) ruff check .
	$(BACKEND) ruff format --check .
	$(FRONTEND) npm run lint

.PHONY: format
format: ## Auto-format both services
	$(BACKEND) ruff check --fix .
	$(BACKEND) ruff format .
	$(FRONTEND) npm run format

.PHONY: typecheck
typecheck: ## Type-check both services
	$(BACKEND) mypy app
	$(FRONTEND) npm run typecheck

.PHONY: check
check: lint typecheck migration-check test ## Everything CI runs

# --- Shells ------------------------------------------------------------------

.PHONY: shell-backend
shell-backend: ## Bash shell in the backend container
	$(COMPOSE) exec backend bash

.PHONY: shell-frontend
shell-frontend: ## Shell in the frontend container
	$(COMPOSE) exec frontend sh

# --- Production --------------------------------------------------------------

.PHONY: prod-build
prod-build: ## Build production images
	$(COMPOSE_PROD) build

.PHONY: prod-up
prod-up: ## Start the production stack
	$(COMPOSE_PROD) up -d

.PHONY: prod-down
prod-down: ## Stop the production stack
	$(COMPOSE_PROD) down
