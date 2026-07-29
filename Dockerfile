FROM python:3.12-slim

# Pin the uv image by version rather than :latest so the build is repeatable.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app

# Dependency manifests first, so an edit to src does not invalidate the
# dependency layer. Source is copied after the install for that reason.
COPY pyproject.toml README.md ./
COPY src/disclosure_rag/__init__.py ./src/disclosure_rag/__init__.py
RUN uv sync --no-editable --no-dev

COPY src ./src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Drop root. The service needs no write access to its own code.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "disclosure_rag.app:app", "--host", "0.0.0.0", "--port", "8000"]
