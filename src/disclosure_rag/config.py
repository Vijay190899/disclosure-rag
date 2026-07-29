"""Application configuration, loaded from environment variables or a .env file.

Settings are grouped by pipeline stage rather than held in one flat namespace.
The pipeline has several stages and each one will grow its own knobs, so
nesting them now avoids a forty-field flat object later. Nested values are read
with a double-underscore delimiter, for example ``RETRIEVAL__TOP_K=20``.
"""

from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class QdrantSettings(BaseModel):
    """Vector store connection and collection naming."""

    url: str = "http://localhost:6333"
    collection: str = "disclosure_passages"


class IngestSettings(BaseModel):
    """Rendering, parsing and chunking. See ADR-0002 for the parser choice."""

    render_dpi: int = Field(default=200, ge=72, le=600)
    target_chunk_tokens: int = Field(default=600, ge=64, le=4096)
    chunk_overlap_tokens: int = Field(default=80, ge=0, le=1024)


class RetrievalSettings(BaseModel):
    """Hybrid retrieval and reranking. See ADR-0006 for the fusion method."""

    top_k: int = Field(default=10, ge=1, le=200)
    candidate_k: int = Field(default=50, ge=1, le=500)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    rerank_enabled: bool = True


class AnswerSettings(BaseModel):
    """Grounded generation and abstention. See ADR-0005."""

    abstain_below: float = Field(default=0.5, ge=0.0, le=1.0)
    max_context_chunks: int = Field(default=8, ge=1, le=50)


class Settings(BaseSettings):
    """Top-level application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Provider credentials. Empty by default so the package imports without a .env.
    openai_api_key: str = ""

    # Pipeline stages.
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    ingest: IngestSettings = Field(default_factory=IngestSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    answer: AnswerSettings = Field(default_factory=AnswerSettings)

    # Runtime.
    log_level: str = "INFO"
    environment: str = "local"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings.

    Cached because re-reading and re-parsing the .env on every call is wasteful
    once this sits behind a request handler. Tests that need isolation from a
    developer's local .env should construct ``Settings(_env_file=None)``
    directly instead of calling this. Anything that overrides the environment
    and then calls this must first call ``get_settings.cache_clear()``.
    """
    return Settings()
