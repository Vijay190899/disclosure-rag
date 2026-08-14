.PHONY: install lint format typecheck test check run docker fetch labels eval review help

help:
	@echo "install    - create venv and install deps with uv"
	@echo "lint       - ruff check + format check"
	@echo "format     - ruff format"
	@echo "typecheck  - mypy in strict mode"
	@echo "test       - run pytest"
	@echo "check      - lint + typecheck + test (what CI runs)"
	@echo "run        - start the API and viewer on :8000"
	@echo "docker     - build the container image"
	@echo "fetch      - download ESEF report packages into data/filings"
	@echo "labels     - build fact ledgers from data/filings"
	@echo "eval       - run the retrieval baseline against the ledgers"
	@echo "review     - confirm prose pair candidates, one keystroke each"

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

fetch:
	uv sync --extra dev --extra labels
	uv run python -m disclosure_rag.labels.fetch --out data/filings --count 8

labels:
	uv sync --extra dev --extra labels
	uv run playwright install chromium
	uv run python -m disclosure_rag.labels.build --filings data/filings --out data/ledgers

# Settings pinned to the ones the published numbers were measured at, so
# `make eval` reproduces the README rather than something adjacent to it.
eval:
	uv run python -m disclosure_rag.evaluation.run --ledgers data/ledgers --chunk-tokens 600 --overlap-tokens 20 --out data/results.json

# Candidates are mechanical, confirmation is not. See the module docstring for
# why no available signal separates a narrative sentence from a table row.
review:
	uv run python -m disclosure_rag.labels.review --ledgers data/ledgers
