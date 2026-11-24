from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PHOTOBRIDGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "PhotoBridge"
    test_mode: Literal[True] = True
    max_photos_per_test: int = Field(default=10, ge=1, le=10)
    delete_originals: Literal[False] = False
    manual_confirmation_required: Literal[True] = True
    automatic_migrations: Literal[False] = False
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)


@lru_cache
def get_settings() -> Settings:
    return Settings()

