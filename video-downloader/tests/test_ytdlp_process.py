from __future__ import annotations

import json
import unittest
from pathlib import Path

from videodownloader.config import AppConfig, AuthConfig, DownloadConfig, Settings
from videodownloader.engine.process import CommandResult
from videodownloader.engine.ytdlp_process import (
    DownloadError,
    YtDlpProcessEngine,
    classify_error,
    parse_ffprobe_media_info,
    parse_output_path,
    parse_progress_line,
    redact_sensitive,
    validate_url,
    video_format_selector,
)
from videodownloader.models import ErrorKind, Job


class FakeRunner:
    def __init__(
        self,
        *,
        run_result: CommandResult | None = None,
        stream_result: CommandResult | None = None,
        stream_results: list[CommandResult] | None = None,
    ) -> None:
        self.run_result = run_result or CommandResult(0)
        self.stream_result = stream_result or CommandResult(0)
        self.stream_results = stream_results or []
        self.run_args: list[str] = []
        self.stream_args: list[str] = []
        self.stream_calls = 0
        self.cancelled = False

    def run(self, args: list[str], *, timeout: float | None = None) -> CommandResult:
        self.run_args = list(args)
        return self.run_result

    def stream(self, args: list[str], *, on_line: object) -> CommandResult:
        self.stream_args = list(args)
        result = (
            self.stream_results[self.stream_calls]
            if self.stream_calls < len(self.stream_results)
            else self.stream_result
        )
        self.stream_calls += 1
        for line in result.stdout.splitlines():
            on_line(line)  # type: ignore[operator]
        return result

    def cancel_current(self) -> None:
        self.cancelled = True


class UrlValidationTests(unittest.TestCase):
    def test_accepts_http_url_and_trims_whitespace(self) -> None:
        self.assertEqual(
            validate_url(" https://example.com/watch?v=1 "), "https://example.com/watch?v=1"
        )

    def test_rejects_non_http_url(self) -> None:
        with self.assertRaises(DownloadError):
            validate_url("file:///c:/secret.txt")

    def test_rejects_embedded_credentials(self) -> None:
        with self.assertRaises(DownloadError):
            validate_url("https://user:password@example.com/video")


class ParserTests(unittest.TestCase):
    def test_progress_marker_is_parsed(self) -> None:
        event = parse_progress_line("VDL_PROGRESS: 51.2%|2.0MiB/s|00:10|1024|2048")

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event["percent"], "51.2%")
        self.assertEqual(event["downloaded_bytes"], 1024)

    def test_output_marker_uses_json_escaped_path(self) -> None:
        raw_path = str(Path("savedVideo") / "테스트 영상.mp4")
        path = parse_output_path(f"VDL_OUTPUT:{json.dumps(raw_path)}")

        self.assertEqual(path, Path(raw_path).resolve())

    def test_ffprobe_output_is_parsed(self) -> None:
        payload = json.dumps(
            {
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "av1",
                        "width": 3840,
                        "height": 2160,
                        "avg_frame_rate": "60000/1001",
                    },
                    {"codec_type": "audio", "codec_name": "opus"},
                ],
                "format": {"format_name": "matroska,webm"},
            }
        )

        media = parse_ffprobe_media_info(payload)

        self.assertIsNotNone(media)
        assert media is not None
        self.assertEqual(media.resolution, "3840×2160")
        self.assertAlmostEqual(media.fps or 0, 59.94, places=2)
        self.assertEqual(media.video_codec, "av1")
        self.assertEqual(media.audio_codec, "opus")

    def test_quality_selectors_apply_caps_and_compatibility(self) -> None:
        self.assertEqual(video_format_selector("best"), "bv*+ba/b")
        self.assertIn("height<=?1080", video_format_selector("1080p"))
        self.assertIn("vcodec^=avc1", video_format_selector("compatible"))

    def test_error_kinds_are_classified(self) -> None:
        cases = {
            "ERROR: HTTP Error 403: Forbidden": ErrorKind.HTTP_FORBIDDEN,
            "This video is DRM protected": ErrorKind.DRM_PROTECTED,
            "ERROR: Unsupported URL": ErrorKind.UNSUPPORTED_URL,
            "Sign in to confirm your age": ErrorKind.AUTH_REQUIRED,
            "Requested format is not available": ErrorKind.FORMAT_UNAVAILABLE,
            "connection reset by peer": ErrorKind.NETWORK_TRANSIENT,
            "Unable to connect to proxy": ErrorKind.NETWORK_TRANSIENT,
            "ERROR: ffmpeg not found": ErrorKind.DEPENDENCY_MISSING,
            "Postprocessing: ffmpeg exited with code 1": ErrorKind.POSTPROCESS_FAILED,
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(classify_error(message), expected)

    def test_sensitive_values_are_redacted(self) -> None:
        source_url = "https://example.com/video?token=secret"
        output = f"URL={source_url} Cookie:SID=private Authorization=BearerSecret"

        redacted = redact_sensitive(output, source_url=source_url)

        self.assertNotIn("secret", redacted)
        self.assertNotIn("private", redacted)
        self.assertNotIn("BearerSecret", redacted)


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            app=AppConfig(save_dir=Path("savedVideo")),
            download=DownloadConfig(retries=3),
        )

    def test_probe_uses_argument_list_and_parses_json(self) -> None:
        payload = {
            "id": "abc123",
            "title": "Test video",
            "webpage_url": "https://example.com/video",
            "uploader": "Uploader",
            "duration": 65,
            "formats": [{"format_id": "1", "ext": "mp4"}],
        }
        runner = FakeRunner(run_result=CommandResult(0, stdout=json.dumps(payload)))
        engine = YtDlpProcessEngine(self.settings, executable="yt-dlp", runner=runner)  # type: ignore[arg-type]

        result = engine.probe(Job("https://example.com/video"))

        self.assertEqual(result.title, "Test video")
        self.assertEqual(result.duration, 65)
        self.assertEqual(runner.run_args[-2:], ["--", "https://example.com/video"])
        self.assertIn("--ignore-config", runner.run_args)
        self.assertIn("--no-update", runner.run_args)
        self.assertIn("--dump-single-json", runner.run_args)

    def test_probe_failure_raises_classified_error_and_redacts_url(self) -> None:
        url = "https://example.com/private?token=secret"
        runner = FakeRunner(run_result=CommandResult(1, stderr=f"ERROR: HTTP Error 403: {url}"))
        engine = YtDlpProcessEngine(self.settings, executable="yt-dlp", runner=runner)  # type: ignore[arg-type]

        with self.assertRaises(DownloadError) as raised:
            engine.probe(Job(url))

        self.assertEqual(raised.exception.kind, ErrorKind.HTTP_FORBIDDEN)
        self.assertNotIn("token=secret", raised.exception.details)

    def test_video_command_selects_best_video_audio_and_mp4(self) -> None:
        engine = YtDlpProcessEngine(self.settings, executable="yt-dlp", runner=FakeRunner())  # type: ignore[arg-type]

        args = engine.build_download_args(Job("https://example.com/video"), Path("savedVideo"))

        self.assertIn(
            "bv*+ba/b",
            args,
        )
        self.assertNotIn("bv[vcodec^=avc1]", args)
        self.assertIn("--merge-output-format", args)
        self.assertIn("--progress", args)
        self.assertIn("--no-overwrites", args)
        self.assertEqual(args[-2:], ["--", "https://example.com/video"])

    def test_video_command_uses_configured_height_limit(self) -> None:
        settings = Settings(
            app=AppConfig(save_dir=Path("savedVideo")),
            download=DownloadConfig(video_quality="1080p"),
        )
        engine = YtDlpProcessEngine(settings, executable="yt-dlp", runner=FakeRunner())  # type: ignore[arg-type]

        args = engine.build_download_args(Job("https://example.com/video"), Path("savedVideo"))

        selector = args[args.index("--format") + 1]
        self.assertEqual(selector, "bv*[height<=?1080]+ba/b[height<=?1080]")

    def test_network_limits_apply_to_probe_and_download(self) -> None:
        settings = Settings(
            app=AppConfig(save_dir=Path("savedVideo")),
            download=DownloadConfig(
                retries=4,
                socket_timeout_seconds=17,
                retry_sleep_seconds=2.5,
            ),
        )
        engine = YtDlpProcessEngine(settings, executable="yt-dlp", runner=FakeRunner())  # type: ignore[arg-type]

        probe_args = engine.build_probe_args("https://example.com/video")
        download_args = engine.build_download_args(
            Job("https://example.com/video"), Path("savedVideo")
        )

        for args in (probe_args, download_args):
            self.assertEqual(args[args.index("--socket-timeout") + 1], "17")
            self.assertEqual(args[args.index("--retries") + 1], "4")
            self.assertEqual(args[args.index("--fragment-retries") + 1], "4")
            self.assertEqual(args[args.index("--retry-sleep") + 1], "2.5")

    def test_audio_command_enables_ffmpeg_extraction(self) -> None:
        engine = YtDlpProcessEngine(self.settings, executable="yt-dlp", runner=FakeRunner())  # type: ignore[arg-type]

        args = engine.build_download_args(
            Job("https://example.com/video", mode="audio"),
            Path("savedVideo"),
        )

        self.assertIn("--extract-audio", args)
        self.assertIn("--audio-format", args)
        self.assertIn("mp3", args)

    def test_selected_browser_and_profile_are_passed_as_one_argument(self) -> None:
        settings = Settings(
            app=AppConfig(save_dir=Path("savedVideo")),
            auth=AuthConfig(browser="chrome", profile="Profile 2"),
        )
        engine = YtDlpProcessEngine(settings, executable="yt-dlp", runner=FakeRunner())  # type: ignore[arg-type]

        args = engine.build_probe_args("https://example.com/video")

        index = args.index("--cookies-from-browser")
        self.assertEqual(args[index + 1], "chrome:Profile 2")

    def test_capture_request_context_uses_allowed_headers_and_cookie_file(self) -> None:
        cookie_path = Path(__file__).parent / "runtime" / "request-cookies.txt"
        cookie_path.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
        self.addCleanup(cookie_path.unlink, missing_ok=True)
        engine = YtDlpProcessEngine(self.settings, executable="yt-dlp", runner=FakeRunner())  # type: ignore[arg-type]
        job = Job(
            "https://cdn.example.com/master.m3u8",
            http_headers=(("Referer", "https://example.com/watch"), ("User-Agent", "Browser")),
            cookie_file=cookie_path,
        )

        args = engine.build_download_args(job, Path("savedVideo"))

        self.assertIn("Referer:https://example.com/watch", args)
        self.assertIn("User-Agent:Browser", args)
        self.assertIn(str(cookie_path.resolve()), args)

    def test_download_returns_final_path_and_progress(self) -> None:
        output_path = (Path.cwd() / "savedVideo" / "video.mp4").resolve()
        stdout = "\n".join(
            (
                "VDL_PROGRESS: 10.0%|1MiB/s|00:09|100|1000",
                f"VDL_OUTPUT:{json.dumps(str(output_path))}",
            )
        )
        runner = FakeRunner(stream_result=CommandResult(0, stdout=stdout))
        engine = YtDlpProcessEngine(self.settings, executable="yt-dlp", runner=runner)  # type: ignore[arg-type]
        events: list[dict[str, object]] = []

        result = engine.download(Job("https://example.com/video"), on_progress=events.append)

        self.assertTrue(result.success)
        self.assertEqual(result.output_path, output_path)
        self.assertEqual(len(events), 1)

    def test_download_reports_actual_media_info_from_ffprobe(self) -> None:
        output_path = (Path(__file__).parent / "runtime" / "media-info.mp4").resolve()
        output_path.write_bytes(b"")
        self.addCleanup(output_path.unlink, missing_ok=True)
        ffprobe_output = json.dumps(
            {
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 1920,
                        "height": 1080,
                        "avg_frame_rate": "30/1",
                    },
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
                "format": {"format_name": "mov,mp4"},
            }
        )
        runner = FakeRunner(
            run_result=CommandResult(0, stdout=ffprobe_output),
            stream_result=CommandResult(
                0,
                stdout=f"VDL_OUTPUT:{json.dumps(str(output_path))}",
            ),
        )
        engine = YtDlpProcessEngine(self.settings, executable="yt-dlp", runner=runner)  # type: ignore[arg-type]

        result = engine.download(Job("https://example.com/video"))

        self.assertTrue(result.success)
        self.assertIsNotNone(result.media_info)
        assert result.media_info is not None
        self.assertEqual(result.media_info.resolution, "1920×1080")
        self.assertEqual(result.media_info.container, "mp4")

    def test_download_failure_returns_classified_result(self) -> None:
        runner = FakeRunner(
            stream_result=CommandResult(1, stdout="ERROR: Requested format is not available")
        )
        engine = YtDlpProcessEngine(self.settings, executable="yt-dlp", runner=runner)  # type: ignore[arg-type]

        result = engine.download(Job("https://example.com/video"))

        self.assertFalse(result.success)
        self.assertEqual(result.error_kind, ErrorKind.FORMAT_UNAVAILABLE)

    def test_operational_failures_return_stable_error_kinds(self) -> None:
        cases = {
            "ERROR: connection reset by peer": ErrorKind.NETWORK_TRANSIENT,
            "ERROR: Sign in to view this video": ErrorKind.AUTH_REQUIRED,
            "ERROR: ffmpeg not found": ErrorKind.DEPENDENCY_MISSING,
            "ERROR: Postprocessing: ffmpeg exited with code 1": ErrorKind.POSTPROCESS_FAILED,
            "ERROR: This video is DRM protected": ErrorKind.DRM_PROTECTED,
        }
        for output, expected in cases.items():
            with self.subTest(expected=expected):
                runner = FakeRunner(stream_result=CommandResult(1, stdout=output))
                engine = YtDlpProcessEngine(
                    self.settings,
                    executable="yt-dlp",
                    runner=runner,  # type: ignore[arg-type]
                )

                result = engine.download(Job("https://example.com/video"))

                self.assertFalse(result.success)
                self.assertEqual(result.error_kind, expected)

    def test_download_invalid_url_returns_result_instead_of_raising(self) -> None:
        engine = YtDlpProcessEngine(self.settings, executable="yt-dlp", runner=FakeRunner())  # type: ignore[arg-type]

        result = engine.download(Job("file:///c:/secret.txt"))

        self.assertFalse(result.success)
        self.assertEqual(result.error_kind, ErrorKind.UNSUPPORTED_URL)

    def test_cancelled_process_returns_cancelled_result(self) -> None:
        runner = FakeRunner(stream_result=CommandResult(1, cancelled=True))
        engine = YtDlpProcessEngine(self.settings, executable="yt-dlp", runner=runner)  # type: ignore[arg-type]

        result = engine.download(Job("https://example.com/video"))

        self.assertFalse(result.success)
        self.assertEqual(result.error_kind, ErrorKind.CANCELLED)

    def test_cancel_is_forwarded_to_process_runner(self) -> None:
        runner = FakeRunner()
        engine = YtDlpProcessEngine(self.settings, executable="yt-dlp", runner=runner)  # type: ignore[arg-type]

        engine.cancel()

        self.assertTrue(runner.cancelled)

    def test_http_403_is_retried_only_once(self) -> None:
        output_path = (Path.cwd() / "savedVideo" / "video.mp4").resolve()
        runner = FakeRunner(
            stream_results=[
                CommandResult(1, stdout="ERROR: HTTP Error 403: Forbidden"),
                CommandResult(0, stdout=f"VDL_OUTPUT:{json.dumps(str(output_path))}"),
            ]
        )
        engine = YtDlpProcessEngine(self.settings, executable="yt-dlp", runner=runner)  # type: ignore[arg-type]

        result = engine.download(Job("https://example.com/video"))

        self.assertTrue(result.success)
        self.assertEqual(runner.stream_calls, 2)


if __name__ == "__main__":
    unittest.main()
