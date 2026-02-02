from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    """Application configuration with Pydantic validation."""

    # OpenAI
    openai_api_key: str = Field(..., validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", validation_alias="OPENAI_MODEL")

    # LiveKit
    livekit_url: str = Field(default="ws://localhost:7880")
    livekit_api_key: str = Field(default="devkey")
    livekit_api_secret: str = Field(default="secret")

    # Database
    database_url: str = Field(default="sqlite+aiosqlite:///./data/dealership.db")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Voice
    whisper_model: str = Field(default="base")
    whisper_device: str = Field(default="cpu")
    piper_voice: str = Field(default="en_US-amy-medium")

    # App
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    # Background Tasks
    human_check_min_seconds: int = Field(default=15)
    human_check_max_seconds: int = Field(default=25)
    human_availability_chance: float = Field(default=0.6)

    # Session
    session_timeout_minutes: int = Field(default=30)
    max_turns: int = Field(default=50)

    # Email (optional - for callback notifications)
    smtp_host: str = Field(default="")
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    sales_email: str = Field(default="")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
