from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from videodownloader.config import AppConfig, Settings  # noqa: E402
from videodownloader.gui import (  # noqa: E402
    MainWindow,
    format_media_summary,
    format_url_for_display,
    main,
    parse_url_text,
)
from videodownloader.gui_workers import (  # noqa: E402
    BatchThread,
    DownloadThread,
    WebPlaybackDownloadThread,
)
from videodownloader.models import DownloadResult, ErrorKind, Job, MediaInfo  # noqa: E402
from videodownloader.service.batch import (  # noqa: E402
    BatchItemEvent,
    BatchItemStatus,
    BatchSummary,
)


class FakeEngine:
    def __init__(self, result: DownloadResult) -> None:
        self.result = result
        self.jobs: list[Job] = []
        self.cancelled = False

    def probe(self, job: Job) -> object:
        raise NotImplementedError

    def download(self, job: Job, *, on_progress: object = None) -> DownloadResult:
        self.jobs.append(job)
        if on_progress is not None:
            on_progress({"percent": "50.0%", "speed": "1MiB/s", "eta": "00:01"})  # type: ignore[operator]
        return self.result

    def cancel(self) -> None:
        self.cancelled = True


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_url_text_parser_rejects_invalid_and_deduplicates(self) -> None:
        urls, invalid, duplicates = parse_url_text(
            "https://example.com/one\ninvalid\nhttps://example.com/one\n"
        )

        self.assertEqual(urls, ("https://example.com/one",))
        self.assertEqual(invalid, (2,))
        self.assertEqual(duplicates, 1)

    def test_gui_version_exits_without_starting_event_loop(self) -> None:
        self.assertEqual(main(["--version"]), 0)

    def test_window_exposes_single_batch_and_advanced_settings(self) -> None:
        window = MainWindow(Settings(app=AppConfig(save_dir=Path("downloads"))))
        self.addCleanup(window.close)

        self.assertEqual(window.tabs.count(), 3)
        self.assertEqual(window.tabs.tabText(2), "파일 일괄 다운로드")
        self.assertEqual(window.file_concurrency.value(), 1)
        self.assertEqual(window.file_save_dir_edit.text(), "savedFiles")
        window.tabs.setCurrentIndex(2)
        self.assertTrue(window.download_settings_group.isHidden())
        window.tabs.setCurrentIndex(0)
        self.assertFalse(window.download_settings_group.isHidden())
        self.assertEqual(window.save_dir_edit.text(), "downloads")
        self.assertIn("최고 화질", window.quality_combo.currentText())
        self.assertIn("QMessageBox QLabel", self.application.styleSheet())
        self.assertIn("QTableWidget::item", self.application.styleSheet())
        self.assertIn("QHeaderView::section", self.application.styleSheet())
        self.assertIn("QSpinBox", self.application.styleSheet())

        window.show()
        self.application.processEvents()
        palette = window.file_table.palette()
        self.assertEqual(palette.color(QPalette.ColorRole.Base).name(), "#ffffff")
        self.assertEqual(palette.color(QPalette.ColorRole.Text).name(), "#172033")
        self.assertEqual(palette.color(QPalette.ColorRole.Highlight).name(), "#dbe7ff")
        self.assertEqual(palette.color(QPalette.ColorRole.HighlightedText).name(), "#14213d")
        self.assertFalse(window.profile_edit.isEnabled())
        self.assertTrue(window.capture_browser_combo.isEnabled())
        self.assertEqual(window.web_download_button.text(), "웹 재생으로 다운로드")
        self.assertFalse(window.confirm_content_button.isVisible())

        window.auth_browser_combo.setCurrentIndex(window.auth_browser_combo.findData("chrome"))
        window.profile_edit.setText("Profile 2")
        window.quality_combo.setCurrentIndex(window.quality_combo.findData("1080p"))
        window.capture_checkbox.setChecked(True)
        settings = window.current_settings()

        self.assertEqual(settings.auth.browser, "chrome")
        self.assertEqual(settings.auth.profile, "Profile 2")
        self.assertEqual(settings.download.video_quality, "1080p")
        self.assertTrue(settings.browser_capture.enabled)

        window.mode_combo.setCurrentIndex(window.mode_combo.findData("audio"))
        self.assertFalse(window.quality_combo.isEnabled())

    def test_youtube_web_playback_is_rejected_without_starting_worker(self) -> None:
        window = MainWindow(Settings())
        self.addCleanup(window.close)
        window.url_edit.setText("https://www.youtube.com/watch?v=test")

        with patch.object(window, "_show_error") as show_error:
            window.start_web_download()

        show_error.assert_called_once_with("YouTube는 일반 다운로드를 사용하세요.")
        self.assertIsNone(window.worker)
        self.assertFalse(window.confirm_content_button.isVisible())

    def test_download_result_displays_actual_media_details(self) -> None:
        window = MainWindow(Settings())
        self.addCleanup(window.close)
        result = DownloadResult(
            success=True,
            output_path=Path("video.mp4"),
            media_info=MediaInfo(
                width=3840,
                height=2160,
                fps=59.94,
                video_codec="av1",
                audio_codec="opus",
                container="mp4",
            ),
        )

        window._download_finished(result)

        output = window.info_output.toPlainText()
        self.assertIn("3840×2160", output)
        self.assertIn("AV1", output)
        self.assertIn("Opus", output)

    def test_media_summary_uses_friendly_codec_names(self) -> None:
        summary = format_media_summary(
            MediaInfo(width=1920, height=1080, fps=30.0, video_codec="h264", audio_codec="aac")
        )

        self.assertEqual(summary, "1920×1080 · 30 fps · H.264 (AVC) · AAC")

    def test_display_url_removes_credentials_query_and_fragment(self) -> None:
        label = format_url_for_display(
            "https://user:password@example.com/video?id=secret&token=private#fragment"
        )

        self.assertEqual(label, "example.com/video")
        self.assertNotIn("secret", label)
        self.assertNotIn("password", label)

    def test_batch_progress_keeps_position_and_tracks_item_results(self) -> None:
        window = MainWindow(Settings())
        self.addCleanup(window.close)
        window.worker = BatchThread(
            Settings(),
            ("https://example.com/one", "https://example.com/two?token=secret"),
            "video",
        )
        window._reset_batch_progress(2)
        window._batch_item_started(1, 2, "https://example.com/one?token=secret")

        window._update_progress({"percent": "40%", "speed": "1MiB/s", "eta": "00:10"})

        self.assertIn("현재 1/2", window.progress_label.text())
        self.assertEqual(window.batch_progress_bar.value(), 20)
        self.assertNotIn("secret", window.batch_log.toPlainText())

        window._batch_item_finished(
            BatchItemEvent(
                index=1,
                total=2,
                url="https://example.com/one?token=secret",
                status=BatchItemStatus.SUCCEEDED,
                result=DownloadResult(success=True, output_path=Path("one.mp4")),
            )
        )
        window._batch_item_finished(
            BatchItemEvent(
                index=2,
                total=2,
                url="https://example.com/two?token=secret",
                status=BatchItemStatus.FAILED,
                result=DownloadResult(
                    success=False,
                    error_kind=ErrorKind.HTTP_FORBIDDEN,
                    message="request failed for https://example.com/two?token=secret",
                ),
            )
        )
        window._batch_finished(BatchSummary(total=2, succeeded=1, failed=1))

        self.assertEqual(window.batch_progress_bar.value(), 100)
        self.assertIn("전체 2/2", window.batch_progress_label.text())
        self.assertIn("실패 1", window.batch_log.toPlainText())
        self.assertNotIn("secret", window.batch_log.toPlainText())

    def test_file_batch_table_tracks_progress_and_failed_retry_urls(self) -> None:
        window = MainWindow(Settings())
        self.addCleanup(window.close)
        urls = (
            "https://example.com/report.pdf?token=secret",
            "https://example.com/archive.zip",
        )
        window._prepare_file_table(urls)
        window._reset_batch_progress(2)

        window._file_item_started(1, 2, urls[0])
        window._file_progress_changed(
            {
                "index": 1,
                "filename": "report.pdf",
                "percent": 50.0,
                "downloaded_bytes": 512,
                "speed": "1.0 MiB/s",
            }
        )

        self.assertEqual(window.file_table.item(0, 1).text(), "report.pdf")
        self.assertEqual(window.file_table.item(0, 3).text(), "50%")
        self.assertEqual(window.batch_progress_bar.value(), 25)

        window._file_item_finished(
            BatchItemEvent(
                1,
                2,
                urls[0],
                BatchItemStatus.FAILED,
                DownloadResult(
                    False,
                    error_kind=ErrorKind.HTTP_FORBIDDEN,
                    message=f"expired: {urls[0]}",
                ),
            )
        )

        self.assertEqual(window.file_table.item(0, 2).text(), "실패")
        self.assertNotIn("secret", window.file_table.item(0, 2).toolTip())
        self.assertEqual(window._file_failed_urls, [urls[0]])

        window._file_progress_changed(
            {
                "index": 2,
                "phase": "waiting",
                "idle_seconds": 4,
                "attempt": 1,
                "max_attempts": 3,
            }
        )
        self.assertEqual(window.file_table.item(1, 2).text(), "응답 대기 4초")
        window._file_progress_changed(
            {
                "index": 2,
                "phase": "retrying",
                "retry_in_seconds": 1.5,
                "attempt": 2,
                "max_attempts": 3,
            }
        )
        self.assertEqual(window.file_table.item(1, 2).text(), "재시도 대기 (2/3) · 1.5초 후")
        window._file_item_finished(
            BatchItemEvent(
                2,
                2,
                urls[1],
                BatchItemStatus.SUCCEEDED,
                DownloadResult(True, output_path=Path("archive.zip")),
            )
        )

        window.clear_completed_file_items()

        self.assertEqual(window.file_table.rowCount(), 1)
        self.assertEqual(window.file_table.item(0, 2).text(), "실패")
        self.assertEqual(window._file_rows, {1: 0})

        window.reset_file_batch_state()

        self.assertEqual(window.file_urls.toPlainText(), "")
        self.assertEqual(window.file_table.rowCount(), 0)
        self.assertEqual(window.progress_bar.value(), 0)
        self.assertFalse(window.batch_progress_bar.isVisible())
        self.assertFalse(window.file_retry_button.isEnabled())

    @patch("videodownloader.gui_workers.build_download_engine")
    def test_download_thread_emits_progress_and_result(self, build_engine: object) -> None:
        engine = FakeEngine(DownloadResult(success=True, output_path=Path("video.mp4")))
        build_engine.return_value = engine  # type: ignore[attr-defined]
        worker = DownloadThread(Settings(), "https://example.com/video", "video")
        progress: list[dict[str, object]] = []
        results: list[DownloadResult] = []
        worker.progress_changed.connect(progress.append)
        worker.result_ready.connect(results.append)

        worker.run()

        self.assertEqual(progress[0]["percent"], "50.0%")
        self.assertTrue(results[0].success)
        self.assertEqual(engine.jobs[0].mode, "video")

    @patch("videodownloader.gui_workers.build_web_playback_engine")
    def test_web_playback_thread_uses_dedicated_engine(self, build_engine: object) -> None:
        engine = FakeEngine(DownloadResult(success=True, output_path=Path("video.mp4")))
        build_engine.return_value = engine  # type: ignore[attr-defined]
        worker = WebPlaybackDownloadThread(
            Settings(),
            "https://example.com/watch",
            "video",
        )
        results: list[DownloadResult] = []
        worker.result_ready.connect(results.append)

        worker.confirm_main_content()
        worker.run()

        self.assertTrue(results[0].success)
        self.assertEqual(engine.jobs[0].url, "https://example.com/watch")
        call = build_engine.call_args  # type: ignore[attr-defined]
        self.assertTrue(call.kwargs["confirmation_event"].is_set())


if __name__ == "__main__":
    unittest.main()
