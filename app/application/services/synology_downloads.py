import asyncio
import hashlib
import json
import os
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol
from uuid import uuid4

from app.application.services.synology_connections import (
    PHOTO_EXTENSIONS,
    SynologyConnectionService,
)
from app.config import Settings
from app.domain.models.photos import Photo, PhotoAlbum, PhotoSpace
from app.domain.models.synology import (
    DownloadItem,
    DownloadOperation,
    DownloadState,
    RemoteFile,
)
from app.infrastructure.synology.client import SynologyClientError

WINDOWS_INVALID = re.compile(r'[<>:"|?*\x00-\x1f]')
WINDOWS_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.IGNORECASE)


class _HashDigest(Protocol):
    def update(self, data: bytes, /) -> None: ...

    def hexdigest(self) -> str: ...


class DownloadValidationError(ValueError):
    pass


class SynologyDownloadService:
    def __init__(
        self,
        settings: Settings,
        connections: SynologyConnectionService,
    ) -> None:
        self.settings = settings
        self.connections = connections
        self.operations: dict[str, DownloadOperation] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._active_operation: str | None = None
        self._start_lock = asyncio.Lock()

    async def start_operation(
        self, connection_id: str, paths: list[str], *, confirmed: bool
    ) -> DownloadOperation:
        if self._start_lock.locked():
            raise DownloadValidationError("Ya se está preparando una descarga.")
        async with self._start_lock:
            return await self._start_file_operation(connection_id, paths, confirmed=confirmed)

    async def _start_file_operation(
        self,
        connection_id: str,
        paths: list[str],
        *,
        confirmed: bool,
    ) -> DownloadOperation:
        if not self.settings.manual_confirmation_required or not confirmed:
            raise DownloadValidationError(
                "Debes confirmar manualmente la descarga de los archivos seleccionados."
            )
        if not paths:
            raise DownloadValidationError("Selecciona al menos una fotografía.")
        if len(paths) > self.settings.synology_max_photos_per_operation:
            raise DownloadValidationError(
                f"El modo de prueba permite como máximo "
                f"{self.settings.synology_max_photos_per_operation} fotografías por operación."
            )
        if len(set(paths)) != len(paths):
            raise DownloadValidationError("La selección contiene rutas duplicadas.")
        if self._active_operation is not None:
            raise DownloadValidationError("Ya hay una operación de descarga en curso.")

        connection = self.connections.get_connection(connection_id)
        selected: list[RemoteFile] = []
        for path in paths:
            self._validate_remote_file_path(path)
            remote_file = connection.known_files.get(path)
            if remote_file is None or remote_file.is_directory:
                raise DownloadValidationError(
                    "La selección contiene un archivo no listado o que ya no está disponible."
                )
            if remote_file.extension not in PHOTO_EXTENSIONS:
                raise DownloadValidationError("La selección contiene un formato no permitido.")
            if remote_file.size is None:
                raise DownloadValidationError(
                    f"No se pudo determinar el tamaño remoto de {remote_file.name}."
                )
            selected.append(remote_file)

        total_size = sum(item.size or 0 for item in selected)
        if total_size > self.settings.synology_max_operation_bytes:
            raise DownloadValidationError("La selección supera el límite de 250 MB por operación.")
        if not connection.diagnostic.download_api_available:
            raise DownloadValidationError(
                "La API de descarga de File Station no está disponible en este NAS."
            )

        connection_root = self._connection_root(connection_id)
        await self._run_blocking(self._ensure_safe_directory, connection_root)
        available = (await self._run_blocking(shutil.disk_usage, connection_root)).free
        if total_size > available:
            raise DownloadValidationError("No hay espacio libre suficiente para esta operación.")

        operation_id = uuid4().hex
        items = [
            DownloadItem(
                remote_path=item.path,
                local_path=str(self._local_path(connection_id, item.path)),
                expected_size=item.size or 0,
            )
            for item in selected
        ]
        for item in items:
            if await self._run_blocking(Path(item.local_path).exists):
                raise DownloadValidationError(f"Ya existe {item.local_path}; no se sobrescribió.")
        operation = DownloadOperation(
            operation_id=operation_id,
            connection_id=connection_id,
            connection_name=connection.diagnostic.name,
            started_at=datetime.now(UTC),
            items=items,
        )
        self.operations[operation_id] = operation
        self._active_operation = operation_id
        self._tasks[operation_id] = asyncio.create_task(self._run(operation))
        return operation

    async def start_photo_operation(
        self, connection_id: str, photos: list[Photo], *, album_id: str, confirmed: bool
    ) -> DownloadOperation:
        if self._start_lock.locked():
            raise DownloadValidationError("Ya se está preparando una descarga.")
        async with self._start_lock:
            return await self._start_photo_operation(
                connection_id, photos, album_id=album_id, confirmed=confirmed
            )

    async def _start_photo_operation(
        self,
        connection_id: str,
        photos: list[Photo],
        *,
        album_id: str,
        confirmed: bool,
    ) -> DownloadOperation:
        if not self.settings.manual_confirmation_required or not confirmed:
            raise DownloadValidationError(
                "Debes confirmar manualmente la descarga de los archivos seleccionados."
            )
        if not photos:
            raise DownloadValidationError("Selecciona al menos una fotografía.")
        if len(photos) > self.settings.synology_max_photos_per_operation:
            raise DownloadValidationError(
                f"El modo de prueba permite como máximo "
                f"{self.settings.synology_max_photos_per_operation} fotografías por operación."
            )
        if len({photo.photo_id for photo in photos}) != len(photos):
            raise DownloadValidationError("La selección contiene fotografías duplicadas.")
        if self._active_operation is not None:
            raise DownloadValidationError("Ya hay una operación de descarga en curso.")

        connection = self.connections.get_connection(connection_id)
        if connection.photos_client is None:
            raise DownloadValidationError("Synology Photos no está disponible en esta conexión.")
        if not connection.diagnostic.photos_download_available:
            raise DownloadValidationError(
                "La API de descarga de Synology Photos no está disponible."
            )
        if connection.active_album_id != album_id:
            raise DownloadValidationError("El álbum activo cambió; revisa la selección.")
        album = connection.known_albums.get(album_id)
        if album is None:
            raise DownloadValidationError("El álbum no se ha consultado en esta sesión.")
        for photo in photos:
            if connection.known_photos.get(photo.photo_id) != photo:
                raise DownloadValidationError(
                    "La selección contiene una fotografía que no se ha listado en esta sesión."
                )
            if photo.photo_id not in connection.album_photo_ids:
                raise DownloadValidationError("La fotografía no procede del álbum seleccionado.")
            if (
                photo.media_type != "photo"
                or photo.extension not in PHOTO_EXTENSIONS
                or photo.size < 0
            ):
                raise DownloadValidationError("La selección contiene un formato no permitido.")
            if not connection.photos_client.supports(
                "SYNO.Foto.Download"
                if photo.space == PhotoSpace.PERSONAL
                else "SYNO.FotoTeam.Download"
            ):
                raise DownloadValidationError(
                    f"La API de descarga de Synology Photos no está disponible para "
                    f"el espacio {photo.space.value}."
                )

        total_size = sum(photo.size for photo in photos)
        if total_size > self.settings.synology_max_operation_bytes:
            raise DownloadValidationError("La selección supera el límite de 250 MB por operación.")

        connection_root = self.photo_download_directory(album)
        await self._run_blocking(self._ensure_safe_target, connection_root / ".destination")
        await self._run_blocking(self._ensure_safe_directory, connection_root)
        available = (await self._run_blocking(shutil.disk_usage, connection_root)).free
        if total_size > available:
            raise DownloadValidationError("No hay espacio libre suficiente para esta operación.")

        operation_id = uuid4().hex
        items = [
            DownloadItem(
                remote_path=(
                    f"Synology Photos/{photo.space.value}/{photo.folder_id}/"
                    f"{photo.name}"
                ),
                local_path=str(self.photo_download_path(album, photo)),
                expected_size=photo.size,
                source_type="synology_photos",
                source_id=photo.photo_id,
            )
            for photo in photos
        ]
        if len({item.local_path.casefold() for item in items}) != len(items):
            raise DownloadValidationError(
                "Hay fotografías con el mismo nombre de destino; descárgalas por separado."
            )
        for item in items:
            destination = Path(item.local_path)
            if await self._run_blocking(destination.exists):
                item.state = DownloadState.SKIPPED
                item.error = "El archivo de destino ya existe; se omitió sin sobrescribir."
        operation = DownloadOperation(
            operation_id=operation_id,
            connection_id=connection_id,
            connection_name=connection.diagnostic.name,
            started_at=datetime.now(UTC),
            items=items,
            album_id=album_id,
            album_name=album.name,
        )
        self.operations[operation_id] = operation
        self._active_operation = operation_id
        self._tasks[operation_id] = asyncio.create_task(self._run(operation))
        return operation

    async def cancel(self, operation_id: str) -> DownloadOperation:
        operation = self.get_operation(operation_id)
        task = self._tasks.get(operation_id)
        if task is not None and not task.done():
            operation.cancel_requested = True
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if operation.state == DownloadState.PENDING:
                operation.state = DownloadState.CANCELLED
                operation.completed_at = datetime.now(UTC)
                operation.report_path = str(self._report_path(operation))
                await self._run_blocking(
                    self._write_report,
                    operation,
                    Path(operation.report_path),
                )
                self._active_operation = None
        return operation

    async def cancel_active(self) -> None:
        for operation_id, task in list(self._tasks.items()):
            if not task.done():
                await self.cancel(operation_id)

    def get_operation(self, operation_id: str) -> DownloadOperation:
        operation = self.operations.get(operation_id)
        if operation is None:
            raise DownloadValidationError("La operación de descarga no existe.")
        return operation

    async def _run(self, operation: DownloadOperation) -> None:
        operation.state = DownloadState.DOWNLOADING
        try:
            for item in operation.items:
                if operation.cancel_requested:
                    raise asyncio.CancelledError
                if item.state == DownloadState.SKIPPED:
                    continue
                operation.current_item = item.remote_path
                operation.current_bytes = 0
                operation.current_total = item.expected_size
                item.state = DownloadState.DOWNLOADING
                try:
                    await self._download_one(operation, item)
                except asyncio.CancelledError:
                    raise
                except (SynologyClientError, OSError, DownloadValidationError) as exc:
                    item.state = DownloadState.FAILED
                    item.error = str(exc)
                    operation.errors.append(f"{item.remote_path}: {exc}")
            operation.state = (
                DownloadState.COMPLETED
                if all(
                    item.state in {DownloadState.COMPLETED, DownloadState.SKIPPED}
                    for item in operation.items
                )
                else DownloadState.FAILED
            )
            if all(item.state == DownloadState.SKIPPED for item in operation.items):
                operation.state = DownloadState.SKIPPED
        except asyncio.CancelledError:
            operation.state = DownloadState.CANCELLED
            for item in operation.items:
                if item.state in {
                    DownloadState.PENDING,
                    DownloadState.DOWNLOADING,
                    DownloadState.DOWNLOADED,
                    DownloadState.VALIDATING,
                }:
                    item.state = DownloadState.CANCELLED
                    item.error = "Descarga cancelada; se conserva cualquier archivo parcial."
            raise
        finally:
            operation.completed_at = datetime.now(UTC)
            report_path = self._report_path(operation)
            operation.report_path = str(report_path)
            try:
                await self._run_blocking(self._write_report, operation, report_path)
            except OSError as exc:
                operation.state = DownloadState.FAILED
                operation.report_path = None
                operation.errors.append(f"No se pudo escribir el informe JSON: {exc}")
            finally:
                self._active_operation = None

    async def _download_one(
        self,
        operation: DownloadOperation,
        item: DownloadItem,
    ) -> None:
        connection = self.connections.get_connection(operation.connection_id)
        if item.source_type == "synology_photos":
            photo = connection.known_photos.get(item.source_id or "")
            if photo is None or connection.photos_client is None:
                raise DownloadValidationError(
                    "La fotografía Synology Photos ya no está disponible en esta sesión."
                )
            if photo.size != item.expected_size:
                raise DownloadValidationError(
                    "El tamaño del original difiere del tamaño recibido al listar."
                )
            if operation.album_id is None:
                raise DownloadValidationError("La operación no tiene un álbum asociado.")
            stream = connection.photos_client.stream_original(
                photo, album_id=operation.album_id
            )
        else:
            fresh_info = await self.connections.get_file_info(
                operation.connection_id,
                item.remote_path,
            )
            if fresh_info.is_directory or fresh_info.extension not in PHOTO_EXTENSIONS:
                raise DownloadValidationError(
                    "El elemento remoto ya no es una fotografía permitida."
                )
            if fresh_info.path != item.remote_path:
                raise DownloadValidationError("Synology devolvió información de otra ruta remota.")
            if fresh_info.size != item.expected_size:
                raise DownloadValidationError(
                    "El tamaño remoto cambió desde que se listó el archivo."
                )
            stream = connection.client.stream_download(item.remote_path)

        destination = Path(item.local_path)
        part = destination.with_name(destination.name + ".part")
        await self._run_blocking(self._ensure_safe_target, destination)
        if await self._run_blocking(destination.exists):
            item.state = DownloadState.SKIPPED
            item.error = "El archivo de destino ya existe; se omitió sin sobrescribir."
            return
        if await self._run_blocking(part.exists):
            item.partial_path = str(part)
            raise DownloadValidationError(
                "Ya existe un archivo temporal .part; revísalo antes de reintentar."
            )
        await self._run_blocking(destination.parent.mkdir, parents=True, exist_ok=True)
        await self._run_blocking(self._ensure_safe_target, destination)
        file_handle = await self._run_blocking(part.open, "xb")
        item.partial_path = str(part)
        digest = hashlib.sha256()
        downloaded = 0
        started = time.monotonic()
        operation.current_item = item.remote_path
        try:
            async with connection.lock:
                async for chunk in stream:
                    if operation.cancel_requested:
                        raise asyncio.CancelledError
                    if downloaded + len(chunk) > item.expected_size:
                        raise DownloadValidationError(
                            "La respuesta supera el tamaño esperado del original; "
                            "se conserva el parcial."
                        )
                    downloaded += await self._run_blocking(
                        self._write_and_hash,
                        file_handle,
                        digest,
                        chunk,
                    )
                    operation.current_bytes = downloaded
                    operation.bytes_per_second = downloaded / max(time.monotonic() - started, 0.001)
            await self._run_blocking(file_handle.flush)
            await self._run_blocking(os.fsync, file_handle.fileno())
        finally:
            item.downloaded_size = downloaded
            item.sha256 = digest.hexdigest()
            try:
                await stream.aclose()
            finally:
                await self._run_blocking(file_handle.close)

        item.downloaded_size = downloaded
        item.state = DownloadState.DOWNLOADED
        if downloaded != item.expected_size:
            raise DownloadValidationError(
                f"Tamaño descargado incorrecto ({downloaded} de {item.expected_size} bytes)."
            )

        item.state = DownloadState.VALIDATING
        await self._run_blocking(self._ensure_safe_target, destination)
        try:
            await self._run_blocking(os.link, part, destination)
        except asyncio.CancelledError:
            if await self._run_blocking(destination.exists):
                item.sha256 = digest.hexdigest()
                item.integrity_verified = False
                item.state = DownloadState.COMPLETED
            raise
        except FileExistsError as exc:
            raise DownloadValidationError(
                "Ya existe un archivo local con ese nombre; no se sobrescribió."
            ) from exc
        item.sha256 = digest.hexdigest()
        item.integrity_verified = False
        item.state = DownloadState.COMPLETED
        operation.current_bytes = downloaded
        operation.current_total = item.expected_size
        operation.bytes_per_second = downloaded / max(time.monotonic() - started, 0.001)
        operation.current_item = item.remote_path

    @staticmethod
    def _write_and_hash(
        file_handle: BinaryIO,
        digest: _HashDigest,
        chunk: bytes,
    ) -> int:
        written = file_handle.write(chunk)
        if written is None:
            raise OSError("No se pudo escribir el archivo temporal.")
        digest.update(chunk[:written])
        if written != len(chunk):
            raise OSError("La escritura del archivo temporal quedó incompleta.")
        return written

    def _connection_root(self, connection_id: str) -> Path:
        if not connection_id.isalnum():
            raise DownloadValidationError("Identificador de conexión no válido.")
        return self._download_base() / connection_id

    def _download_base(self) -> Path:
        base = self.settings.synology_download_directory
        return base if base.is_absolute() else Path.cwd() / base

    @staticmethod
    def _safe_component(value: str) -> str:
        value = WINDOWS_INVALID.sub("_", value.replace("/", "_").replace("\\", "_"))
        value = value.rstrip(". ")
        if not value or value in {".", ".."} or WINDOWS_RESERVED.match(value):
            value = "_" + value
        SynologyDownloadService._validate_windows_component(value)
        return value

    def photo_download_directory(self, album: PhotoAlbum) -> Path:
        return self._download_base() / self._safe_component(album.name)

    def photo_download_path(self, album: PhotoAlbum, photo: Photo) -> Path:
        return self.photo_download_directory(album) / self._safe_component(photo.name)

    def _local_path(self, connection_id: str, remote_path: str) -> Path:
        self._validate_remote_file_path(remote_path)
        parts = PurePosixPath(remote_path).parts[1:]
        for part in parts:
            self._validate_windows_component(part)
        return self._connection_root(connection_id).joinpath(*parts)

    def _photo_local_path(self, connection_id: str, photo: Photo) -> Path:
        for component in (photo.space.value, str(photo.folder_id), photo.name):
            self._validate_windows_component(component)
        return self._connection_root(connection_id).joinpath(
            "SynologyPhotos",
            photo.space.value,
            str(photo.folder_id),
            photo.name,
        )

    @staticmethod
    def _validate_remote_file_path(path: str) -> None:
        if (
            not path.startswith("/")
            or path.startswith("//")
            or "\\" in path
            or "\x00" in path
            or any(part in {"", ".", ".."} for part in path.split("/")[1:])
        ):
            raise DownloadValidationError("La ruta remota no es segura.")

    @staticmethod
    def _validate_windows_component(value: str) -> None:
        if (
            not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
            or WINDOWS_INVALID.search(value)
            or value.endswith((".", " "))
            or WINDOWS_RESERVED.match(value)
            or len(value) > 255
        ):
            raise DownloadValidationError(
                "El nombre remoto no es compatible con Windows y no se descargó."
            )

    @staticmethod
    def _ensure_safe_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or not path.resolve().is_dir():
            raise DownloadValidationError("El destino local no es un directorio.")

    def _ensure_safe_target(self, destination: Path) -> None:
        connection_root = self._download_base()
        if connection_root.is_symlink() or connection_root.is_junction():
            raise DownloadValidationError("La carpeta de descargas es un enlace.")
        root_resolved = connection_root.resolve()
        target_resolved = destination.resolve()
        if not target_resolved.is_relative_to(root_resolved):
            raise DownloadValidationError(
                "El destino local intenta escapar de la carpeta de esta conexión."
            )
        current = destination
        while current != root_resolved and current != current.parent:
            if current.is_symlink() or current.is_junction():
                raise DownloadValidationError(
                    "El destino contiene un enlace simbólico que escapa de la carpeta permitida."
                )
            current = current.parent

    def _connection_id_from_path(self, destination: Path) -> str:
        base = self.settings.synology_download_directory
        if not base.is_absolute():
            base = Path.cwd() / base
        try:
            relative = destination.relative_to(base)
        except ValueError as exc:
            raise DownloadValidationError("La ruta local no está bajo data/downloads.") from exc
        if not relative.parts:
            raise DownloadValidationError("La ruta local no tiene conexión asociada.")
        return relative.parts[0]

    def _report_path(self, operation: DownloadOperation) -> Path:
        return (
            self._connection_root(operation.connection_id)
            / ".reports"
            / f"{operation.operation_id}.json"
        )

    @staticmethod
    def _write_report(operation: DownloadOperation, path: Path) -> None:
        connection_root = path.parent.parent
        if (
            connection_root.is_symlink() or connection_root.is_junction()
            or path.parent.is_symlink() or path.parent.is_junction()
        ):
            raise OSError("La carpeta del informe contiene un enlace simbólico.")
        if not path.parent.resolve().is_relative_to(connection_root.resolve()):
            raise OSError("La carpeta del informe escapa del destino de la conexión.")
        path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "operation_id": operation.operation_id,
            "started_at": operation.started_at.isoformat(),
            "finished_at": operation.completed_at.isoformat() if operation.completed_at else None,
            "connection_name": operation.connection_name,
            "album_name": operation.album_name,
            "state": operation.state.value,
            "errors": operation.errors,
            "items": [
                {
                    "remote_path": item.remote_path,
                    "source_type": item.source_type,
                    "source_id": item.source_id,
                    "local_path": item.local_path,
                    "remote_expected_size": item.expected_size,
                    "downloaded_size": item.downloaded_size,
                    "sha256_local": item.sha256,
                    "state": item.state.value,
                    "error": item.error,
                    "integrity_verified": item.integrity_verified,
                    "partial_path": item.partial_path,
                }
                for item in operation.items
            ],
        }
        temporary = path.with_suffix(".json.part")
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(report, ensure_ascii=False, indent=2))
        os.link(temporary, path)

    @staticmethod
    async def _run_blocking(function, *args, **kwargs):
        task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise
