import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest

from app.application.services.synology_connections import SynologyConnectionService
from app.application.services.synology_downloads import (
    DownloadValidationError,
    SynologyDownloadService,
)
from app.config import Settings
from app.domain.models.photos import PhotoSearchCriteria, PhotoSpace
from app.infrastructure.synology.client import SynologyApiClient, SynologyClientError
from app.infrastructure.synology.photos import SynologyPhotosClient
from tests.helpers.synology import MemoryCredentials, make_client_factory


def run(awaitable):
    return asyncio.run(awaitable)


def test_photos_api_discovery_and_diagnostic_probe(tmp_path) -> None:
    factory, requests = make_client_factory(include_photos=True)
    service = SynologyConnectionService(
        Settings(_env_file=None, synology_download_directory=tmp_path / "downloads"),
        credential_store=MemoryCredentials(),
        client_factory=factory,
    )

    async def scenario():
        diagnostic = await service.connect(
            name="NAS",
            server_url="https://nas.example",
            username="reader",
            password="secret",
        )
        await service.disconnect(diagnostic.connection_id)
        return diagnostic

    diagnostic = run(scenario())
    assert diagnostic.photos_api_available
    assert diagnostic.photos_personal_space_accessible
    assert diagnostic.photos_shared_space_accessible
    assert diagnostic.photos_albums_available
    assert diagnostic.photos_thumbnail_available
    assert diagnostic.photos_download_available
    assert any(request.url.path == "/photo/webapi/query.cgi" for request in requests)
    photos_requests = [
        request for request in requests if request.url.path == "/photo/webapi/entry.cgi"
    ]
    assert photos_requests
    assert all(
        request.headers.get("x-syno-token") == "private-token"
        for request in photos_requests
    )
    assert all(request.headers.get("cookie") == "id=private-session" for request in photos_requests)
    assert all("private-token" not in str(request.url) for request in photos_requests)


def test_missing_or_forbidden_photos_apis_do_not_break_file_station(tmp_path) -> None:
    async def connect_with_factory(factory):
        service = SynologyConnectionService(
            Settings(_env_file=None, synology_download_directory=tmp_path / "downloads"),
            MemoryCredentials(),
            client_factory=factory,
        )
        diagnostic = await service.connect(
            name="NAS",
            server_url="https://nas.example",
            username="reader",
            password="secret",
        )
        await service.disconnect(diagnostic.connection_id)
        return diagnostic

    unavailable = run(connect_with_factory(make_client_factory()[0]))
    forbidden = run(
        connect_with_factory(
            make_client_factory(
                include_photos=True,
                photos_permission_error=True,
            )[0]
        )
    )
    assert unavailable.read_access
    assert not unavailable.photos_api_available
    assert forbidden.read_access
    assert forbidden.photos_api_available
    assert not forbidden.photos_personal_space_accessible
    assert not forbidden.photos_shared_space_accessible


def test_photo_library_paginates_parses_metadata_and_filters_current_page() -> None:
    factory, requests = make_client_factory(include_photos=True)

    async def scenario():
        client = SynologyApiClient("https://nas.example", client_factory=factory)
        await client.open()
        await client.discover()
        photos_apis = await client.discover_photos()
        await client.login("reader", "secret")
        photos = SynologyPhotosClient(client, photos_apis)
        page = await photos.list_photos(
            PhotoSpace.PERSONAL,
            folder_id=5,
            offset=0,
            limit=2,
            criteria=PhotoSearchCriteria(name="land", extension="jpg"),
        )
        await client.close()
        return page

    page = run(scenario())
    assert len(page.items) == 1
    photo = page.items[0]
    assert photo.photo_id == "personal:901"
    assert photo.name == "landscape.jpg"
    assert photo.size > 0
    assert photo.metadata.captured_at is not None
    assert photo.metadata.width == 1920
    assert photo.metadata.camera == "Test Camera"
    assert photo.thumbnail_cache_key == "901_1700000000"
    assert page.has_more
    item_request = next(
        request
        for request in requests
        if request.url.params.get("api") == "SYNO.Foto.Browse.Item"
    )
    assert item_request.url.params["folder_id"] == "5"
    assert item_request.url.params["offset"] == "0"
    assert item_request.url.params["limit"] == "2"
    assert item_request.url.params["type"] == "photo"
    assert json.loads(item_request.url.params["additional"]) == [
        "thumbnail",
        "resolution",
        "orientation",
        "exif",
        "description",
    ]


def test_shared_space_folders_and_photo_album_list_use_discovered_apis() -> None:
    factory, requests = make_client_factory(include_photos=True)

    async def scenario():
        client = SynologyApiClient("https://nas.example", client_factory=factory)
        await client.open()
        await client.discover()
        apis = await client.discover_photos()
        await client.login("reader", "secret")
        photos = SynologyPhotosClient(client, apis)
        folders, _ = await photos.list_folders(PhotoSpace.SHARED, limit=50)
        albums, _ = await photos.list_albums(limit=50)
        page = await photos.list_photos(
            PhotoSpace.SHARED,
            folder_id=7,
        )
        album_page = await photos.list_photos(
            PhotoSpace.PERSONAL,
            criteria=PhotoSearchCriteria(album_id="19"),
        )
        await client.close()
        return folders, albums, page, album_page

    folders, albums, page, album_page = run(scenario())
    assert folders[0].folder_id == 1
    assert folders[1].space == PhotoSpace.SHARED
    assert albums[0].album_id == "19"
    assert albums[0].item_count == 2
    assert page.items[0].space == PhotoSpace.SHARED
    assert album_page.items[0].space == PhotoSpace.PERSONAL
    assert any(
        request.url.params.get("api") == "SYNO.Foto.Browse.Item"
        and request.url.params.get("album_id") == "19"
        for request in requests
    )


def test_photo_thumbnails_and_originals_stream_using_backend_session_only() -> None:
    factory, requests = make_client_factory(include_photos=True)

    async def scenario():
        client = SynologyApiClient("https://nas.example", client_factory=factory)
        await client.open()
        await client.discover()
        apis = await client.discover_photos()
        await client.login("reader", "secret")
        photos = SynologyPhotosClient(client, apis)
        photo = (await photos.list_photos(PhotoSpace.PERSONAL)).items[0]
        content_type, thumbnail = await photos.stream_thumbnail(photo, size="xl")
        thumb_bytes = b"".join([chunk async for chunk in thumbnail])
        original = b"".join([chunk async for chunk in photos.stream_original(photo)])
        await client.close()
        return content_type, thumb_bytes, original

    content_type, thumbnail, original = run(scenario())
    assert content_type == "image/jpeg"
    assert thumbnail == b"\xff\xd8photos-thumbnail"
    assert original == b"photobridge-original-image"
    thumb_request = next(
        request
        for request in requests
        if request.url.params.get("api") == "SYNO.Foto.Thumbnail"
    )
    assert thumb_request.url.params["size"] == "xl"
    download_request = next(
        request
        for request in requests
        if request.url.params.get("api") == "SYNO.Foto.Download"
    )
    assert json.loads(download_request.url.params["unit_id"]) == [901]
    assert "private-session" not in str(download_request.url)
    assert "private-token" not in str(download_request.url)


def test_photo_api_rejects_json_errors_and_caps_pagination() -> None:
    error_response = httpx.Response(
        200,
        json={"success": False, "error": {"code": 403}},
        headers={"content-type": "application/json"},
    )
    factory, _ = make_client_factory(
        include_photos=True,
        photos_download_response=error_response,
    )

    async def scenario():
        client = SynologyApiClient("https://nas.example", client_factory=factory)
        await client.open()
        await client.discover()
        apis = await client.discover_photos()
        await client.login("reader", "secret")
        photos = SynologyPhotosClient(client, apis)
        photo = (await photos.list_photos(PhotoSpace.PERSONAL)).items[0]
        with pytest.raises(SynologyClientError):
            _ = [chunk async for chunk in photos.stream_original(photo)]
        with pytest.raises(SynologyClientError, match="50 elementos"):
            await photos.list_photos(PhotoSpace.PERSONAL, limit=51)
        await client.close()

    run(scenario())


def test_photo_filters_are_applied_without_scanning_beyond_the_requested_page() -> None:
    factory, _ = make_client_factory(include_photos=True)

    async def scenario():
        client = SynologyApiClient("https://nas.example", client_factory=factory)
        await client.open()
        await client.discover()
        apis = await client.discover_photos()
        await client.login("reader", "secret")
        photos = SynologyPhotosClient(client, apis)
        page = await photos.list_photos(
            PhotoSpace.PERSONAL,
            offset=0,
            limit=2,
            criteria=PhotoSearchCriteria(
                date_to=datetime.fromtimestamp(1_695_000_000, tz=UTC),
            ),
        )
        await client.close()
        return page

    page = run(scenario())
    assert page.has_more
    assert [photo.name for photo in page.items] == ["second.png"]


def test_photo_download_uses_shared_stream_validation_and_writes_private_report(tmp_path) -> None:
    factory, _ = make_client_factory(include_photos=True)
    settings = Settings(
        _env_file=None,
        synology_download_directory=tmp_path / "downloads",
    )
    connections = SynologyConnectionService(
        settings,
        MemoryCredentials(),
        client_factory=factory,
    )
    downloads = SynologyDownloadService(settings, connections)

    async def scenario():
        diagnostic = await connections.connect(
            name="NAS",
            server_url="https://nas.example",
            username="reader",
            password="secret",
        )
        page = await connections.list_photos(
            diagnostic.connection_id,
            PhotoSpace.PERSONAL,
        )
        photos = page.items[:1]
        operation = await downloads.start_photo_operation(
            diagnostic.connection_id,
            photos,
            confirmed=True,
        )
        await downloads._tasks[operation.operation_id]
        await connections.disconnect(diagnostic.connection_id)
        return operation

    operation = run(scenario())
    item = operation.items[0]
    assert item.state.value == "COMPLETED"
    assert item.downloaded_size == item.expected_size
    assert item.sha256 is not None
    assert item.integrity_verified is False
    assert item.source_type == "synology_photos"
    assert item.local_path.endswith("SynologyPhotos\\personal\\5\\landscape.jpg")
    assert (tmp_path / "downloads" / operation.connection_id / "SynologyPhotos"
            / "personal" / "5" / "landscape.jpg").read_bytes() == b"photobridge-original-image"
    report = json.loads((tmp_path / "downloads" / operation.connection_id / ".reports"
                         / f"{operation.operation_id}.json").read_text(encoding="utf-8"))
    assert report["items"][0]["source_type"] == "synology_photos"
    assert report["items"][0]["sha256_local"] == item.sha256
    assert "private-token" not in json.dumps(report)
    assert "private-session" not in json.dumps(report)


def test_photo_download_requires_confirmation_and_enforces_item_limit(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        synology_download_directory=tmp_path / "downloads",
        synology_max_photos_per_operation=1,
    )
    connections = SynologyConnectionService(
        settings,
        MemoryCredentials(),
        client_factory=make_client_factory(include_photos=True)[0],
    )
    downloads = SynologyDownloadService(settings, connections)

    async def scenario():
        diagnostic = await connections.connect(
            name="NAS",
            server_url="https://nas.example",
            username="reader",
            password="secret",
        )
        photos = (await connections.list_photos(
            diagnostic.connection_id,
            PhotoSpace.PERSONAL,
        )).items
        with pytest.raises(DownloadValidationError, match="confirmar"):
            await downloads.start_photo_operation(
                diagnostic.connection_id,
                photos[:1],
                confirmed=False,
            )
        with pytest.raises(DownloadValidationError, match="como máximo"):
            await downloads.start_photo_operation(
                diagnostic.connection_id,
                photos,
                confirmed=True,
            )
        await connections.disconnect(diagnostic.connection_id)

    run(scenario())


def test_photo_download_enforces_operation_size_limit(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        synology_download_directory=tmp_path / "downloads",
        synology_max_operation_bytes=1,
    )
    connections = SynologyConnectionService(
        settings,
        MemoryCredentials(),
        client_factory=make_client_factory(include_photos=True)[0],
    )
    downloads = SynologyDownloadService(settings, connections)

    async def scenario():
        diagnostic = await connections.connect(
            name="NAS",
            server_url="https://nas.example",
            username="reader",
            password="secret",
        )
        photos = (
            await connections.list_photos(
                diagnostic.connection_id,
                PhotoSpace.PERSONAL,
            )
        ).items
        with pytest.raises(DownloadValidationError, match="250 MB"):
            await downloads.start_photo_operation(
                diagnostic.connection_id,
                photos[:1],
                confirmed=True,
            )
        await connections.disconnect(diagnostic.connection_id)

    run(scenario())
