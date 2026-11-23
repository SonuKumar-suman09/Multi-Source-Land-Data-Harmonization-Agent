"""Application settings loaded from environment variables and the local .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Land Data Harmonization Agent"
    app_env: str = "local"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://land_app:change_me_local_only@127.0.0.1:5433/land_harmonizer"
    redis_url: str = "redis://127.0.0.1:6379/0"
    celery_queue: str = "land_workflows"
    embedding_dimensions: int = Field(default=768, ge=1)
    rag_embedding_provider: str = "local"
    gemini_api_key: SecretStr | None = None
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_chat_model: str = "gemini-3.5-flash-lite"
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "land-data-harmonization-agent"
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str | None = None
    jwt_secret_key: str = "replace_with_a_random_secret_before_running_auth"
    jwt_access_token_minutes: int = Field(default=30, ge=1, le=1440)
    frontend_origins: str = "http://localhost:5173"
    upload_dir: str = "./data/uploads"
    storage_backend: Literal["local", "minio"] = "local"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: SecretStr | None = None
    minio_secret_key: SecretStr | None = None
    minio_bucket: str = "land-source-files"
    minio_secure: bool = False
    max_upload_mb: int = Field(default=100, ge=1, le=1024)

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
