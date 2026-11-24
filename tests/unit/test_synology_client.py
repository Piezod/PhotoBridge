import asyncio
import json

import httpx
import pytest

from app.infrastructure.synology.client import SynologyApiClient, SynologyClientError
from tests.helpers.synology import PHOTO_PATH, make_client_factory


def run(awaitable):
    return asyncio.run(awaitable)


def test_discovery_uses_dynamic_api_paths_versions_and_post_authentication() -> None:
    factory, requests = make_client_factory()

    async def scenario() -> None:
        client = SynologyApiClient(
            "https://nas.example:5001/custom",
            client_factory=factory,
        )
        await client.open()
        apis = await client.discover()
        await client.login("reader", "private-password")
        shares = await client.list_shares(limit=50)
        files, has_more = await client.list_directory("/photo", offset=50, limit=50)
        await client.logout()
        await client.close()

        assert apis["SYNO.API.Auth"].path == "auth.cgi"
        assert apis["SYNO.API.Auth"].max_version == 7
        assert apis["SYNO.FileStation.List"].max_version == 2
        assert shares[0].path == "/photo"
        assert files == []
        assert not has_more

    run(scenario())

    assert any(request.url.path.endswith("/custom/webapi/query.cgi") for request in requests)
    auth_request = next(
        request
        for request in requests
        if request.url.path.endswith("/custom/webapi/auth.cgi") and b"login" in request.content
    )
    assert auth_request.method == "POST"
    assert b"private-password" in auth_request.content
    assert "private-password" not in str(auth_request.url)
    list_request = next(
        request
        for request in requests
        if request.url.path.endswith("/custom/webapi/FileStation/file_share.cgi")
        and request.url.params.get("method") == "list"
    )
    assert list_request.url.params["version"] == "2"
    assert list_request.url.params["offset"] == "50"
    assert list_request.url.params["limit"] == "50"
    assert any(request.method == "POST" and b"logout" in request.content for request in requests)


@pytest.mark.parametrize(
    ("code", "category"),
    [(401, "authentication"), (403, "mfa_required"), (404, "mfa_invalid")],
)
def test_authentication_errors_are_explicit_and_never_retried(
    code: int,
    category: str,
) -> None:
    factory, requests = make_client_factory(auth_code=code)

    async def scenario() -> None:
        client = SynologyApiClient("https://nas.example", client_factory=factory)
        await client.open()
        await client.discover()
        with pytest.raises(SynologyClientError) as error:
            await client.login("reader", "wrong", "123456")
        assert error.value.code == code
        assert error.value.category == category
        await client.close()

    run(scenario())
    auth_requests = [request for request in requests if b"login" in request.content]
    assert len(auth_requests) == 1


def test_list_directory_caps_results_and_parses_file_metadata() -> None:
    factory, _ = make_client_factory()

    async def scenario():
        client = SynologyApiClient("https://nas.example", client_factory=factory)
        await client.open()
        await client.discover()
        await client.login("reader", "secret")
        files, has_more = await client.list_directory("/photo", limit=2)
        await client.close()
        return files, has_more

    files, has_more = run(scenario())
    assert len(files) == 2
    assert files[0].is_directory
    assert files[1].extension == "jpg"
    assert files[1].size == 20
    assert files[1].modified_at is not None
    assert has_more


def test_download_streams_original_bytes_and_discovers_thumbnail_api() -> None:
    factory, requests = make_client_factory()

    async def scenario():
        client = SynologyApiClient("https://nas.example", client_factory=factory)
        await client.open()
        await client.discover()
        await client.login("reader", "secret")
        chunks = [chunk async for chunk in client.stream_download(PHOTO_PATH)]
        content_type, thumbnail = await client.stream_thumbnail(PHOTO_PATH)
        thumb_bytes = b"".join([chunk async for chunk in thumbnail])
        await client.close()
        return chunks, content_type, thumb_bytes

    chunks, content_type, thumb_bytes = run(scenario())
    assert b"".join(chunks) == b"photobridge-original-image"
    assert content_type == "image/jpeg"
    assert thumb_bytes == b"\xff\xd8thumbnail"
    download_request = next(
        request
        for request in requests
        if request.url.params.get("api") == "SYNO.FileStation.Download"
    )
    assert json.loads(download_request.url.params["path"]) == [PHOTO_PATH]
    assert json.loads(download_request.url.params["mode"]) == "download"


def test_filestation_missing_file_error_is_not_misclassified_as_mfa() -> None:
    with pytest.raises(SynologyClientError) as error:
        SynologyApiClient._raise_for_api_error(
            {"success": False, "error": {"code": 404}},
            api_name="SYNO.FileStation.List",
            method="getinfo",
        )

    assert error.value.category == "remote_not_found"


def test_unavailable_thumbnail_api_is_reported() -> None:
    factory, _ = make_client_factory(include_thumbnail=False)

    async def scenario():
        client = SynologyApiClient("https://nas.example", client_factory=factory)
        await client.open()
        await client.discover()
        with pytest.raises(SynologyClientError) as error:
            await client.stream_thumbnail(PHOTO_PATH)
        await client.close()
        return error.value

    assert run(scenario()).category == "api_unavailable"


def test_dsm_error_response_is_not_yielded_as_an_original() -> None:
    response = httpx.Response(
        200,
        json={"success": False, "error": {"code": 404}},
        headers={"content-type": "application/json"},
    )
    factory, _ = make_client_factory(download_response=response)

    async def scenario():
        client = SynologyApiClient("https://nas.example", client_factory=factory)
        await client.open()
        await client.discover()
        await client.login("reader", "secret")
        with pytest.raises(SynologyClientError, match="respuesta de error"):
            _ = [chunk async for chunk in client.stream_download(PHOTO_PATH)]
        await client.close()

    run(scenario())


def test_remote_path_validation_rejects_traversal_and_absolute_unc() -> None:
    for path in ("/photo/../private.jpg", "//server/share.jpg", "/photo\\evil.jpg", "/photo/"):
        with pytest.raises(SynologyClientError) as error:
            SynologyApiClient.validate_remote_path(path)
        assert error.value.category == "invalid_path"


def test_api_path_from_server_cannot_escape_webapi_prefix() -> None:
    client = SynologyApiClient("https://nas.example")
    client.apis = {
        "SYNO.FileStation.List": type(
            "Api",
            (),
            {
                "path": "../attacker",
                "name": "SYNO.FileStation.List",
                "min_version": 1,
                "max_version": 1,
            },
        )()
    }

    with pytest.raises(SynologyClientError, match="ruta API"):
        client._api_url(client.apis["SYNO.FileStation.List"])
