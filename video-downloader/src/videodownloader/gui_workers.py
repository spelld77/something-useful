from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from videodownloader.config import Settings
from videodownloader.engine.base import DownloadEngine
from videodownloader.engine.factory import build_download_engine, build_web_playback_engine
from videodownloader.engine.ytdlp_process import DownloadError
from videodownloader.models import DownloadResult, ErrorKind, Job
from videodownloader.service.batch import BatchService, BatchSummary
from videodownloader.service.file_batch import FileBatchService
from videodownloader.storage.file_history import FileHistoryStore
from videodownloader.storage.history import FailedUrlStore, HistoryStore


class OperationThread(QThread):
    status_changed = Signal(str)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._cancel_requested = threading.Event()
        self._engine_lock = threading.Lock()
        self._engine: DownloadEngine | None = None

    def _build_engine(self) -> DownloadEngine:
        engine = build_download_engine(
            self.settings,
            status_callback=self.status_changed.emit,
            runtime_dir=Path.cwd() / ".runtime",
        )
        with self._engine_lock:
            self._engine = engine
        if self._cancel_requested.is_set():
            engine.cancel()
        return engine

    def cancel(self) -> None:
        self._cancel_requested.set()
        self.status_changed.emit("취소 요청을 처리하고 있습니다...")
        with self._engine_lock:
            engine = self._engine
        if engine is not None:
            engine.cancel()

    @property
    def cancellation_requested(self) -> bool:
        return self._cancel_requested.is_set()


class ProbeThread(OperationThread):
    probe_ready = Signal(object)
    error = Signal(str)

    def __init__(self, settings: Settings, url: str) -> None:
        super().__init__(settings)
        self.url = url

    def run(self) -> None:
        try:
            if self.cancellation_requested:
                self.error.emit("분석을 취소했습니다.")
                return
            result = self._build_engine().probe(Job(self.url))
            if self.cancellation_requested:
                self.error.emit("분석을 취소했습니다.")
                return
            self.probe_ready.emit(result)
        except DownloadError as exc:
            self.error.emit(f"[{exc.kind}] {exc.message}")
        except Exception as exc:
            self.error.emit(f"분석 중 예상하지 못한 오류가 발생했습니다: {exc}")


class DownloadThread(OperationThread):
    progress_changed = Signal(object)
    result_ready = Signal(object)

    def __init__(self, settings: Settings, url: str, mode: str) -> None:
        super().__init__(settings)
        self.url = url
        self.mode = mode

    def run(self) -> None:
        if self.cancellation_requested:
            self.result_ready.emit(
                DownloadResult(
                    success=False,
                    error_kind=ErrorKind.CANCELLED,
                    message="사용자 요청으로 다운로드를 취소했습니다.",
                )
            )
            return
        try:
            result = self._build_engine().download(
                Job(self.url, mode=self.mode),
                on_progress=self.progress_changed.emit,
            )
        except Exception as exc:
            result = DownloadResult(
                success=False,
                error_kind=ErrorKind.UNKNOWN,
                message=f"다운로드 중 예상하지 못한 오류가 발생했습니다: {exc}",
            )
        self.result_ready.emit(result)


class WebPlaybackDownloadThread(OperationThread):
    browser_ready = Signal()
    progress_changed = Signal(object)
    result_ready = Signal(object)

    def __init__(self, settings: Settings, url: str, mode: str) -> None:
        super().__init__(settings)
        self.url = url
        self.mode = mode
        self._main_content_confirmed = threading.Event()

    def _build_engine(self) -> DownloadEngine:
        engine = build_web_playback_engine(
            self.settings,
            confirmation_event=self._main_content_confirmed,
            ready_callback=self.browser_ready.emit,
            status_callback=self.status_changed.emit,
            runtime_dir=Path.cwd() / ".runtime",
        )
        with self._engine_lock:
            self._engine = engine
        if self._cancel_requested.is_set():
            engine.cancel()
        return engine

    def confirm_main_content(self) -> None:
        self._main_content_confirmed.set()
        self.status_changed.emit("본편 미디어 요청을 확인하고 있습니다...")

    def run(self) -> None:
        if self.cancellation_requested:
            self.result_ready.emit(
                DownloadResult(
                    success=False,
                    error_kind=ErrorKind.CANCELLED,
                    message="사용자 요청으로 다운로드를 취소했습니다.",
                )
            )
            return
        try:
            result = self._build_engine().download(
                Job(self.url, mode=self.mode),
                on_progress=self.progress_changed.emit,
            )
        except Exception as exc:
            result = DownloadResult(
                success=False,
                error_kind=ErrorKind.UNKNOWN,
                message=f"웹 재생 다운로드 중 예상하지 못한 오류가 발생했습니다: {exc}",
            )
        self.result_ready.emit(result)


class BatchThread(OperationThread):
    progress_changed = Signal(object)
    item_started = Signal(int, int, str)
    item_finished = Signal(object)
    summary_ready = Signal(object)

    def __init__(self, settings: Settings, urls: tuple[str, ...], mode: str) -> None:
        super().__init__(settings)
        self.urls = urls
        self.mode = mode

    def _interruptible_sleep(self, seconds: float) -> None:
        if self._cancel_requested.wait(seconds):
            raise KeyboardInterrupt

    def run(self) -> None:
        if self.cancellation_requested:
            self.summary_ready.emit(BatchSummary(total=len(self.urls), cancelled=True))
            return
        engine = self._build_engine()
        service = BatchService(
            engine,
            HistoryStore(self.settings.batch.history_file),
            FailedUrlStore(self.settings.batch.failed_file),
            delay_seconds=self.settings.batch.delay_seconds,
            sleep=self._interruptible_sleep,
        )
        summary = service.run(
            self.urls,
            mode=self.mode,
            quality=self.settings.download.video_quality,
            resume=self.settings.batch.resume,
            on_item_start=self.item_started.emit,
            on_item_finished=self.item_finished.emit,
            on_progress=self.progress_changed.emit,
        )
        self.summary_ready.emit(summary)


class FileBatchThread(OperationThread):
    progress_changed = Signal(object)
    item_started = Signal(int, int, str)
    item_finished = Signal(object)
    summary_ready = Signal(object)

    def __init__(self, settings: Settings, urls: tuple[str, ...]) -> None:
        super().__init__(settings)
        self.urls = urls
        self._file_service: FileBatchService | None = None

    def cancel(self) -> None:
        self._cancel_requested.set()
        self.status_changed.emit("파일 다운로드 취소 요청을 처리하고 있습니다...")
        if self._file_service is not None:
            self._file_service.cancel()

    def run(self) -> None:
        if self.cancellation_requested:
            self.summary_ready.emit(BatchSummary(total=len(self.urls), cancelled=True))
            return
        service = FileBatchService(
            self.settings.file_download,
            FileHistoryStore(self.settings.file_download.history_file),
        )
        self._file_service = service
        if self.cancellation_requested:
            service.cancel()
        try:
            summary = service.run(
                self.urls,
                resume=self.settings.file_download.resume_partial,
                on_item_start=self.item_started.emit,
                on_item_finished=self.item_finished.emit,
                on_progress=self.progress_changed.emit,
            )
        except Exception as exc:
            summary = BatchSummary(
                total=len(self.urls),
                failed=len(self.urls),
                warnings=[f"파일 일괄 다운로드를 시작할 수 없습니다: {exc}"],
            )
        finally:
            self._file_service = None
        self.summary_ready.emit(summary)
