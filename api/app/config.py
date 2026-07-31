"""Configuration, loaded and validated from the environment.

The LLM endpoint is OpenAI-compatible, so the same settings point at OpenAI or
at a proxy such as KKU IntelSphere via OPENAI_BASE_URL.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- LLM ---
    openai_api_key: str = ""
    openai_base_url: str | None = None
    llm_model: str = "qwen3.7-max"

    # --- Storage ---
    # SQLite is the catalogue of record: every number in the report is computed
    # from it with SQL, never guessed by the model.
    database_path: str = "./data/market.db"

    # --- Vector store ---
    qdrant_location: str = "./data/qdrant"
    qdrant_collection: str = "market_intel"
    embedding_model: str = "BAAI/bge-small-en-v1.5"  # local, via fastembed

    # --- Analysis ---
    reviews_per_llm_call: int = 25  # batch size for aspect extraction
    max_review_chars: int = 600  # truncate very long reviews before sending
    report_dir: str = "../reports"

    # Static FX table. Rates this coarse are fine for "is brand A pricier than
    # brand B", and a hard-coded table is honest about that; a live FX feed
    # would imply a precision the rest of the pipeline does not have.
    base_currency: str = "USD"
    fx_rates: dict[str, float] = {
        "USD": 1.0,
        "GBP": 1.27,
        "EUR": 1.08,
        "THB": 0.028,
    }

    @property
    def llm_configured(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
