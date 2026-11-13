"""Environment-backed configuration for the local application."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    data_dir: Path = ROOT_DIR / "data"
    openai_api_key: str = ""
    openai_model: str = ""
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    run_timeout_seconds: float = 120

    @property
    def llm_configured(self) -> bool:
        return bool(self.openai_api_key.strip() and self.openai_model.strip())

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
