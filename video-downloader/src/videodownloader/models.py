from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path
from typing import Any


class JobState(StrEnum):
    QUEUED = auto()
    PROBING = auto()
    WAITING_USER = auto()
    DOWNLOADING = auto()
    POSTPROCESSING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class ErrorKind(StrEnum):
    CANCELLED = auto()
    DEPENDENCY_MISSING = auto()
    UNSUPPORTED_URL = auto()
    AUTH_REQUIRED = auto()
    TOKEN_REQUIRED = auto()
    HTTP_FORBIDDEN = auto()
    DRM_PROTECTED = auto()
    FORMAT_UNAVAILABLE = auto()
    NETWORK_TRANSIENT = auto()
    POSTPROCESS_FAILED = auto()
    FILE_NOT_FOUND = auto()
    UNEXPECTED_CONTENT = auto()
    DISK_FULL = auto()
    SIZE_MISMATCH = auto()
    UNKNOWN = auto()


@dataclass(frozen=True, slots=True)
class Job:
    url: str
    mode: str = "video"
    state: JobState = JobState.QUEUED
    http_headers: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    cookie_file: Path | None = None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    id: str
    title: str
    webpage_url: str
    uploader: str = ""
    duration: int | float | None = None
    formats: tuple[dict[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class DownloadResult:
    success: bool
    output_path: Path | None = None
    media_info: MediaInfo | None = None
    error_kind: ErrorKind | None = None
    message: str = ""


@dataclass(frozen=True, slots=True)
class MediaInfo:
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str = ""
    audio_codec: str = ""
    container: str = ""

    @property
    def resolution(self) -> str:
        if self.width is not None and self.height is not None:
            return f"{self.width}×{self.height}"
        if self.height is not None:
            return f"{self.height}p"
        return ""
