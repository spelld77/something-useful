from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from videodownloader.engine.base import ProgressCallback
from videodownloader.engine.browser_capture import CaptureResult, scoped_cookie_file
from videodownloader.engine.ytdlp_process import YtDlpProcessEngine
from videodownloader.models import DownloadResult, ErrorKind, Job


def download_capture_result(
    primary: YtDlpProcessEngine,
    captured: CaptureResult,
    job: Job,
    *,
    runtime_dir: Path,
    on_progress: ProgressCallback | None = None,
) -> DownloadResult:
    try:
        with scoped_cookie_file(
            captured.cookies,
            captured.media_url,
            runtime_dir,
        ) as cookie_file:
            captured_job = replace(
                job,
                url=captured.media_url,
                http_headers=captured.http_headers,
                cookie_file=cookie_file,
            )
            return primary.download(captured_job, on_progress=on_progress)
    except OSError as exc:
        return DownloadResult(
            success=False,
            error_kind=ErrorKind.AUTH_REQUIRED,
            message=f"임시 브라우저 쿠키 파일을 처리할 수 없습니다: {exc}",
        )
