"""Environment-driven settings.

The model substrate is the OpenAI API locally and Azure OpenAI in the
cloud target (identical wire format). Models are configurable; changing
the embedding model requires re-seeding, which the API enforces via the
seed-compatibility guard (ADR-005).
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

    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_embed_model: str = "text-embedding-3-small"

    database_url: str = "postgresql://assist:assist@localhost:5433/assist"

    retrieval_k: int = 6
    grounding_min_similarity: float = 0.30


@lru_cache
def get_settings() -> Settings:
    return Settings()