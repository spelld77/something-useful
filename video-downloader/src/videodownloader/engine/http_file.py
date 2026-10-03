from __future__ import annotations

import errno
import json
import mimetypes
import random
import re
import shutil
import socket
import threading
import time
import unicodedata
from collections.abc import Callable
from contextlib import suppress
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, build_opener

from videodownloader.config import FileDownloadConfig
from videodownloader.engine.base import ProgressCallback
from videodownloader.engine.ytdlp_process import DownloadError, validate_url
from videodownloader.models import DownloadResult, ErrorKind, Job, ProbeResult
from videodownloader.storage.history import url_fingerprint

CHUNK_SIZE = 256 * 1024
READ_POLL_SECONDS = 2.0
PROGRESS_EMIT_INTERVAL_SECONDS = 0.25
INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
CONTENT_RANGE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", re.IGNORECASE)
UNSATISFIED_RANGE = re.compile(r"bytes\s+\*/(\d+)", re.IGNORECASE)
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def format_bytes(value: int | float | None) -> str:
    if value is None:
        return "알 수 없음"
    amount = float(value)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if abs(amount) < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{amount:.1f} TiB"


def safe_filename(value: str, *, fallback: str = "download.bin", max_length: int = 180) -> str:
    name = unicodedata.normalize("NFKC", Path(value.replace("\\", "/")).name)
    name = INVALID_FILENAME.sub("_", name).strip().rstrip(". ")
    if not name:
        name = fallback
    stem = Path(name).stem.rstrip(". ") or "download"
    suffix = Path(name).suffix
    if stem.upper() in RESERVED_NAMES:
        stem = f"_{stem}"
    available = max(1, max_length - len(suffix))
    stem = stem[:available].rstrip(". ") or "download"
    return f"{stem}{suffix}"


def response_filename(content_disposition: str, final_url: str, content_type: str) -> str:
    filename = ""
    if content_disposition:
        message = Message()
        message["content-disposition"] = content_disposition
        filename = message.get_filename() or ""
    if not filename:
        filename = unquote(Path(urlsplit(final_url).path).name)
    if not filename:
        media_type = content_type.partition(";")[0].strip().casefold()
        extension = mimetypes.guess_extension(media_type) or ".bin"
        filename = f"download{extension}"
    return safe_filename(filename)


def is_unexpected_html(content_type: str, content_disposition: str, final_url: str) -> bool:
    media_type = content_type.partition(";")[0].strip().casefold()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        return False
    if content_disposition.casefold().lstrip().startswith("attachment"):
        return False
    return Path(urlsplit(final_url).path).suffix.casefold() not in {".html", ".htm", ".xhtml"}


class FilenameRegistry:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._lock = threading.Lock()
        self._reserved: set[str] = set()

    def reserve(self, filename: str) -> Path:
        cleaned = safe_filename(filename)
        stem = Path(cleaned).stem
        suffix = Path(cleaned).suffix
        with self._lock:
            index = 0
            while True:
                candidate_name = cleaned if index == 0 else f"{stem} ({index}){suffix}"
                candidate = self.directory / candidate_name
                key = candidate_name.casefold()
                if key not in self._reserved and not candidate.exists():
                    self._reserved.add(key)
                    return candidate
                index += 1


class SpaceReservation:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._lock = threading.Lock()
        self._reserved = 0

    def reserve(self, required: int) -> bool:
        if required <= 0:
            return True
        with self._lock:
            free = shutil.disk_usage(self.directory).free
            if required + self._reserved > free:
                return False
            self._reserved += required
            return True

    def release(self, required: int) -> None:
        if required <= 0:
            return
        with self._lock:
            self._reserved = max(0, self._reserved - required)


class HttpFileEngine:
    def __init__(
        self,
        settings: FileDownloadConfig,
        registry: FilenameRegistry,
        space: SpaceReservation,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.space = space
        self.sleep = sleep
        self._cancel_requested = threading.Event()
        self._response_lock = threading.Lock()
        self._response: object | None = None

    def probe(self, job: Job) -> ProbeResult:
        raise DownloadError(
            ErrorKind.UNSUPPORTED_URL,
            "일반 파일 다운로드는 별도의 정보 확인을 제공하지 않습니다.",
        )

    def cancel(self) -> None:
        self._cancel_requested.set()
        with self._response_lock:
            response = self._response
        if response is not None:
            with suppress(OSError):
                response.close()  # type: ignore[attr-defined]

    def download(
        self,
        job: Job,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> DownloadResult:
        try:
            url = validate_url(job.url)
            save_dir = self.settings.save_dir.expanduser().resolve()
            save_dir.mkdir(parents=True, exist_ok=True)
        except DownloadError as exc:
            return DownloadResult(False, error_kind=exc.kind, message=exc.message)
        except OSError as exc:
            return DownloadResult(
                False,
                error_kind=ErrorKind.DEPENDENCY_MISSING,
                message=f"저장 폴더를 준비할 수 없습니다: {exc}",
            )

        fingerprint = url_fingerprint(url)
        part_path = save_dir / f".file-{fingerprint[:20]}.part"
        metadata_path = save_dir / f".file-{fingerprint[:20]}.json"
        metadata = self._load_metadata(metadata_path, fingerprint)
        if not self.settings.resume_partial:
            part_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            metadata = {}

        output_path: Path | None = None
        opener = build_opener()
        attempts = self.settings.retries + 1
        last_result: DownloadResult | None = None

        for attempt in range(1, attempts + 1):
            if self._cancel_requested.is_set():
                return self._cancelled_result()
            self._emit_progress(
                on_progress,
                phase="connecting",
                attempt=attempt,
                max_attempts=attempts,
            )
            resume_size = part_path.stat().st_size if part_path.exists() else 0
            headers = {
                "Accept-Encoding": "identity",
                "User-Agent": "VideoDownloader/0.5 (Windows file batch)",
            }
            if resume_size and metadata:
                headers["Range"] = f"bytes={resume_size}-"
                validator = str(metadata.get("etag") or metadata.get("last_modified") or "")
                if validator:
                    headers["If-Range"] = validator

            try:
                request = Request(url, headers=headers, method="GET")
                response = opener.open(request, timeout=self.settings.connect_timeout_seconds)
                with self._response_lock:
                    self._response = response
                self._set_read_timeout(response)
                status = int(getattr(response, "status", 200))
                final_url = validate_url(response.geturl())
                content_disposition = response.headers.get("Content-Disposition", "")
                content_type = response.headers.get("Content-Type", "")
                if status == 204:
                    response.close()
                    return DownloadResult(
                        False,
                        error_kind=ErrorKind.UNEXPECTED_CONTENT,
                        message="파일 내용이 없는 응답을 받았습니다. (HTTP 204)",
                    )
                if is_unexpected_html(content_type, content_disposition, final_url):
                    response.close()
                    return DownloadResult(
                        False,
                        error_kind=ErrorKind.UNEXPECTED_CONTENT,
                        message=(
                            "파일 대신 웹페이지가 반환되었습니다. "
                            "영상 주소라면 영상 다운로드를 사용하세요."
                        ),
                    )

                append = status == 206 and resume_size > 0
                total_bytes = self._response_total(response, status, resume_size)
                if append and not self._valid_partial_response(response, resume_size, metadata):
                    response.close()
                    part_path.unlink(missing_ok=True)
                    metadata_path.unlink(missing_ok=True)
                    metadata = {}
                    last_result = DownloadResult(
                        False,
                        error_kind=ErrorKind.SIZE_MISMATCH,
                        message="이어받기 응답이 기존 부분 파일과 일치하지 않아 다시 시작합니다.",
                    )
                    continue

                if output_path is None:
                    saved_name = str(metadata.get("filename") or "")
                    filename = saved_name or response_filename(
                        content_disposition, final_url, content_type
                    )
                    output_path = self.registry.reserve(filename)

                initial_size = resume_size if append else 0
                remaining = max(0, total_bytes - initial_size) if total_bytes is not None else 0
                if not self.space.reserve(remaining):
                    response.close()
                    return DownloadResult(
                        False,
                        error_kind=ErrorKind.DISK_FULL,
                        message=(f"저장 공간이 부족합니다. 필요한 공간: {format_bytes(remaining)}"),
                    )
                try:
                    metadata = {
                        "url_hash": fingerprint,
                        "filename": output_path.name,
                        "etag": response.headers.get("ETag", ""),
                        "last_modified": response.headers.get("Last-Modified", ""),
                        "total_bytes": total_bytes,
                    }
                    self._write_metadata(metadata_path, metadata)
                    result = self._stream_response(
                        response,
                        part_path,
                        output_path,
                        append=append,
                        initial_size=initial_size,
                        total_bytes=total_bytes,
                        on_progress=on_progress,
                        attempt=attempt,
                        max_attempts=attempts,
                    )
                finally:
                    with suppress(OSError):
                        response.close()
                    self.space.release(remaining)
                    with self._response_lock:
                        self._response = None

                if result.success:
                    metadata_path.unlink(missing_ok=True)
                    return result
                last_result = result
                if result.error_kind == ErrorKind.CANCELLED:
                    return result
                if attempt < attempts:
                    self._retry_wait(attempt, None, on_progress, attempts)
            except HTTPError as exc:
                with self._response_lock:
                    self._response = None
                if exc.code == 416 and part_path.exists():
                    total = self._unsatisfied_total(exc.headers.get("Content-Range", ""))
                    if total is not None and total == part_path.stat().st_size:
                        filename = str(metadata.get("filename") or "download.bin")
                        output_path = output_path or self.registry.reserve(filename)
                        with suppress(OSError):
                            exc.close()
                        part_path.replace(output_path)
                        metadata_path.unlink(missing_ok=True)
                        return DownloadResult(
                            True,
                            output_path=output_path,
                            message="완료된 부분 파일을 확인했습니다.",
                        )
                    part_path.unlink(missing_ok=True)
                    metadata_path.unlink(missing_ok=True)
                    with suppress(OSError):
                        exc.close()
                    return self.download(job, on_progress=on_progress)
                last_result = self._http_error_result(exc.code)
                with suppress(OSError):
                    exc.close()
                if exc.code not in RETRYABLE_STATUS or attempt >= attempts:
                    return last_result
                self._retry_wait(
                    attempt,
                    exc.headers.get("Retry-After"),
                    on_progress,
                    attempts,
                )
            except (URLError, TimeoutError, OSError) as exc:
                with self._response_lock:
                    self._response = None
                if self._cancel_requested.is_set():
                    return self._cancelled_result()
                kind = (
                    ErrorKind.DISK_FULL
                    if getattr(exc, "errno", None) == errno.ENOSPC
                    else ErrorKind.NETWORK_TRANSIENT
                )
                last_result = DownloadResult(
                    False, error_kind=kind, message=self._network_message(kind)
                )
                if attempt >= attempts or kind == ErrorKind.DISK_FULL:
                    return last_result
                self._retry_wait(attempt, None, on_progress, attempts)
            finally:
                with self._response_lock:
                    response = self._response
                    self._response = None
                if response is not None:
                    with suppress(OSError):
                        response.close()  # type: ignore[attr-defined]

        return last_result or DownloadResult(
            False,
            error_kind=ErrorKind.UNKNOWN,
            message="파일 다운로드를 완료하지 못했습니다.",
        )

    def _stream_response(
        self,
        response: object,
        part_path: Path,
        output_path: Path,
        *,
        append: bool,
        initial_size: int,
        total_bytes: int | None,
        on_progress: ProgressCallback | None,
        attempt: int,
        max_attempts: int,
    ) -> DownloadResult:
        downloaded = initial_size
        started = time.monotonic()
        last_data_at = started
        last_progress_at = started
        last_reported_bytes = initial_size
        mode = "ab" if append else "wb"
        try:
            with part_path.open(mode) as output:
                while True:
                    if self._cancel_requested.is_set():
                        return self._cancelled_result()
                    try:
                        read = getattr(response, "read1", None)
                        chunk = (
                            read(CHUNK_SIZE) if callable(read) else response.read(CHUNK_SIZE)  # type: ignore[attr-defined]
                        )
                    except OSError as exc:
                        if not self._is_timeout_error(exc):
                            raise
                        idle_seconds = time.monotonic() - last_data_at
                        self._emit_progress(
                            on_progress,
                            phase="waiting",
                            filename=output_path.name,
                            downloaded_bytes=downloaded,
                            total_bytes=total_bytes,
                            percent=self._percent(downloaded, total_bytes),
                            speed="-",
                            idle_seconds=max(1, int(idle_seconds)),
                            attempt=attempt,
                            max_attempts=max_attempts,
                        )
                        if idle_seconds >= self.settings.read_timeout_seconds:
                            return DownloadResult(
                                False,
                                error_kind=ErrorKind.NETWORK_TRANSIENT,
                                message=(
                                    f"{self.settings.read_timeout_seconds}초 동안 데이터가 "
                                    "도착하지 않아 연결을 다시 시도합니다."
                                ),
                            )
                        continue
                    if not chunk:
                        break
                    last_data_at = time.monotonic()
                    output.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    if now - last_progress_at < PROGRESS_EMIT_INTERVAL_SECONDS and (
                        total_bytes is None or downloaded < total_bytes
                    ):
                        continue
                    elapsed = max(0.001, now - started)
                    speed_value = max(0.0, (downloaded - initial_size) / elapsed)
                    remaining = (
                        max(0, total_bytes - downloaded) if total_bytes is not None else None
                    )
                    eta = (
                        int(remaining / speed_value)
                        if remaining is not None and speed_value
                        else None
                    )
                    self._emit_progress(
                        on_progress,
                        phase="downloading",
                        filename=output_path.name,
                        downloaded_bytes=downloaded,
                        total_bytes=total_bytes,
                        percent=self._percent(downloaded, total_bytes),
                        speed_bytes=speed_value,
                        speed=f"{format_bytes(speed_value)}/s",
                        eta_seconds=eta,
                        eta=self._format_eta(eta),
                        attempt=attempt,
                        max_attempts=max_attempts,
                    )
                    last_progress_at = now
                    last_reported_bytes = downloaded
                if downloaded != last_reported_bytes:
                    elapsed = max(0.001, time.monotonic() - started)
                    speed_value = max(0.0, (downloaded - initial_size) / elapsed)
                    remaining = (
                        max(0, total_bytes - downloaded) if total_bytes is not None else None
                    )
                    eta = (
                        int(remaining / speed_value)
                        if remaining is not None and speed_value
                        else None
                    )
                    self._emit_progress(
                        on_progress,
                        phase="downloading",
                        filename=output_path.name,
                        downloaded_bytes=downloaded,
                        total_bytes=total_bytes,
                        percent=self._percent(downloaded, total_bytes),
                        speed_bytes=speed_value,
                        speed=f"{format_bytes(speed_value)}/s",
                        eta_seconds=eta,
                        eta=self._format_eta(eta),
                        attempt=attempt,
                        max_attempts=max_attempts,
                    )
                output.flush()
        except OSError as exc:
            if self._cancel_requested.is_set():
                return self._cancelled_result()
            kind = ErrorKind.DISK_FULL if exc.errno == errno.ENOSPC else ErrorKind.NETWORK_TRANSIENT
            return DownloadResult(False, error_kind=kind, message=self._network_message(kind))

        actual_size = part_path.stat().st_size
        if total_bytes is not None and actual_size != total_bytes:
            return DownloadResult(
                False,
                error_kind=ErrorKind.SIZE_MISMATCH,
                message=(
                    f"파일 크기가 예상과 다릅니다: "
                    f"{format_bytes(actual_size)} / {format_bytes(total_bytes)}"
                ),
            )
        try:
            part_path.replace(output_path)
        except OSError as exc:
            return DownloadResult(
                False,
                error_kind=ErrorKind.UNKNOWN,
                message=f"완료 파일 이름을 적용할 수 없습니다: {exc}",
            )
        return DownloadResult(
            True, output_path=output_path, message="파일 다운로드가 완료되었습니다."
        )

    @staticmethod
    def _load_metadata(path: Path, fingerprint: str) -> dict[str, object]:
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict) or payload.get("url_hash") != fingerprint:
            return {}
        return payload

    @staticmethod
    def _write_metadata(path: Path, metadata: dict[str, object]) -> None:
        path.write_text(
            json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
            newline="\n",
        )

    @staticmethod
    def _response_total(response: object, status: int, resume_size: int) -> int | None:
        content_range = response.headers.get("Content-Range", "")  # type: ignore[attr-defined]
        match = CONTENT_RANGE.fullmatch(content_range.strip())
        if status == 206 and match and match.group(3) != "*":
            return int(match.group(3))
        raw_length = response.headers.get("Content-Length")  # type: ignore[attr-defined]
        if raw_length and raw_length.isdigit():
            length = int(raw_length)
            return resume_size + length if status == 206 else length
        return None

    @staticmethod
    def _valid_partial_response(
        response: object,
        resume_size: int,
        metadata: dict[str, object],
    ) -> bool:
        content_range = response.headers.get("Content-Range", "")  # type: ignore[attr-defined]
        match = CONTENT_RANGE.fullmatch(content_range.strip())
        if match is None or int(match.group(1)) != resume_size:
            return False
        old_etag = str(metadata.get("etag") or "")
        new_etag = str(response.headers.get("ETag", ""))  # type: ignore[attr-defined]
        return not (old_etag and new_etag and old_etag != new_etag)

    @staticmethod
    def _unsatisfied_total(value: str) -> int | None:
        match = UNSATISFIED_RANGE.fullmatch(value.strip())
        return int(match.group(1)) if match else None

    def _set_read_timeout(self, response: object) -> None:
        with suppress(AttributeError, OSError):
            response.fp.raw._sock.settimeout(  # type: ignore[attr-defined]
                min(READ_POLL_SECONDS, float(self.settings.read_timeout_seconds))
            )

    def _retry_wait(
        self,
        attempt: int,
        retry_after: str | None,
        on_progress: ProgressCallback | None,
        max_attempts: int,
    ) -> None:
        delay = min(30.0, 2 ** (attempt - 1) + random.uniform(0, 0.5))
        if retry_after and retry_after.strip().isdigit():
            delay = min(60.0, float(retry_after.strip()))
        self._emit_progress(
            on_progress,
            phase="retrying",
            attempt=attempt + 1,
            max_attempts=max_attempts,
            retry_in_seconds=round(delay, 1),
        )
        if self._cancel_requested.wait(delay):
            return

    @staticmethod
    def _emit_progress(
        callback: ProgressCallback | None,
        **payload: object,
    ) -> None:
        if callback is not None:
            callback(payload)

    @staticmethod
    def _percent(downloaded: int, total_bytes: int | None) -> float | None:
        if total_bytes in {None, 0}:
            return None
        return downloaded * 100 / total_bytes

    @staticmethod
    def _is_timeout_error(exc: OSError) -> bool:
        return (
            isinstance(exc, (TimeoutError, socket.timeout))
            or exc.errno in {errno.EAGAIN, errno.ETIMEDOUT, errno.EWOULDBLOCK}
            or getattr(exc, "winerror", None) == 10060
        )

    @staticmethod
    def _http_error_result(status: int) -> DownloadResult:
        if status == 401:
            return DownloadResult(
                False,
                error_kind=ErrorKind.AUTH_REQUIRED,
                message="로그인 세션이 필요한 URL입니다.",
            )
        if status == 403:
            return DownloadResult(
                False,
                error_kind=ErrorKind.HTTP_FORBIDDEN,
                message="접근이 거부되었거나 다운로드 URL이 만료되었습니다.",
            )
        if status in {404, 410}:
            return DownloadResult(
                False,
                error_kind=ErrorKind.FILE_NOT_FOUND,
                message="파일을 찾을 수 없거나 다운로드 URL이 만료되었습니다.",
            )
        if status in RETRYABLE_STATUS:
            return DownloadResult(
                False,
                error_kind=ErrorKind.NETWORK_TRANSIENT,
                message=f"서버가 일시적으로 요청을 처리하지 못했습니다. (HTTP {status})",
            )
        return DownloadResult(
            False,
            error_kind=ErrorKind.UNKNOWN,
            message=f"파일 서버가 HTTP {status} 오류를 반환했습니다.",
        )

    @staticmethod
    def _network_message(kind: ErrorKind) -> str:
        if kind == ErrorKind.DISK_FULL:
            return "파일을 저장할 공간이 부족합니다."
        return "네트워크 연결이 끊겼거나 제한시간을 초과했습니다."

    @staticmethod
    def _format_eta(seconds: int | None) -> str:
        if seconds is None:
            return "알 수 없음"
        minutes, remaining = divmod(max(0, seconds), 60)
        hours, minutes = divmod(minutes, 60)
        return (
            f"{hours:02d}:{minutes:02d}:{remaining:02d}"
            if hours
            else f"{minutes:02d}:{remaining:02d}"
        )

    @staticmethod
    def _cancelled_result() -> DownloadResult:
        return DownloadResult(
            False,
            error_kind=ErrorKind.CANCELLED,
            message="사용자 요청으로 파일 다운로드를 취소했습니다.",
        )
