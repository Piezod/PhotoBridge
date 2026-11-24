import hmac
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from starlette.templating import Jinja2Templates

from app.presentation.formatting import format_size

BASE_DIR = Path(__file__).parents[1]
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["format_size"] = format_size
CSRF_COOKIE = "photobridge_session"


def render_template(
    request: Request,
    name: str,
    context: dict[str, object] | None = None,
) -> HTMLResponse:
    session_id = request.cookies.get(CSRF_COOKIE)
    tokens: dict[str, str] = request.app.state.csrf_tokens
    if not session_id or session_id not in tokens:
        session_id = secrets.token_urlsafe(32)
        tokens[session_id] = secrets.token_urlsafe(32)
    page_context = dict(context or {})
    page_context.setdefault("app_name", "PhotoBridge")
    page_context["csrf_token"] = tokens[session_id]
    response = templates.TemplateResponse(
        request=request,
        name=name,
        context=page_context,
    )
    response.set_cookie(
        CSRF_COOKIE,
        session_id,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )
    return response


def validate_csrf(request: Request, submitted_token: str | None) -> None:
    origin = request.headers.get("origin")
    if origin:
        parsed_origin = urlsplit(origin)
        if (
            parsed_origin.netloc.casefold() != request.headers.get("host", "").casefold()
            or parsed_origin.scheme.casefold() != request.url.scheme.casefold()
        ):
            raise HTTPException(status_code=403, detail="Origen de solicitud no permitido.")
    session_id = request.cookies.get(CSRF_COOKIE)
    expected = request.app.state.csrf_tokens.get(session_id or "")
    if not expected or not submitted_token or not hmac.compare_digest(expected, submitted_token):
        raise HTTPException(status_code=403, detail="Token CSRF ausente o no válido.")


async def parse_protected_form(request: Request) -> Any:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type != "application/x-www-form-urlencoded":
        validate_csrf(request, request.headers.get("x-csrf-token"))
        raise HTTPException(
            status_code=415,
            detail="Este endpoint solo acepta formularios URL-encoded.",
        )
    try:
        values = parse_qs(
            (await request.body()).decode("utf-8"),
            keep_blank_values=True,
            max_num_fields=100,
            strict_parsing=False,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Formulario no válido.") from exc
    form = {key: items[-1] for key, items in values.items()}
    token = form.get("csrf_token") or request.headers.get("x-csrf-token")
    validate_csrf(request, str(token) if token is not None else None)
    return form
