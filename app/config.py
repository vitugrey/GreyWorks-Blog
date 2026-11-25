from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    site_title: str = "GreyWorks Blog"
    site_url: str = "http://127.0.0.1:8000"
    site_description: str = (
        "Notas minimalistas sobre Tecnologia, cultura Geek e Off-Topic por Vitor Grey."
    )

    database_url: str = "sqlite:///./greyworks.db"

    secret_key: str = ""
    api_token: str = ""
    cookie_secure: bool = False
    allowed_origins: str = "http://127.0.0.1:8000,http://localhost:8000"

    session_ttl_hours: int = Field(default=8, ge=1, le=72)
    session_inactivity_minutes: int = Field(default=60, ge=5, le=480)
    view_dedup_seconds: int = Field(default=1800, ge=0, le=86400)
    max_markdown_upload_bytes: int = Field(default=2 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024)
    max_image_upload_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024)
    upload_dir: str = "uploads"

    admin_username: str = ""
    admin_password: str = ""

    @field_validator("site_url")
    @classmethod
    def normalize_site_url(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_secrets(self) -> Settings:
        if not self.secret_key:
            if self.app_env == "production":
                raise ValueError(
                    "SECRET_KEY deve ser configurado via variável de ambiente em produção."
                )
            self.secret_key = secrets.token_hex(32)
            logger.warning(
                "SECRET_KEY não definido; usando chave efêmera aleatória "
                "(não recomendada para produção ou múltiplas instâncias)."
            )
        elif len(self.secret_key) < 32 and self.app_env == "production":
            raise ValueError("SECRET_KEY deve ter ao menos 32 caracteres em produção.")

        if self.app_env == "production" and not self.cookie_secure:
            self.cookie_secure = True

        return self

    @property
    def cors_origins(self) -> list[str]:
        origins = [item.strip() for item in self.allowed_origins.split(",") if item.strip()]
        return [origin for origin in origins if origin != "*"]

    @property
    def session_cookie_name(self) -> str:
        # TODO(security): Em desenvolvimento local HTTP (cookie_secure=False),
        # navegadores recusam cookies com prefixo __Host-. Em produção HTTPS,
        # __Host- é obrigatório e ativado automaticamente.
        return "__Host-gw_session" if self.cookie_secure else "gw_session"

    @property
    def csrf_cookie_name(self) -> str:
        return "__Host-gw_csrf" if self.cookie_secure else "gw_csrf"


@lru_cache
def get_settings() -> Settings:
    return Settings()
