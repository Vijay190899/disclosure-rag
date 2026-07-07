"""Application configuration, loaded from environment / .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Providers
    openai_api_key: str = ""
    cohere_api_key: str = ""
    llama_cloud_api_key: str = ""

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "finrag_documents"

    # App
    log_level: str = "INFO"
    environment: str = "local"


def get_settings() -> Settings:
    """Return application settings. Kept as a function so it's easy to override in tests."""
    return Settings()
