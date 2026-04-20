import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    gemini_api_key: str
    elevenlabs_api_key: str
    heygen_api_key: str
    deepgram_api_key: str = ""
    admin_password: str = "Sergey"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
