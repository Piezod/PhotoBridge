from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.presentation.api.routes import router as api_router

BASE_DIR = Path(__file__).parent
settings = get_settings()

app = FastAPI(title=settings.app_name)
app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "presentation" / "static"),
    name="static",
)
templates = Jinja2Templates(directory=BASE_DIR / "presentation" / "templates")
app.include_router(api_router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"app_name": settings.app_name},
    )

