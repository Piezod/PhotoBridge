import json
import ssl
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx

from app.domain.models.synology import ApiDescription, RemoteFile

ApiRegistry = dict[str, ApiDescription]
ClientFactory = Callable[..., httpx.AsyncClient]
QUICKCONNECT_HOSTS = frozenset({"quickconnect.to", "quickconnect.cn"})
MAX_QUICKCONNECT_REDIRECTS = 5


class SynologyClientError(Exception):
    def __init__(
        self,
        code: int | None,
        message: str,
        *,
        category: str = "api_error",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.category = category


class SynologyApiClient:
    def __init__(
        self,
        server_url: str,
        *,
        timeout: float = 15,
        verify: bool | ssl.SSLContext = True,
        client_factory: ClientFactory = httpx.AsyncClient,
        quickconnect: bool = False,
    ) -> None:
        self.server_url = server_url.rstrip("/") + "/"
        self.timeout = timeout
        self.verify = verify
        self.client_factory = client_factory
        self.quickconnect = quickconnect
        self._http: httpx.AsyncClient | None = None
        self.apis: ApiRegistry = {}
        self.authenticated = False
        self.synology_token: str | None = None
        self.synology_sid: str | None = None

    async def open(self) -> None:
        self._http = self.client_factory(
            timeout=httpx.Timeout(self.timeout),
            verify=self.verify,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        )

    async def resolve_quickconnect_alias(self) -> None:
        parts = urlsplit(self.server_url)
        hostname = (parts.hostname or "").lower()
        if hostname not in QUICKCONNECT_HOSTS or not parts.path.strip("/"):
            return

        current_url = self.server_url.rstrip("/")
        visited: set[str] = set()
        for _ in range(MAX_QUICKCONNECT_REDIRECTS + 1):
            if current_url in visited:
                raise SynologyClientError(
                    None,
                    "QuickConnect devolvió una cadena de redirecciones circular.",
                    category="quickconnect_redirect",
                )
            visited.add(current_url)
            response = await self._send_request("GET", current_url)
            if 300 <= response.status_code < 400:
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    raise SynologyClientError(
                        None,
                        "QuickConnect devolvió una redirección sin destino.",
                        category="quickconnect_redirect",
                    )
                target_url = urljoin(current_url, location)
                self._validate_quickconnect_redirect(target_url)
                current_url = target_url
                self._require_http().cookies.clear()
                continue

            if response.status_code >= 400:
                await response.aclose()
                raise SynologyClientError(
                    None,
                    f"QuickConnect respondió HTTP {response.status_code} al resolver el NAS.",
                    category="quickconnect_resolution",
                )
            resolved = urlsplit(str(response.url))
            resolved_host = (resolved.hostname or "").lower()
            if resolved_host in QUICKCONNECT_HOSTS:
                raise SynologyClientError(
                    None,
                    "QuickConnect no resolvió a un endpoint DSM regional.",
                    category="quickconnect_unresolved",
                )
            self.server_url = urlunsplit(
                (resolved.scheme, resolved.netloc, "/", "", "")
            )
            await response.aclose()
            self._require_http().cookies.clear()
            return

        raise SynologyClientError(
            None,
            "QuickConnect excedió el máximo de redirecciones permitidas.",
            category="quickconnect_redirect",
        )

    async def discover(self) -> ApiRegistry:
        self.apis = await self._discover_at(self._webapi_url("query.cgi"))
        return self.apis

    async def discover_photos(self) -> ApiRegistry:
        photos_apis = {
            name: api
            for name, api in self.apis.items()
            if name.startswith(("SYNO.Foto.", "SYNO.FotoTeam."))
        }
        if not photos_apis:
            registry = await self._discover_at(
                urljoin(self.server_url, "webapi/entry.cgi")
            )
            photos_apis = {
                name: api
                for name, api in registry.items()
                if name.startswith(("SYNO.Foto.", "SYNO.FotoTeam."))
            }

        for name in (
            "SYNO.Foto.Browse.SimilarTimeline",
            "SYNO.Foto.Browse.SimilarItem",
            "SYNO.FotoTeam.Browse.SimilarTimeline",
            "SYNO.FotoTeam.Browse.SimilarItem",
        ):
            if name not in photos_apis:
                photos_apis[name] = ApiDescription(
                    name=name,
                    path="entry.cgi",
                    min_version=1,
                    max_version=1,
                )
        return photos_apis

    async def _discover_at(self, url: str) -> ApiRegistry:
        response = await self._request(
            "GET",
            url,
            params={
                "api": "SYNO.API.Info",
                "version": "1",
                "method": "query",
                "query": "all",
            },
        )
        data = self._decode_json(response)
        try:
            self._raise_for_api_error(data, api_name="SYNO.API.Info", method="query")
        except SynologyClientError as exc:
            if self.quickconnect and exc.category == "api_error":
                raise SynologyClientError(
                    exc.code,
                    "QuickConnect devolvió JSON, pero no una respuesta válida de SYNO.API.Info.",
                    category="quickconnect_api_unavailable",
                ) from exc
            raise
        api_data = data.get("data")
        if not isinstance(api_data, dict):
            if self.quickconnect:
                raise SynologyClientError(
                    None,
                    "El endpoint resuelto de QuickConnect no expone SYNO.API.Info.",
                    category="quickconnect_api_unavailable",
                )
            raise SynologyClientError(None, "El servidor no devolvió APIs disponibles.")

        return self._parse_api_registry(api_data)

    async def login(self, username: str, password: str, otp_code: str | None = None) -> None:
        data = await self.api_request(
            "SYNO.API.Auth",
            "login",
            {
                "account": username,
                "passwd": password,
                "session": "FileStation",
                "format": "cookie",
                "enable_syno_token": "yes",
                **({"otp_code": otp_code} if otp_code else {}),
            },
            http_method="POST",
        )
        if not self._require_http().cookies.get("id"):
            raise SynologyClientError(
                None,
                "Synology no devolvió una cookie de sesión válida.",
                category="authentication",
            )
        self.authenticated = True
        token = data.get("SynoToken", data.get("synotoken"))
        self.synology_token = token if isinstance(token, str) and token else None
        sid = data.get("sid")
        self.synology_sid = sid if isinstance(sid, str) and sid else None

    async def logout(self) -> None:
        if self._http is None or not self.authenticated:
            return
        auth = self.apis.get("SYNO.API.Auth")
        if auth is None:
            return
        try:
            await self.api_request(
                "SYNO.API.Auth",
                "logout",
                {"session": "FileStation"},
                http_method="POST",
            )
        finally:
            self.authenticated = False
            self.synology_token = None
            self.synology_sid = None

    async def list_shares(self, offset: int = 0, limit: int = 50) -> list[RemoteFile]:
        self._validate_pagination(offset, limit)
        data = await self.api_request(
            "SYNO.FileStation.List",
            "list_share",
            {
                "offset": str(offset),
                "limit": str(limit),
                "additional": json.dumps(["volume_status"]),
            },
        )
        shares = data.get("shares", [])
        if not isinstance(shares, list):
            raise SynologyClientError(None, "Respuesta de carpetas compartidas inválida.")
        return [self._parse_file(item, "/") for item in shares if isinstance(item, dict)]

    async def list_directory(
        self,
        path: str,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[RemoteFile], bool]:
        self._validate_pagination(offset, limit)
        self.validate_remote_path(path)
        api = self._require_api("SYNO.FileStation.List")
        params = {
            "folder_path": json.dumps(path),
            "offset": str(offset),
            "limit": str(limit),
            "additional": json.dumps(["size", "time", "type"]),
        }
        data = await self._api_request(api, "list", params)
        files = data.get("files", [])
        if not isinstance(files, list):
            raise SynologyClientError(None, "Respuesta de contenido de carpeta inválida.")
        parsed = [self._parse_file(item, path) for item in files if isinstance(item, dict)]
        return parsed, len(parsed) == limit

    async def get_file_info(self, path: str) -> RemoteFile:
        self.validate_remote_path(path)
        api = self._require_api("SYNO.FileStation.List")
        data = await self._api_request(
            api,
            "getinfo",
            {"path": json.dumps(path), "additional": json.dumps(["size", "time", "type"])},
        )
        files = data.get("files", [])
        if not isinstance(files, list) or not files or not isinstance(files[0], dict):
            raise SynologyClientError(None, "Synology no devolvió información del archivo.")
        return self._parse_file(files[0], str(PurePosixPath(path).parent))

    async def stream_download(self, path: str) -> AsyncGenerator[bytes, None]:
        self.validate_remote_path(path)
        api = self._require_api("SYNO.FileStation.Download")
        url = self._api_url(api)
        params = {
            "api": api.name,
            "version": str(api.max_version),
            "method": "download",
            "path": json.dumps([path]),
            "mode": json.dumps("download"),
        }
        client = self._require_http()
        try:
            async with client.stream("GET", url, params=params) as response:
                self._check_http_status(response)
                content_type = response.headers.get("content-type", "").lower()
                if "text/html" in content_type or "application/json" in content_type:
                    raise SynologyClientError(
                        None,
                        "Synology devolvió una respuesta de error en vez del archivo.",
                    )
                async for chunk in response.aiter_raw():
                    if chunk:
                        yield chunk
        except httpx.TimeoutException as exc:
            raise SynologyClientError(
                None, "La descarga superó el tiempo de espera.", category="timeout"
            ) from exc
        except httpx.TransportError as exc:
            raise SynologyClientError(
                None, "Se interrumpió la conexión durante la descarga.", category="transport"
            ) from exc

    async def stream_thumbnail(self, path: str) -> tuple[str, AsyncIterator[bytes]]:
        self.validate_remote_path(path)
        api = self._require_api("SYNO.FileStation.Thumb")
        url = self._api_url(api)
        params = {
            "api": api.name,
            "version": str(api.max_version),
            "method": "get",
            "path": json.dumps(path),
            "size": "small",
            "rotate": "0",
        }
        response = await self._request("GET", url, params=params)
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if not content_type.startswith("image/"):
            await response.aclose()
            raise SynologyClientError(None, "Synology no devolvió una miniatura de imagen.")

        async def chunks() -> AsyncIterator[bytes]:
            try:
                async for chunk in response.aiter_bytes(chunk_size=32 * 1024):
                    if chunk:
                        if chunk.lstrip().startswith((b"{", b"<")):
                            raise SynologyClientError(
                                None,
                                "Synology devolvió JSON o HTML en vez del archivo original.",
                            )
                        yield chunk
            finally:
                await response.aclose()

        return content_type, chunks()

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def api_request(
        self,
        name: str,
        method: str,
        params: dict[str, str],
        *,
        http_method: str = "GET",
    ) -> dict[str, Any]:
        api = self._require_api(name)
        return await self._api_request(api, method, params, http_method=http_method)

    async def _api_request(
        self,
        api: ApiDescription,
        method: str,
        params: dict[str, str],
        *,
        http_method: str = "GET",
        endpoint_prefix: str = "webapi",
    ) -> dict[str, Any]:
        values = {
            "api": api.name,
            "version": str(api.max_version),
            "method": method,
            **params,
        }
        response = await self._request(
            http_method,
            self._api_url_at(api, endpoint_prefix),
            params=values if http_method == "GET" else None,
            data=values if http_method == "POST" else None,
            headers=self._api_headers(endpoint_prefix),
        )
        data = self._decode_json(response)
        self._raise_for_api_error(data, api_name=api.name, method=method)
        result = data.get("data", {})
        if not isinstance(result, dict):
            raise SynologyClientError(None, "Respuesta de API de Synology inválida.")
        return result

    async def api_request_at(
        self,
        api: ApiDescription,
        method: str,
        params: dict[str, str],
        *,
        endpoint_prefix: str,
        http_method: str = "GET",
    ) -> dict[str, Any]:
        return await self._api_request(
            api,
            method,
            params,
            http_method=http_method,
            endpoint_prefix=endpoint_prefix,
        )

    async def stream_api_at(
        self,
        api: ApiDescription,
        method: str,
        params: dict[str, str],
        *,
        endpoint_prefix: str,
        http_method: str = "GET",
    ) -> AsyncGenerator[bytes, None]:
        _, chunks = await self.open_api_stream_at(
            api,
            method,
            params,
            endpoint_prefix=endpoint_prefix,
            http_method=http_method,
        )
        try:
            async for chunk in chunks:
                yield chunk
        finally:
            await chunks.aclose()

    async def open_api_stream_at(
        self,
        api: ApiDescription,
        method: str,
        params: dict[str, str],
        *,
        endpoint_prefix: str,
        require_image: bool = False,
        http_method: str = "GET",
    ) -> tuple[str, AsyncGenerator[bytes, None]]:
        url = self._api_url_at(api, endpoint_prefix)
        values = {
            "api": api.name,
            "version": str(api.max_version),
            "method": method,
            **params,
        }
        return await self._open_stream(
            url,
            values,
            headers=self._api_headers(endpoint_prefix),
            require_image=require_image,
            http_method=http_method,
        )

    async def open_photo_thumbnail_stream(
        self,
        item_id: int,
        cache_key: str,
        *,
        size: str,
        team_space: bool,
    ) -> tuple[str, AsyncGenerator[bytes, None]]:
        space = "t" if team_space else "p"
        url = urljoin(
            self.server_url,
            f"synofoto/api/v2/{space}/Thumbnail/get",
        )
        params = {
            "id": str(item_id),
            "cache_key": cache_key,
            "type": "unit",
            "size": size,
        }
        if self.synology_token:
            params["SynoToken"] = self.synology_token
        return await self._open_stream(
            url,
            params,
            headers=self._api_headers("webapi"),
            require_image=True,
        )

    async def _open_stream(
        self,
        url: str,
        params: dict[str, str],
        *,
        headers: dict[str, str],
        require_image: bool,
        http_method: str = "GET",
    ) -> tuple[str, AsyncGenerator[bytes, None]]:
        try:
            request = self._require_http().build_request(
                http_method,
                url,
                params=params if http_method == "GET" else None,
                data=params if http_method == "POST" else None,
                headers=headers,
            )
            response = await self._require_http().send(request, stream=True)
            try:
                self._check_http_status(response)
            except SynologyClientError:
                await response.aclose()
                raise
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if (
                content_type in {"text/html", "application/json", "text/json"}
                or content_type in {"application/zip", "application/x-zip-compressed"}
                or require_image and not content_type.startswith("image/")
            ):
                await response.aclose()
                raise SynologyClientError(
                    None,
                    "Synology Photos devolvió una respuesta que no es el archivo solicitado.",
                    category="unexpected_response",
                )

            async def chunks() -> AsyncGenerator[bytes, None]:
                first_chunk = True
                try:
                    async for chunk in response.aiter_bytes():
                        if not chunk:
                            continue
                        if first_chunk and chunk.lstrip().startswith((b"{", b"<", b"PK\x03\x04")):
                            raise SynologyClientError(
                                None,
                                "Synology Photos devolvió un error en vez del archivo original.",
                                category="unexpected_response",
                            )
                        first_chunk = False
                        yield chunk
                except httpx.TimeoutException as exc:
                    raise SynologyClientError(
                        None,
                        "La descarga desde Synology Photos superó el tiempo de espera.",
                        category="timeout",
                    ) from exc
                except httpx.TransportError as exc:
                    raise SynologyClientError(
                        None,
                        "Se interrumpió la descarga desde Synology Photos.",
                        category="transport",
                    ) from exc
                finally:
                    await response.aclose()

            return content_type or "application/octet-stream", chunks()
        except httpx.TimeoutException as exc:
            raise SynologyClientError(
                None,
                "La solicitud a Synology Photos superó el tiempo de espera.",
                category="timeout",
            ) from exc
        except httpx.TransportError as exc:
            raise SynologyClientError(
                None,
                "Se interrumpió la conexión con Synology Photos.",
                category="transport",
            ) from exc

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        response = await self._send_request(method, url, **kwargs)
        self._check_http_status(response)
        return response

    async def _send_request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._require_http().request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise SynologyClientError(
                None, "El servidor superó el tiempo de espera.", category="timeout"
            ) from exc
        except httpx.ConnectError as exc:
            if any(marker in str(exc).casefold() for marker in ("certificate", "ssl", "tls")):
                raise SynologyClientError(
                    None,
                    "El certificado TLS no es válido. Configura una CA de confianza si procede.",
                    category="tls_error",
                ) from exc
            raise SynologyClientError(
                None, "No se pudo conectar con el servidor Synology.", category="unreachable"
            ) from exc
        except httpx.TransportError as exc:
            raise SynologyClientError(
                None, "Error de transporte al conectar con Synology.", category="transport"
            ) from exc

    @classmethod
    def _validate_quickconnect_redirect(cls, value: str) -> None:
        if len(value) > 2048:
            raise SynologyClientError(
                None,
                "QuickConnect devolvió un destino de redirección demasiado largo.",
                category="quickconnect_redirect",
            )
        try:
            parts = urlsplit(value)
            hostname = parts.hostname
            port = parts.port
        except ValueError as exc:
            raise SynologyClientError(
                None,
                "QuickConnect devolvió un destino de redirección no válido.",
                category="quickconnect_redirect",
            ) from exc
        normalized_host = (hostname or "").lower().rstrip(".")
        if (
            parts.scheme != "https"
            or not normalized_host
            or parts.username
            or parts.password
            or parts.fragment
            or (port is not None and not 1 <= port <= 65535)
            or not cls._is_quickconnect_host(normalized_host)
        ):
            raise SynologyClientError(
                None,
                "QuickConnect intentó redirigir a un destino HTTPS no autorizado.",
                category="quickconnect_redirect_untrusted",
            )
        decoded_path = unquote(parts.path)
        if (
            "\\" in decoded_path
            or any(ord(character) < 32 for character in decoded_path)
            or any(segment in {".", ".."} for segment in decoded_path.split("/"))
        ):
            raise SynologyClientError(
                None,
                "QuickConnect devolvió una ruta de redirección no válida.",
                category="quickconnect_redirect",
            )

    @staticmethod
    def _is_quickconnect_host(hostname: str) -> bool:
        return any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in QUICKCONNECT_HOSTS
        )

    def _decode_json(self, response: httpx.Response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "").casefold()
        body_start = response.content.lstrip()[:32].lower()
        if "text/html" in content_type or body_start.startswith(
            (b"<!doctype html", b"<html")
        ):
            if self.quickconnect:
                raise SynologyClientError(
                    None,
                    "QuickConnect devolvió una página HTML, no la API DSM. "
                    "Comprueba que el endpoint resuelto permite el acceso a DSM API.",
                    category="quickconnect_api_unavailable",
                )
            raise SynologyClientError(
                None,
                "El servidor devolvió HTML en lugar de la respuesta JSON de Synology.",
                category="unexpected_response",
            )
        try:
            data = response.json()
        except ValueError as exc:
            if self.quickconnect:
                raise SynologyClientError(
                    None,
                    "QuickConnect no devolvió JSON de SYNO.API.Info.",
                    category="quickconnect_api_unavailable",
                ) from exc
            raise SynologyClientError(
                None,
                "El servidor no devolvió una respuesta JSON de Synology.",
            ) from exc
        if not isinstance(data, dict):
            raise SynologyClientError(None, "Respuesta JSON de Synology inválida.")
        return data

    @staticmethod
    def _raise_for_api_error(
        data: dict[str, Any],
        *,
        api_name: str,
        method: str,
    ) -> None:
        if data.get("success") is True:
            return
        error = data.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        is_login = api_name == "SYNO.API.Auth" and method == "login"
        if code == 403 and is_login:
            raise SynologyClientError(
                code,
                "Synology requiere el código de verificación MFA. Introdúcelo manualmente.",
                category="mfa_required",
            )
        if code == 404 and is_login:
            raise SynologyClientError(
                code,
                "El código de verificación MFA no es válido. No se realizará otro intento.",
                category="mfa_invalid",
            )
        if api_name.startswith("SYNO.FileStation.") and code in {401, 403}:
            raise SynologyClientError(
                code,
                "La cuenta Synology no tiene permiso para esta operación de File Station.",
                category="permission",
            )
        if api_name.startswith("SYNO.FileStation.") and code == 404:
            raise SynologyClientError(
                code,
                "El archivo o la carpeta remotos ya no existen.",
                category="remote_not_found",
            )
        if api_name.startswith(("SYNO.Foto.", "SYNO.FotoTeam.")) and code in {401, 403}:
            raise SynologyClientError(
                code,
                "La cuenta Synology no tiene permiso para esta operación de Synology Photos.",
                category="permission",
            )
        if code in {400, 401, 402, 409} and is_login:
            raise SynologyClientError(
                code,
                "Synology rechazó la autenticación o la cuenta no puede iniciar sesión.",
                category="authentication",
            )
        if code in {105, 106}:
            raise SynologyClientError(
                code,
                "La sesión de Synology caducó o no tiene permisos para esta operación.",
                category="session_or_permission",
            )
        raise SynologyClientError(
            code if isinstance(code, int) else None,
            "Synology rechazó la solicitud de API.",
            category="api_error",
        )

    @staticmethod
    def _check_http_status(response: httpx.Response) -> None:
        if 300 <= response.status_code < 400:
            raise SynologyClientError(
                None,
                "El servidor redirigió la solicitud; no se siguió para proteger las credenciales.",
                category="redirect",
            )
        if response.status_code >= 400:
            raise SynologyClientError(
                None,
                f"El servidor Synology respondió HTTP {response.status_code}.",
                category="http_error",
            )

    def _webapi_url(self, path: str) -> str:
        return urljoin(self.server_url, f"webapi/{path}")

    def _api_url(self, api: ApiDescription) -> str:
        return self._api_url_at(api, "webapi")

    def _api_url_at(self, api: ApiDescription, endpoint_prefix: str) -> str:
        raw_path = api.path.strip("/")
        prefix = endpoint_prefix.strip("/")
        is_absolute_api_path = raw_path.startswith(f"{prefix}/")
        if not is_absolute_api_path and raw_path.startswith("webapi/"):
            raw_path = raw_path.removeprefix("webapi/")
        decoded_path = unquote(raw_path)
        if not decoded_path or any(part in {"..", "."} for part in decoded_path.split("/")):
            raise SynologyClientError(None, "Synology anunció una ruta API no válida.")
        if "\\" in decoded_path or "?" in decoded_path or "#" in decoded_path:
            raise SynologyClientError(None, "Synology anunció una ruta API no válida.")
        if (
            not prefix
            or "\\" in prefix
            or "?" in prefix
            or "#" in prefix
            or any(part in {"..", "."} for part in prefix.split("/"))
        ):
            raise SynologyClientError(None, "La ruta base de API no es válida.")
        if is_absolute_api_path:
            return urljoin(self.server_url, raw_path)
        return urljoin(self.server_url, f"{prefix}/{raw_path}")

    def _api_headers(self, endpoint_prefix: str) -> dict[str, str]:
        return {"X-Syno-Token": self.synology_token} if self.synology_token else {}

    @staticmethod
    def _parse_api_registry(api_data: dict[str, Any]) -> ApiRegistry:
        discovered: ApiRegistry = {}
        for name, value in api_data.items():
            if not isinstance(value, dict):
                continue
            path = value.get("path")
            minimum = value.get("minVersion")
            maximum = value.get("maxVersion")
            request_format = value.get("requestFormat")
            if (
                isinstance(path, str)
                and isinstance(minimum, int)
                and isinstance(maximum, int)
                and minimum > 0
                and maximum >= minimum
            ):
                discovered[name] = ApiDescription(
                    name=name,
                    path=path,
                    min_version=minimum,
                    max_version=maximum,
                    request_format=request_format if isinstance(request_format, str) else None,
                )
        return discovered

    def _require_api(self, name: str) -> ApiDescription:
        api = self.apis.get(name)
        if api is None:
            raise SynologyClientError(
                None, f"La API {name} no está disponible.", category="api_unavailable"
            )
        return api

    def supports_api(self, name: str) -> bool:
        return name in self.apis

    def _require_http(self) -> httpx.AsyncClient:
        if self._http is None:
            raise SynologyClientError(None, "El cliente Synology no está abierto.")
        return self._http

    @staticmethod
    def validate_remote_path(path: str) -> None:
        if (
            not path.startswith("/")
            or path.startswith("//")
            or "\\" in path
            or "\x00" in path
            or any(part in {"", ".", ".."} for part in path.split("/")[1:])
        ):
            raise SynologyClientError(None, "La ruta remota no es segura.", category="invalid_path")

    @staticmethod
    def _validate_pagination(offset: int, limit: int) -> None:
        if offset < 0 or limit < 1 or limit > 50:
            raise SynologyClientError(
                None,
                "La paginación requiere offset no negativo y un máximo de 50 elementos.",
                category="invalid_pagination",
            )

    @staticmethod
    def _parse_file(item: dict[str, Any], parent: str) -> RemoteFile:
        name = item.get("name")
        is_directory = item.get("isdir") is True
        path = item.get("path")
        if not isinstance(name, str) or not name or not isinstance(path, str):
            if not isinstance(name, str) or not name:
                raise SynologyClientError(None, "Synology devolvió un elemento sin nombre.")
            path = str(PurePosixPath(parent) / name)
        SynologyApiClient.validate_remote_path(path)
        additional = item.get("additional")
        additional = additional if isinstance(additional, dict) else {}
        size = additional.get("size")
        size = size if isinstance(size, int) and size >= 0 else None
        time_info = additional.get("time")
        mtime = time_info.get("mtime") if isinstance(time_info, dict) else None
        modified_at = (
            datetime.fromtimestamp(mtime, UTC) if isinstance(mtime, (int, float)) else None
        )
        suffix = PurePosixPath(name).suffix.lower().lstrip(".")
        return RemoteFile(
            name=name,
            path=path,
            is_directory=is_directory,
            size=size,
            modified_at=modified_at,
            extension=suffix,
        )
