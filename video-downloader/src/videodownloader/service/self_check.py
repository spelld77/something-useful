from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from videodownloader.config import Settings
from videodownloader.engine.ytdlp_process import (
    DownloadError,
    classify_error,
    redact_sensitive,
    validate_url,
)
from videodownloader.models import ErrorKind
from videodownloader.preflight import run_preflight
from videodownloader.storage.naming import build_output_template


@dataclass(frozen=True, slots=True)
class SelfCheckItem:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class SelfCheckReport:
    items: tuple[SelfCheckItem, ...]

    @property
    def passed(self) -> bool:
        return all(item.passed for item in self.items)


def _url_policy_ready() -> bool:
    try:
        validate_url("https://user:password@example.com/video")
    except DownloadError as exc:
        return exc.kind == ErrorKind.UNSUPPORTED_URL
    return False


def _redaction_ready() -> bool:
    secret = "self-check-secret"
    value = redact_sensitive(f"https://example.com/video?token={secret} Cookie:SID={secret}")
    return secret not in value


def _error_policy_ready() -> bool:
    cases = {
        "Sign in to view": ErrorKind.AUTH_REQUIRED,
        "DRM protected": ErrorKind.DRM_PROTECTED,
        "connection reset": ErrorKind.NETWORK_TRANSIENT,
        "ffmpeg not found": ErrorKind.DEPENDENCY_MISSING,
        "Postprocessing: ffmpeg exited": ErrorKind.POSTPROCESS_FAILED,
    }
    return all(classify_error(message) == expected for message, expected in cases.items())


def run_self_check(settings: Settings) -> SelfCheckReport:
    preflight = run_preflight(settings)
    output_template = build_output_template(Path("self-check"))
    items = (
        SelfCheckItem(
            "필수 도구",
            preflight.required_ok,
            "yt-dlp, FFmpeg, FFprobe와 저장 경로" if preflight.required_ok else "doctor 확인 필요",
        ),
        SelfCheckItem(
            "YouTube 구성",
            preflight.youtube_ready,
            "JavaScript runtime과 EJS solver"
            if preflight.youtube_ready
            else "JavaScript runtime 또는 EJS solver 확인 필요",
        ),
        SelfCheckItem(
            "URL 안전성",
            _url_policy_ready(),
            "비 HTTP URL과 URL 내 인증정보 차단",
        ),
        SelfCheckItem(
            "비밀값 마스킹",
            _redaction_ready(),
            "URL token과 Cookie 값 비노출",
        ),
        SelfCheckItem(
            "파일명 충돌 방지",
            "[%(id)s]" in output_template,
            "영상 ID를 출력 파일명에 포함",
        ),
        SelfCheckItem(
            "오류 분류",
            _error_policy_ready(),
            "인증, DRM, 네트워크, 의존성, 후처리 오류 구분",
        ),
        SelfCheckItem(
            "네트워크 제한",
            settings.download.socket_timeout_seconds > 0
            and settings.download.retries >= 0
            and settings.download.retry_sleep_seconds >= 0,
            (
                f"timeout={settings.download.socket_timeout_seconds}s, "
                f"retries={settings.download.retries}"
            ),
        ),
    )
    return SelfCheckReport(items)


def format_self_check(report: SelfCheckReport) -> str:
    lines = ["VideoDownloader v5 자체 점검", "=" * 32]
    for item in report.items:
        status = "통과" if item.passed else "실패"
        lines.append(f"[{status:^6}] {item.name:<12} {item.detail}")
    lines.append("-" * 32)
    lines.append("릴리스 점검 통과" if report.passed else "실패 항목을 먼저 해결해야 합니다.")
    return "\n".join(lines)
