from __future__ import annotations

import threading
from collections.abc import Callable
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


class BrowserCaptureDownloadEngine:
    """Capture a user-confirmed main stream before invoking yt-dlp."""

    def __init__(
        self,
        primary: YtDlpProcessEngine,
        capture: BrowserCapture,
        *,
        confirmation_event: threading.Event,
        ready_callback: Callable[[], None] | None,
        runtime_dir: Path,
    ) -> None:
        self.primary = primary
        self.capture = capture
        self.confirmation_event = confirmation_event
        self.ready_callback = ready_callback
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
        if is_capture_blocked_url(job.url):
            return DownloadResult(
                success=False,
                error_kind=ErrorKind.UNSUPPORTED_URL,
                message="YouTube는 일반 다운로드를 사용하세요.",
            )
        try:
            captured = self.capture.capture(
                job.url,
                confirmation_event=self.confirmation_event,
                ready_callback=self.ready_callback,
            )
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
