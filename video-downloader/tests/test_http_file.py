from __future__ import annotations

import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from videodownloader.config import FileDownloadConfig
from videodownloader.engine.http_file import (
    FilenameRegistry,
    HttpFileEngine,
    SpaceReservation,
    is_unexpected_html,
    response_filename,
    safe_filename,
)
from videodownloader.models import DownloadResult, ErrorKind, Job
from videodownloader.service.batch import BatchItemEvent, BatchItemStatus, BatchSummary
from videodownloader.service.file_batch import FileBatchService
from videodownloader.storage.file_history import FileHistoryStore
from videodownloader.storage.history import url_fingerprint

PAYLOAD = (b"direct-file-content-" * 4096) + b"end"
RUNTIME_DIR = Path(__file__).parent / "runtime"


class DownloadHandler(BaseHTTPRequestHandler):
    range_seen = False
    stall_requests = 0
    stall_lock = threading.Lock()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/file")
            self.end_headers()
            return
        if self.path == "/html":
            body = b"<html><body>login</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/missing":
            self.send_error(404)
            return
        if self.path == "/empty":
            self.send_response(204)
            self.end_headers()
            return
        if self.path in {"/file", "/range", "/stall-once"}:
            if self.path == "/stall-once":
                with type(self).stall_lock:
                    type(self).stall_requests += 1
                    should_stall = type(self).stall_requests == 1
                if should_stall:
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(len(PAYLOAD)))
                    self.send_header("Content-Disposition", "attachment; filename=movie.mp4")
                    self.end_headers()
                    self.wfile.write(PAYLOAD[:1024])
                    self.wfile.flush()
                    time.sleep(1.25)
                    return
            start = 0
            range_header = self.headers.get("Range", "")
            if self.path == "/range" and range_header.startswith("bytes="):
                start = int(range_header.removeprefix("bytes=").removesuffix("-"))
                type(self).range_seen = True
                self.send_response(206)
                self.send_header(
                    "Content-Range", f"bytes {start}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}"
                )
            else:
                self.send_response(200)
            body = PAYLOAD[start:]
            self.send_header("Content-Type", "application/pdf")
            self.send_header("ETag", '"test-etag"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Content-Disposition",
                "attachment; filename*=UTF-8''report-%ED%95%9C%EA%B8%80.pdf",
            )
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(500)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class HttpFileEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), DownloadHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory(dir=RUNTIME_DIR)
        self.addCleanup(self.temp_dir.cleanup)
        self.directory = Path(self.temp_dir.name)
        self.settings = FileDownloadConfig(
            save_dir=self.directory,
            retries=0,
            connect_timeout_seconds=3,
            read_timeout_seconds=3,
        )

    def _engine(self) -> HttpFileEngine:
        return HttpFileEngine(
            self.settings,
            FilenameRegistry(self.directory),
            SpaceReservation(self.directory),
        )

    def test_downloads_redirect_and_uses_utf8_content_disposition(self) -> None:
        events: list[dict[str, object]] = []

        result = self._engine().download(
            Job(f"{self.base_url}/redirect", mode="file"),
            on_progress=events.append,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.output_path.name, "report-한글.pdf")  # type: ignore[union-attr]
        self.assertEqual(result.output_path.read_bytes(), PAYLOAD)  # type: ignore[union-attr]
        self.assertTrue(events)
        self.assertEqual(events[-1]["total_bytes"], len(PAYLOAD))

    def test_rejects_unexpected_html_and_http_204(self) -> None:
        html = self._engine().download(Job(f"{self.base_url}/html", mode="file"))
        empty = self._engine().download(Job(f"{self.base_url}/empty", mode="file"))

        self.assertEqual(html.error_kind, ErrorKind.UNEXPECTED_CONTENT)
        self.assertEqual(empty.error_kind, ErrorKind.UNEXPECTED_CONTENT)
        self.assertFalse(tuple(self.directory.glob("*.html")))

    def test_classifies_missing_file(self) -> None:
        result = self._engine().download(Job(f"{self.base_url}/missing", mode="file"))

        self.assertEqual(result.error_kind, ErrorKind.FILE_NOT_FOUND)

    def test_resumes_matching_partial_file_with_range(self) -> None:
        url = f"{self.base_url}/range"
        fingerprint = url_fingerprint(url)
        part = self.directory / f".file-{fingerprint[:20]}.part"
        metadata = self.directory / f".file-{fingerprint[:20]}.json"
        midpoint = len(PAYLOAD) // 2
        part.write_bytes(PAYLOAD[:midpoint])
        metadata.write_text(
            json.dumps(
                {
                    "url_hash": fingerprint,
                    "filename": "resumed.pdf",
                    "etag": '"test-etag"',
                    "last_modified": "",
                    "total_bytes": len(PAYLOAD),
                }
            ),
            encoding="utf-8",
        )
        DownloadHandler.range_seen = False

        result = self._engine().download(Job(url, mode="file"))

        self.assertTrue(result.success)
        self.assertTrue(DownloadHandler.range_seen)
        self.assertEqual(result.output_path.name, "resumed.pdf")  # type: ignore[union-attr]
        self.assertEqual(result.output_path.read_bytes(), PAYLOAD)  # type: ignore[union-attr]
        self.assertFalse(part.exists())
        self.assertFalse(metadata.exists())

    def test_filename_safety_and_html_rules(self) -> None:
        self.assertEqual(safe_filename("../../CON.txt"), "_CON.txt")
        self.assertEqual(safe_filename("bad<name>.zip"), "bad_name_.zip")
        self.assertEqual(
            response_filename("", "https://example.com/path/archive.zip?token=x", ""),
            "archive.zip",
        )
        self.assertTrue(is_unexpected_html("text/html", "", "https://example.com/login"))
        self.assertFalse(
            is_unexpected_html("text/html", "attachment; filename=page.html", "https://x")
        )

    def test_registry_avoids_case_insensitive_collisions(self) -> None:
        registry = FilenameRegistry(self.directory)

        first = registry.reserve("File.zip")
        second = registry.reserve("file.zip")

        self.assertEqual(first.name, "File.zip")
        self.assertEqual(second.name, "file (1).zip")

    def test_many_small_network_reads_do_not_flood_progress_updates(self) -> None:
        payload = b"x" * (1024 * 1024)

        class TinyChunkResponse:
            def __init__(self) -> None:
                self.offset = 0

            def read1(self, _size: int) -> bytes:
                chunk = payload[self.offset : self.offset + 1024]
                self.offset += len(chunk)
                return chunk

        events: list[dict[str, object]] = []
        output = self.directory / "tiny-chunks.bin"
        part = self.directory / ".tiny-chunks.part"

        with patch("videodownloader.engine.http_file.time.monotonic", return_value=100.0):
            result = self._engine()._stream_response(
                TinyChunkResponse(),
                part,
                output,
                append=False,
                initial_size=0,
                total_bytes=len(payload),
                on_progress=events.append,
                attempt=1,
                max_attempts=1,
            )

        self.assertTrue(result.success)
        self.assertEqual(output.stat().st_size, len(payload))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["percent"], 100.0)

    def test_file_batch_downloads_concurrently_and_resumes_history(self) -> None:
        settings = FileDownloadConfig(
            save_dir=self.directory,
            history_file=self.directory / "history.jsonl",
            concurrency=2,
            retries=0,
            connect_timeout_seconds=3,
            read_timeout_seconds=3,
        )
        urls = (f"{self.base_url}/file", f"{self.base_url}/redirect")
        events: list[BatchItemEvent] = []
        service = FileBatchService(settings, FileHistoryStore(settings.history_file))

        summary = service.run(urls, on_item_finished=events.append)

        self.assertEqual(summary.succeeded, 2)
        self.assertEqual(
            [event.status for event in sorted(events, key=lambda event: event.index)],
            [BatchItemStatus.SUCCEEDED, BatchItemStatus.SUCCEEDED],
        )
        outputs = sorted(path.name for path in self.directory.glob("*.pdf"))
        self.assertEqual(outputs, ["report-한글 (1).pdf", "report-한글.pdf"])

        resumed_events: list[BatchItemEvent] = []
        resumed = FileBatchService(settings, FileHistoryStore(settings.history_file)).run(
            urls, on_item_finished=resumed_events.append
        )

        self.assertEqual(resumed.skipped, 2)
        self.assertEqual(
            [event.status for event in resumed_events],
            [BatchItemStatus.SKIPPED, BatchItemStatus.SKIPPED],
        )

    def test_stalled_response_reports_wait_and_retries_from_partial_file(self) -> None:
        DownloadHandler.stall_requests = 0
        settings = FileDownloadConfig(
            save_dir=self.directory,
            retries=1,
            connect_timeout_seconds=3,
            read_timeout_seconds=1,
        )
        progress: list[dict[str, object]] = []
        engine = HttpFileEngine(
            settings,
            FilenameRegistry(self.directory),
            SpaceReservation(self.directory),
        )

        result = engine.download(
            Job(f"{self.base_url}/stall-once", mode="file"),
            on_progress=progress.append,
        )

        self.assertTrue(result.success)
        self.assertGreaterEqual(DownloadHandler.stall_requests, 2)
        phases = [event.get("phase") for event in progress]
        self.assertIn("waiting", phases)
        self.assertIn("retrying", phases)
        self.assertEqual(
            [event.get("attempt") for event in progress if event.get("phase") == "connecting"],
            [1, 2],
        )

    def test_file_batch_cancel_leaves_queued_items_unprocessed(self) -> None:
        started = threading.Event()

        class BlockingEngine:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                self.cancelled = threading.Event()

            def cancel(self) -> None:
                self.cancelled.set()

            def download(self, _job: Job, *, on_progress: object = None) -> DownloadResult:
                started.set()
                self.cancelled.wait(2)
                return DownloadResult(
                    False,
                    error_kind=ErrorKind.CANCELLED,
                    message="cancelled",
                )

        settings = FileDownloadConfig(
            save_dir=self.directory,
            history_file=self.directory / "history.jsonl",
            concurrency=1,
            retries=0,
        )
        service = FileBatchService(settings, FileHistoryStore(settings.history_file))
        summaries: list[BatchSummary] = []

        with patch("videodownloader.service.file_batch.HttpFileEngine", BlockingEngine):
            thread = threading.Thread(
                target=lambda: summaries.append(
                    service.run(
                        (
                            "https://example.com/one",
                            "https://example.com/two",
                            "https://example.com/three",
                        )
                    )
                )
            )
            thread.start()
            self.assertTrue(started.wait(1))
            service.cancel()
            thread.join(timeout=3)

        self.assertFalse(thread.is_alive())
        summary = summaries[0]
        self.assertTrue(summary.cancelled)
        self.assertEqual(summary.cancelled_items, 1)
        self.assertEqual(summary.unprocessed, 2)


if __name__ == "__main__":
    unittest.main()
