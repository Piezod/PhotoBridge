from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class DownloadState(StrEnum):
    PENDING = "PENDING"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class ApiDescription:
    name: str
    path: str
    min_version: int
    max_version: int
    request_format: str | None = None


@dataclass(frozen=True)
class RemoteFile:
    name: str
    path: str
    is_directory: bool
    size: int | None
    modified_at: datetime | None
    extension: str


@dataclass
class DownloadItem:
    remote_path: str
    local_path: str
    expected_size: int
    source_type: str = "file_station"
    source_id: str | None = None
    state: DownloadState = DownloadState.PENDING
    downloaded_size: int = 0
    sha256: str | None = None
    error: str | None = None
    integrity_verified: bool = False
    partial_path: str | None = None


@dataclass
class DownloadOperation:
    operation_id: str
    connection_id: str
    connection_name: str
    started_at: datetime
    items: list[DownloadItem]
    state: DownloadState = DownloadState.PENDING
    completed_at: datetime | None = None
    current_item: str | None = None
    current_bytes: int = 0
    current_total: int = 0
    bytes_per_second: float = 0
    errors: list[str] = field(default_factory=list)
    report_path: str | None = None
    cancel_requested: bool = False
    album_id: str | None = None
    album_name: str | None = None
