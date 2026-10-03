from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from videodownloader.config import Settings
from videodownloader.preflight import PreflightReport, ToolCheck
from videodownloader.service.self_check import format_self_check, run_self_check


def preflight(*, required: bool = True, youtube: bool = True) -> PreflightReport:
    return PreflightReport(
        tools=(
            ToolCheck("yt-dlp", found=required, required=True),
            ToolCheck("ffmpeg", found=required, required=True),
            ToolCheck("js:node", found=youtube, required=False),
            ToolCheck("yt-dlp-ejs", found=youtube, required=False),
        ),
        save_dir=Path("savedVideo"),
        save_dir_ready=required,
    )


class SelfCheckTests(unittest.TestCase):
    @patch("videodownloader.service.self_check.run_preflight", return_value=preflight())
    def test_all_internal_checks_pass(self, _run_preflight: object) -> None:
        report = run_self_check(Settings())

        self.assertTrue(report.passed)
        self.assertEqual(len(report.items), 7)
        self.assertIn("릴리스 점검 통과", format_self_check(report))

    @patch(
        "videodownloader.service.self_check.run_preflight",
        return_value=preflight(youtube=False),
    )
    def test_missing_youtube_runtime_fails_release_check(self, _run_preflight: object) -> None:
        report = run_self_check(Settings())

        self.assertFalse(report.passed)
        self.assertIn("실패 항목", format_self_check(report))


if __name__ == "__main__":
    unittest.main()
