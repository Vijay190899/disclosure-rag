.PHONY: install lint format test run docker help

help:
	@echo "install  - create venv and install deps with uv"
	@echo "lint     - ruff check + format check"
	@echo "format   - ruff format"
	@echo "test     - run pytest"
	@echo "run      - start the FastAPI app"
	@echo "docker   - build the container image"

install:
	uv sync --extra dev

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .

test:
	uv run pytest

run:
	uv run uvicorn finrag.app:app --reload --port 8000

docker:
	docker build -t finrag:local .
