from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from videodownloader.app import build_parser, main
from videodownloader.config import AppConfig, Settings
from videodownloader.models import DownloadResult, ErrorKind, Job
from videodownloader.preflight import PreflightReport, ToolCheck


class FakeEngine:
    def __init__(self, result: DownloadResult) -> None:
        self.result = result
        self.jobs: list[Job] = []

    def probe(self, job: Job) -> object:
        raise NotImplementedError

    def download(self, job: Job, *, on_progress: object = None) -> DownloadResult:
        self.jobs.append(job)
        return self.result


def report(*, ready: bool) -> PreflightReport:
    return PreflightReport(
        tools=(ToolCheck("yt-dlp", found=ready, required=True, version="test"),),
        save_dir=Path("savedVideo"),
        save_dir_ready=ready,
    )


class CliTests(unittest.TestCase):
    def test_parser_exposes_release_commands_and_capture_switch(self) -> None:
        args = build_parser().parse_args(
            [
                "download",
                "--video",
                "--quality",
                "1080p",
                "--browser-capture",
                "https://example.com/video",
            ]
        )

        self.assertEqual(args.command, "download")
        self.assertEqual(args.mode, "video")
        self.assertEqual(args.quality, "1080p")
        self.assertTrue(args.browser_capture)

        self.assertEqual(build_parser().parse_args(["self-check"]).command, "self-check")

    @patch("videodownloader.app.run_preflight", return_value=report(ready=True))
    @patch("videodownloader.app.load_config")
    @patch("videodownloader.app._build_download_engine")
    def test_download_success_returns_zero(
        self,
        build_engine: object,
        load_settings: object,
        _run_preflight: object,
    ) -> None:
        settings = Settings(app=AppConfig(save_dir=Path("savedVideo")))
        engine = FakeEngine(DownloadResult(success=True, output_path=Path("video.mp4")))
        load_settings.return_value = settings  # type: ignore[attr-defined]
        build_engine.return_value = engine  # type: ignore[attr-defined]

        exit_code = main(["download", "--video", "https://example.com/video"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(engine.jobs[0].mode, "video")

    @patch("videodownloader.app.run_preflight", return_value=report(ready=True))
    @patch("videodownloader.app.load_config")
    @patch("videodownloader.app._build_download_engine")
    def test_download_failure_returns_one(
        self,
        build_engine: object,
        load_settings: object,
        _run_preflight: object,
    ) -> None:
        load_settings.return_value = Settings()  # type: ignore[attr-defined]
        build_engine.return_value = FakeEngine(  # type: ignore[attr-defined]
            DownloadResult(
                success=False,
                error_kind=ErrorKind.NETWORK_TRANSIENT,
                message="네트워크 오류",
            )
        )

        exit_code = main(["download", "https://example.com/video"])

        self.assertEqual(exit_code, 1)

    @patch("videodownloader.app.run_preflight", return_value=report(ready=False))
    @patch("videodownloader.app.load_config", return_value=Settings())
    def test_doctor_returns_one_when_required_tool_is_missing(
        self,
        _load_settings: object,
        _run_preflight: object,
    ) -> None:
        self.assertEqual(main(["doctor"]), 1)


if __name__ == "__main__":
    unittest.main()
