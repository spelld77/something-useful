from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from videodownloader.engine.process import hidden_subprocess_kwargs


class FakeStartupInfo:
    def __init__(self) -> None:
        self.dwFlags = 0
        self.wShowWindow = -1


class HiddenSubprocessTests(unittest.TestCase):
    def test_non_windows_does_not_add_platform_specific_options(self) -> None:
        with patch("videodownloader.engine.process.sys.platform", "linux"):
            self.assertEqual(hidden_subprocess_kwargs(), {})

    def test_windows_hides_console_children(self) -> None:
        startup_info = FakeStartupInfo()
        with (
            patch("videodownloader.engine.process.sys.platform", "win32"),
            patch.object(subprocess, "STARTUPINFO", return_value=startup_info, create=True),
            patch.object(subprocess, "STARTF_USESHOWWINDOW", 1, create=True),
            patch.object(subprocess, "SW_HIDE", 0, create=True),
            patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True),
        ):
            options = hidden_subprocess_kwargs()

        self.assertEqual(options["creationflags"], 0x08000000)
        self.assertIs(options["startupinfo"], startup_info)
        self.assertEqual(startup_info.dwFlags & 1, 1)
        self.assertEqual(startup_info.wShowWindow, 0)


if __name__ == "__main__":
    unittest.main()
