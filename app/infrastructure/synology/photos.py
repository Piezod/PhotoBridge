import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from app.domain.models.photos import (
    Photo,
    PhotoAlbum,
    PhotoFolder,
    PhotoMetadata,
    PhotoPage,
    PhotoSearchCriteria,
    PhotoSpace,
)
from app.domain.models.synology import ApiDescription
from app.infrastructure.synology.client import ApiRegistry, SynologyApiClient, SynologyClientError

PHOTO_API_PREFIX = "webapi"
MAX_PAGE_SIZE = 50


class SynologyPhotosClient:
    def __init__(
        self,
        client: SynologyApiClient,
        apis: ApiRegistry,
    ) -> None:
        self.client = client
        self.apis = apis

    def supports(self, api_name: str) -> bool:
        return api_name in self.apis

    async def list_photos(
        self,
        space: PhotoSpace,
        *,
        folder_id: int | None = None,
        offset: int = 0,
        limit: int = 50,
        criteria: PhotoSearchCriteria | None = None,
    ) -> PhotoPage:
        self._validate_pagination(offset, limit)
        if folder_id is not None and folder_id < 0:
            raise ValueError("El identificador de carpeta no puede ser negativo.")
        album_id = criteria.album_id if criteria is not None else None
        if album_id is not None and space != PhotoSpace.PERSONAL:
            raise ValueError(
                "El filtrado por álbum solo está disponible en el espacio personal."
            )
        if album_id is not None and (
            not str(album_id)
            or len(str(album_id)) > 128
            or any(ord(char) < 32 for char in str(album_id))
        ):
            raise ValueError("El identificador de álbum no es válido.")

        additional = json.dumps(
            [
                "thumbnail",
                "resolution",
                "orientation",
                "video_convert",
                "video_meta",
                "address",
            ]
        )
        if folder_id is not None or album_id is not None:
            api_name = self._api_name(space, "Browse.Item")
            params: dict[str, str] = {
                "offset": str(offset),
                "limit": str(limit),
                "sort_by": json.dumps("takentime"),
                "sort_direction": json.dumps("desc"),
                "additional": additional,
            }
            if folder_id is not None and album_id is None:
                params["folder_id"] = str(folder_id)
            if album_id is not None:
                params["album_id"] = str(album_id)
        else:
            api_name = self._api_name(space, "Browse.SimilarItem")
            start_time = (
                int(criteria.date_from.timestamp())
                if criteria is not None and criteria.date_from is not None
                else 0
            )
            end_time = (
                int(criteria.date_to.timestamp())
                if criteria is not None and criteria.date_to is not None
                else int(datetime.now(UTC).timestamp())
            )
            params = {
                "offset": str(offset),
                "limit": str(limit),
                "start_time": str(start_time),
                "end_time": str(end_time),
                "additional": additional,
            }
        data = await self._request(api_name, "list", params)
        rows = data.get("list", [])
        if not isinstance(rows, list):
            raise SynologyClientError(None, "Respuesta de biblioteca Synology Photos inválida.")
        items = [
            photo
            for row in rows
            if isinstance(row, dict)
            and (photo := self._parse_photo(row, space)) is not None
        ]
        if criteria is not None:
            items = [photo for photo in items if self._matches(photo, criteria)]
        return PhotoPage(items=items, offset=offset, limit=limit, has_more=len(rows) == limit)

    async def list_folders(
        self,
        space: PhotoSpace,
        *,
        folder_id: int | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[PhotoFolder], bool]:
        self._validate_pagination(offset, limit)
        api_name = self._api_name(space, "Browse.Folder")
        root_id = 0 if space == PhotoSpace.PERSONAL else 1
        params = {
            "id": str(root_id if folder_id is None else folder_id),
            "offset": str(offset),
            "limit": str(limit),
        }
        data = await self._request(api_name, "list", params)
        rows = data.get("list", [])
        if not isinstance(rows, list):
            raise SynologyClientError(None, "Respuesta de carpetas Synology Photos inválida.")
        folders = [
            PhotoFolder(
                folder_id=int(row["id"]),
                name=str(row["name"]),
                parent_id=self._optional_int(row.get("parent")),
                space=space,
            )
            for row in rows
            if isinstance(row, dict)
            and self._optional_int(row.get("id")) is not None
            and isinstance(row.get("name"), str)
        ]
        return folders, len(rows) == limit

    async def list_albums(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[PhotoAlbum], bool]:
        self._validate_pagination(offset, limit)
        api_name = "SYNO.Foto.Browse.Album"
        data = await self._request(
            api_name,
            "list",
            {"offset": str(offset), "limit": str(limit)},
        )
        rows = data.get("list", [])
        if not isinstance(rows, list):
            raise SynologyClientError(None, "Respuesta de álbumes Synology Photos inválida.")
        albums = [
            PhotoAlbum(
                album_id=str(row["id"]),
                name=str(row["name"]),
                item_count=int(row.get("item_count", 0)),
                owner_user_id=self._optional_int(row.get("owner_user_id")),
                created_at=self._timestamp(row.get("create_time")),
            )
            for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("id"), (int, str))
            and bool(str(row.get("id")))
            and isinstance(row.get("name"), str)
        ]
        return albums, len(rows) == limit

    async def stream_thumbnail(
        self,
        photo: Photo,
        *,
        size: str = "sm",
    ) -> tuple[str, AsyncGenerator[bytes, None]]:
        if size not in {"sm", "xl"}:
            raise ValueError("El tamaño de miniatura no está permitido.")
        self._require_api(self._api_name(photo.space, "Thumbnail"))
        if not photo.thumbnail_cache_key:
            raise SynologyClientError(
                None,
                "Synology Photos no anunció una miniatura para esta fotografía.",
                category="thumbnail_unavailable",
            )
        return await self.client.open_photo_thumbnail_stream(
            photo.item_id,
            photo.thumbnail_cache_key,
            size=size,
            team_space=photo.space == PhotoSpace.SHARED,
        )

    def stream_original(
        self, photo: Photo, *, album_id: str
    ) -> AsyncGenerator[bytes, None]:
        api = self._require_api(self._api_name(photo.space, "Download"))
        params = {
            "item_id": json.dumps([photo.item_id]),
            "album_id": album_id,
            "force_download": "true",
            "download_type": "source",
        }
        return self.client.stream_api_at(
            api,
            "download",
            params,
            endpoint_prefix=PHOTO_API_PREFIX,
            http_method="POST",
        )

    async def get_album(self, album_id: str) -> PhotoAlbum:
        if not album_id.isdecimal():
            raise ValueError("El identificador del álbum no es válido.")
        data = await self._request(
            "SYNO.Foto.Browse.Album", "get", {"id": json.dumps([int(album_id)])}
        )
        rows = data.get("list")
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise SynologyClientError(
                None, "El álbum no está disponible para esta cuenta.", category="album_unavailable"
            )
        row = rows[0]
        if str(row.get("id")) != album_id or not isinstance(row.get("name"), str):
            raise SynologyClientError(None, "Synology devolvió información de otro álbum.")
        return PhotoAlbum(
            album_id=album_id,
            name=row["name"],
            item_count=int(row.get("item_count", 0)),
            owner_user_id=self._optional_int(row.get("owner_user_id")),
            created_at=self._timestamp(row.get("create_time")),
        )

    async def _request(
        self,
        api_name: str,
        method: str,
        params: dict[str, str],
    ) -> dict[str, Any]:
        api = self._require_api(api_name)
        return await self.client.api_request_at(
            api,
            method,
            params,
            endpoint_prefix=PHOTO_API_PREFIX,
            http_method="POST",
        )

    def _require_api(self, api_name: str) -> ApiDescription:
        api = self.apis.get(api_name)
        if api is None:
            raise SynologyClientError(
                None,
                f"La API Synology Photos {api_name} no está disponible.",
                category="api_unavailable",
            )
        return api

    @staticmethod
    def _api_name(space: PhotoSpace, suffix: str) -> str:
        prefix = "SYNO.Foto" if space == PhotoSpace.PERSONAL else "SYNO.FotoTeam"
        return f"{prefix}.{suffix}"

    @classmethod
    def _parse_photo(cls, row: dict[str, Any], space: PhotoSpace) -> Photo | None:
        item_id = cls._optional_int(row.get("id"))
        folder_id = cls._optional_int(row.get("folder_id"))
        name = row.get("filename")
        size = cls._optional_int(row.get("filesize"))
        media_type = row.get("type")
        if (
            item_id is None
            or folder_id is None
            or not isinstance(name, str)
            or not name
            or size is None
            or size < 0
            or media_type not in {"photo", "video"}
        ):
            return None

        extension = PurePosixPath(name).suffix.lower().lstrip(".")
        additional = row.get("additional")
        additional = additional if isinstance(additional, dict) else {}
        thumbnail = additional.get("thumbnail")
        thumbnail = thumbnail if isinstance(thumbnail, dict) else {}
        resolution = additional.get("resolution")
        resolution = resolution if isinstance(resolution, dict) else {}
        exif = additional.get("exif")
        exif = exif if isinstance(exif, dict) else {}
        video_meta = additional.get("video_meta")
        video_meta = video_meta if isinstance(video_meta, dict) else {}
        duration = video_meta.get("duration")
        metadata = PhotoMetadata(
            captured_at=cls._timestamp(row.get("time")),
            width=cls._optional_int(resolution.get("width")),
            height=cls._optional_int(resolution.get("height")),
            orientation=cls._optional_int(additional.get("orientation")),
            duration_seconds=(
                float(duration)
                if isinstance(duration, (int, float)) and not isinstance(duration, bool)
                else None
            ),
            camera=exif.get("camera") if isinstance(exif.get("camera"), str) else None,
            description=(
                additional.get("description")
                if isinstance(additional.get("description"), str)
                else None
            ),
        )
        cache_key = thumbnail.get("cache_key")
        return Photo(
            photo_id=f"{space.value}:{item_id}",
            item_id=item_id,
            space=space,
            folder_id=folder_id,
            name=name,
            size=size,
            media_type=media_type,
            extension=extension,
            metadata=metadata,
            thumbnail_cache_key=cache_key if isinstance(cache_key, str) else None,
        )

    @staticmethod
    def _matches(photo: Photo, criteria: PhotoSearchCriteria) -> bool:
        if criteria.name and criteria.name.casefold() not in photo.name.casefold():
            return False
        if criteria.extension and photo.extension != criteria.extension.casefold().lstrip("."):
            return False
        if criteria.media_type and photo.media_type != criteria.media_type:
            return False
        captured_at = photo.metadata.captured_at
        if criteria.date_from and (captured_at is None or captured_at < criteria.date_from):
            return False
        if criteria.date_to and (captured_at is None or captured_at > criteria.date_to):
            return False
        return True

    @staticmethod
    def _validate_pagination(offset: int, limit: int) -> None:
        if offset < 0 or limit < 1 or limit > MAX_PAGE_SIZE:
            raise SynologyClientError(
                None,
                "La paginación de Synology Photos admite como máximo 50 elementos.",
                category="invalid_pagination",
            )

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @staticmethod
    def _timestamp(value: Any) -> datetime | None:
        if not isinstance(value, (int, float)):
            return None
        try:
            seconds = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
