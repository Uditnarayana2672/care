from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../../.env"), extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./carebridge.db"
    redis_url: str = ""
    hindsight_base_url: str = "https://api.hindsight.vectorize.io"
    hindsight_api_key: str = ""
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_fallback_model: str = "qwen/qwen3-32b"
    jwt_secret: str = "change-me"
    org_slug: str = "demo"
    cors_origins: str = "http://localhost:3000"
    memory_enabled: bool = True
    app_tz: str = "Asia/Kolkata"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.app_tz)


@lru_cache
def get_settings() -> Settings:
    return Settings()
