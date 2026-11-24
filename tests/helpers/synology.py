import asyncio
import json
from collections.abc import Callable
from urllib.parse import parse_qs

import httpx

PHOTO_PATH = "/photo/vacation/sample.jpg"
PHOTO_BYTES = b"photobridge-original-image"
PHOTO_SIZE = len(PHOTO_BYTES)


class MemoryCredentials:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get_password(self, key: str) -> str | None:
        return self.values.get(key)

    def set_password(self, key: str, password: str) -> None:
        self.values[key] = password


class BytesAsyncStream(httpx.AsyncByteStream):
    def __init__(self, value: bytes) -> None:
        self.value = value

    async def __aiter__(self):
        yield self.value

    async def aclose(self) -> None:
        return None


def run(awaitable):
    return asyncio.run(awaitable)


def make_client_factory(
    *,
    auth_code: int | None = None,
    include_thumbnail: bool = True,
    include_download: bool = True,
    file_bytes: bytes = PHOTO_BYTES,
    getinfo_size: int | None = None,
    download_response: httpx.Response | None = None,
    download_stream: httpx.AsyncByteStream | None = None,
    quickconnect_redirect: str | None = None,
    auth_redirect: str | None = None,
    discovery_response: httpx.Response | None = None,
    connect_error: bool = False,
    include_photos: bool = False,
    photos_download_response: httpx.Response | None = None,
    photos_permission_error: bool = False,
) -> tuple[Callable[..., httpx.AsyncClient], list[httpx.Request]]:
    requests: list[httpx.Request] = []
    apis = {
        "SYNO.API.Auth": {
            "path": "auth.cgi",
            "minVersion": 1,
            "maxVersion": 7,
        },
        "SYNO.FileStation.List": {
            "path": "FileStation/file_share.cgi",
            "minVersion": 1,
            "maxVersion": 2,
        },
    }
    if include_download:
        apis["SYNO.FileStation.Download"] = {
            "path": "FileStation/file_download.cgi",
            "minVersion": 1,
            "maxVersion": 2,
        }
    if include_thumbnail:
        apis["SYNO.FileStation.Thumb"] = {
            "path": "FileStation/file_thumb.cgi",
            "minVersion": 1,
            "maxVersion": 2,
        }
    photo_apis = {
        "SYNO.Foto.Browse.Item": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 1},
        "SYNO.Foto.Browse.Folder": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 1},
        "SYNO.Foto.Browse.Album": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 1},
        "SYNO.Foto.Thumbnail": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 1},
        "SYNO.Foto.Download": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 1},
        "SYNO.FotoTeam.Browse.Item": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 1},
        "SYNO.FotoTeam.Browse.Folder": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 1},
        "SYNO.FotoTeam.Thumbnail": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 1},
        "SYNO.FotoTeam.Download": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 1},
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if connect_error:
            raise httpx.ConnectError("mock connection refused", request=request)
        if (
            quickconnect_redirect is not None
            and request.url.host == "quickconnect.to"
            and request.url.path.strip("/")
            and not request.url.path.startswith("/webapi/")
        ):
            return httpx.Response(
                302,
                headers={
                    "location": quickconnect_redirect,
                    "set-cookie": "qc_cookie=discard-me; Path=/",
                },
                request=request,
            )
        if (
            quickconnect_redirect is not None
            and request.url.host != "quickconnect.to"
            and request.url.path == "/"
        ):
            return httpx.Response(
                200,
                text="<html><title>DSM</title></html>",
                headers={"content-type": "text/html"},
                request=request,
            )
        body = parse_qs(request.content.decode()) if request.content else {}
        params = dict(request.url.params)
        params.update({key: value[0] for key, value in body.items()})
        method = params.get("method")
        api = params.get("api")
        if request.url.path.endswith("/query.cgi"):
            if discovery_response is not None:
                return discovery_response
            if request.url.path.startswith("/photo/webapi/"):
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": photo_apis if include_photos else {},
                    },
                )
            return httpx.Response(200, json={"success": True, "data": apis})
        if api == "SYNO.API.Auth" and method == "login":
            if request.method != "POST":
                return httpx.Response(405)
            if auth_redirect is not None:
                return httpx.Response(
                    302,
                    headers={"location": auth_redirect},
                    request=request,
                )
            if auth_code is not None:
                return httpx.Response(200, json={"success": False, "error": {"code": auth_code}})
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"sid": "private-session", "SynoToken": "private-token"},
                },
                headers={"set-cookie": "id=private-session; Path=/"},
            )
        if api == "SYNO.API.Auth" and method == "logout":
            return httpx.Response(200, json={"success": True, "data": {}})
        if api == "SYNO.FileStation.List" and method == "list_share":
            shares = [
                {"name": "photo", "path": "/photo", "isdir": True},
                {"name": "homes", "path": "/homes", "isdir": True},
            ]
            offset = int(params.get("offset", "0"))
            limit = int(params.get("limit", "50"))
            return httpx.Response(
                200,
                json={"success": True, "data": {"shares": shares[offset : offset + limit]}},
            )
        if api == "SYNO.FileStation.List" and method in {"list", "getinfo"}:
            path = json.loads(params.get("folder_path", params.get("path", '"/photo"')))
            if method == "getinfo":
                size = getinfo_size if getinfo_size is not None else len(file_bytes)
                files = [
                    {
                        "name": path.rsplit("/", 1)[-1],
                        "path": path,
                        "isdir": False,
                        "additional": {"size": size, "time": {"mtime": 1_700_000_000}},
                    }
                ]
            elif path == "/photo":
                files = [
                    {"name": "vacation", "path": "/photo/vacation", "isdir": True},
                    {
                        "name": "sample.jpg",
                        "path": "/photo/sample.jpg",
                        "isdir": False,
                        "additional": {"size": 20, "time": {"mtime": 1_700_000_000}},
                    },
                    {
                        "name": "notes.txt",
                        "path": "/photo/notes.txt",
                        "isdir": False,
                        "additional": {"size": 4},
                    },
                ]
            elif path == "/photo/vacation":
                files = [
                    {
                        "name": PHOTO_PATH.rsplit("/", 1)[-1],
                        "path": PHOTO_PATH,
                        "isdir": False,
                        "additional": {
                            "size": len(file_bytes),
                            "time": {"mtime": 1_700_000_000},
                        },
                    },
                    {
                        "name": "notes.txt",
                        "path": "/photo/vacation/notes.txt",
                        "isdir": False,
                        "additional": {"size": 4},
                    },
                ]
            else:
                files = []
            if method == "list":
                offset = int(params.get("offset", "0"))
                limit = int(params.get("limit", "50"))
                files = files[offset : offset + limit]
            return httpx.Response(200, json={"success": True, "data": {"files": files}})
        if api == "SYNO.FileStation.Download" and method == "download":
            if download_response is not None:
                return download_response
            if download_stream is not None:
                return httpx.Response(
                    200,
                    stream=download_stream,
                    headers={"content-type": "image/jpeg"},
                )
            return httpx.Response(
                200,
                stream=BytesAsyncStream(file_bytes),
                headers={"content-type": "image/jpeg"},
            )
        if include_photos and api in {
            "SYNO.Foto.Browse.Folder",
            "SYNO.FotoTeam.Browse.Folder",
        } and method == "list":
            if photos_permission_error:
                return httpx.Response(
                    200,
                    json={"success": False, "error": {"code": 403}},
                )
            space = "shared" if "FotoTeam" in api else "personal"
            all_folders = [{"id": 5, "name": "/2024", "owner_user_id": 1, "parent": 0}]
            if space == "shared":
                all_folders = [
                    {"id": 1, "name": "/", "owner_user_id": 0, "parent": 1},
                    {"id": 7, "name": "/Shared", "owner_user_id": 0, "parent": 1},
                ]
            offset = int(params.get("offset", "0"))
            limit = int(params.get("limit", "50"))
            return httpx.Response(
                200,
                json={"success": True, "data": {"list": all_folders[offset : offset + limit]}},
            )
        if include_photos and api in {
            "SYNO.Foto.Browse.Item",
            "SYNO.FotoTeam.Browse.Item",
        } and method == "list":
            if photos_permission_error:
                return httpx.Response(
                    200,
                    json={"success": False, "error": {"code": 403}},
                )
            is_shared = "FotoTeam" in api
            rows = [
                {
                    "id": 901,
                    "filename": "landscape.jpg",
                    "filesize": len(file_bytes),
                    "folder_id": 5 if not is_shared else 7,
                    "time": 1_700_000_000,
                    "type": "photo",
                    "additional": {
                        "thumbnail": {
                            "cache_key": "901_1700000000",
                            "sm": "ready",
                            "xl": "ready",
                        },
                        "resolution": {"width": 1920, "height": 1080},
                        "orientation": 1,
                        "exif": {"camera": "Test Camera"},
                    },
                },
                {
                    "id": 902,
                    "filename": "second.png",
                    "filesize": len(file_bytes),
                    "folder_id": 5 if not is_shared else 7,
                    "time": 1_690_000_000,
                    "type": "photo",
                    "additional": {"thumbnail": {"cache_key": "902_1690000000"}},
                },
                {
                    "id": 903,
                    "filename": "clip.mp4",
                    "filesize": 5,
                    "folder_id": 5 if not is_shared else 7,
                    "time": 1_690_000_000,
                    "type": "video",
                },
            ]
            if params.get("folder_id"):
                rows = [
                    row for row in rows
                    if row["folder_id"] == int(params["folder_id"])
                ]
            if params.get("album_id"):
                rows = rows[:1]
            offset = int(params.get("offset", "0"))
            limit = int(params.get("limit", "50"))
            return httpx.Response(
                200,
                json={"success": True, "data": {"list": rows[offset : offset + limit]}},
            )
        if include_photos and api == "SYNO.Foto.Browse.Album" and method == "list":
            albums = [
                {
                    "id": 19,
                    "name": "Viajes",
                    "item_count": 2,
                    "owner_user_id": 1,
                    "create_time": 1_700_000_000,
                }
            ]
            offset = int(params.get("offset", "0"))
            limit = int(params.get("limit", "50"))
            return httpx.Response(
                200,
                json={"success": True, "data": {"list": albums[offset : offset + limit]}},
            )
        if include_photos and api in {
            "SYNO.Foto.Thumbnail",
            "SYNO.FotoTeam.Thumbnail",
        }:
            return httpx.Response(
                200,
                stream=BytesAsyncStream(b"\xff\xd8photos-thumbnail"),
                headers={"content-type": "image/jpeg"},
            )
        if include_photos and api in {"SYNO.Foto.Download", "SYNO.FotoTeam.Download"}:
            if photos_download_response is not None:
                return photos_download_response
            return httpx.Response(
                200,
                stream=BytesAsyncStream(file_bytes),
                headers={"content-type": "image/jpeg"},
            )
        if api == "SYNO.FileStation.Thumb":
            return httpx.Response(
                200, content=b"\xff\xd8thumbnail", headers={"content-type": "image/jpeg"}
            )
        return httpx.Response(404, json={"success": False, "error": {"code": 999}})

    def factory(**kwargs) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    return factory, requests
