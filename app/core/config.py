import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    gemini_api_key: str
    elevenlabs_api_key: str
    heygen_api_key: str
    deepgram_api_key: str = ""
    anthropic_api_key: str = ""
    submagic_api_key: str = ""
    creatomate_api_key: str = ""
    pexels_api_key: str = ""
    pixabay_api_key: str = ""
    runway_api_key: str = ""
    luma_api_key: str = ""
    admin_password: str = "Sergey"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
