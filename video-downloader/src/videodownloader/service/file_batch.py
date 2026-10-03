from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

from videodownloader.config import FileDownloadConfig
from videodownloader.engine.http_file import FilenameRegistry, HttpFileEngine, SpaceReservation
from videodownloader.models import DownloadResult, ErrorKind, Job
from videodownloader.service.batch import (
    BatchItemEvent,
    BatchItemStatus,
    BatchSummary,
    ItemFinishedCallback,
    ItemStartCallback,
)
from videodownloader.storage.file_history import FileHistoryRecord, FileHistoryStore
from videodownloader.storage.history import url_fingerprint

FileProgressCallback = Callable[[dict[str, object]], None]


class FileBatchService:
    def __init__(
        self,
        settings: FileDownloadConfig,
        history: FileHistoryStore,
    ) -> None:
        self.settings = settings
        self.history = history
        self._cancel_requested = threading.Event()
        self._engines_lock = threading.Lock()
        self._active_engines: set[HttpFileEngine] = set()

    def cancel(self) -> None:
        self._cancel_requested.set()
        with self._engines_lock:
            engines = tuple(self._active_engines)
        for engine in engines:
            engine.cancel()

    def run(
        self,
        urls: Sequence[str],
        *,
        resume: bool = True,
        on_item_start: ItemStartCallback | None = None,
        on_item_finished: ItemFinishedCallback | None = None,
        on_progress: FileProgressCallback | None = None,
    ) -> BatchSummary:
        total = len(urls)
        summary = BatchSummary(total=total)
        if self._cancel_requested.is_set():
            summary.cancelled = True
            return summary

        try:
            completed = self.history.completed_hashes() if resume else set()
        except OSError as exc:
            completed = set()
            summary.warnings.append(f"파일 이력을 읽을 수 없어 재개를 건너뜁니다: {exc}")

        save_dir = self.settings.save_dir.expanduser().resolve()
        save_dir.mkdir(parents=True, exist_ok=True)
        registry = FilenameRegistry(save_dir)
        space = SpaceReservation(save_dir)
        queue: deque[tuple[int, str]] = deque()

        for index, url in enumerate(urls, start=1):
            if url_fingerprint(url) in completed:
                summary.skipped += 1
                self._notify(
                    on_item_finished,
                    BatchItemEvent(index, total, url, BatchItemStatus.SKIPPED),
                )
            else:
                queue.append((index, url))

        executor = ThreadPoolExecutor(
            max_workers=self.settings.concurrency,
            thread_name_prefix="file-download",
        )
        active: dict[Future[DownloadResult], tuple[int, str]] = {}
        try:
            self._fill_active(
                executor,
                active,
                queue,
                total,
                registry,
                space,
                on_item_start,
                on_progress,
            )
            while active:
                done, _pending = wait(active, timeout=0.2, return_when=FIRST_COMPLETED)
                for future in done:
                    index, url = active.pop(future)
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = DownloadResult(
                            False,
                            error_kind=ErrorKind.UNKNOWN,
                            message=f"파일 다운로드 중 예상하지 못한 오류가 발생했습니다: {exc}",
                        )
                    if result.error_kind == ErrorKind.CANCELLED:
                        summary.cancelled = True
                        summary.cancelled_items += 1
                        status = BatchItemStatus.CANCELLED
                    elif result.success:
                        summary.succeeded += 1
                        status = BatchItemStatus.SUCCEEDED
                        if result.output_path is not None:
                            try:
                                self.history.append(
                                    FileHistoryRecord.completed(url, result.output_path)
                                )
                            except OSError as exc:
                                summary.warnings.append(
                                    f"파일 다운로드 이력을 기록하지 못했습니다: {exc}"
                                )
                    else:
                        summary.failed += 1
                        status = BatchItemStatus.FAILED
                    self._notify(
                        on_item_finished,
                        BatchItemEvent(index, total, url, status, result),
                    )

                if self._cancel_requested.is_set():
                    summary.cancelled = True
                else:
                    self._fill_active(
                        executor,
                        active,
                        queue,
                        total,
                        registry,
                        space,
                        on_item_start,
                        on_progress,
                    )
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

        if self._cancel_requested.is_set():
            summary.cancelled = True
        return summary

    def _fill_active(
        self,
        executor: ThreadPoolExecutor,
        active: dict[Future[DownloadResult], tuple[int, str]],
        queue: deque[tuple[int, str]],
        total: int,
        registry: FilenameRegistry,
        space: SpaceReservation,
        on_item_start: ItemStartCallback | None,
        on_progress: FileProgressCallback | None,
    ) -> None:
        while (
            queue
            and len(active) < self.settings.concurrency
            and not self._cancel_requested.is_set()
        ):
            index, url = queue.popleft()
            if on_item_start is not None:
                on_item_start(index, total, url)
            future = executor.submit(
                self._download_one,
                index,
                total,
                url,
                registry,
                space,
                on_progress,
            )
            active[future] = (index, url)

    def _download_one(
        self,
        index: int,
        total: int,
        url: str,
        registry: FilenameRegistry,
        space: SpaceReservation,
        on_progress: FileProgressCallback | None,
    ) -> DownloadResult:
        engine = HttpFileEngine(self.settings, registry, space)
        with self._engines_lock:
            self._active_engines.add(engine)
        if self._cancel_requested.is_set():
            engine.cancel()

        def progress(payload: dict[str, object]) -> None:
            if on_progress is not None:
                on_progress({**payload, "index": index, "total": total, "url": url})

        try:
            return engine.download(Job(url=url, mode="file"), on_progress=progress)
        finally:
            with self._engines_lock:
                self._active_engines.discard(engine)

    @staticmethod
    def _notify(callback: ItemFinishedCallback | None, event: BatchItemEvent) -> None:
        if callback is not None:
            callback(event)
