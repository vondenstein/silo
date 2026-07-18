DEV_DATA_DIR ?= /tmp/silo-dev/data
DEV_LIBRARY_DIR ?= /tmp/silo-dev/games
DEV_ENV = SILO_DATA_DIR=$(DEV_DATA_DIR) SILO_LIBRARY_DIR=$(DEV_LIBRARY_DIR)

.PHONY: reset-dev-db dev check drift-check regen-initial-migration export-openapi

reset-dev-db:
	rm -f $(DEV_DATA_DIR)/silo.db

dev:
	@mkdir -p $(DEV_DATA_DIR) $(DEV_LIBRARY_DIR)
	cd api && $(DEV_ENV) uv run fastapi dev --port 9550

check:
	cd api && uv run ruff check . && uv run ruff format --check && uv run ty check && uv run pytest -v

drift-check:
	@mkdir -p $(DEV_DATA_DIR) $(DEV_LIBRARY_DIR)
	cd api && $(DEV_ENV) uv run alembic check

export-openapi:
	@mkdir -p $(DEV_DATA_DIR) $(DEV_LIBRARY_DIR)
	cd api && $(DEV_ENV) uv run python -c "import json; from silo.app import create_app; print(json.dumps(create_app().openapi(), indent=2))" > openapi.json

regen-initial-migration:
	@echo "Regenerating initial migration (squash policy; pre-release only — PD2)..."
	rm -f api/alembic/versions/*.py
	$(MAKE) reset-dev-db
	@mkdir -p $(DEV_DATA_DIR) $(DEV_LIBRARY_DIR)
	cd api && $(DEV_ENV) uv run alembic revision --autogenerate -m "initial" --rev-id 6922cd618079
	cd api && $(DEV_ENV) uv run alembic upgrade head
	cd api && $(DEV_ENV) uv run alembic check
