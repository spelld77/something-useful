from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from videodownloader.engine.runtime import inspect_js_runtime, select_js_runtime


class RuntimeTests(unittest.TestCase):
    def tearDown(self) -> None:
        inspect_js_runtime.cache_clear()
        select_js_runtime.cache_clear()

    @patch("videodownloader.engine.runtime.subprocess.run")
    @patch("videodownloader.engine.runtime.shutil.which")
    def test_supported_node_is_selected(self, which: object, run: object) -> None:
        which.return_value = "C:/Program Files/nodejs/node.exe"  # type: ignore[attr-defined]
        run.return_value = subprocess.CompletedProcess([], 0, stdout="v24.12.0\n", stderr="")  # type: ignore[attr-defined]

        runtime = select_js_runtime("node")

        self.assertIsNotNone(runtime)
        assert runtime is not None
        self.assertEqual(runtime.name, "node")
        self.assertTrue(runtime.supported)

    @patch("videodownloader.engine.runtime.subprocess.run")
    @patch("videodownloader.engine.runtime.shutil.which")
    def test_old_node_is_rejected(self, which: object, run: object) -> None:
        which.return_value = "node.exe"  # type: ignore[attr-defined]
        run.return_value = subprocess.CompletedProcess([], 0, stdout="v20.0.0\n", stderr="")  # type: ignore[attr-defined]

        self.assertIsNone(select_js_runtime("node"))


if __name__ == "__main__":
    unittest.main()
