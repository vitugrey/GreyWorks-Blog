from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CategoryEnum(StrEnum):
    TECNOLOGIA = "tecnologia"
    GEEK = "geek"
    OFF_TOPIC = "off-topic"


CATEGORY_METADATA: dict[str, dict[str, str]] = {
    CategoryEnum.TECNOLOGIA.value: {
        "name": "Tecnologia",
        "short": "Tec",
        "description": "Engenharia de software, infraestrutura, Docker, IA aplicada e arquitetura de sistemas.",
    },
    CategoryEnum.GEEK.value: {
        "name": "Geek",
        "short": "Geek",
        "description": "Games, retrocomputação, cinema, livros, hardware curioso e cultura nerd.",
    },
    CategoryEnum.OFF_TOPIC.value: {
        "name": "Off-Topic",
        "short": "Off-Topic",
        "description": "Reflexões soltas, produtividade, bastidores, processos criativos e assuntos fora da caixa.",
    },
}


def slugify(value: str, max_length: int = 180) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.lower()).strip("-")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned[:max_length].strip("-") or "post"


def normalize_tag_list(raw_tags: list[str] | str) -> list[str]:
    if isinstance(raw_tags, str):
        parts = re.split(r"[,;\s]+", raw_tags)
    else:
        parts = raw_tags

    seen: set[str] = set()
    result: list[str] = []
    for item in parts:
        token = item.strip().lstrip("#").lower()
        if not token:
            continue
        slug = slugify(token, max_length=48)
        if slug and slug not in seen:
            seen.add(slug)
            result.append(slug)
        if len(result) >= 12:
            break
    return result


class TagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str


class PostCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    slug: str | None = Field(default=None, max_length=220)
    summary: str = Field(default="", max_length=420)
    category: CategoryEnum
    content_md: str = Field(..., min_length=1, max_length=500_000)
    tags: list[str] = Field(default_factory=list)
    is_published: bool = True
    published_at: datetime | None = None

    @field_validator("title", "summary")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return slugify(value)

    @field_validator("tags", mode="before")
    @classmethod
    def validate_tags(cls, value: list[str] | str | None) -> list[str]:
        if value is None:
            return []
        return normalize_tag_list(value)

    @field_validator("published_at")
    @classmethod
    def ensure_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class PostUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    slug: str | None = Field(default=None, max_length=220)
    summary: str | None = Field(default=None, max_length=420)
    category: CategoryEnum | None = None
    content_md: str | None = Field(default=None, min_length=1, max_length=500_000)
    tags: list[str] | None = None
    is_published: bool | None = None
    published_at: datetime | None = None

    @field_validator("title", "summary")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return slugify(value)

    @field_validator("tags", mode="before")
    @classmethod
    def validate_tags(cls, value: list[str] | str | None) -> list[str] | None:
        if value is None:
            return None
        return normalize_tag_list(value)

    @field_validator("published_at")
    @classmethod
    def ensure_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class PostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    slug: str
    summary: str
    category: str
    content_md: str
    reading_time_min: int
    views: int
    is_published: bool
    published_at: datetime
    created_at: datetime
    updated_at: datetime
    tags: list[TagRead]


class PostListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    slug: str
    summary: str
    category: str
    reading_time_min: int
    views: int
    is_published: bool
    published_at: datetime
    tags: list[TagRead]
