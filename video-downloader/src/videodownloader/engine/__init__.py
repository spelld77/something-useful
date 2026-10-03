"""Download engine adapters."""

from videodownloader.engine.base import DownloadEngine, ProgressCallback
from videodownloader.engine.fallback import BrowserFallbackEngine
from videodownloader.engine.http_file import HttpFileEngine
from videodownloader.engine.web_playback import BrowserCaptureDownloadEngine
from videodownloader.engine.ytdlp_process import DownloadError, YtDlpProcessEngine

__all__ = [
    "BrowserFallbackEngine",
    "HttpFileEngine",
    "BrowserCaptureDownloadEngine",
    "DownloadEngine",
    "DownloadError",
    "ProgressCallback",
    "YtDlpProcessEngine",
]
