"""Environment-backed configuration for the local application."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    data_dir: Path = ROOT_DIR / "data"
    openai_api_key: str = ""
    openai_model: str = ""
    openai_max_output_tokens: int = Field(default=4096, ge=1, le=128000)
    openai_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = "low"
    openai_max_retries: int = Field(default=0, ge=0, le=3)
    openai_timeout_seconds: float = Field(default=60, gt=0, le=600)
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    run_timeout_seconds: float = Field(default=120, gt=0, le=600)

    @property
    def llm_configured(self) -> bool:
        return bool(self.openai_api_key.strip() and self.openai_model.strip())

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
