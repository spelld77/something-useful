from __future__ import annotations

import unittest
from pathlib import Path

from videodownloader.storage.naming import build_output_template


class NamingTests(unittest.TestCase):
    def test_template_limits_title_and_includes_video_id(self) -> None:
        template = build_output_template(Path("downloads"))

        self.assertIn("%(title).180B", template)
        self.assertIn("[%(id)s]", template)
        self.assertTrue(template.endswith(".%(ext)s"))


if __name__ == "__main__":
    unittest.main()
