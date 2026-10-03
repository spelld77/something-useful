from __future__ import annotations

import unittest
from pathlib import Path

from videodownloader.preflight import PreflightReport, ToolCheck, format_report


class PreflightTests(unittest.TestCase):
    def test_missing_optional_tool_does_not_fail_report(self) -> None:
        report = PreflightReport(
            tools=(
                ToolCheck("yt-dlp", found=True, required=True),
                ToolCheck("deno", found=False, required=False),
            ),
            save_dir=Path("savedVideo"),
            save_dir_ready=True,
        )

        self.assertTrue(report.required_ok)
        self.assertIn("선택 누락", format_report(report))

    def test_missing_required_tool_fails_report(self) -> None:
        report = PreflightReport(
            tools=(ToolCheck("ffmpeg", found=False, required=True),),
            save_dir=Path("savedVideo"),
            save_dir_ready=True,
        )

        self.assertFalse(report.required_ok)

    def test_youtube_ready_requires_runtime_and_ejs(self) -> None:
        report = PreflightReport(
            tools=(
                ToolCheck("js:node", found=True, required=False),
                ToolCheck("yt-dlp-ejs", found=True, required=False),
            ),
            save_dir=Path("savedVideo"),
            save_dir_ready=True,
        )

        self.assertTrue(report.youtube_ready)


if __name__ == "__main__":
    unittest.main()
