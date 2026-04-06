"""Application configuration via pydantic-settings.

Reads from .env file and environment variables.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """MedBuddy application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # --- Google / Gemini ---
    GOOGLE_API_KEY: str
    GOOGLE_AI_DEFAULT_MODEL: str = "gemini-2.5-pro"
    GOOGLE_AI_FAST_MODEL: str = "gemini-2.5-flash"

    # Google Search (drug info lookups)
    GOOGLE_CSE_ID: str = ""
    GOOGLE_SEARCH_API_KEY: str = ""
    GOOGLE_SEARCH_ENGINE_ID: str = ""

    # --- LINE Messaging API ---
    LINE_CHANNEL_SECRET: str
    LINE_CHANNEL_ACCESS_TOKEN: str

    # --- Database ---
    DATABASE_URL: str = "postgresql+asyncpg://medbuddy:medbuddy@localhost:5432/medbuddy"

    # --- OpenAI (Whisper STT fallback) ---
    OPENAI_API_KEY: str = ""

    # --- Google Cloud (optional, not used in current stack) ---
    GOOGLE_CLOUD_PROJECT: str = ""
    GOOGLE_APPLICATION_CREDENTIALS: str = ""

    # --- Encryption ---
    AES_ENCRYPTION_KEY: str = ""  # 32-byte hex string for AES-256

    # --- App ---
    APP_ENV: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # --- Rate Limiting ---
    RATE_LIMIT_PER_USER: int = 10  # AI requests per minute per LINE user

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.APP_ENV == "production"

    @property
    def database_url_sync(self) -> str:
        """Synchronous database URL for Alembic migrations."""
        return self.DATABASE_URL.replace("+asyncpg", "")


settings = Settings()
