from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from videodownloader.engine.browser_capture import (
    BrowserCapture,
    BrowserCaptureError,
    CapturedCookie,
    CaptureResult,
    MediaCandidate,
    contains_drm,
    cookies_for_url,
    is_capture_blocked_url,
    media_candidate,
    parse_performance_entry,
    scoped_cookie_file,
    select_candidate,
    select_confirmed_candidate,
)
from videodownloader.engine.fallback import BrowserFallbackEngine
from videodownloader.engine.web_playback import BrowserCaptureDownloadEngine
from videodownloader.models import DownloadResult, ErrorKind, Job

RUNTIME_DIR = Path(__file__).parent / "runtime"


def performance_response(request_id: str, url: str) -> dict[str, str]:
    return {
        "message": json.dumps(
            {
                "message": {
                    "method": "Network.responseReceived",
                    "params": {
                        "requestId": request_id,
                        "response": {
                            "url": url,
                            "mimeType": "application/vnd.apple.mpegurl",
                            "status": 200,
                        },
                    },
                }
            }
        )
    }


class FakeDriver:
    title = "Playback page"

    def __init__(self, entries: list[dict[str, str]]) -> None:
        self.entries = entries
        self.quit_called = False

    def set_page_load_timeout(self, timeout: int) -> None:
        self.timeout = timeout

    def execute_cdp_cmd(self, method: str, payload: dict[str, object]) -> object:
        return {}

    def get(self, url: str) -> None:
        self.url = url

    def get_log(self, name: str) -> list[dict[str, str]]:
        entries, self.entries = self.entries, []
        return entries

    def get_cookies(self) -> list[dict[str, object]]:
        return []

    def execute_script(self, script: str) -> str:
        return "Test Browser"

    def quit(self) -> None:
        self.quit_called = True


class BrowserCaptureParserTests(unittest.TestCase):
    def test_performance_entry_is_parsed(self) -> None:
        entry = {
            "message": json.dumps(
                {
                    "message": {
                        "method": "Network.responseReceived",
                        "params": {"requestId": "1"},
                    }
                }
            )
        }

        self.assertEqual(
            parse_performance_entry(entry),
            ("Network.responseReceived", {"requestId": "1"}),
        )

    def test_hls_candidate_and_master_are_preferred_over_ads(self) -> None:
        candidates = [
            MediaCandidate("https://ads.example.com/preroll/ad.m3u8"),
            MediaCandidate("https://cdn.example.com/720p.m3u8"),
            MediaCandidate("https://cdn.example.com/master.m3u8", is_master=True),
        ]

        selected = select_candidate(candidates)

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.url, "https://cdn.example.com/master.m3u8")

    def test_confirmed_candidate_prefers_recent_main_content(self) -> None:
        candidates = [
            MediaCandidate(
                "https://cdn.example.com/old.m3u8",
                is_master=True,
                last_seen_at=40.0,
            ),
            MediaCandidate(
                "https://ads.example.com/preroll/ad.m3u8",
                last_seen_at=99.0,
            ),
            MediaCandidate(
                "https://cdn.example.com/content/master.m3u8",
                is_master=True,
                last_seen_at=100.0,
            ),
            MediaCandidate(
                "https://cdn.example.com/content/1080p.m3u8",
                last_seen_at=101.0,
            ),
        ]

        selected = select_confirmed_candidate(candidates, confirmed_at=101.0)

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.url, "https://cdn.example.com/content/master.m3u8")

    def test_confirmed_candidate_never_returns_ad_only_candidate(self) -> None:
        selected = select_confirmed_candidate(
            [MediaCandidate("https://ads.example.com/preroll/ad.m3u8", last_seen_at=10.0)],
            confirmed_at=11.0,
        )

        self.assertIsNone(selected)

    def test_capture_policy_blocks_all_youtube_domains(self) -> None:
        self.assertTrue(is_capture_blocked_url("https://music.youtube.com/watch?v=test"))
        self.assertTrue(is_capture_blocked_url("https://youtu.be/test"))
        self.assertTrue(is_capture_blocked_url("https://www.youtube-nocookie.com/embed/test"))
        self.assertFalse(is_capture_blocked_url("https://example.com/youtube.com/video"))

    def test_media_candidate_uses_url_or_mime_and_rejects_errors(self) -> None:
        self.assertIsNotNone(media_candidate("https://cdn.example.com/master.m3u8", "", 200))
        self.assertIsNotNone(
            media_candidate("https://cdn.example.com/manifest", "application/dash+xml", 200)
        )
        self.assertIsNone(media_candidate("https://cdn.example.com/master.m3u8", "", 403))

    def test_manifest_drm_markers_are_detected(self) -> None:
        self.assertTrue(contains_drm('<ContentProtection schemeIdUri="urn:uuid:test"/>'))
        self.assertTrue(contains_drm("#EXT-X-KEY:METHOD=SAMPLE-AES"))
        self.assertFalse(contains_drm("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000"))


class InteractiveBrowserCaptureTests(unittest.TestCase):
    @staticmethod
    def _create_test_profile(*, prefix: str, dir: str | Path) -> str:
        profile = Path(dir) / f"{prefix}test"
        profile.mkdir()
        return str(profile)

    def test_user_confirmation_selects_main_content_and_cleans_profile(self) -> None:
        driver = FakeDriver(
            [
                performance_response("ad", "https://ads.example.com/preroll/ad.m3u8"),
                performance_response(
                    "main",
                    "https://cdn.example.com/content/master.m3u8",
                ),
            ]
        )
        confirmation_event = threading.Event()
        ready_calls: list[bool] = []
        profile_root = RUNTIME_DIR / "interactive-success-profiles-v2"
        capture = BrowserCapture(
            grace_seconds=0,
            interactive_timeout_seconds=1,
            profile_root=profile_root,
        )
        capture._create_driver = lambda profile: driver  # type: ignore[method-assign]

        def ready() -> None:
            ready_calls.append(True)
            confirmation_event.set()

        with patch(
            "videodownloader.engine.browser_capture.tempfile.mkdtemp",
            side_effect=self._create_test_profile,
        ):
            result = capture.capture(
                "https://example.com/watch",
                confirmation_event=confirmation_event,
                ready_callback=ready,
            )

        self.assertEqual(
            result.media_url,
            "https://cdn.example.com/content/master.m3u8",
        )
        self.assertEqual(ready_calls, [True])
        self.assertTrue(driver.quit_called)
        self.assertFalse(profile_root.exists())

    def test_interactive_capture_times_out_without_user_confirmation(self) -> None:
        driver = FakeDriver([])
        profile_root = RUNTIME_DIR / "interactive-timeout-profiles-v2"
        capture = BrowserCapture(
            interactive_timeout_seconds=0,
            profile_root=profile_root,
        )
        capture._create_driver = lambda profile: driver  # type: ignore[method-assign]

        with (
            patch(
                "videodownloader.engine.browser_capture.tempfile.mkdtemp",
                side_effect=self._create_test_profile,
            ),
            self.assertRaisesRegex(BrowserCaptureError, "시간이 초과"),
        ):
            capture.capture(
                "https://example.com/watch",
                confirmation_event=threading.Event(),
            )
        self.assertFalse(profile_root.exists())


class CookieScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cookies = (
            CapturedCookie("session", "allowed", ".example.com", secure=True),
            CapturedCookie("other", "blocked", ".other.com"),
        )

    def test_only_target_domain_cookies_are_selected(self) -> None:
        selected = cookies_for_url(self.cookies, "https://cdn.example.com/video/master.m3u8")

        self.assertEqual([cookie.name for cookie in selected], ["session"])

    def test_cookie_file_is_deleted_and_excludes_other_domains(self) -> None:
        captured_path: Path | None = None
        with scoped_cookie_file(
            self.cookies,
            "https://cdn.example.com/video/master.m3u8",
            RUNTIME_DIR,
        ) as path:
            captured_path = path
            self.assertIsNotNone(path)
            assert path is not None
            content = path.read_text(encoding="utf-8")
            self.assertIn("allowed", content)
            self.assertNotIn("blocked", content)

        assert captured_path is not None
        self.assertFalse(captured_path.exists())


class FakePrimaryEngine:
    def __init__(self, results: list[DownloadResult]) -> None:
        self.results = list(results)
        self.jobs: list[Job] = []
        self.cookie_snapshot = ""

    def probe(self, job: Job) -> object:
        raise NotImplementedError

    def download(self, job: Job, *, on_progress: object = None) -> DownloadResult:
        self.jobs.append(job)
        if job.cookie_file is not None:
            self.cookie_snapshot = job.cookie_file.read_text(encoding="utf-8")
        return self.results.pop(0)


class FakeCapture:
    def __init__(
        self, result: CaptureResult | None = None, error: BrowserCaptureError | None = None
    ):
        self.result = result
        self.error = error
        self.calls = 0
        self.confirmation_event: threading.Event | None = None

    def capture(
        self,
        source_url: str,
        *,
        confirmation_event: threading.Event | None = None,
        ready_callback: object = None,
    ) -> CaptureResult:
        self.calls += 1
        self.confirmation_event = confirmation_event
        if callable(ready_callback):
            ready_callback()
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class BrowserFallbackTests(unittest.TestCase):
    def test_generic_site_falls_back_with_scoped_headers_and_cookies(self) -> None:
        primary = FakePrimaryEngine(
            [
                DownloadResult(success=False, error_kind=ErrorKind.UNSUPPORTED_URL),
                DownloadResult(success=True, output_path=Path("video.mp4")),
            ]
        )
        capture_result = CaptureResult(
            source_url="https://www.example.com/watch/1",
            media_url="https://cdn.example.com/master.m3u8?token=signed",
            page_title="Example",
            user_agent="Test Browser",
            cookies=(
                CapturedCookie("session", "allowed", ".example.com"),
                CapturedCookie("foreign", "blocked", ".other.com"),
            ),
        )
        capture = FakeCapture(capture_result)
        engine = BrowserFallbackEngine(
            primary,  # type: ignore[arg-type]
            capture,  # type: ignore[arg-type]
            runtime_dir=RUNTIME_DIR,
        )

        result = engine.download(Job("https://www.example.com/watch/1"))

        self.assertTrue(result.success)
        self.assertEqual(capture.calls, 1)
        self.assertEqual(primary.jobs[1].url, capture_result.media_url)
        self.assertIn(("User-Agent", "Test Browser"), primary.jobs[1].http_headers)
        self.assertIn("allowed", primary.cookie_snapshot)
        self.assertNotIn("blocked", primary.cookie_snapshot)
        self.assertFalse(any(RUNTIME_DIR.glob(".browser-cookies-*.txt")))

    def test_youtube_never_uses_browser_network_capture(self) -> None:
        primary = FakePrimaryEngine(
            [DownloadResult(success=False, error_kind=ErrorKind.HTTP_FORBIDDEN)]
        )
        capture = FakeCapture()
        engine = BrowserFallbackEngine(
            primary,  # type: ignore[arg-type]
            capture,  # type: ignore[arg-type]
            runtime_dir=RUNTIME_DIR,
        )

        result = engine.download(Job("https://www.youtube.com/watch?v=test"))

        self.assertFalse(result.success)
        self.assertEqual(capture.calls, 0)

    def test_generic_auth_required_can_use_explicit_browser_capture(self) -> None:
        primary = FakePrimaryEngine(
            [
                DownloadResult(success=False, error_kind=ErrorKind.AUTH_REQUIRED),
                DownloadResult(success=True, output_path=Path("video.mp4")),
            ]
        )
        capture_result = CaptureResult(
            source_url="https://example.com/private",
            media_url="https://cdn.example.com/private/master.m3u8?token=signed",
            page_title="Private video",
            user_agent="Test Browser",
            cookies=(),
        )
        capture = FakeCapture(capture_result)
        engine = BrowserFallbackEngine(
            primary,  # type: ignore[arg-type]
            capture,  # type: ignore[arg-type]
            runtime_dir=RUNTIME_DIR,
        )

        result = engine.download(Job("https://example.com/private"))

        self.assertTrue(result.success)
        self.assertEqual(capture.calls, 1)

    def test_drm_capture_error_is_returned_without_retry(self) -> None:
        primary = FakePrimaryEngine(
            [DownloadResult(success=False, error_kind=ErrorKind.UNSUPPORTED_URL)]
        )
        capture = FakeCapture(error=BrowserCaptureError(ErrorKind.DRM_PROTECTED, "DRM detected"))
        engine = BrowserFallbackEngine(
            primary,  # type: ignore[arg-type]
            capture,  # type: ignore[arg-type]
            runtime_dir=RUNTIME_DIR,
        )

        result = engine.download(Job("https://example.com/watch"))

        self.assertEqual(result.error_kind, ErrorKind.DRM_PROTECTED)
        self.assertEqual(len(primary.jobs), 1)


class BrowserCaptureDownloadEngineTests(unittest.TestCase):
    def test_explicit_capture_runs_before_single_primary_download(self) -> None:
        primary = FakePrimaryEngine([DownloadResult(success=True, output_path=Path("video.mp4"))])
        capture_result = CaptureResult(
            source_url="https://example.com/watch",
            media_url="https://cdn.example.com/content/master.m3u8",
            page_title="Example",
            user_agent="Test Browser",
            cookies=(),
        )
        capture = FakeCapture(capture_result)
        confirmation_event = threading.Event()
        ready_calls: list[bool] = []
        engine = BrowserCaptureDownloadEngine(
            primary,  # type: ignore[arg-type]
            capture,  # type: ignore[arg-type]
            confirmation_event=confirmation_event,
            ready_callback=lambda: ready_calls.append(True),
            runtime_dir=RUNTIME_DIR,
        )

        result = engine.download(Job("https://example.com/watch"))

        self.assertTrue(result.success)
        self.assertEqual(capture.calls, 1)
        self.assertIs(capture.confirmation_event, confirmation_event)
        self.assertEqual(ready_calls, [True])
        self.assertEqual(len(primary.jobs), 1)
        self.assertEqual(primary.jobs[0].url, capture_result.media_url)

    def test_explicit_capture_rejects_youtube_before_browser_start(self) -> None:
        primary = FakePrimaryEngine([])
        capture = FakeCapture()
        engine = BrowserCaptureDownloadEngine(
            primary,  # type: ignore[arg-type]
            capture,  # type: ignore[arg-type]
            confirmation_event=threading.Event(),
            ready_callback=None,
            runtime_dir=RUNTIME_DIR,
        )

        result = engine.download(Job("https://www.youtube.com/watch?v=test"))

        self.assertFalse(result.success)
        self.assertEqual(result.error_kind, ErrorKind.UNSUPPORTED_URL)
        self.assertEqual(capture.calls, 0)


if __name__ == "__main__":
    unittest.main()
