from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path

from videodownloader.engine.base import DownloadEngine, ProgressCallback
from videodownloader.engine.ytdlp_process import DownloadError, validate_url
from videodownloader.models import DownloadResult, ErrorKind, Job
from videodownloader.storage.history import (
    FailedUrlStore,
    HistoryRecord,
    HistoryStore,
    url_fingerprint,
)


@dataclass(frozen=True, slots=True)
class UrlFileResult:
    urls: tuple[str, ...]
    invalid_lines: tuple[int, ...] = ()
    duplicate_count: int = 0


@dataclass(slots=True)
class BatchSummary:
    total: int
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled_items: int = 0
    cancelled: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def processed(self) -> int:
        return self.succeeded + self.failed + self.skipped + self.cancelled_items

    @property
    def unprocessed(self) -> int:
        return max(0, self.total - self.processed)


class BatchItemStatus(StrEnum):
    SUCCEEDED = auto()
    FAILED = auto()
    SKIPPED = auto()
    CANCELLED = auto()


@dataclass(frozen=True, slots=True)
class BatchItemEvent:
    index: int
    total: int
    url: str
    status: BatchItemStatus
    result: DownloadResult | None = None


ItemStartCallback = Callable[[int, int, str], None]
ItemFinishedCallback = Callable[[BatchItemEvent], None]


def parse_url_file(path: Path) -> UrlFileResult:
    urls: list[str] = []
    seen: set[str] = set()
    invalid_lines: list[int] = []
    duplicate_count = 0

    with path.expanduser().resolve().open("r", encoding="utf-8-sig") as url_file:
        for line_number, raw_line in enumerate(url_file, start=1):
            value = raw_line.strip()
            if not value or value.startswith("#"):
                continue
            try:
                normalized = validate_url(value)
            except DownloadError:
                invalid_lines.append(line_number)
                continue
            if normalized in seen:
                duplicate_count += 1
                continue
            seen.add(normalized)
            urls.append(normalized)

    return UrlFileResult(
        urls=tuple(urls),
        invalid_lines=tuple(invalid_lines),
        duplicate_count=duplicate_count,
    )


class BatchService:
    def __init__(
        self,
        engine: DownloadEngine,
        history: HistoryStore,
        failed_urls: FailedUrlStore,
        *,
        delay_seconds: float = 2.0,
        engine_version: str = "",
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.engine = engine
        self.history = history
        self.failed_urls = failed_urls
        self.delay_seconds = max(0.0, delay_seconds)
        self.engine_version = engine_version
        self.sleep = sleep

    def run(
        self,
        urls: Sequence[str],
        *,
        mode: str,
        quality: str = "best",
        resume: bool = True,
        on_item_start: ItemStartCallback | None = None,
        on_item_finished: ItemFinishedCallback | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> BatchSummary:
        summary = BatchSummary(total=len(urls))
        completed = self._completed_keys(summary) if resume else set()
        history_quality = quality if mode == "video" else ""

        for index, url in enumerate(urls, start=1):
            key = (url_fingerprint(url), mode, history_quality)
            if key in completed:
                summary.skipped += 1
                self._notify_item_finished(
                    on_item_finished,
                    BatchItemEvent(
                        index=index,
                        total=len(urls),
                        url=url,
                        status=BatchItemStatus.SKIPPED,
                    ),
                )
                continue
            if on_item_start is not None:
                on_item_start(index, len(urls), url)

            try:
                result = self.engine.download(Job(url=url, mode=mode), on_progress=on_progress)
            except KeyboardInterrupt:
                summary.cancelled = True
                summary.cancelled_items += 1
                self._notify_item_finished(
                    on_item_finished,
                    BatchItemEvent(
                        index=index,
                        total=len(urls),
                        url=url,
                        status=BatchItemStatus.CANCELLED,
                    ),
                )
                break
            except Exception as exc:
                result = DownloadResult(
                    success=False,
                    error_kind=ErrorKind.UNKNOWN,
                    message=f"다운로드 중 예상하지 못한 오류가 발생했습니다: {exc}",
                )

            if result.error_kind == ErrorKind.CANCELLED:
                summary.cancelled = True
                summary.cancelled_items += 1
                self._notify_item_finished(
                    on_item_finished,
                    BatchItemEvent(
                        index=index,
                        total=len(urls),
                        url=url,
                        status=BatchItemStatus.CANCELLED,
                        result=result,
                    ),
                )
                break

            self._record_result(summary, url, mode, history_quality, result)
            if result.success:
                summary.succeeded += 1
                completed.add(key)
                status = BatchItemStatus.SUCCEEDED
            else:
                summary.failed += 1
                self._record_failure(summary, url, result)
                status = BatchItemStatus.FAILED

            self._notify_item_finished(
                on_item_finished,
                BatchItemEvent(
                    index=index,
                    total=len(urls),
                    url=url,
                    status=status,
                    result=result,
                ),
            )

            if index < len(urls) and self.delay_seconds:
                try:
                    self.sleep(self.delay_seconds)
                except KeyboardInterrupt:
                    summary.cancelled = True
                    break

        return summary

    @staticmethod
    def _notify_item_finished(
        callback: ItemFinishedCallback | None,
        event: BatchItemEvent,
    ) -> None:
        if callback is not None:
            callback(event)

    def _completed_keys(self, summary: BatchSummary) -> set[tuple[str, str, str]]:
        try:
            return self.history.completed_keys()
        except OSError as exc:
            summary.warnings.append(f"이력 파일을 읽을 수 없어 재개를 건너뜁니다: {exc}")
            return set()

    def _record_result(
        self,
        summary: BatchSummary,
        url: str,
        mode: str,
        quality: str,
        result: DownloadResult,
    ) -> None:
        record = HistoryRecord.from_result(
            url,
            mode,
            result,
            quality=quality,
            engine_version=self.engine_version,
        )
        try:
            self.history.append(record)
        except OSError as exc:
            summary.warnings.append(f"작업 이력을 기록하지 못했습니다: {exc}")

    def _record_failure(
        self,
        summary: BatchSummary,
        url: str,
        result: DownloadResult,
    ) -> None:
        try:
            self.failed_urls.append(url, result.error_kind)
        except OSError as exc:
            summary.warnings.append(f"실패 URL을 기록하지 못했습니다: {exc}")
