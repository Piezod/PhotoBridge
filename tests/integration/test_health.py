import asyncio

import httpx

from app.main import app


def get(path: str) -> httpx.Response:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get(path)

    return asyncio.run(request())


def test_health_returns_ok() -> None:
    response = get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_home_page_is_available_in_spanish() -> None:
    response = get("/")

    assert response.status_code == 200
    assert "PhotoBridge" in response.text
    assert 'lang="es"' in response.text
    assert "Conexiones" in response.text
    assert "Migraciones" in response.text


def test_ui_libraries_are_served_locally() -> None:
    bootstrap_response = get("/static/vendor/bootstrap.min.css")
    htmx_response = get("/static/vendor/htmx.min.js")

    assert bootstrap_response.status_code == 200
    assert htmx_response.status_code == 200
