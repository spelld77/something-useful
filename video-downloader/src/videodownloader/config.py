from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when config.toml contains an invalid value."""


VIDEO_QUALITY_CHOICES = ("best", "2160p", "1440p", "1080p", "720p", "compatible")


@dataclass(frozen=True, slots=True)
class AppConfig:
    save_dir: Path = Path("savedVideo")
    timestamp: bool = False
    overwrite: bool = False


@dataclass(frozen=True, slots=True)
class DownloadConfig:
    mode: str = "video"
    container: str = "mp4"
    video_quality: str = "best"
    audio_format: str = "mp3"
    audio_quality: str = "192K"
    concurrency: int = 1
    retries: int = 2
    socket_timeout_seconds: int = 30
    retry_sleep_seconds: float = 1.0


@dataclass(frozen=True, slots=True)
class AuthConfig:
    browser: str = "none"
    profile: str = ""


@dataclass(frozen=True, slots=True)
class BrowserCaptureConfig:
    enabled: bool = False
    browser: str = "chrome"
    timeout_seconds: int = 90
    interactive_timeout_seconds: int = 180
    grace_seconds: float = 3.0


@dataclass(frozen=True, slots=True)
class YouTubeConfig:
    js_runtime: str = "auto"
    remote_ejs: bool = False
    retry_on_403: bool = True


@dataclass(frozen=True, slots=True)
class BatchConfig:
    history_file: Path = Path("history.jsonl")
    failed_file: Path = Path("failed_urls.txt")
    resume: bool = True
    delay_seconds: float = 2.0


@dataclass(frozen=True, slots=True)
class FileDownloadConfig:
    save_dir: Path = Path("savedFiles")
    history_file: Path = Path("file_history.jsonl")
    concurrency: int = 1
    retries: int = 2
    connect_timeout_seconds: int = 20
    read_timeout_seconds: int = 30
    resume_partial: bool = True


@dataclass(frozen=True, slots=True)
class Settings:
    app: AppConfig = field(default_factory=AppConfig)
    download: DownloadConfig = field(default_factory=DownloadConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    browser_capture: BrowserCaptureConfig = field(default_factory=BrowserCaptureConfig)
    youtube: YouTubeConfig = field(default_factory=YouTubeConfig)
    batch: BatchConfig = field(default_factory=BatchConfig)
    file_download: FileDownloadConfig = field(default_factory=FileDownloadConfig)


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] 섹션은 테이블이어야 합니다.")
    return value


def _reject_unknown(section: dict[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ConfigError(f"[{name}]에 알 수 없는 항목이 있습니다: {', '.join(unknown)}")


def load_config(path: str | Path = "config.toml") -> Settings:
    config_path = Path(path)
    if not config_path.exists():
        return Settings()

    try:
        with config_path.open("rb") as config_file:
            data = tomllib.load(config_file)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"TOML을 읽을 수 없습니다: {exc}") from exc

    allowed_sections = {
        "app",
        "download",
        "auth",
        "browser_capture",
        "youtube",
        "batch",
        "file_download",
    }
    unknown_sections = sorted(set(data) - allowed_sections)
    if unknown_sections:
        raise ConfigError(f"알 수 없는 설정 섹션: {', '.join(unknown_sections)}")

    app_data = _section(data, "app")
    download_data = _section(data, "download")
    auth_data = _section(data, "auth")
    capture_data = _section(data, "browser_capture")
    youtube_data = _section(data, "youtube")
    batch_data = _section(data, "batch")
    file_download_data = _section(data, "file_download")

    _reject_unknown(app_data, {"save_dir", "timestamp", "overwrite"}, "app")
    _reject_unknown(
        download_data,
        {
            "mode",
            "container",
            "video_quality",
            "audio_format",
            "audio_quality",
            "concurrency",
            "retries",
            "socket_timeout_seconds",
            "retry_sleep_seconds",
        },
        "download",
    )
    _reject_unknown(auth_data, {"browser", "profile"}, "auth")
    _reject_unknown(
        capture_data,
        {
            "enabled",
            "browser",
            "timeout_seconds",
            "interactive_timeout_seconds",
            "grace_seconds",
        },
        "browser_capture",
    )
    _reject_unknown(youtube_data, {"js_runtime", "remote_ejs", "retry_on_403"}, "youtube")
    _reject_unknown(batch_data, {"history_file", "failed_file", "resume", "delay_seconds"}, "batch")
    _reject_unknown(
        file_download_data,
        {
            "save_dir",
            "history_file",
            "concurrency",
            "retries",
            "connect_timeout_seconds",
            "read_timeout_seconds",
            "resume_partial",
        },
        "file_download",
    )

    try:
        settings = Settings(
            app=AppConfig(
                save_dir=Path(app_data.get("save_dir", "savedVideo")),
                timestamp=app_data.get("timestamp", False),
                overwrite=app_data.get("overwrite", False),
            ),
            download=DownloadConfig(**download_data),
            auth=AuthConfig(**auth_data),
            browser_capture=BrowserCaptureConfig(**capture_data),
            youtube=YouTubeConfig(**youtube_data),
            batch=BatchConfig(
                history_file=Path(batch_data.get("history_file", "history.jsonl")),
                failed_file=Path(batch_data.get("failed_file", "failed_urls.txt")),
                resume=batch_data.get("resume", True),
                delay_seconds=batch_data.get("delay_seconds", 2.0),
            ),
            file_download=FileDownloadConfig(
                save_dir=Path(file_download_data.get("save_dir", "savedFiles")),
                history_file=Path(file_download_data.get("history_file", "file_history.jsonl")),
                concurrency=file_download_data.get("concurrency", 1),
                retries=file_download_data.get("retries", 2),
                connect_timeout_seconds=file_download_data.get("connect_timeout_seconds", 20),
                read_timeout_seconds=file_download_data.get("read_timeout_seconds", 30),
                resume_partial=file_download_data.get("resume_partial", True),
            ),
        )
    except TypeError as exc:
        raise ConfigError(f"설정 값 형식이 올바르지 않습니다: {exc}") from exc

    if not isinstance(settings.app.timestamp, bool) or not isinstance(settings.app.overwrite, bool):
        raise ConfigError("app.timestamp와 app.overwrite는 true 또는 false여야 합니다.")
    if not isinstance(settings.download.mode, str):
        raise ConfigError("download.mode는 문자열이어야 합니다.")
    if settings.download.mode not in {"video", "audio"}:
        raise ConfigError("download.mode는 video 또는 audio여야 합니다.")
    if settings.download.container not in {"mp4", "mkv", "mov", "webm"}:
        raise ConfigError("download.container는 mp4, mkv, mov, webm 중 하나여야 합니다.")
    if settings.download.video_quality not in VIDEO_QUALITY_CHOICES:
        raise ConfigError(
            "download.video_quality는 best, 2160p, 1440p, 1080p, 720p, "
            "compatible 중 하나여야 합니다."
        )
    if settings.download.audio_format not in {
        "aac",
        "alac",
        "flac",
        "m4a",
        "mp3",
        "opus",
        "vorbis",
        "wav",
    }:
        raise ConfigError("지원하지 않는 download.audio_format입니다.")
    if not isinstance(settings.download.audio_quality, str) or not re.fullmatch(
        r"(?:[0-9]|10|\d+[Kk])", settings.download.audio_quality
    ):
        raise ConfigError("download.audio_quality는 0~10 또는 192K 같은 비트레이트여야 합니다.")
    if isinstance(settings.download.concurrency, bool) or not isinstance(
        settings.download.concurrency, int
    ):
        raise ConfigError("download.concurrency는 정수여야 합니다.")
    if settings.download.concurrency < 1:
        raise ConfigError("download.concurrency는 1 이상이어야 합니다.")
    if isinstance(settings.download.retries, bool) or not isinstance(
        settings.download.retries, int
    ):
        raise ConfigError("download.retries는 정수여야 합니다.")
    if settings.download.retries < 0:
        raise ConfigError("download.retries는 0 이상이어야 합니다.")
    if isinstance(settings.download.socket_timeout_seconds, bool) or not isinstance(
        settings.download.socket_timeout_seconds, int
    ):
        raise ConfigError("download.socket_timeout_seconds는 정수여야 합니다.")
    if settings.download.socket_timeout_seconds < 1:
        raise ConfigError("download.socket_timeout_seconds는 1 이상이어야 합니다.")
    if isinstance(settings.download.retry_sleep_seconds, bool) or not isinstance(
        settings.download.retry_sleep_seconds, (int, float)
    ):
        raise ConfigError("download.retry_sleep_seconds는 숫자여야 합니다.")
    if settings.download.retry_sleep_seconds < 0:
        raise ConfigError("download.retry_sleep_seconds는 0 이상이어야 합니다.")
    if not isinstance(settings.browser_capture.enabled, bool):
        raise ConfigError("browser_capture.enabled는 true 또는 false여야 합니다.")
    if settings.browser_capture.browser not in {"chrome", "edge"}:
        raise ConfigError("browser_capture.browser는 chrome 또는 edge여야 합니다.")
    if isinstance(settings.browser_capture.timeout_seconds, bool) or not isinstance(
        settings.browser_capture.timeout_seconds, int
    ):
        raise ConfigError("browser_capture.timeout_seconds는 정수여야 합니다.")
    if settings.browser_capture.timeout_seconds < 1:
        raise ConfigError("browser_capture.timeout_seconds는 1 이상이어야 합니다.")
    if isinstance(settings.browser_capture.interactive_timeout_seconds, bool) or not isinstance(
        settings.browser_capture.interactive_timeout_seconds, int
    ):
        raise ConfigError("browser_capture.interactive_timeout_seconds는 정수여야 합니다.")
    if settings.browser_capture.interactive_timeout_seconds < 1:
        raise ConfigError("browser_capture.interactive_timeout_seconds는 1 이상이어야 합니다.")
    if isinstance(settings.browser_capture.grace_seconds, bool) or not isinstance(
        settings.browser_capture.grace_seconds, (int, float)
    ):
        raise ConfigError("browser_capture.grace_seconds는 숫자여야 합니다.")
    if settings.browser_capture.grace_seconds < 0:
        raise ConfigError("browser_capture.grace_seconds는 0 이상이어야 합니다.")
    supported_browsers = {
        "none",
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
    if settings.auth.browser not in supported_browsers:
        raise ConfigError("지원하지 않는 auth.browser입니다.")
    if not isinstance(settings.auth.profile, str) or any(
        character in settings.auth.profile for character in "\r\n"
    ):
        raise ConfigError("auth.profile은 줄바꿈이 없는 문자열이어야 합니다.")
    if settings.auth.profile and settings.auth.browser == "none":
        raise ConfigError("auth.profile을 사용하려면 auth.browser를 선택해야 합니다.")
    if settings.youtube.js_runtime not in {"auto", "none", "deno", "node", "quickjs"}:
        raise ConfigError(
            "youtube.js_runtime은 auto, none, deno, node, quickjs 중 하나여야 합니다."
        )
    if not isinstance(settings.youtube.remote_ejs, bool):
        raise ConfigError("youtube.remote_ejs는 true 또는 false여야 합니다.")
    if not isinstance(settings.youtube.retry_on_403, bool):
        raise ConfigError("youtube.retry_on_403은 true 또는 false여야 합니다.")
    if not isinstance(settings.batch.resume, bool):
        raise ConfigError("batch.resume은 true 또는 false여야 합니다.")
    if isinstance(settings.batch.delay_seconds, bool) or not isinstance(
        settings.batch.delay_seconds, (int, float)
    ):
        raise ConfigError("batch.delay_seconds는 숫자여야 합니다.")
    if settings.batch.delay_seconds < 0:
        raise ConfigError("batch.delay_seconds는 0 이상이어야 합니다.")
    if isinstance(settings.file_download.concurrency, bool) or not isinstance(
        settings.file_download.concurrency, int
    ):
        raise ConfigError("file_download.concurrency는 정수여야 합니다.")
    if not 1 <= settings.file_download.concurrency <= 4:
        raise ConfigError("file_download.concurrency는 1~4여야 합니다.")
    if isinstance(settings.file_download.retries, bool) or not isinstance(
        settings.file_download.retries, int
    ):
        raise ConfigError("file_download.retries는 정수여야 합니다.")
    if settings.file_download.retries < 0:
        raise ConfigError("file_download.retries는 0 이상이어야 합니다.")
    for name, value in (
        ("connect_timeout_seconds", settings.file_download.connect_timeout_seconds),
        ("read_timeout_seconds", settings.file_download.read_timeout_seconds),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ConfigError(f"file_download.{name}는 1 이상의 정수여야 합니다.")
    if not isinstance(settings.file_download.resume_partial, bool):
        raise ConfigError("file_download.resume_partial은 true 또는 false여야 합니다.")

    return settings
