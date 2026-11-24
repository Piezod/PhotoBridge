import asyncio
import re

import httpx

from app.application.services.synology_connections import SynologyConnectionService
from app.application.services.synology_downloads import SynologyDownloadService
from app.config import Settings
from app.main import app
from tests.helpers.synology import MemoryCredentials, make_client_factory


async def request_app():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def test_connections_and_explorer_pages_are_available_without_network():
    async def scenario() -> None:
        async with await request_app() as client:
            connections = await client.get("/connections")
            explorer = await client.get("/explorer")
        assert connections.status_code == 200
        assert "Probar conexión a Synology" in connections.text
        assert explorer.status_code == 200
        assert "Primero necesitas una sesión Synology activa" in explorer.text
        assert "PhotoBridge" in explorer.text

    asyncio.run(scenario())


def test_mutating_synology_endpoints_require_csrf_and_reject_foreign_origin():
    async def scenario() -> None:
        async with await request_app() as client:
            page = await client.get("/connections")
            token = re.search(
                r'<meta name="csrf-token" content="([^"]+)"',
                page.text,
            ).group(1)
            no_token = await client.post(
                "/api/synology/connect",
                data={"name": "NAS"},
            )
            foreign_origin = await client.post(
                "/api/synology/connect",
                data={"name": "NAS"},
                headers={"x-csrf-token": token, "origin": "http://attacker.example"},
            )
            rejected_connection = await client.post(
                "/api/synology/connect",
                data={
                    "csrf_token": token,
                    "name": "NAS",
                    "server_url": "http://nas.example:5000",
                    "username": "reader",
                    "password": "do-not-return-this",
                },
            )
            assert no_token.status_code == 403
            assert foreign_origin.status_code == 403
            assert rejected_connection.status_code == 200
            assert rejected_connection.text.count("Utiliza HTTPS") == 1
            assert "do-not-return-this" not in rejected_connection.text
            assert "do-not-return-this" not in str(rejected_connection.url)

    asyncio.run(scenario())


def test_all_mutating_endpoints_require_csrf_before_service_access():
    async def scenario() -> None:
        async with await request_app() as client:
            response = await client.post("/api/synology/not-a-session/disconnect")
        assert response.status_code == 403

    asyncio.run(scenario())


def test_photos_library_is_preferred_and_thumbnail_is_proxied_without_session_data(tmp_path):
    async def scenario() -> None:
        original_connections = app.state.synology_connections
        original_downloads = app.state.synology_downloads
        settings = Settings(
            _env_file=None,
            synology_download_directory=tmp_path / "downloads",
        )
        connections = SynologyConnectionService(
            settings,
            MemoryCredentials(),
            client_factory=make_client_factory(include_photos=True)[0],
        )
        try:
            diagnostic = await connections.connect(
                name="NAS",
                server_url="https://nas.example",
                username="reader",
                password="secret",
            )
            downloads = SynologyDownloadService(settings, connections)
            app.state.synology_connections = connections
            app.state.synology_downloads = downloads
            async with await request_app() as client:
                page = await client.get(f"/explorer?connection_id={diagnostic.connection_id}")
                assert page.status_code == 200
                assert "Biblioteca Synology Photos" in page.text
                assert "landscape.jpg" in page.text
                assert "File Station" in page.text
                assert "private-session" not in page.text
                assert "private-token" not in page.text
                token = re.search(
                    r'<meta name="csrf-token" content="([^"]+)"',
                    page.text,
                ).group(1)
                thumbnail = await client.get(
                    f"/api/synology/{diagnostic.connection_id}/photo-thumbnail",
                    params={"photo_id": "personal:901"},
                )
                assert thumbnail.status_code == 200
                assert thumbnail.headers["content-type"] == "image/jpeg"
                assert thumbnail.content == b"\xff\xd8photos-thumbnail"
                selected = await client.post(
                    f"/api/synology/{diagnostic.connection_id}/photo-selection",
                    data={
                        "csrf_token": token,
                        "photo_id": "personal:901",
                        "checked": "on",
                    },
                )
                assert selected.status_code == 200
                assert 'data-count="1"' in selected.text
                rejected = await client.post(
                    f"/api/synology/{diagnostic.connection_id}/photo-selection",
                    data={"photo_id": "personal:902", "checked": "on"},
                )
                assert rejected.status_code == 403
        finally:
            for connection_id in list(connections.connections):
                await connections.disconnect(connection_id)
            app.state.synology_connections = original_connections
            app.state.synology_downloads = original_downloads

    asyncio.run(scenario())
