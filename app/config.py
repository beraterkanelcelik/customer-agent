from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    """Application configuration with Pydantic validation."""

    # OpenAI
    openai_api_key: str = Field(..., validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", validation_alias="OPENAI_MODEL")

    # Database
    database_url: str = Field(default="sqlite+aiosqlite:///./data/dealership.db")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # App
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    # Background Tasks
    human_check_min_seconds: int = Field(default=15)
    human_check_max_seconds: int = Field(default=25)
    human_availability_chance: float = Field(default=0.6)

    # Sales handoff
    sales_connection_delay_seconds: float = Field(
        default=10.0,
        description="Delay before sales can connect (gives time for agent to speak handoff message)"
    )

    # Session
    session_timeout_minutes: int = Field(default=30)
    max_turns: int = Field(default=50)

    # Email (optional - for callback notifications)
    smtp_host: str = Field(default="")
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    sales_email: str = Field(default="")

    # Twilio Voice (for phone conversations and escalation)
    twilio_account_sid: str = Field(default="")
    twilio_auth_token: str = Field(default="")
    twilio_phone_number: str = Field(default="")  # Your Twilio number (E.164 format)
    twilio_webhook_base_url: str = Field(default="")  # Public URL for webhooks (e.g., ngrok)
    customer_service_phone: str = Field(default="")  # Human agent number (E.164 format)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
