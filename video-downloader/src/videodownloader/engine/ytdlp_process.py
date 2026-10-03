from __future__ import annotations

import json
import re
import shutil
from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlsplit

from videodownloader.config import Settings
from videodownloader.engine.base import ProgressCallback
from videodownloader.engine.process import ProcessRunner, ProcessStartError
from videodownloader.engine.runtime import select_js_runtime
from videodownloader.models import DownloadResult, ErrorKind, Job, MediaInfo, ProbeResult
from videodownloader.storage.naming import build_output_template, prepare_output_directory

PROGRESS_PREFIX = "VDL_PROGRESS:"
OUTPUT_PREFIX = "VDL_OUTPUT:"
PROGRESS_TEMPLATE = (
    f"download:{PROGRESS_PREFIX}"
    "%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s|"
    "%(progress.downloaded_bytes)s|%(progress.total_bytes_estimate)s"
)

SUPPORTED_BROWSERS = {
    "brave",
    "chrome",
    "chromium",
    "edge",
    "firefox",
    "opera",
    "safari",
    "vivaldi",
    "whale",
}
CAPTURE_HEADER_NAMES = {"origin", "referer", "user-agent"}
VIDEO_QUALITY_HEIGHTS = {"2160p": 2160, "1440p": 1440, "1080p": 1080, "720p": 720}


class DownloadError(RuntimeError):
    def __init__(self, kind: ErrorKind, message: str, *, details: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.details = details


def validate_url(url: str) -> str:
    normalized = url.strip()
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise DownloadError(ErrorKind.UNSUPPORTED_URL, "http 또는 https URL을 입력하세요.")
    if parsed.username or parsed.password:
        raise DownloadError(
            ErrorKind.UNSUPPORTED_URL,
            "사용자명이나 비밀번호가 포함된 URL은 사용할 수 없습니다.",
        )
    return normalized


def classify_error(output: str) -> ErrorKind:
    lowered = output.casefold()
    patterns: tuple[tuple[ErrorKind, tuple[str, ...]], ...] = (
        (ErrorKind.DRM_PROTECTED, ("drm protected", "drm-protected", "protected by drm")),
        (
            ErrorKind.DEPENDENCY_MISSING,
            (
                "no supported javascript runtime",
                "challenge solver scripts are missing",
                "ejs script not available",
                "javascript challenge solving failed",
                "ffmpeg not found",
                "ffprobe not found",
                "ffmpeg is not installed",
            ),
        ),
        (ErrorKind.TOKEN_REQUIRED, ("po token", "proof of origin token")),
        (
            ErrorKind.AUTH_REQUIRED,
            (
                "login required",
                "sign in to confirm",
                "sign in to view",
                "private video",
                "cookies-from-browser",
                "authentication required",
            ),
        ),
        (ErrorKind.HTTP_FORBIDDEN, ("http error 403", "403 forbidden", "status code: 403")),
        (
            ErrorKind.FORMAT_UNAVAILABLE,
            ("requested format is not available", "no video formats found"),
        ),
        (
            ErrorKind.UNSUPPORTED_URL,
            ("unsupported url", "no suitable extractor", "url could be a direct video link"),
        ),
        (
            ErrorKind.POSTPROCESS_FAILED,
            ("postprocessing:", "post-processing:", "ffmpegpostprocessor", "ffmpeg exited"),
        ),
        (
            ErrorKind.NETWORK_TRANSIENT,
            (
                "timed out",
                "connection reset",
                "temporary failure",
                "remote end closed connection",
                "unable to resolve",
                "unable to connect to proxy",
                "failed to establish a new connection",
                "unable to download webpage",
                "proxyerror",
            ),
        ),
    )
    for kind, needles in patterns:
        if any(needle in lowered for needle in needles):
            return kind
    return ErrorKind.UNKNOWN


def redact_sensitive(text: str, *, source_url: str | None = None) -> str:
    redacted = text.replace(source_url, "[URL]") if source_url else text
    redacted = re.sub(r"https?://[^\s\"'<>]+", "[URL]", redacted, flags=re.IGNORECASE)
    redacted = re.sub(
        r"(?i)\b(cookie|authorization)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)([?&;](?:po_)?token|[?&;](?:signature|sig|key|expire))=[^&;\s]+",
        r"\1=[REDACTED]",
        redacted,
    )
    return redacted


def parse_progress_line(line: str) -> dict[str, object] | None:
    if not line.startswith(PROGRESS_PREFIX):
        return None
    values = line.removeprefix(PROGRESS_PREFIX).split("|", maxsplit=4)
    values.extend([""] * (5 - len(values)))

    def optional_int(value: str) -> int | None:
        stripped = value.strip()
        return int(stripped) if stripped.isdigit() else None

    return {
        "status": "downloading",
        "percent": values[0].strip(),
        "speed": values[1].strip(),
        "eta": values[2].strip(),
        "downloaded_bytes": optional_int(values[3]),
        "total_bytes": optional_int(values[4]),
    }


def parse_output_path(line: str) -> Path | None:
    if not line.startswith(OUTPUT_PREFIX):
        return None
    raw_value = line.removeprefix(OUTPUT_PREFIX).strip()
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        value = raw_value
    if not isinstance(value, str) or not value:
        return None
    return Path(value).expanduser().resolve()


def video_format_selector(quality: str) -> str:
    if quality == "best":
        return "bv*+ba/b"
    if quality == "compatible":
        return "bv[vcodec^=avc1]+ba[acodec^=mp4a]/b[ext=mp4]/bv*+ba/b"
    height = VIDEO_QUALITY_HEIGHTS.get(quality)
    if height is None:
        raise DownloadError(ErrorKind.FORMAT_UNAVAILABLE, "지원하지 않는 영상 화질입니다.")
    # The trailing ? keeps direct files whose generic extractor cannot report
    # a height. Known resolutions still obey the selected upper bound.
    return f"bv*[height<=?{height}]+ba/b[height<=?{height}]"


def parse_ffprobe_media_info(output: str, *, container: str = "") -> MediaInfo | None:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    streams = payload.get("streams")
    if not isinstance(streams, list):
        return None
    video = next(
        (item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"),
        None,
    )
    audio = next(
        (item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"),
        None,
    )
    if video is None and audio is None:
        return None

    def optional_int(value: object) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    fps: float | None = None
    if video is not None:
        raw_fps = video.get("avg_frame_rate") or video.get("r_frame_rate")
        if isinstance(raw_fps, str):
            try:
                parsed_fps = float(Fraction(raw_fps))
            except (ValueError, ZeroDivisionError):
                pass
            else:
                fps = parsed_fps if parsed_fps > 0 else None

    format_payload = payload.get("format")
    format_name = format_payload.get("format_name") if isinstance(format_payload, dict) else ""
    detected_container = container or (
        str(format_name).split(",", maxsplit=1)[0] if format_name else ""
    )
    return MediaInfo(
        width=optional_int(video.get("width")) if video is not None else None,
        height=optional_int(video.get("height")) if video is not None else None,
        fps=fps,
        video_codec=str(video.get("codec_name") or "") if video is not None else "",
        audio_codec=str(audio.get("codec_name") or "") if audio is not None else "",
        container=detected_container,
    )


class YtDlpProcessEngine:
    def __init__(
        self,
        settings: Settings,
        *,
        executable: str | None = None,
        runner: ProcessRunner | None = None,
    ) -> None:
        self.settings = settings
        self.executable = executable or shutil.which("yt-dlp") or "yt-dlp"
        self.ffprobe_executable = shutil.which("ffprobe") or "ffprobe"
        self.runner = runner or ProcessRunner()
        self.js_runtime = select_js_runtime(settings.youtube.js_runtime)

    def cancel(self) -> None:
        self.runner.cancel_current()

    def _base_args(self) -> list[str]:
        args = [
            self.executable,
            "--ignore-config",
            "--no-update",
            "--no-playlist",
            "--no-colors",
        ]
        if self.js_runtime is not None:
            args.extend(("--js-runtimes", self.js_runtime.yt_dlp_value))
        elif self.settings.youtube.js_runtime == "none":
            args.append("--no-js-runtimes")

        if self.settings.youtube.remote_ejs:
            args.extend(("--remote-components", "ejs:github"))
        else:
            args.append("--no-remote-components")

        args.extend(self._cookie_args())
        return args

    def _cookie_args(self) -> list[str]:
        browser = self.settings.auth.browser.casefold()
        profile = self.settings.auth.profile.strip()
        if browser == "none":
            if profile:
                raise DownloadError(
                    ErrorKind.AUTH_REQUIRED,
                    "브라우저 프로필을 사용하려면 브라우저를 선택해야 합니다.",
                )
            return ["--no-cookies-from-browser"]
        if browser not in SUPPORTED_BROWSERS:
            raise DownloadError(ErrorKind.AUTH_REQUIRED, "지원하지 않는 브라우저입니다.")
        if any(character in profile for character in "\r\n"):
            raise DownloadError(
                ErrorKind.AUTH_REQUIRED, "브라우저 프로필 형식이 올바르지 않습니다."
            )
        cookie_source = f"{browser}:{profile}" if profile else browser
        return ["--cookies-from-browser", cookie_source]

    def build_probe_args(self, url: str) -> list[str]:
        return [
            *self._base_args(),
            *self._network_args(),
            "--dump-single-json",
            "--skip-download",
            "--",
            validate_url(url),
        ]

    def _network_args(self) -> list[str]:
        retries = str(self.settings.download.retries)
        return [
            "--socket-timeout",
            str(self.settings.download.socket_timeout_seconds),
            "--retries",
            retries,
            "--fragment-retries",
            retries,
            "--retry-sleep",
            str(self.settings.download.retry_sleep_seconds),
        ]

    def _request_context_args(self, job: Job) -> list[str]:
        args: list[str] = []
        for name, value in job.http_headers:
            normalized_name = name.strip().casefold()
            if normalized_name not in CAPTURE_HEADER_NAMES:
                raise DownloadError(ErrorKind.AUTH_REQUIRED, "허용되지 않은 요청 헤더입니다.")
            if not value or any(character in value for character in "\r\n"):
                raise DownloadError(ErrorKind.AUTH_REQUIRED, "요청 헤더 형식이 올바르지 않습니다.")
            args.extend(("--add-header", f"{name.strip()}:{value}"))
        if job.cookie_file is not None:
            cookie_path = job.cookie_file.expanduser().resolve()
            if not cookie_path.is_file():
                raise DownloadError(ErrorKind.AUTH_REQUIRED, "임시 쿠키 파일을 찾을 수 없습니다.")
            args.extend(("--cookies", str(cookie_path)))
        return args

    def probe(self, job: Job) -> ProbeResult:
        url = validate_url(job.url)
        try:
            result = self.runner.run(self.build_probe_args(url), timeout=90)
        except ProcessStartError as exc:
            raise DownloadError(
                ErrorKind.DEPENDENCY_MISSING,
                "yt-dlp를 실행할 수 없습니다.",
                details=str(exc),
            ) from exc

        if result.cancelled:
            raise DownloadError(
                ErrorKind.CANCELLED,
                "사용자 요청으로 분석을 취소했습니다.",
            )

        if result.returncode != 0:
            self._raise_command_error(result.stdout, result.stderr, url)

        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise DownloadError(
                ErrorKind.UNKNOWN,
                "yt-dlp 메타데이터 응답을 해석할 수 없습니다.",
                details=self._redact(result.stdout, url),
            ) from exc

        if not isinstance(payload, dict):
            raise DownloadError(ErrorKind.UNKNOWN, "yt-dlp 메타데이터 형식이 올바르지 않습니다.")

        formats = payload.get("formats")
        safe_formats = (
            tuple(item for item in formats if isinstance(item, dict))
            if isinstance(formats, list)
            else ()
        )
        return ProbeResult(
            id=str(payload.get("id") or ""),
            title=str(payload.get("title") or "제목 없음"),
            webpage_url=str(payload.get("webpage_url") or url),
            uploader=str(payload.get("uploader") or ""),
            duration=payload.get("duration")
            if isinstance(payload.get("duration"), (int, float))
            else None,
            formats=safe_formats,
        )

    def build_download_args(self, job: Job, save_dir: Path) -> list[str]:
        url = validate_url(job.url)
        if job.mode not in {"video", "audio"}:
            raise DownloadError(
                ErrorKind.FORMAT_UNAVAILABLE, "다운로드 모드는 video 또는 audio여야 합니다."
            )

        args = [
            *self._base_args(),
            *self._request_context_args(job),
            *self._network_args(),
            "--no-simulate",
            "--progress",
            "--newline",
            "--progress-delta",
            "0.5",
            "--progress-template",
            PROGRESS_TEMPLATE,
            "--print",
            f"after_move:{OUTPUT_PREFIX}%(filepath)j",
            "--windows-filenames",
            "--trim-filenames",
            "220",
            "--output",
            build_output_template(save_dir, timestamp=self.settings.app.timestamp),
        ]

        if self.settings.app.overwrite:
            args.append("--force-overwrites")
        else:
            args.extend(("--no-overwrites", "--no-post-overwrites"))

        if job.mode == "audio":
            args.extend(
                (
                    "--format",
                    "bestaudio/best",
                    "--extract-audio",
                    "--audio-format",
                    self.settings.download.audio_format,
                    "--audio-quality",
                    self.settings.download.audio_quality,
                )
            )
        else:
            format_selector = video_format_selector(self.settings.download.video_quality)
            args.extend(
                (
                    "--format",
                    format_selector,
                    "--merge-output-format",
                    self.settings.download.container,
                )
            )

        args.extend(("--", url))
        return args

    def download(
        self,
        job: Job,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> DownloadResult:
        try:
            validate_url(job.url)
            if job.mode not in {"video", "audio"}:
                raise DownloadError(
                    ErrorKind.FORMAT_UNAVAILABLE,
                    "다운로드 모드는 video 또는 audio여야 합니다.",
                )
        except DownloadError as exc:
            return DownloadResult(
                success=False,
                error_kind=exc.kind,
                message=exc.message,
            )

        try:
            save_dir = prepare_output_directory(self.settings.app.save_dir)
        except OSError as exc:
            return DownloadResult(
                success=False,
                error_kind=ErrorKind.DEPENDENCY_MISSING,
                message=f"저장 폴더를 준비할 수 없습니다: {exc}",
            )

        max_attempts = 2 if self.settings.youtube.retry_on_403 else 1
        for attempt in range(max_attempts):
            output_path: Path | None = None

            def handle_line(line: str) -> None:
                nonlocal output_path
                progress = parse_progress_line(line)
                if progress is not None and on_progress is not None:
                    on_progress(progress)
                parsed_path = parse_output_path(line)
                if parsed_path is not None:
                    output_path = parsed_path

            try:
                result = self.runner.stream(
                    self.build_download_args(job, save_dir), on_line=handle_line
                )
            except (ProcessStartError, DownloadError) as exc:
                if isinstance(exc, DownloadError):
                    return DownloadResult(
                        success=False,
                        error_kind=exc.kind,
                        message=exc.message,
                    )
                return DownloadResult(
                    success=False,
                    error_kind=ErrorKind.DEPENDENCY_MISSING,
                    message=f"yt-dlp를 실행할 수 없습니다: {exc}",
                )

            if result.cancelled:
                return DownloadResult(
                    success=False,
                    error_kind=ErrorKind.CANCELLED,
                    message="사용자 요청으로 다운로드를 취소했습니다.",
                )

            if result.returncode == 0:
                media_info = self._inspect_output(output_path) if output_path is not None else None
                return DownloadResult(
                    success=True,
                    output_path=output_path,
                    media_info=media_info,
                    message="다운로드가 완료되었습니다.",
                )

            kind = classify_error(result.stdout or result.stderr)
            should_retry = kind == ErrorKind.HTTP_FORBIDDEN and attempt + 1 < max_attempts
            if should_retry:
                continue
            return DownloadResult(
                success=False,
                error_kind=kind,
                message=self._public_error_message(kind),
            )

        return DownloadResult(
            success=False,
            error_kind=ErrorKind.UNKNOWN,
            message=self._public_error_message(ErrorKind.UNKNOWN),
        )

    def _inspect_output(self, output_path: Path) -> MediaInfo | None:
        if not output_path.is_file():
            return None
        try:
            result = self.runner.run(
                [
                    self.ffprobe_executable,
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate:"
                    "format=format_name",
                    "-of",
                    "json",
                    str(output_path),
                ],
                timeout=30,
            )
        except ProcessStartError:
            return None
        if result.returncode != 0 or result.cancelled:
            return None
        return parse_ffprobe_media_info(
            result.stdout,
            container=output_path.suffix.removeprefix(".").casefold(),
        )

    def _raise_command_error(self, stdout: str, stderr: str, url: str) -> None:
        combined = "\n".join(part for part in (stderr, stdout) if part).strip()
        kind = classify_error(combined)
        raise DownloadError(
            kind,
            self._public_error_message(kind),
            details=self._redact(combined, url),
        )

    @staticmethod
    def _redact(text: str, url: str) -> str:
        redacted = redact_sensitive(text, source_url=url)
        lines = redacted.splitlines()
        return "\n".join(lines[-12:])

    @staticmethod
    def _public_error_message(kind: ErrorKind) -> str:
        messages = {
            ErrorKind.CANCELLED: "사용자 요청으로 작업을 취소했습니다.",
            ErrorKind.DEPENDENCY_MISSING: (
                "필수 실행 파일 또는 YouTube JavaScript 구성요소가 없습니다."
            ),
            ErrorKind.UNSUPPORTED_URL: "지원하지 않는 URL입니다.",
            ErrorKind.AUTH_REQUIRED: "로그인 또는 브라우저 쿠키가 필요한 콘텐츠입니다.",
            ErrorKind.TOKEN_REQUIRED: (
                "YouTube가 PO Token을 요구합니다. 자동 PO Token provider 설정이 필요합니다."
            ),
            ErrorKind.HTTP_FORBIDDEN: (
                "서버가 재시도한 요청도 거부했습니다(HTTP 403). "
                "브라우저 쿠키 또는 PO Token이 필요할 수 있습니다."
            ),
            ErrorKind.DRM_PROTECTED: "DRM으로 보호된 콘텐츠는 다운로드하지 않습니다.",
            ErrorKind.FORMAT_UNAVAILABLE: "요청한 형식을 사용할 수 없습니다.",
            ErrorKind.NETWORK_TRANSIENT: "일시적인 네트워크 오류가 발생했습니다.",
            ErrorKind.POSTPROCESS_FAILED: "FFmpeg 후처리에 실패했습니다.",
            ErrorKind.UNKNOWN: "다운로드 엔진에서 알 수 없는 오류가 발생했습니다.",
        }
        return messages[kind]


def compact_format_rows(formats: Sequence[dict[str, object]]) -> tuple[dict[str, object], ...]:
    """Return one useful row per format for a compact probe summary."""
    rows: list[dict[str, object]] = []
    for item in formats:
        if item.get("vcodec") == "none" and item.get("acodec") == "none":
            continue
        rows.append(
            {
                "id": item.get("format_id", ""),
                "resolution": item.get("resolution") or item.get("format_note") or "audio",
                "ext": item.get("ext", ""),
                "vcodec": item.get("vcodec", ""),
                "acodec": item.get("acodec", ""),
                "filesize": item.get("filesize") or item.get("filesize_approx"),
            }
        )
    return tuple(rows)
