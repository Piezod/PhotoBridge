import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.application.services.synology_connections import SynologyConnectionService
from app.application.services.synology_downloads import SynologyDownloadService
from app.config import get_settings
from app.infrastructure.security.keyring_store import KeyringCredentialStore
from app.presentation.api.csrf import render_template
from app.presentation.api.routes import router as api_router
from app.presentation.api.synology_routes import router as synology_router

BASE_DIR = Path(__file__).parent
settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    yield
    await application.state.synology_downloads.cancel_active()
    errors = await application.state.synology_connections.disconnect_all()
    for error in errors:
        logger.warning(
            "Synology logout failed during application shutdown",
            extra={"category": error.category},
        )


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.state.csrf_tokens = {}
app.state.synology_connections = SynologyConnectionService(
    settings,
    KeyringCredentialStore(),
)
app.state.synology_downloads = SynologyDownloadService(
    settings,
    app.state.synology_connections,
)
app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "presentation" / "static"),
    name="static",
)
app.include_router(api_router)
app.include_router(synology_router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home(request: Request) -> HTMLResponse:
    return render_template(
        request,
        "index.html",
        {"app_name": settings.app_name, "page": "home", "page_title": "Inicio"},
    )
