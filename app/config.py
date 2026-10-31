from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
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
    llm_context_tokens: int = Field(default=8192, ge=1024, le=1048576)
    llm_context_margin_tokens: int = Field(default=256, ge=0, le=8192)
    conversation_max_input_characters: int = Field(default=1000000, ge=1, le=10000000)
    llm_reasoning_effort: str = "none"
    # 本地 Ollama/vLLM 调用失败时使用的云端回退；key 为空即关闭。
    llm_fallback_base_url: str = "https://api.deepseek.com"
    llm_fallback_model: str = "deepseek-flash"
    llm_fallback_api_key: SecretStr = SecretStr("")
    llm_fallback_timeout_seconds: float = Field(default=60, gt=0, le=600)
    llm_fallback_reasoning_effort: str = "none"
    agent_recursion_limit: int = Field(default=8, ge=3, le=50)
    langsmith_tracing: bool = False

    templates_root: Path = ROOT / "data/ocr/templates"
    admin_root: Path = ROOT / "data/ocr/admin"
    asset_root: Path = ROOT / "data/ocr/assets"
    projects_root: Path = ROOT / "data/ocr/projects"
    ocr_model_root: Path = ROOT / "data/ocr/models"

    @field_validator(
        "templates_root", "admin_root", "asset_root", "projects_root", "ocr_model_root"
    )
    @classmethod
    def resolve_ocr_path(cls, value: Path) -> Path:
        """相对路径始终以仓库根目录为基准，不受启动目录影响。"""
        return (ROOT / value.expanduser()).resolve()

    @model_validator(mode="after")
    def validate_context_budget(self) -> "Settings":
        if self.llm_max_tokens + self.llm_context_margin_tokens >= self.llm_context_tokens:
            raise ValueError("context must exceed output and margin token reservations")
        return self

    @field_validator("llm_base_url", "llm_fallback_base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname:
            raise ValueError("LLM_BASE_URL must be an HTTP(S) URL")
        if url.query or url.fragment or url.username or url.password:
            raise ValueError("LLM_BASE_URL must not contain credentials, query or fragment")
        return value.rstrip("/")
