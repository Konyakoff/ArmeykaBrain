import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    gemini_api_key: str
    elevenlabs_api_key: str
    heygen_api_key: str
    
    # Можно добавить и другие настройки, например:
    # app_env: str = "production"
    # log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
