import ssl
from functools import lru_cache
from pathlib import Path
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
    synology_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    synology_max_photos_per_operation: int = Field(default=10, ge=1, le=10)
    synology_max_operation_bytes: int = Field(
        default=250_000_000,
        ge=1,
        le=250_000_000,
    )
    synology_download_directory: Path = Path("data/downloads")
    synology_ca_bundle: Path | None = None
    synology_default_name: str = Field(default="", max_length=80)
    synology_default_server_url: str = Field(default="", max_length=2048)
    synology_default_username: str = Field(default="", max_length=255)

    def tls_verify(self) -> bool | ssl.SSLContext:
        if self.synology_ca_bundle is None:
            return True
        if not self.synology_ca_bundle.is_file():
            raise ValueError("El archivo CA configurado no existe o no es un archivo.")
        return ssl.create_default_context(cafile=str(self.synology_ca_bundle))


@lru_cache
def get_settings() -> Settings:
    return Settings()
