from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_base_url: str = Field(default="https://9c01-217-217-247-31.ngrok-free.app ", alias="APP_BASE_URL")
    livekit_url: str = Field(default="ws://livekit:7880", alias="LIVEKIT_URL")
    livekit_public_url: str = Field(default="ws://localhost:18080", alias="LIVEKIT_PUBLIC_URL")
    livekit_api_key: str = Field(default="devkey", alias="LIVEKIT_API_KEY")
    livekit_api_secret: str = Field(default="secret", alias="LIVEKIT_API_SECRET")
    call_token_ttl_hours: int = Field(default=2, alias="CALL_TOKEN_TTL_HOURS")
    room_empty_timeout_seconds: int = Field(default=600, alias="ROOM_EMPTY_TIMEOUT_SECONDS")
    max_attachment_size_mb: int = Field(default=100, alias="MAX_ATTACHMENT_SIZE_MB")
    uploads_dir: str = Field(default="uploads", alias="UPLOADS_DIR")
    telegram_alerting_enabled: bool = Field(default=False, alias="TELEGRAM_ALERTING_ENABLED")
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    telegram_topic_id: int | None = Field(default=None, alias="TELEGRAM_TOPIC_ID")
    block_probe_paths: bool = Field(default=True, alias="BLOCK_PROBE_PATHS")

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    @property
    def max_attachment_size_bytes(self) -> int:
        return self.max_attachment_size_mb * 1024 * 1024

    @property
    def uploads_path(self) -> Path:
        return Path(self.uploads_dir)

    @property
    def telegram_alerting_available(self) -> bool:
        return bool(self.telegram_alerting_enabled and self.telegram_bot_token.strip() and self.telegram_chat_id.strip())

    @property
    def cors_origins(self) -> list[str]:
        raw = getattr(self, 'cors_allow_origins', '')
        return [origin.strip() for origin in raw.split(',') if origin.strip()]


settings = Settings()
