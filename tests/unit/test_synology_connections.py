import asyncio
from dataclasses import replace

import httpx
import pytest

from app.application.services.synology_connections import SynologyConnectionService
from app.config import Settings
from app.infrastructure.synology.client import SynologyClientError
from tests.helpers.synology import MemoryCredentials, make_client_factory


def run(awaitable):
    return asyncio.run(awaitable)


def make_service(tmp_path, factory):
    settings = Settings(
        _env_file=None,
        synology_download_directory=tmp_path / "downloads",
    )
    credentials = MemoryCredentials()
    return SynologyConnectionService(
        settings,
        credentials,
        client_factory=factory,
    ), credentials


def test_url_validation_supports_ddns_custom_ports_ip_and_vpn_paths() -> None:
    examples = {
        "https://nas.example:5001": "https://nas.example:5001",
        "https://192.168.10.5:5001": "https://192.168.10.5:5001",
        "https://[2001:db8::1]:5001/dsm": "https://[2001:db8::1]:5001/dsm",
        "https://nas.example:5001/synology/": "https://nas.example:5001/synology",
        "https://münich.example:5001": "https://xn--mnich-kva.example:5001",
    }

    for given, expected in examples.items():
        normalized, quickconnect = SynologyConnectionService.validate_server_url(given)
        assert normalized == expected
        assert quickconnect is False


@pytest.mark.parametrize(
    "url",
    [
        "ftp://nas.example",
        "http://nas.example:5000",
        "https://user:password@nas.example",
        "https://nas.example/path?token=secret",
        "https://nas.example/../outside",
        "https://nas.example/%2e%2e/outside",
        "https://bad host/path",
    ],
)
def test_unsafe_server_urls_are_rejected(url: str) -> None:
    with pytest.raises(SynologyClientError, match="URL|dominio|ruta"):
        SynologyConnectionService.validate_server_url(url)


def test_quickconnect_api_capabilities_are_checked_before_authentication(tmp_path) -> None:
    factory, requests = make_client_factory(
        quickconnect_redirect="https://sample.fr1.quickconnect.to",
        include_download=False,
    )
    service, _ = make_service(tmp_path, factory)

    async def scenario() -> None:
        with pytest.raises(SynologyClientError) as error:
            await service.connect(
                name="NAS",
                server_url="https://quickconnect.to/example-id",
                username="reader",
                password="not-sent",
            )
        assert error.value.category == "quickconnect_api_unavailable"

    run(scenario())
    assert any("query.cgi" in request.url.path for request in requests)
    assert not any(b"login" in request.content for request in requests)


def test_quickconnect_redirect_is_resolved_and_credentials_stay_on_regional_host(
    tmp_path,
) -> None:
    factory, requests = make_client_factory(
        quickconnect_redirect="https://sample.fr1.quickconnect.to"
    )
    service, _ = make_service(tmp_path, factory)

    async def scenario():
        result = await service.connect(
            name="NAS",
            server_url="https://quickconnect.to/sample-id",
            username="reader",
            password="private-password",
        )
        await service.disconnect(result.connection_id)
        return result

    result = run(scenario())
    assert result.quickconnect
    assert result.server_url == "https://sample.fr1.quickconnect.to"
    redirect_request = requests[0]
    regional_probe = requests[1]
    api_info_request = next(request for request in requests if "query.cgi" in request.url.path)
    auth_request = next(request for request in requests if b"login" in request.content)
    assert redirect_request.url.host == "quickconnect.to"
    assert "cookie" not in regional_probe.headers
    assert api_info_request.url.host == "sample.fr1.quickconnect.to"
    assert requests.index(api_info_request) < requests.index(auth_request)
    assert auth_request.url.host == "sample.fr1.quickconnect.to"
    assert all(
        b"private-password" not in request.content
        for request in requests[: requests.index(auth_request)]
    )


@pytest.mark.parametrize(
    "server_url",
    [
        "https://quickconnect.to/sample-id",
        "https://quickconnect.cn/piezod",
        "https://sample.fr1.quickconnect.to",
        "https://piezod.quickconnect.cn",
    ],
)
def test_quickconnect_root_and_regional_hosts_are_recognized(server_url: str) -> None:
    normalized, quickconnect = SynologyConnectionService.validate_server_url(server_url)

    assert normalized == server_url
    assert quickconnect


def test_quickconnect_redirect_to_untrusted_host_is_rejected_before_credentials(
    tmp_path,
) -> None:
    factory, requests = make_client_factory(
        quickconnect_redirect="https://attacker.example"
    )
    service, _ = make_service(tmp_path, factory)

    async def scenario() -> SynologyClientError:
        with pytest.raises(SynologyClientError) as error:
            await service.connect(
                name="NAS",
                server_url="https://quickconnect.to/sample-id",
                username="reader",
                password="private-password",
            )
        return error.value

    error = run(scenario())
    assert error.category == "quickconnect_redirect_untrusted"
    assert [request.url.host for request in requests] == ["quickconnect.to"]
    assert all(b"private-password" not in request.content for request in requests)


def test_quickconnect_http_redirect_is_rejected(tmp_path) -> None:
    factory, requests = make_client_factory(
        quickconnect_redirect="http://sample.fr1.quickconnect.to"
    )
    service, _ = make_service(tmp_path, factory)

    async def scenario() -> SynologyClientError:
        with pytest.raises(SynologyClientError) as error:
            await service.connect(
                name="NAS",
                server_url="https://quickconnect.to/sample-id",
                username="reader",
                password="private-password",
            )
        return error.value

    error = run(scenario())
    assert error.category == "quickconnect_redirect_untrusted"
    assert len(requests) == 1


def test_login_redirect_is_not_followed_to_untrusted_host(tmp_path) -> None:
    factory, requests = make_client_factory(
        auth_redirect="https://attacker.example/collect"
    )
    service, _ = make_service(tmp_path, factory)

    async def scenario() -> SynologyClientError:
        with pytest.raises(SynologyClientError) as error:
            await service.connect(
                name="NAS",
                server_url="https://sample.fr1.quickconnect.to",
                username="reader",
                password="private-password",
            )
        return error.value

    error = run(scenario())
    assert error.category == "redirect"
    login_request = next(request for request in requests if b"login" in request.content)
    assert login_request.url.host == "sample.fr1.quickconnect.to"
    assert all(request.url.host != "attacker.example" for request in requests)
    assert b"private-password" in login_request.content


def test_quickconnect_html_endpoint_is_rejected_before_login(tmp_path) -> None:
    factory, requests = make_client_factory(
        discovery_response=httpx.Response(
            200,
            text="<html><title>Login</title></html>",
            headers={"content-type": "text/html"},
        )
    )
    service, _ = make_service(tmp_path, factory)

    async def scenario() -> SynologyClientError:
        with pytest.raises(SynologyClientError) as error:
            await service.connect(
                name="NAS",
                server_url="https://sample.fr1.quickconnect.to",
                username="reader",
                password="private-password",
            )
        return error.value

    error = run(scenario())
    assert error.category == "quickconnect_api_unavailable"
    assert "HTML" in str(error)
    assert not any(b"login" in request.content for request in requests)
    assert all(b"private-password" not in request.content for request in requests)


def test_quickconnect_json_api_error_is_reported_before_login(tmp_path) -> None:
    factory, requests = make_client_factory(
        discovery_response=httpx.Response(
            200,
            json={"success": False, "error": {"code": 999}},
        )
    )
    service, _ = make_service(tmp_path, factory)

    async def scenario() -> SynologyClientError:
        with pytest.raises(SynologyClientError) as error:
            await service.connect(
                name="NAS",
                server_url="https://sample.fr1.quickconnect.to",
                username="reader",
                password="private-password",
            )
        return error.value

    error = run(scenario())
    assert error.category == "quickconnect_api_unavailable"
    assert "JSON" in str(error)
    assert not any(b"login" in request.content for request in requests)


def test_connection_error_is_reported_without_retrying(tmp_path) -> None:
    factory, requests = make_client_factory(connect_error=True)
    service, _ = make_service(tmp_path, factory)

    async def scenario() -> SynologyClientError:
        with pytest.raises(SynologyClientError) as error:
            await service.connect(
                name="NAS",
                server_url="https://nas.example:5001",
                username="reader",
                password="private-password",
            )
        return error.value

    assert run(scenario()).category == "unreachable"
    assert len(requests) == 1


def test_direct_connection_still_authenticates_and_reports_non_quickconnect(tmp_path) -> None:
    factory, requests = make_client_factory()
    service, _ = make_service(tmp_path, factory)

    async def scenario():
        result = await service.connect(
            name="NAS",
            server_url="https://192.168.10.5:5001",
            username="reader",
            password="private-password",
        )
        await service.disconnect(result.connection_id)
        return result

    result = run(scenario())
    assert not result.quickconnect
    assert result.server_url == "https://192.168.10.5:5001"
    assert all(request.url.host == "192.168.10.5" for request in requests)


def test_connection_discovers_capabilities_checks_read_access_and_closes_session(
    tmp_path,
) -> None:
    factory, requests = make_client_factory()
    service, _ = make_service(tmp_path, factory)

    async def scenario():
        result = await service.connect(
            name="Casa",
            server_url="https://nas.example:5001",
            username="reader",
            password="secret",
        )
        assert result.authenticated
        assert result.list_api_available
        assert result.download_api_available
        assert result.thumbnail_api_available
        assert result.read_access
        assert result.latency_ms >= 0
        await service.disconnect(result.connection_id)
        return result

    result = run(scenario())
    assert result.connection_id not in service.connections
    assert any(request.method == "POST" and b"logout" in request.content for request in requests)


def test_remember_password_uses_credential_store_only_after_successful_login(
    tmp_path,
) -> None:
    factory, _ = make_client_factory()
    service, credentials = make_service(tmp_path, factory)

    async def scenario():
        result = await service.connect(
            name="Casa",
            server_url="https://nas.example:5001",
            username="reader",
            password="secret",
            remember_password=True,
        )
        key = service.credential_key(result.server_url, "reader")
        assert credentials.get_password(key) == "secret"
        await service.disconnect(result.connection_id)
        result = await service.connect(
            name="Casa",
            server_url="https://nas.example:5001",
            username="reader",
            password="",
        )
        await service.disconnect(result.connection_id)

    run(scenario())


def test_authentication_failure_does_not_save_credentials_or_log_secrets(
    tmp_path,
    caplog,
) -> None:
    factory, requests = make_client_factory(auth_code=401)
    service, credentials = make_service(tmp_path, factory)

    async def scenario() -> None:
        with pytest.raises(SynologyClientError):
            await service.connect(
                name="Casa",
                server_url="https://nas.example",
                username="secret-user",
                password="private-password",
                remember_password=True,
            )

    run(scenario())
    key = service.credential_key("https://nas.example", "secret-user")
    assert credentials.get_password(key) is None
    assert "private-password" not in caplog.text
    assert "secret-user" not in caplog.text
    assert len([request for request in requests if b"login" in request.content]) == 1


def test_file_listing_filters_extensions_and_rejects_pages_over_50(tmp_path) -> None:
    factory, _ = make_client_factory()
    service, _ = make_service(tmp_path, factory)

    async def scenario():
        connection = await service.connect(
            name="NAS",
            server_url="https://nas.example",
            username="reader",
            password="secret",
        )
        files, has_more = await service.list_directory(
            connection.connection_id,
            "/photo/vacation",
            offset=0,
            limit=50,
        )
        with pytest.raises(SynologyClientError) as error:
            await service.list_directory(
                connection.connection_id,
                "/photo",
                limit=51,
            )
        await service.disconnect(connection.connection_id)
        return files, has_more, error.value

    files, has_more, error = run(scenario())
    assert [item.name for item in files] == ["sample.jpg"]
    assert not has_more
    assert error.category == "invalid_pagination"


def test_selection_total_and_ten_photo_limit_are_enforced_by_service(tmp_path) -> None:
    factory, _ = make_client_factory()
    service, _ = make_service(tmp_path, factory)

    async def scenario():
        diagnostic = await service.connect(
            name="NAS",
            server_url="https://nas.example",
            username="reader",
            password="secret",
        )
        await service.list_directory(diagnostic.connection_id, "/photo/vacation")
        count, total = service.update_selection(
            diagnostic.connection_id,
            "/photo/vacation/sample.jpg",
            selected=True,
        )
        connection = service.get_connection(diagnostic.connection_id)
        for index in range(10):
            path = f"/photo/vacation/other-{index}.jpg"
            connection.known_files[path] = connection.known_files["/photo/vacation/sample.jpg"]
            connection.known_files[path] = replace(
                connection.known_files[path],
                name=f"other-{index}.jpg",
                path=path,
            )
            if index < 9:
                service.update_selection(
                    diagnostic.connection_id,
                    path,
                    selected=True,
                )
        with pytest.raises(SynologyClientError) as error:
            service.update_selection(
                diagnostic.connection_id,
                "/photo/vacation/other-9.jpg",
                selected=True,
            )
        await service.disconnect(diagnostic.connection_id)
        return count, total, error.value

    count, total, error = run(scenario())
    assert count == 1
    assert total > 0
    assert error.category == "test_limit"
