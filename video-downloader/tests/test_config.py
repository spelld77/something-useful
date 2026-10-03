from __future__ import annotations

import unittest
from pathlib import Path

from videodownloader.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def test_missing_config_uses_defaults(self) -> None:
        settings = load_config(Path(__file__).parent / "fixtures" / "missing.toml")

        self.assertEqual(settings.download.mode, "video")
        self.assertEqual(settings.download.video_quality, "best")
        self.assertEqual(settings.download.concurrency, 1)
        self.assertEqual(settings.app.save_dir, Path("savedVideo"))
        self.assertEqual(settings.browser_capture.interactive_timeout_seconds, 180)
        self.assertEqual(settings.file_download.save_dir, Path("savedFiles"))
        self.assertEqual(settings.file_download.concurrency, 1)

    def test_invalid_mode_is_rejected(self) -> None:
        path = Path(__file__).parent / "fixtures" / "invalid_mode.toml"
        with self.assertRaisesRegex(ConfigError, "video 또는 audio"):
            load_config(path)

    def test_unknown_key_is_rejected(self) -> None:
        path = Path(__file__).parent / "fixtures" / "unknown_key.toml"
        with self.assertRaisesRegex(ConfigError, "알 수 없는 항목"):
            load_config(path)

    def test_invalid_video_quality_is_rejected(self) -> None:
        path = Path(__file__).parent / "fixtures" / "invalid_video_quality.toml"
        with self.assertRaisesRegex(ConfigError, "download.video_quality"):
            load_config(path)

    def test_profile_requires_browser(self) -> None:
        path = Path(__file__).parent / "fixtures" / "profile_without_browser.toml"
        with self.assertRaisesRegex(ConfigError, "auth.browser를 선택"):
            load_config(path)

    def test_invalid_js_runtime_is_rejected(self) -> None:
        path = Path(__file__).parent / "fixtures" / "invalid_js_runtime.toml"
        with self.assertRaisesRegex(ConfigError, "youtube.js_runtime"):
            load_config(path)

    def test_negative_batch_delay_is_rejected(self) -> None:
        path = Path(__file__).parent / "fixtures" / "invalid_batch_delay.toml"
        with self.assertRaisesRegex(ConfigError, "batch.delay_seconds"):
            load_config(path)

    def test_invalid_capture_browser_is_rejected(self) -> None:
        path = Path(__file__).parent / "fixtures" / "invalid_capture_browser.toml"
        with self.assertRaisesRegex(ConfigError, "browser_capture.browser"):
            load_config(path)

    def test_invalid_socket_timeout_is_rejected(self) -> None:
        path = Path(__file__).parent / "fixtures" / "invalid_socket_timeout.toml"
        with self.assertRaisesRegex(ConfigError, "download.socket_timeout_seconds"):
            load_config(path)

    def test_negative_retry_sleep_is_rejected(self) -> None:
        path = Path(__file__).parent / "fixtures" / "invalid_retry_sleep.toml"
        with self.assertRaisesRegex(ConfigError, "download.retry_sleep_seconds"):
            load_config(path)

    def test_file_download_concurrency_is_limited(self) -> None:
        path = Path(__file__).parent / "fixtures" / "invalid_file_concurrency.toml"
        with self.assertRaisesRegex(ConfigError, "file_download.concurrency"):
            load_config(path)


if __name__ == "__main__":
    unittest.main()
