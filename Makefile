.PHONY: install lint format typecheck test check run docker spike labels eval help

help:
	@echo "install    - create venv and install deps with uv"
	@echo "lint       - ruff check + format check"
	@echo "format     - ruff format"
	@echo "typecheck  - mypy in strict mode"
	@echo "test       - run pytest"
	@echo "check      - lint + typecheck + test (what CI runs)"
	@echo "run        - start the FastAPI app on :8000"
	@echo "docker     - build the container image"
	@echo "labels     - build fact ledgers from data/filings"
	@echo "eval       - run the retrieval baseline against the ledgers"
	@echo "spike      - install spike extras and run the ESEF probe"

install:
	uv sync --extra dev

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .

typecheck:
	uv run mypy

test:
	uv run pytest

check: lint typecheck test

run:
	uv run uvicorn disclosure_rag.app:app --reload --port 8000

docker:
	docker build -t disclosure-rag:local .

labels:
	uv sync --extra dev --extra labels
	uv run playwright install chromium
	uv run python -m disclosure_rag.labels.build --filings data/filings --out data/ledgers

eval:
	uv run python -m disclosure_rag.evaluation.run --ledgers data/ledgers --out data/results.json

spike:
	uv sync --extra dev --extra spike
	uv run playwright install chromium
	uv run python -m spikes.esef_probe
