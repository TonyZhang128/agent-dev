from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_model: str = "qwen3.5:9b-q4_K_M"
    llm_api_key: SecretStr = SecretStr("ollama")
    llm_timeout_seconds: float = Field(default=180, gt=0, le=600)
    llm_max_tokens: int = Field(default=2048, ge=256, le=8192)
    llm_reasoning_effort: str = "none"
    agent_recursion_limit: int = Field(default=8, ge=3, le=50)
    langsmith_tracing: bool = False

    @field_validator("llm_base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname:
            raise ValueError("LLM_BASE_URL must be an HTTP(S) URL")
        if url.query or url.fragment or url.username or url.password:
            raise ValueError("LLM_BASE_URL must not contain credentials, query or fragment")
        return value.rstrip("/")
