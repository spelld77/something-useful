from __future__ import annotations

import json
import unittest
from pathlib import Path

from videodownloader.models import DownloadResult, ErrorKind, MediaInfo
from videodownloader.storage.history import HistoryRecord, HistoryStore, url_fingerprint

RUNTIME_DIR = Path(__file__).parent / "runtime"


class HistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = RUNTIME_DIR / "history-test.jsonl"
        self.path.unlink(missing_ok=True)
        self.addCleanup(self.path.unlink, missing_ok=True)

    def test_completed_keys_ignore_failures_and_corrupt_lines(self) -> None:
        store = HistoryStore(self.path)
        completed = HistoryRecord.from_result(
            "https://example.com/complete",
            "video",
            DownloadResult(success=True, output_path=Path("video.mp4")),
        )
        failed = HistoryRecord.from_result(
            "https://example.com/failed",
            "video",
            DownloadResult(success=False, error_kind=ErrorKind.HTTP_FORBIDDEN),
        )
        store.append(completed)
        store.append(failed)
        with self.path.open("a", encoding="utf-8") as history_file:
            history_file.write("not-json\n")

        keys = store.completed_keys()

        self.assertEqual(
            keys,
            {(url_fingerprint("https://example.com/complete"), "video", "")},
        )

    def test_history_does_not_store_original_url(self) -> None:
        url = "https://example.com/video?token=secret"
        store = HistoryStore(self.path)
        store.append(HistoryRecord.from_result(url, "audio", DownloadResult(success=True)))

        raw = self.path.read_text(encoding="utf-8")
        payload = json.loads(raw)

        self.assertNotIn(url, raw)
        self.assertEqual(payload["url_hash"], url_fingerprint(url))

    def test_history_records_actual_media_details(self) -> None:
        result = DownloadResult(
            success=True,
            output_path=Path("video.mp4"),
            media_info=MediaInfo(
                width=1920,
                height=1080,
                video_codec="h264",
                audio_codec="aac",
            ),
        )

        record = HistoryRecord.from_result("https://example.com/video", "video", result)

        self.assertEqual(record.resolution, "1920×1080")
        self.assertEqual(record.video_codec, "h264")
        self.assertEqual(record.audio_codec, "aac")


if __name__ == "__main__":
    unittest.main()
