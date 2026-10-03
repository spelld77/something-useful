from __future__ import annotations

from pathlib import Path

from videodownloader.engine.base import ProgressCallback
from videodownloader.engine.browser_capture import (
    BrowserCapture,
    BrowserCaptureError,
    is_capture_blocked_url,
)
from videodownloader.engine.capture_download import download_capture_result
from videodownloader.engine.ytdlp_process import YtDlpProcessEngine
from videodownloader.models import DownloadResult, ErrorKind, Job, ProbeResult

FALLBACK_ERROR_KINDS = {
    ErrorKind.UNSUPPORTED_URL,
    ErrorKind.FORMAT_UNAVAILABLE,
    ErrorKind.AUTH_REQUIRED,
    ErrorKind.HTTP_FORBIDDEN,
    ErrorKind.UNKNOWN,
}


class BrowserFallbackEngine:
    """Try yt-dlp first, then explicitly enabled browser capture for generic sites."""

    def __init__(
        self,
        primary: YtDlpProcessEngine,
        capture: BrowserCapture,
        *,
        runtime_dir: Path,
    ) -> None:
        self.primary = primary
        self.capture = capture
        self.runtime_dir = runtime_dir

    def cancel(self) -> None:
        self.capture.cancel()
        self.primary.cancel()

    def probe(self, job: Job) -> ProbeResult:
        return self.primary.probe(job)

    def download(
        self,
        job: Job,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> DownloadResult:
        initial = self.primary.download(job, on_progress=on_progress)
        if initial.success or initial.error_kind not in FALLBACK_ERROR_KINDS:
            return initial

        if is_capture_blocked_url(job.url):
            return initial

        try:
            captured = self.capture.capture(job.url)
            return download_capture_result(
                self.primary,
                captured,
                job,
                runtime_dir=self.runtime_dir,
                on_progress=on_progress,
            )
        except BrowserCaptureError as exc:
            return DownloadResult(
                success=False,
                error_kind=exc.kind,
                message=exc.message,
            )
