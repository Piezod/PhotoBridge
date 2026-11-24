import asyncio
import hashlib
import ipaddress
import re
import time
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit, urlunsplit
from uuid import uuid4

import httpx
from keyring.errors import KeyringError

from app.config import Settings
from app.domain.models.photos import (
    Photo,
    PhotoAlbum,
    PhotoFolder,
    PhotoPage,
    PhotoSearchCriteria,
    PhotoSpace,
)
from app.domain.models.synology import RemoteFile
from app.domain.ports.credential_store import CredentialStore
from app.infrastructure.synology.client import (
    QUICKCONNECT_HOSTS,
    ClientFactory,
    SynologyApiClient,
    SynologyClientError,
)
from app.infrastructure.synology.photos import SynologyPhotosClient

PHOTO_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "heic", "webp"})
VIDEO_EXTENSIONS = frozenset(
    {"3gp", "avi", "m4v", "mkv", "mov", "mp4", "mpeg", "mpg", "mts", "ts", "webm", "wmv"}
)


@dataclass(frozen=True)
class ConnectionDiagnostic:
    connection_id: str
    name: str
    server_url: str
    quickconnect: bool
    authenticated: bool
    list_api_available: bool
    download_api_available: bool
    thumbnail_api_available: bool
    read_access: bool
    read_message: str
    latency_ms: int
    photos_api_available: bool
    photos_personal_space_accessible: bool
    photos_shared_space_accessible: bool
    photos_albums_available: bool
    photos_thumbnail_available: bool
    photos_download_available: bool
    photos_message: str


@dataclass
class SynologyConnection:
    diagnostic: ConnectionDiagnostic
    username: str
    client: SynologyApiClient
    known_files: dict[str, RemoteFile]
    selected_paths: set[str]
    lock: asyncio.Lock
    photos_client: SynologyPhotosClient | None
    known_photos: dict[str, Photo]
    selected_photo_ids: set[str]


class SynologyConnectionService:
    def __init__(
        self,
        settings: Settings,
        credential_store: CredentialStore,
        *,
        client_factory: ClientFactory = httpx.AsyncClient,
    ) -> None:
        self.settings = settings
        self.credential_store = credential_store
        self.client_factory = client_factory
        self.connections: dict[str, SynologyConnection] = {}

    async def connect(
        self,
        *,
        name: str,
        server_url: str,
        username: str,
        password: str,
        otp_code: str | None = None,
        remember_password: bool = False,
    ) -> ConnectionDiagnostic:
        normalized_url, quickconnect = self.validate_server_url(server_url)
        if not name.strip() or not username.strip():
            raise SynologyClientError(
                None, "El nombre y el usuario son obligatorios.", category="input"
            )

        credential_key = self.credential_key(normalized_url, username)
        verify = self.settings.tls_verify()
        client = SynologyApiClient(
            normalized_url,
            timeout=self.settings.synology_timeout_seconds,
            verify=verify,
            client_factory=self.client_factory,
            quickconnect=quickconnect,
        )
        await client.open()
        started = time.monotonic()
        photos_apis = {}
        photos_message = "Synology Photos no anuncia sus APIs."
        try:
            if quickconnect:
                await client.resolve_quickconnect_alias()
            await client.discover()
            try:
                photos_apis = await client.discover_photos()
                photos_message = (
                    "APIs de Synology Photos anunciadas."
                    if any(
                        name.startswith(("SYNO.Foto.", "SYNO.FotoTeam."))
                        for name in photos_apis
                    )
                    else "Se comprobará el acceso de solo lectura a Synology Photos."
                )
            except SynologyClientError as exc:
                photos_message = str(exc)
            has_filestation = {
                "SYNO.FileStation.List",
                "SYNO.FileStation.Download",
            }.issubset(client.apis)
            has_photos = bool(
                {
                    "SYNO.Foto.Browse.Item",
                    "SYNO.Foto.Browse.SimilarItem",
                    "SYNO.FotoTeam.Browse.Item",
                    "SYNO.FotoTeam.Browse.SimilarItem",
                }
                & photos_apis.keys()
            )
            missing_auth = "SYNO.API.Auth" not in client.apis
            if missing_auth or not (has_filestation or has_photos):
                if quickconnect:
                    raise SynologyClientError(
                        None,
                        "El endpoint QuickConnect no anuncia las APIs necesarias "
                        "para autenticación y para al menos un explorador compatible.",
                        category="quickconnect_api_unavailable",
                    )
                raise SynologyClientError(
                    None,
                    "El servidor debe anunciar SYNO.API.Auth y las APIs de File Station "
                    "o Synology Photos.",
                    category="api_unavailable",
                )
            if not password:
                try:
                    password = (
                        await asyncio.to_thread(
                            self.credential_store.get_password,
                            credential_key,
                        )
                        or ""
                    )
                except (KeyringError, RuntimeError, ValueError, OSError) as exc:
                    raise SynologyClientError(
                        None,
                        "No se pudo acceder al almacén seguro de credenciales del sistema.",
                        category="credential_store",
                    ) from exc
            if not password:
                raise SynologyClientError(
                    None,
                    "Introduce la contraseña o utiliza una guardada en el almacén seguro.",
                    category="credential_required",
                )
            await client.login(username, password, otp_code)
            if remember_password:
                try:
                    await asyncio.to_thread(
                        self.credential_store.set_password,
                        credential_key,
                        password,
                    )
                except (KeyringError, RuntimeError, ValueError, OSError) as exc:
                    await client.logout()
                    raise SynologyClientError(
                        None,
                        "No se pudo guardar la contraseña en el almacén seguro del sistema.",
                        category="credential_store",
                    ) from exc
            read_access = False
            read_message = "No se pudo verificar el permiso de lectura."
            if "SYNO.FileStation.List" in client.apis:
                try:
                    shares = await client.list_shares(limit=50)
                    if shares:
                        await client.list_directory(shares[0].path, limit=1)
                        read_access = True
                        read_message = "Permisos de lectura comprobados."
                    else:
                        read_message = "La cuenta no tiene carpetas compartidas visibles."
                except SynologyClientError as exc:
                    read_message = exc.args[0]
            else:
                read_message = "La API de listado de File Station no está disponible."
            photos_client = SynologyPhotosClient(client, photos_apis)
            photos_personal_accessible = False
            photos_shared_accessible = False
            photos_albums_available = False
            photos_thumbnail_available = False
            personal_page = None
            if photos_client.supports("SYNO.Foto.Browse.SimilarItem"):
                try:
                    personal_page = await photos_client.list_photos(
                        PhotoSpace.PERSONAL,
                        limit=1,
                    )
                    photos_personal_accessible = True
                    photos_message = (
                        "La biblioteca personal es accesible. "
                        "La descarga de originales no está validada."
                    )
                except SynologyClientError as exc:
                    photos_message = f"Espacio personal: {exc}"
            if photos_client.supports("SYNO.FotoTeam.Browse.SimilarItem"):
                try:
                    await photos_client.list_photos(PhotoSpace.SHARED, limit=1)
                    photos_shared_accessible = True
                    if not photos_personal_accessible:
                        photos_message = "El espacio compartido de Synology Photos es accesible."
                except SynologyClientError as exc:
                    if not photos_personal_accessible:
                        photos_message = f"Espacio compartido: {exc}"
            if photos_client.supports("SYNO.Foto.Browse.Album"):
                try:
                    await photos_client.list_albums(limit=1)
                    photos_albums_available = True
                except SynologyClientError as exc:
                    photos_message = f"{photos_message} Álbumes: {exc}"
            if (
                personal_page is not None
                and personal_page.items
                and personal_page.items[0].thumbnail_cache_key
                and photos_client.supports("SYNO.Foto.Thumbnail")
            ):
                chunks = None
                try:
                    content_type, chunks = await photos_client.stream_thumbnail(
                        personal_page.items[0],
                        size="sm",
                    )
                    first_chunk = await anext(chunks, None)
                    if not content_type.startswith("image/") or not first_chunk:
                        raise SynologyClientError(
                            None,
                            "La miniatura no contiene una imagen.",
                            category="thumbnail_unavailable",
                        )
                    photos_thumbnail_available = True
                except SynologyClientError as exc:
                    photos_message = f"{photos_message} Miniaturas: {exc}"
                finally:
                    if chunks is not None:
                        await chunks.aclose()
            photos_api_available = (
                photos_personal_accessible or photos_shared_accessible
            )
            if not has_filestation and not photos_api_available:
                raise SynologyClientError(
                    None,
                    "No se pudo confirmar acceso de lectura a File Station ni "
                    "a Synology Photos.",
                    category="read_access",
                )
            diagnostic = ConnectionDiagnostic(
                connection_id=uuid4().hex,
                name=name.strip(),
                server_url=client.server_url.rstrip("/"),
                quickconnect=quickconnect,
                authenticated=client.authenticated,
                list_api_available="SYNO.FileStation.List" in client.apis,
                download_api_available="SYNO.FileStation.Download" in client.apis,
                thumbnail_api_available="SYNO.FileStation.Thumb" in client.apis,
                read_access=read_access,
                read_message=read_message,
                latency_ms=round((time.monotonic() - started) * 1000),
                photos_api_available=photos_api_available,
                photos_personal_space_accessible=photos_personal_accessible,
                photos_shared_space_accessible=photos_shared_accessible,
                photos_albums_available=photos_albums_available,
                photos_thumbnail_available=photos_thumbnail_available,
                photos_download_available=False,
                photos_message=photos_message,
            )
            self.connections[diagnostic.connection_id] = SynologyConnection(
                diagnostic=diagnostic,
                username=username,
                client=client,
                known_files={},
                selected_paths=set(),
                lock=asyncio.Lock(),
                photos_client=photos_client if photos_apis else None,
                known_photos={},
                selected_photo_ids=set(),
            )
            return diagnostic
        except (SynologyClientError, httpx.InvalidURL, ValueError):
            await client.close()
            raise

    async def disconnect(self, connection_id: str) -> None:
        connection = self.get_connection(connection_id)
        try:
            await connection.client.logout()
        finally:
            await connection.client.close()
            self.connections.pop(connection_id, None)

    async def disconnect_all(self) -> list[SynologyClientError]:
        errors: list[SynologyClientError] = []
        for connection_id in list(self.connections):
            try:
                await self.disconnect(connection_id)
            except SynologyClientError as exc:
                errors.append(exc)
        return errors

    def get_connection(self, connection_id: str) -> SynologyConnection:
        connection = self.connections.get(connection_id)
        if connection is None:
            raise SynologyClientError(
                None,
                "La sesión Synology no está disponible.",
                category="session_expired",
            )
        return connection

    async def list_shares(self, connection_id: str, offset: int = 0) -> list[RemoteFile]:
        self._validate_pagination(offset, 50)
        connection = self.get_connection(connection_id)
        async with connection.lock:
            shares = await connection.client.list_shares(offset=offset, limit=50)
        connection.known_files.update({share.path: share for share in shares})
        return shares

    async def list_directory(
        self,
        connection_id: str,
        path: str,
        *,
        offset: int = 0,
        limit: int = 50,
        extensions: set[str] | None = None,
    ) -> tuple[list[RemoteFile], bool]:
        self._validate_pagination(offset, limit)
        connection = self.get_connection(connection_id)
        async with connection.lock:
            files, has_more = await connection.client.list_directory(
                path,
                offset=offset,
                limit=limit,
            )
        filtered = [
            item
            for item in files
            if item.is_directory
            or item.extension in PHOTO_EXTENSIONS
            and (extensions is None or item.extension in extensions)
        ]
        connection.known_files.update({item.path: item for item in files if not item.is_directory})
        return filtered, has_more

    async def get_file_info(self, connection_id: str, path: str) -> RemoteFile:
        connection = self.get_connection(connection_id)
        async with connection.lock:
            return await connection.client.get_file_info(path)

    async def list_photos(
        self,
        connection_id: str,
        space: PhotoSpace,
        *,
        folder_id: int | None = None,
        offset: int = 0,
        limit: int = 50,
        criteria: PhotoSearchCriteria | None = None,
    ) -> PhotoPage:
        connection = self.get_connection(connection_id)
        if connection.photos_client is None:
            raise SynologyClientError(
                None,
                "Synology Photos no está disponible para esta conexión.",
                category="api_unavailable",
            )
        async with connection.lock:
            page = await connection.photos_client.list_photos(
                space,
                folder_id=folder_id,
                offset=offset,
                limit=limit,
                criteria=criteria,
            )
        connection.known_photos.update({photo.photo_id: photo for photo in page.items})
        return page

    async def list_photo_folders(
        self,
        connection_id: str,
        space: PhotoSpace,
        *,
        folder_id: int | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[PhotoFolder], bool]:
        connection = self.get_connection(connection_id)
        if connection.photos_client is None:
            raise SynologyClientError(
                None, "Synology Photos no está disponible.", category="api_unavailable"
            )
        async with connection.lock:
            return await connection.photos_client.list_folders(
                space,
                folder_id=folder_id,
                offset=offset,
                limit=limit,
            )

    async def list_photo_albums(
        self,
        connection_id: str,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[PhotoAlbum], bool]:
        connection = self.get_connection(connection_id)
        if connection.photos_client is None:
            raise SynologyClientError(
                None, "Synology Photos no está disponible.", category="api_unavailable"
            )
        async with connection.lock:
            return await connection.photos_client.list_albums(offset=offset, limit=limit)

    def update_photo_selection(
        self,
        connection_id: str,
        photo_id: str,
        *,
        selected: bool,
    ) -> tuple[int, int]:
        connection = self.get_connection(connection_id)
        photo = connection.known_photos.get(photo_id)
        if photo is None:
            raise SynologyClientError(
                None,
                "El elemento multimedia ya no está en la página disponible.",
                category="invalid_selection",
            )
        if selected and not connection.diagnostic.photos_download_available:
            raise SynologyClientError(
                None,
                "La descarga de originales de Synology Photos no está validada.",
                category="download_unavailable",
            )
        if photo.media_type != "photo" or photo.extension not in PHOTO_EXTENSIONS:
            raise SynologyClientError(
                None,
                "Solo se pueden seleccionar fotografías en formatos descargables.",
                category="invalid_selection",
            )
        if selected:
            candidate = connection.selected_photo_ids | {photo_id}
            total = sum(
                connection.known_photos[item].size
                for item in candidate
                if item in connection.known_photos
            )
            if len(candidate) > self.settings.synology_max_photos_per_operation:
                raise SynologyClientError(
                    None,
                    "El modo de prueba permite seleccionar hasta 10 fotografías.",
                    category="test_limit",
                )
            if total > self.settings.synology_max_operation_bytes:
                raise SynologyClientError(
                    None,
                    "La selección supera el límite de 250 MB por operación.",
                    category="size_limit",
                )
            connection.selected_photo_ids = candidate
        else:
            connection.selected_photo_ids.discard(photo_id)
        return self.photo_selection_summary(connection_id)

    def photo_selection_summary(self, connection_id: str) -> tuple[int, int]:
        connection = self.get_connection(connection_id)
        return len(connection.selected_photo_ids), sum(
            connection.known_photos[photo_id].size
            for photo_id in connection.selected_photo_ids
            if photo_id in connection.known_photos
        )

    def get_selected_photos(self, connection_id: str) -> list[Photo]:
        connection = self.get_connection(connection_id)
        return [
            connection.known_photos[photo_id]
            for photo_id in sorted(connection.selected_photo_ids)
            if photo_id in connection.known_photos
        ]

    def update_selection(
        self,
        connection_id: str,
        path: str,
        *,
        selected: bool,
    ) -> tuple[int, int]:
        connection = self.get_connection(connection_id)
        remote_file = connection.known_files.get(path)
        if remote_file is None or remote_file.is_directory:
            raise SynologyClientError(
                None,
                "El archivo ya no está en la lista disponible.",
                category="invalid_selection",
            )
        if remote_file.extension not in PHOTO_EXTENSIONS or remote_file.size is None:
            raise SynologyClientError(
                None,
                "Solo se pueden seleccionar fotografías permitidas con tamaño conocido.",
                category="invalid_selection",
            )
        if selected:
            candidate = connection.selected_paths | {path}
            total = sum(
                connection.known_files[item].size or 0
                for item in candidate
                if item in connection.known_files
            )
            if len(candidate) > self.settings.synology_max_photos_per_operation:
                raise SynologyClientError(
                    None,
                    "El modo de prueba permite seleccionar hasta 10 fotografías.",
                    category="test_limit",
                )
            if total > self.settings.synology_max_operation_bytes:
                raise SynologyClientError(
                    None,
                    "La selección supera el límite de 250 MB por operación.",
                    category="size_limit",
                )
            connection.selected_paths = candidate
        else:
            connection.selected_paths.discard(path)
        return self.selection_summary(connection_id)

    def selection_summary(self, connection_id: str) -> tuple[int, int]:
        connection = self.get_connection(connection_id)
        total_size = sum(
            connection.known_files[path].size or 0
            for path in connection.selected_paths
            if path in connection.known_files
        )
        return len(connection.selected_paths), total_size

    @staticmethod
    def validate_server_url(value: str) -> tuple[str, bool]:
        if len(value) > 2048:
            raise SynologyClientError(
                None, "La URL del servidor supera la longitud permitida.", category="invalid_url"
            )
        try:
            parts = urlsplit(value.strip())
            hostname = parts.hostname
            port = parts.port
        except ValueError as exc:
            raise SynologyClientError(
                None, "La URL del servidor no es válida.", category="invalid_url"
            ) from exc
        if parts.scheme != "https" or not hostname:
            raise SynologyClientError(
                None,
                "Utiliza HTTPS con dominio o dirección IP accesible.",
                category="invalid_url",
            )
        if parts.username or parts.password or parts.query or parts.fragment:
            raise SynologyClientError(
                None,
                "La URL no puede incluir credenciales, parámetros ni fragmentos.",
                category="invalid_url",
            )
        decoded_path = unquote(parts.path)
        if (
            "\\" in decoded_path
            or any(ord(character) < 32 for character in decoded_path)
            or any(segment in {".", ".."} for segment in decoded_path.split("/"))
        ):
            raise SynologyClientError(
                None, "La ruta base de la URL no es válida.", category="invalid_url"
            )
        try:
            normalized_host = ipaddress.ip_address(hostname).compressed
        except ValueError:
            try:
                normalized_host = hostname.encode("idna").decode("ascii").lower().rstrip(".")
            except UnicodeError:
                raise SynologyClientError(
                    None,
                    "El dominio del servidor no es válido.",
                    category="invalid_url",
                ) from None
            labels = normalized_host.split(".")
            if len(normalized_host) > 253 or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
            ):
                raise SynologyClientError(
                    None,
                    "El dominio del servidor no es válido.",
                    category="invalid_url",
                ) from None
        if not normalized_host:
            raise SynologyClientError(
                None, "El dominio del servidor no es válido.", category="invalid_url"
            )
        quickconnect = normalized_host in QUICKCONNECT_HOSTS or any(
            normalized_host.endswith(f".{host}") for host in QUICKCONNECT_HOSTS
        )
        netloc = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
        if port is not None:
            netloc = f"{netloc}:{port}"
        normalized = urlunsplit((parts.scheme.lower(), netloc, parts.path.rstrip("/"), "", ""))
        return normalized, quickconnect

    @staticmethod
    def credential_key(server_url: str, username: str) -> str:
        digest = hashlib.sha256(f"{server_url.casefold()}|{username}".encode()).hexdigest()
        return f"synology-{digest}"

    @staticmethod
    def _validate_pagination(offset: int, limit: int) -> None:
        if offset < 0 or limit < 1 or limit > 50:
            raise SynologyClientError(
                None,
                "La paginación requiere offset no negativo y un máximo de 50 elementos.",
                category="invalid_pagination",
            )
