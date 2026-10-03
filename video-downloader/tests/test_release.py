from __future__ import annotations

import runpy
import unittest
from pathlib import Path

from videodownloader import __version__
from videodownloader.app import build_parser


class ReleaseTests(unittest.TestCase):
    def test_version_flag_reports_package_version(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            build_parser().parse_args(["--version"])

        self.assertEqual(raised.exception.code, 0)

    def test_release_builder_uses_package_version_and_required_files_exist(self) -> None:
        root = Path(__file__).resolve().parents[1]
        namespace = runpy.run_path(
            str(root / "scripts" / "build_release.py"), run_name="release_test"
        )

        self.assertEqual(namespace["package_version"](), __version__)
        self.assertTrue((root / "scripts" / "install_release.ps1").is_file())
        self.assertTrue((root / "docs" / "acceptance.md").is_file())

        installer = (root / "scripts" / "install_release.ps1").read_text(encoding="utf-8")
        self.assertIn("Assert-ExternalCommand", installer)
        self.assertIn("$env:TMPDIR", installer)

    def test_gui_release_builder_uses_package_version(self) -> None:
        root = Path(__file__).resolve().parents[1]
        namespace = runpy.run_path(
            str(root / "scripts" / "build_gui_release.py"), run_name="gui_release_test"
        )

        self.assertEqual(namespace["package_version"](), __version__)
        self.assertTrue((root / "scripts" / "gui_launcher.py").is_file())
        builder = (root / "scripts" / "build_gui_release.py").read_text(encoding="utf-8")
        self.assertIn('("icuuc.dll", "icudt*.dll")', builder)
