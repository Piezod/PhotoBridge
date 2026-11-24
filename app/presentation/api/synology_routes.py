from datetime import UTC, date, datetime, time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from app.application.services.synology_connections import (
    PHOTO_EXTENSIONS,
    VIDEO_EXTENSIONS,
    ConnectionDiagnostic,
)
from app.application.services.synology_downloads import (
    DownloadValidationError,
)
from app.domain.models.photos import Photo, PhotoSearchCriteria, PhotoSpace
from app.domain.models.synology import DownloadOperation, DownloadState
from app.infrastructure.synology.client import SynologyClientError
from app.presentation.api.csrf import parse_protected_form, render_template
from app.presentation.formatting import format_size

router = APIRouter()


@router.get("/connections", response_class=HTMLResponse, include_in_schema=False)
async def connections_page(request: Request) -> HTMLResponse:
    manager = request.app.state.synology_connections
    return render_template(
        request,
        "connections.html",
        {
            "connections": [item.diagnostic for item in manager.connections.values()],
            "default_name": manager.settings.synology_default_name,
            "default_server_url": manager.settings.synology_default_server_url,
            "default_username": manager.settings.synology_default_username,
        },
    )


@router.get("/explorer", response_class=HTMLResponse, include_in_schema=False)
async def explorer_page(
    request: Request,
    connection_id: str | None = None,
    source: str | None = None,
    space: str = "personal",
    path: str | None = None,
    folder_id: int | None = Query(default=None, ge=0),
    parent_folder_id: int | None = Query(default=None, ge=0),
    folder_name: Annotated[str | None, Query(max_length=255)] = None,
    album_id: Annotated[str | None, Query(max_length=128)] = None,
    name: Annotated[str | None, Query(max_length=120)] = None,
    extension: Annotated[str | None, Query(max_length=10)] = None,
    media_type: Annotated[str | None, Query(max_length=8)] = None,
    date_from: Annotated[str | None, Query(max_length=10)] = None,
    date_to: Annotated[str | None, Query(max_length=10)] = None,
    offset: int = Query(default=0, ge=0, le=2_147_483_647),
    extensions: Annotated[list[str] | None, Query()] = None,
) -> HTMLResponse:
    manager = request.app.state.synology_connections
    selected_connection = connection_id or next(iter(manager.connections), None)
    context: dict[str, Any] = {
        "connections": [item.diagnostic for item in manager.connections.values()],
        "connection_id": selected_connection,
        "extensions": sorted(PHOTO_EXTENSIONS),
        "photo_extensions": sorted(PHOTO_EXTENSIONS | VIDEO_EXTENSIONS),
        "selected_extensions": _parse_extensions(extensions or []),
        "shares": [],
        "files": [],
        "path": path,
        "breadcrumbs": [],
        "offset": offset,
        "has_more": False,
        "error": None,
        "selection_count": 0,
        "selection_size": 0,
        "selected_paths": set(),
        "source": source,
        "space": space,
        "folder_id": folder_id,
        "album_id": album_id,
        "name_filter": name or "",
        "extension_filter": extension or "",
        "media_type_filter": media_type or "",
        "date_from": date_from or "",
        "date_to": date_to or "",
        "photo_folders": [],
        "photo_albums": [],
        "photos": [],
        "photo_groups": [],
        "photo_has_more": False,
        "photo_selection_count": 0,
        "photo_selection_size": 0,
        "selected_photo_ids": set(),
        "current_folder_name": None,
        "parent_folder_id": parent_folder_id,
        "active_connection": None,
        "photo_error": None,
        "photo_folder_error": None,
        "photo_album_error": None,
        "downloadable_extensions": set(PHOTO_EXTENSIONS),
    }
    if selected_connection is None:
        return render_template(request, "explorer.html", context)

    try:
        connection = manager.get_connection(selected_connection)
        context["active_connection"] = connection.diagnostic
        active_source = source or (
            "photos" if connection.diagnostic.photos_api_available else "files"
        )
        if active_source not in {"photos", "files"}:
            raise ValueError("Selecciona una vista de exploración válida.")
        context["source"] = active_source
        if active_source == "photos":
            selected_space = PhotoSpace(space)
            if (
                source is None
                and selected_space == PhotoSpace.PERSONAL
                and not connection.diagnostic.photos_personal_space_accessible
                and connection.diagnostic.photos_shared_space_accessible
            ):
                selected_space = PhotoSpace.SHARED
            if selected_space == PhotoSpace.PERSONAL and not (
                connection.diagnostic.photos_personal_space_accessible
            ):
                raise ValueError("El espacio personal de Synology Photos no está accesible.")
            if selected_space == PhotoSpace.SHARED and not (
                connection.diagnostic.photos_shared_space_accessible
            ):
                raise ValueError("El espacio compartido de Synology Photos no está accesible.")
            from_date = _parse_filter_date(date_from, end_of_day=False)
            to_date = _parse_filter_date(date_to, end_of_day=True)
            if from_date and to_date and from_date > to_date:
                raise ValueError("La fecha inicial no puede ser posterior a la fecha final.")
            criteria = PhotoSearchCriteria(
                name=name.strip() if name and name.strip() else None,
                extension=_validate_photo_extension(extension),
                media_type=_validate_media_type(media_type),
                date_from=from_date,
                date_to=to_date,
                album_id=album_id if album_id else None,
            )
            photo_page = await manager.list_photos(
                selected_connection,
                selected_space,
                folder_id=folder_id,
                offset=offset,
                limit=50,
                criteria=criteria,
            )
            context.update(
                space=selected_space.value,
                photos=photo_page.items,
                photo_groups=_group_photos_by_date(photo_page.items),
                photo_has_more=photo_page.has_more,
                current_folder_name=folder_name or (
                    f"Carpeta {folder_id}" if folder_id is not None else None
                ),
            )
            try:
                context["photo_folders"], _ = await manager.list_photo_folders(
                    selected_connection,
                    selected_space,
                    folder_id=folder_id,
                    limit=50,
                )
            except SynologyClientError as exc:
                context["photo_folder_error"] = (
                    f"La navegación por carpetas no está disponible: {exc}"
                )
            if (
                selected_space == PhotoSpace.PERSONAL
                and connection.diagnostic.photos_albums_available
            ):
                try:
                    albums, _ = await manager.list_photo_albums(
                        selected_connection,
                        limit=50,
                    )
                    context["photo_albums"] = albums
                except SynologyClientError as exc:
                    context["photo_album_error"] = (
                        f"No se pudieron cargar los álbumes: {exc}"
                    )
            (
                context["photo_selection_count"],
                context["photo_selection_size"],
            ) = manager.photo_selection_summary(selected_connection)
            context["selected_photo_ids"] = connection.selected_photo_ids
        elif path:
            files, has_more = await manager.list_directory(
                selected_connection,
                path,
                offset=offset,
                limit=50,
                extensions=context["selected_extensions"] or None,
            )
            context.update(
                files=files,
                has_more=has_more,
                breadcrumbs=_breadcrumbs(path),
            )
        else:
            shares = await manager.list_shares(selected_connection, offset)
            context["shares"] = shares
            context["has_more"] = len(shares) == 50
        if active_source == "files":
            context["selection_count"], context["selection_size"] = manager.selection_summary(
                selected_connection
            )
            context["selected_paths"] = connection.selected_paths
    except (SynologyClientError, ValueError) as exc:
        if context["source"] == "photos":
            context["photo_error"] = str(exc)
        else:
            context["error"] = str(exc)
    return render_template(request, "explorer.html", context)


@router.post("/api/synology/connect", response_class=HTMLResponse)
async def connect_synology(request: Request) -> HTMLResponse:
    form = await parse_protected_form(request)
    manager = request.app.state.synology_connections
    diagnostic: ConnectionDiagnostic | None = None
    error: str | None = None
    try:
        diagnostic = await manager.connect(
            name=str(form.get("name", "")),
            server_url=str(form.get("server_url", "")),
            username=str(form.get("username", "")),
            password=str(form.get("password", "")),
            otp_code=str(form.get("otp_code", "")) or None,
            remember_password=str(form.get("remember_password", "")) == "on",
        )
    except SynologyClientError as exc:
        error = str(exc)
    except ValueError as exc:
        error = str(exc)
    connections = [item.diagnostic for item in manager.connections.values()]
    return render_template(
        request,
        "connection_result.html",
        {
            "connections": connections,
            "diagnostic": diagnostic,
            "error": error,
            "mfa_required": error is not None and "MFA" in error,
        },
    )


@router.post("/api/synology/{connection_id}/disconnect", response_class=HTMLResponse)
async def disconnect_synology(connection_id: str, request: Request) -> HTMLResponse:
    await parse_protected_form(request)
    manager = request.app.state.synology_connections
    error = None
    try:
        await manager.disconnect(connection_id)
    except SynologyClientError as exc:
        error = str(exc)
    return render_template(
        request,
        "connection_list.html",
        {
            "connections": [item.diagnostic for item in manager.connections.values()],
            "error": error,
        },
    )


@router.post(
    "/api/synology/{connection_id}/selection",
    response_class=HTMLResponse,
)
async def update_selection(connection_id: str, request: Request) -> HTMLResponse:
    form = await parse_protected_form(request)
    try:
        count, total_size = request.app.state.synology_connections.update_selection(
            connection_id,
            str(form.get("path", "")),
            selected=str(form.get("checked", "")) == "on",
        )
        error = None
    except SynologyClientError as exc:
        count, total_size = request.app.state.synology_connections.selection_summary(connection_id)
        error = str(exc)
    return render_template(
        request,
        "selection_summary.html",
        {
            "count": count,
            "total_size": total_size,
            "size": format_size(total_size),
            "error": error,
        },
    )


@router.post(
    "/api/synology/{connection_id}/downloads",
    response_class=HTMLResponse,
)
async def start_download(connection_id: str, request: Request) -> HTMLResponse:
    form = await parse_protected_form(request)
    manager = request.app.state.synology_connections
    try:
        source = str(form.get("source", "files"))
        if source not in {"files", "photos"}:
            raise DownloadValidationError("El origen de la descarga no es válido.")
        connection = manager.get_connection(connection_id)
        download_service = request.app.state.synology_downloads
        if source == "photos":
            operation = await download_service.start_photo_operation(
                connection_id,
                manager.get_selected_photos(connection_id),
                confirmed=str(form.get("confirm_download", "")) == "on",
            )
        else:
            operation = await download_service.start_operation(
                connection_id,
                sorted(connection.selected_paths),
                confirmed=str(form.get("confirm_download", "")) == "on",
            )
    except (SynologyClientError, DownloadValidationError) as exc:
        return render_template(request, "download_error.html", {"error": str(exc)})
    return render_template(
        request,
        "download_status.html",
        _operation_context(operation),
    )


@router.get(
    "/api/synology/downloads/{operation_id}",
    response_class=HTMLResponse,
)
async def download_status(operation_id: str, request: Request) -> HTMLResponse:
    operation = request.app.state.synology_downloads.get_operation(operation_id)
    return render_template(request, "download_status.html", _operation_context(operation))


@router.post(
    "/api/synology/downloads/{operation_id}/cancel",
    response_class=HTMLResponse,
)
async def cancel_download(operation_id: str, request: Request) -> HTMLResponse:
    await parse_protected_form(request)
    operation = await request.app.state.synology_downloads.cancel(operation_id)
    return render_template(request, "download_status.html", _operation_context(operation))


@router.get("/api/synology/{connection_id}/thumbnail")
async def thumbnail(
    connection_id: str,
    request: Request,
    path: str,
) -> StreamingResponse:
    if len(path) > 1024:
        raise HTTPException(status_code=422, detail="La ruta de miniatura es demasiado larga.")
    connection = request.app.state.synology_connections.get_connection(connection_id)
    try:
        content_type, chunks = await connection.client.stream_thumbnail(path)
    except SynologyClientError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StreamingResponse(
        chunks,
        media_type=content_type,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/synology/{connection_id}/photo-thumbnail")
async def photo_thumbnail(
    connection_id: str,
    request: Request,
    photo_id: str,
    size: str = "sm",
) -> StreamingResponse:
    if size not in {"sm", "xl"}:
        raise HTTPException(status_code=422, detail="Tamaño de miniatura no permitido.")
    manager = request.app.state.synology_connections
    connection = manager.get_connection(connection_id)
    photo = connection.known_photos.get(photo_id)
    if photo is None or connection.photos_client is None:
        raise HTTPException(status_code=404, detail="La fotografía no está disponible.")
    try:
        content_type, chunks = await connection.photos_client.stream_thumbnail(photo, size=size)
    except SynologyClientError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StreamingResponse(
        chunks,
        media_type=content_type,
        headers={"Cache-Control": "no-store"},
    )


@router.post(
    "/api/synology/{connection_id}/photo-selection",
    response_class=HTMLResponse,
)
async def update_photo_selection(connection_id: str, request: Request) -> HTMLResponse:
    form = await parse_protected_form(request)
    manager = request.app.state.synology_connections
    try:
        count, total_size = manager.update_photo_selection(
            connection_id,
            str(form.get("photo_id", "")),
            selected=str(form.get("checked", "")) == "on",
        )
        error = None
    except SynologyClientError as exc:
        count, total_size = manager.photo_selection_summary(connection_id)
        error = str(exc)
    return render_template(
        request,
        "selection_summary.html",
        {
            "count": count,
            "total_size": total_size,
            "size": format_size(total_size),
            "error": error,
        },
    )


@router.get("/api/synology/{connection_id}/shares", response_class=HTMLResponse)
async def list_shares(
    connection_id: str,
    request: Request,
    offset: int = Query(default=0, ge=0),
) -> HTMLResponse:
    try:
        shares = await request.app.state.synology_connections.list_shares(
            connection_id,
            offset,
        )
        error = None
    except SynologyClientError as exc:
        shares, error = [], str(exc)
    return render_template(
        request,
        "share_list.html",
        {"connection_id": connection_id, "shares": shares, "error": error},
    )


def _breadcrumbs(path: str) -> list[tuple[str, str]]:
    parts = [part for part in path.split("/") if part]
    result: list[tuple[str, str]] = [("Carpetas compartidas", "")]
    current: list[str] = []
    for part in parts:
        current.append(part)
        result.append((part, "/" + "/".join(current)))
    return result


def _parse_extensions(values: list[str]) -> set[str]:
    if not values:
        return set()
    parsed = {
        part.strip().lower().lstrip(".")
        for value in values
        for part in value.split(",")
        if part.strip()
    }
    if not parsed.issubset(PHOTO_EXTENSIONS):
        raise HTTPException(status_code=422, detail="Filtro de extensión no permitido.")
    return parsed


def _validate_photo_extension(value: str | None) -> str | None:
    if not value:
        return None
    extension = value.strip().lower().lstrip(".")
    if extension not in PHOTO_EXTENSIONS | VIDEO_EXTENSIONS:
        raise ValueError("El filtro de extensión no está permitido.")
    return extension


def _validate_media_type(value: str | None) -> str | None:
    if value is not None and value not in {"photo", "video"}:
        raise ValueError("El filtro solo admite fotografías o vídeos.")
    return value


def _parse_filter_date(value: str | None, *, end_of_day: bool) -> datetime | None:
    if not value:
        return None
    try:
        selected_date = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Utiliza fechas válidas en formato AAAA-MM-DD.") from exc
    selected_time = time.max if end_of_day else time.min
    return datetime.combine(selected_date, selected_time, tzinfo=UTC)


def _group_photos_by_date(photos):
    groups: dict[str, list[Photo]] = {}
    for photo in photos:
        captured_at = photo.metadata.captured_at
        label = captured_at.strftime("%d/%m/%Y") if captured_at else "Fecha de captura desconocida"
        groups.setdefault(label, []).append(photo)
    return list(groups.items())


def _operation_context(operation: DownloadOperation) -> dict[str, Any]:
    completed = sum(item.state == DownloadState.COMPLETED for item in operation.items)
    total = len(operation.items)
    percent = (
        round(operation.current_bytes * 100 / operation.current_total)
        if operation.current_total
        else 0
    )
    return {
        "operation": operation,
        "completed_count": completed,
        "total_count": total,
        "percent": min(percent, 100),
        "current_speed": format_size(int(operation.bytes_per_second)) + "/s",
    }
