from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from videodownloader.config import Settings
from videodownloader.engine.base import DownloadEngine
from videodownloader.engine.browser_capture import BrowserCapture
from videodownloader.engine.fallback import BrowserFallbackEngine
from videodownloader.engine.web_playback import BrowserCaptureDownloadEngine
from videodownloader.engine.ytdlp_process import YtDlpProcessEngine


def build_download_engine(
    settings: Settings,
    *,
    status_callback: Callable[[str], None] | None = None,
    runtime_dir: Path | None = None,
) -> DownloadEngine:
    primary = YtDlpProcessEngine(settings)
    if not settings.browser_capture.enabled:
        return primary
    capture = BrowserCapture(
        browser=settings.browser_capture.browser,
        timeout_seconds=settings.browser_capture.timeout_seconds,
        interactive_timeout_seconds=settings.browser_capture.interactive_timeout_seconds,
        grace_seconds=settings.browser_capture.grace_seconds,
        status_callback=status_callback,
    )
    return BrowserFallbackEngine(
        primary,
        capture,
        runtime_dir=runtime_dir or Path.cwd() / ".runtime",
    )


def build_web_playback_engine(
    settings: Settings,
    *,
    confirmation_event: threading.Event,
    ready_callback: Callable[[], None] | None = None,
    status_callback: Callable[[str], None] | None = None,
    runtime_dir: Path | None = None,
) -> DownloadEngine:
    primary = YtDlpProcessEngine(settings)
    capture = BrowserCapture(
        browser=settings.browser_capture.browser,
        timeout_seconds=settings.browser_capture.timeout_seconds,
        interactive_timeout_seconds=settings.browser_capture.interactive_timeout_seconds,
        grace_seconds=settings.browser_capture.grace_seconds,
        status_callback=status_callback,
    )
    return BrowserCaptureDownloadEngine(
        primary,
        capture,
        confirmation_event=confirmation_event,
        ready_callback=ready_callback,
        runtime_dir=runtime_dir or Path.cwd() / ".runtime",
    )
