FROM python:3.12-slim

# Pinned, and pinned to the version that wrote uv.lock. An older uv cannot parse
# a newer lockfile, so this pin and the lockfile have to move together.
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /usr/local/bin/uv

WORKDIR /app

# Two syncs, so an edit to src does not invalidate the dependency layer.
#
# --no-install-project installs dependencies only. The project itself is
# installed by the second sync, after the full source is present. Doing it in
# one step and copying only __init__.py to keep the cache warm does build, and
# then produces an image whose installed package contains nothing but that one
# file, which fails at import with no clue why.
#
# --frozen makes the build fail rather than silently resolve a dependency set
# different from the one CI tested. LICENSE is copied because pyproject declares
# it as the licence file and the build backend reads it.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

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
