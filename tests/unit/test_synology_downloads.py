import asyncio
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app.application.services.synology_connections import SynologyConnectionService
from app.application.services.synology_downloads import (
    DownloadValidationError,
    SynologyDownloadService,
)
from app.config import Settings
from app.domain.models.synology import RemoteFile
from tests.helpers.synology import (
    PHOTO_BYTES,
    PHOTO_PATH,
    BytesAsyncStream,
    MemoryCredentials,
    make_client_factory,
)


def run(awaitable):
    return asyncio.run(awaitable)


async def make_services(tmp_path, factory):
    settings = Settings(
        _env_file=None,
        synology_download_directory=tmp_path / "downloads",
    )
    connections = SynologyConnectionService(
        settings,
        MemoryCredentials(),
        client_factory=factory,
    )
    diagnostic = await connections.connect(
        name="NAS de prueba",
        server_url="https://nas.example",
        username="reader",
        password="secret",
    )
    await connections.list_directory(diagnostic.connection_id, "/photo/vacation")
    connections.update_selection(
        diagnostic.connection_id,
        PHOTO_PATH,
        selected=True,
    )
    downloads = SynologyDownloadService(settings, connections)
    return connections, downloads, diagnostic.connection_id


def test_download_streams_original_hashes_checks_size_and_writes_report(tmp_path):
    factory, _ = make_client_factory()

    async def scenario():
        connections, downloads, connection_id = await make_services(tmp_path, factory)
        operation = await downloads.start_operation(
            connection_id,
            [PHOTO_PATH],
            confirmed=True,
        )
        await downloads._tasks[operation.operation_id]
        await connections.disconnect(connection_id)
        return operation

    operation = run(scenario())
    item = operation.items[0]
    local_path = (
        tmp_path / "downloads" / operation.connection_id / "photo" / "vacation" / "sample.jpg"
    )

    assert operation.state.value == "COMPLETED"
    assert item.downloaded_size == len(PHOTO_BYTES)
    assert item.sha256 == hashlib.sha256(PHOTO_BYTES).hexdigest()
    assert item.integrity_verified is False
    assert local_path.read_bytes() == PHOTO_BYTES
    assert not local_path.with_name(local_path.name + ".part").exists()
    report = json.loads(Path(operation.report_path).read_text(encoding="utf-8"))
    assert report["connection_name"] == "NAS de prueba"
    assert report["items"][0]["remote_expected_size"] == len(PHOTO_BYTES)
    assert report["items"][0]["sha256_local"] == item.sha256
    assert report["items"][0]["integrity_verified"] is False
    assert "secret" not in json.dumps(report)


def test_remote_size_change_fails_before_download_and_report_records_error(tmp_path):
    factory, requests = make_client_factory(getinfo_size=999)

    async def scenario():
        connections, downloads, connection_id = await make_services(tmp_path, factory)
        operation = await downloads.start_operation(
            connection_id,
            [PHOTO_PATH],
            confirmed=True,
        )
        await downloads._tasks[operation.operation_id]
        await connections.disconnect(connection_id)
        return operation

    operation = run(scenario())
    assert operation.state.value == "FAILED"
    assert "tamaño remoto cambió" in operation.items[0].error
    assert not any(
        request.url.params.get("api") == "SYNO.FileStation.Download" for request in requests
    )
    assert os.path.exists(operation.report_path)


def test_download_rejects_dsm_json_error_and_removes_part(tmp_path):
    response = httpx.Response(
        200,
        json={"success": False, "error": {"code": 404}},
        headers={"content-type": "application/json"},
    )
    factory, _ = make_client_factory(download_response=response)

    async def scenario():
        connections, downloads, connection_id = await make_services(tmp_path, factory)
        operation = await downloads.start_operation(
            connection_id,
            [PHOTO_PATH],
            confirmed=True,
        )
        await downloads._tasks[operation.operation_id]
        await connections.disconnect(connection_id)
        return operation

    operation = run(scenario())
    local_path = operation.items[0].local_path
    assert operation.state.value == "FAILED"
    assert not os.path.exists(local_path + ".part")
    assert not os.path.exists(local_path)
    assert "respuesta de error" in operation.items[0].error


def test_downloaded_size_mismatch_removes_partial_and_does_not_finalize(tmp_path):
    response = httpx.Response(
        200,
        stream=BytesAsyncStream(b"short"),
        headers={"content-type": "image/jpeg"},
    )
    factory, _ = make_client_factory(download_response=response)

    async def scenario():
        connections, downloads, connection_id = await make_services(tmp_path, factory)
        operation = await downloads.start_operation(
            connection_id,
            [PHOTO_PATH],
            confirmed=True,
        )
        await downloads._tasks[operation.operation_id]
        await connections.disconnect(connection_id)
        return operation

    operation = run(scenario())
    assert operation.state.value == "FAILED"
    assert operation.items[0].downloaded_size == len(b"short")
    assert operation.items[0].sha256 is None
    assert "Tamaño descargado incorrecto" in operation.items[0].error
    assert not os.path.exists(operation.items[0].local_path)
    assert not os.path.exists(operation.items[0].local_path + ".part")


class InterruptedStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"partial"
        raise httpx.ReadError("connection interrupted")

    async def aclose(self) -> None:
        return None


def test_interrupted_download_cleans_part_and_reports_partial_byte_count(tmp_path):
    factory, _ = make_client_factory(download_stream=InterruptedStream())

    async def scenario():
        connections, downloads, connection_id = await make_services(tmp_path, factory)
        operation = await downloads.start_operation(
            connection_id,
            [PHOTO_PATH],
            confirmed=True,
        )
        await downloads._tasks[operation.operation_id]
        await connections.disconnect(connection_id)
        return operation

    operation = run(scenario())
    assert operation.state.value == "FAILED"
    assert operation.items[0].downloaded_size == len(b"partial")
    assert not os.path.exists(operation.items[0].local_path + ".part")
    assert operation.items[0].sha256 is None


class BlockingStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def __aiter__(self):
        yield b"partial"
        self.started.set()
        await asyncio.Event().wait()

    async def aclose(self) -> None:
        return None


def test_cancellation_cleans_part_and_writes_cancelled_report(tmp_path):
    stream = BlockingStream()
    factory, _ = make_client_factory(download_stream=stream)

    async def scenario():
        connections, downloads, connection_id = await make_services(tmp_path, factory)
        operation = await downloads.start_operation(
            connection_id,
            [PHOTO_PATH],
            confirmed=True,
        )
        await stream.started.wait()
        await downloads.cancel(operation.operation_id)
        await connections.disconnect(connection_id)
        return operation

    operation = run(scenario())
    assert operation.state.value == "CANCELLED"
    assert operation.items[0].state.value == "CANCELLED"
    assert not os.path.exists(operation.items[0].local_path + ".part")
    assert (
        json.loads(Path(operation.report_path).read_text(encoding="utf-8"))["state"] == "CANCELLED"
    )


def test_manual_confirmation_and_photo_count_are_enforced(tmp_path):
    factory, _ = make_client_factory()

    async def scenario():
        connections, downloads, connection_id = await make_services(tmp_path, factory)
        with pytest.raises(DownloadValidationError, match="confirmar manualmente"):
            await downloads.start_operation(connection_id, [PHOTO_PATH], confirmed=False)

        connection = connections.get_connection(connection_id)
        original = connection.known_files[PHOTO_PATH]
        paths = [PHOTO_PATH]
        for index in range(10):
            path = f"/photo/vacation/other-{index}.jpg"
            connection.known_files[path] = replace(
                original,
                name=f"other-{index}.jpg",
                path=path,
            )
            paths.append(path)
        with pytest.raises(DownloadValidationError, match="como máximo 10"):
            await downloads.start_operation(connection_id, paths, confirmed=True)
        operation = await downloads.start_operation(
            connection_id,
            [PHOTO_PATH],
            confirmed=True,
        )
        with pytest.raises(DownloadValidationError, match="Ya hay una operación"):
            await downloads.start_operation(
                connection_id,
                [PHOTO_PATH],
                confirmed=True,
            )
        await downloads.cancel(operation.operation_id)
        await connections.disconnect(connection_id)

    run(scenario())


def test_250_mb_limit_is_enforced_by_backend(tmp_path):
    factory, _ = make_client_factory()

    async def scenario():
        connections, downloads, connection_id = await make_services(tmp_path, factory)
        connection = connections.get_connection(connection_id)
        connection.known_files[PHOTO_PATH] = replace(
            connection.known_files[PHOTO_PATH],
            size=250_000_001,
        )
        with pytest.raises(DownloadValidationError, match="250 MB"):
            await downloads.start_operation(connection_id, [PHOTO_PATH], confirmed=True)
        await connections.disconnect(connection_id)

    run(scenario())


def test_existing_local_file_is_not_overwritten(tmp_path):
    factory, _ = make_client_factory()

    async def scenario():
        connections, downloads, connection_id = await make_services(tmp_path, factory)
        existing = tmp_path / "downloads" / connection_id / "photo" / "vacation" / "sample.jpg"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"keep me")
        with pytest.raises(DownloadValidationError, match="Ya existe"):
            await downloads.start_operation(connection_id, [PHOTO_PATH], confirmed=True)
        await connections.disconnect(connection_id)
        return existing

    existing = run(scenario())
    assert existing.read_bytes() == b"keep me"


def test_path_traversal_and_invalid_windows_names_are_rejected(tmp_path):
    factory, _ = make_client_factory()

    async def scenario():
        connections, downloads, connection_id = await make_services(tmp_path, factory)
        connection = connections.get_connection(connection_id)
        with pytest.raises(DownloadValidationError, match="ruta remota"):
            await downloads.start_operation(
                connection_id,
                ["/photo/../private.jpg"],
                confirmed=True,
            )

        reserved_path = "/photo/vacation/CON.jpg"
        connection.known_files[reserved_path] = RemoteFile(
            name="CON.jpg",
            path=reserved_path,
            is_directory=False,
            size=12,
            modified_at=None,
            extension="jpg",
        )
        with pytest.raises(DownloadValidationError, match="Windows"):
            await downloads.start_operation(
                connection_id,
                [reserved_path],
                confirmed=True,
            )
        await connections.disconnect(connection_id)

    run(scenario())


def test_symbolic_link_cannot_escape_connection_destination(tmp_path):
    factory, _ = make_client_factory()

    async def scenario():
        connections, downloads, connection_id = await make_services(tmp_path, factory)
        root = tmp_path / "downloads" / connection_id
        root.mkdir(parents=True, exist_ok=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        link = root / "photo"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("El sistema no permite crear enlaces simbólicos en esta sesión.")
        destination = link / "vacation" / "sample.jpg"
        with pytest.raises(DownloadValidationError, match="escapar"):
            await asyncio.to_thread(downloads._ensure_safe_target, destination)
        await connections.disconnect(connection_id)

    run(scenario())
