from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PhotoSpace(StrEnum):
    PERSONAL = "personal"
    SHARED = "shared"


@dataclass(frozen=True)
class PhotoMetadata:
    captured_at: datetime | None = None
    width: int | None = None
    height: int | None = None
    orientation: int | None = None
    duration_seconds: float | None = None
    camera: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class Photo:
    photo_id: str
    item_id: int
    space: PhotoSpace
    folder_id: int
    name: str
    size: int
    media_type: str
    extension: str
    metadata: PhotoMetadata
    thumbnail_cache_key: str | None = None


@dataclass(frozen=True)
class PhotoAlbum:
    album_id: str
    name: str
    item_count: int
    owner_user_id: int | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class PhotoFolder:
    folder_id: int
    name: str
    parent_id: int | None
    space: PhotoSpace


@dataclass(frozen=True)
class PhotoSpaceInfo:
    space: PhotoSpace
    accessible: bool


@dataclass(frozen=True)
class PhotoSearchCriteria:
    name: str | None = None
    extension: str | None = None
    media_type: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    album_id: str | int | None = None


@dataclass(frozen=True)
class PhotoPage:
    items: list[Photo]
    offset: int
    limit: int
    has_more: bool
