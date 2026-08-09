"""Environment-driven settings.

One switch (`PROVIDER`) selects the LLM substrate for both chat and
embeddings: "ollama" for the fully local/offline path, "openai" for the
cloud path. Everything else has sensible defaults for the docker-compose
setup in the repo root.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider: str = "ollama"  # "ollama" | "openai"

    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.2:3b"
    ollama_embed_model: str = "nomic-embed-text"

    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_embed_model: str = "text-embedding-3-small"

    database_url: str = "postgresql://assist:assist@localhost:5433/assist"

    retrieval_k: int = 6
    grounding_min_similarity: float = 0.30


@lru_cache
def get_settings() -> Settings:
    return Settings()