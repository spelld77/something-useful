from __future__ import annotations

import unittest
from pathlib import Path

from videodownloader.models import DownloadResult, ErrorKind, Job
from videodownloader.service.batch import (
    BatchItemEvent,
    BatchItemStatus,
    BatchService,
    parse_url_file,
)
from videodownloader.storage.history import FailedUrlStore, HistoryStore

RUNTIME_DIR = Path(__file__).parent / "runtime"


class FakeEngine:
    def __init__(
        self,
        results: list[DownloadResult] | None = None,
        *,
        interrupt: bool = False,
    ) -> None:
        self.results = list(results or [])
        self.interrupt = interrupt
        self.jobs: list[Job] = []

    def probe(self, job: Job) -> object:
        raise NotImplementedError

    def download(self, job: Job, *, on_progress: object = None) -> DownloadResult:
        self.jobs.append(job)
        if self.interrupt:
            raise KeyboardInterrupt
        return self.results.pop(0)


class BatchParserTests(unittest.TestCase):
    def test_parser_skips_comments_invalid_lines_and_duplicates(self) -> None:
        path = Path(__file__).parent / "fixtures" / "batch_urls.txt"

        result = parse_url_file(path)

        self.assertEqual(
            result.urls,
            ("https://example.com/video-1", "https://example.com/video-2"),
        )
        self.assertEqual(result.invalid_lines, (4,))
        self.assertEqual(result.duplicate_count, 1)


class BatchServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.history_path = RUNTIME_DIR / "batch-history.jsonl"
        self.failed_path = RUNTIME_DIR / "batch-failed.txt"
        self.history_path.unlink(missing_ok=True)
        self.failed_path.unlink(missing_ok=True)
        self.addCleanup(self.history_path.unlink, missing_ok=True)
        self.addCleanup(self.failed_path.unlink, missing_ok=True)

    def _service(
        self,
        engine: FakeEngine,
        *,
        sleeps: list[float] | None = None,
    ) -> BatchService:
        return BatchService(
            engine,  # type: ignore[arg-type]
            HistoryStore(self.history_path),
            FailedUrlStore(self.failed_path),
            delay_seconds=1.5,
            engine_version="2026.08.19",
            sleep=(sleeps.append if sleeps is not None else lambda _seconds: None),
        )

    def test_records_success_failure_and_delay(self) -> None:
        engine = FakeEngine(
            [
                DownloadResult(success=True, output_path=Path("one.mp4")),
                DownloadResult(success=False, error_kind=ErrorKind.HTTP_FORBIDDEN),
            ]
        )
        sleeps: list[float] = []
        service = self._service(engine, sleeps=sleeps)

        summary = service.run(
            ["https://example.com/one", "https://example.com/two"],
            mode="video",
        )

        self.assertEqual(summary.succeeded, 1)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(sleeps, [1.5])
        failed_text = self.failed_path.read_text(encoding="utf-8")
        self.assertIn("# ", failed_text)
        self.assertIn("https://example.com/two", failed_text)

    def test_resume_skips_only_completed_url_and_mode(self) -> None:
        first_engine = FakeEngine([DownloadResult(success=True)])
        self._service(first_engine).run(["https://example.com/one"], mode="video")
        second_engine = FakeEngine([DownloadResult(success=True)])

        events: list[BatchItemEvent] = []
        summary = self._service(second_engine).run(
            ["https://example.com/one", "https://example.com/two"],
            mode="video",
            resume=True,
            on_item_finished=events.append,
        )

        self.assertEqual(summary.skipped, 1)
        self.assertEqual(summary.succeeded, 1)
        self.assertEqual([job.url for job in second_engine.jobs], ["https://example.com/two"])
        self.assertEqual(
            [event.status for event in events],
            [BatchItemStatus.SKIPPED, BatchItemStatus.SUCCEEDED],
        )
        self.assertEqual(summary.processed, 2)
        self.assertEqual(summary.unprocessed, 0)

    def test_resume_does_not_skip_a_different_video_quality(self) -> None:
        self._service(FakeEngine([DownloadResult(success=True)])).run(
            ["https://example.com/one"],
            mode="video",
            quality="720p",
        )
        second_engine = FakeEngine([DownloadResult(success=True)])

        summary = self._service(second_engine).run(
            ["https://example.com/one"],
            mode="video",
            quality="1080p",
            resume=True,
        )

        self.assertEqual(summary.skipped, 0)
        self.assertEqual(summary.succeeded, 1)

    def test_keyboard_interrupt_marks_batch_cancelled(self) -> None:
        summary = self._service(FakeEngine(interrupt=True)).run(
            ["https://example.com/one"],
            mode="video",
        )

        self.assertTrue(summary.cancelled)
        self.assertEqual(summary.succeeded, 0)
        self.assertEqual(summary.failed, 0)
        self.assertEqual(summary.cancelled_items, 1)
        self.assertEqual(summary.processed, 1)
        self.assertEqual(summary.unprocessed, 0)

    def test_cancelled_result_stops_without_recording_failure(self) -> None:
        engine = FakeEngine(
            [
                DownloadResult(
                    success=False,
                    error_kind=ErrorKind.CANCELLED,
                    message="cancelled",
                )
            ]
        )

        events: list[BatchItemEvent] = []
        summary = self._service(engine).run(
            ["https://example.com/one", "https://example.com/two"],
            mode="video",
            on_item_finished=events.append,
        )

        self.assertTrue(summary.cancelled)
        self.assertEqual(summary.failed, 0)
        self.assertEqual(summary.cancelled_items, 1)
        self.assertEqual(summary.unprocessed, 1)
        self.assertEqual(events[0].status, BatchItemStatus.CANCELLED)
        self.assertFalse(self.failed_path.exists())

    def test_unexpected_item_error_is_isolated_and_reported(self) -> None:
        class RaisingEngine(FakeEngine):
            def download(self, job: Job, *, on_progress: object = None) -> DownloadResult:
                self.jobs.append(job)
                if len(self.jobs) == 1:
                    raise RuntimeError("boom")
                return DownloadResult(success=True, output_path=Path("two.mp4"))

        events: list[BatchItemEvent] = []
        summary = self._service(RaisingEngine()).run(
            ["https://example.com/one", "https://example.com/two"],
            mode="video",
            on_item_finished=events.append,
        )

        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.succeeded, 1)
        self.assertEqual(summary.processed, 2)
        self.assertEqual(events[0].status, BatchItemStatus.FAILED)
        self.assertEqual(events[0].result.error_kind, ErrorKind.UNKNOWN)  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
